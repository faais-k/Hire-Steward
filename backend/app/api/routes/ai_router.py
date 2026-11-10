"""Controlled AI Router & Assistant Endpoints (Stage 5 & Stage 7 Screen 10).

Enforces:
1. Strict disabled-by-default behavior for live paid AI API requests.
2. Hard budget ceiling reservation and verification before any inference.
3. Offline mock evaluation and local template generation.
4. Answer Bank search and grounded claim synthesis with provenance back-links.
5. Zero secrets or API credentials in status outputs or responses.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_session, require_local_same_origin
from backend.app.domain.application_preparation import (
    ApplicationDraft,
    ApplicationPreparationError,
)
from backend.app.domain.candidate_evidence import FactVerificationState
from backend.app.evaluation.budget import BudgetTracker
from backend.app.evaluation.credentials import load_provider_credentials
from backend.app.services import answer_bank as answer_service
from backend.app.services import candidate_evidence as evidence_service
from backend.app.services import candidate_profile as profile_service
from backend.app.services.application_preparation import prepare_application_draft
from backend.app.services.user_settings import get_user_settings

router = APIRouter(prefix="/api/v1/ai", tags=["AI Assistant & Usage"])

# Default singleton budget tracker
_budget_tracker = BudgetTracker(budget_cap_usd=5.0)


class GenerateDraftRequest(BaseModel):
    job_posting_id: str = Field(..., description="ID of persisted job posting to tailor for")
    fact_ids: list[str] | None = Field(default=None, description="Optional subset of facts to include")


class AnswerQuestionRequest(BaseModel):
    question: str = Field(min_length=3, description="Interview or application question to answer")
    category: str | None = Field(default=None, description="Optional category hint")


@router.get("/status")
def get_ai_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return AI system status, budget metrics, and provider availability without exposing keys."""
    settings = get_user_settings(session)
    creds = load_provider_credentials()
    summary = _budget_tracker.get_summary()

    return {
        "active_mode": "OFFLINE_MOCK",
        "paid_ai_enabled": False,  # Strict offline default
        "live_inference_authorized": False,
        "has_anthropic_key": creds.has_anthropic,
        "has_openai_key": creds.has_openai,
        "budget_cap_usd": summary.budget_cap_usd,
        "committed_spend_usd": summary.committed_spend_usd,
        "active_reservations_usd": summary.active_reservations_usd,
        "remaining_budget_usd": summary.remaining_budget_usd,
        "supported_models": ["offline-mock-evaluator"],
    }


@router.post("/generate-draft")
def generate_application_draft(
    payload: GenerateDraftRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Generate deterministic, evidence-grounded resume and cover letter tailored to a job."""
    settings = get_user_settings(session)
    mode = settings.get("ai_provider_mode", "OFFLINE_MOCK")

    if mode == "DISABLED":
        raise HTTPException(
            status_code=400,
            detail="AI_FEATURES_DISABLED: Enable AI Assistant in Settings to generate drafts.",
        )

    # In local-first offline architecture, drafts are synthesized through the deterministic engine
    try:
        draft = prepare_application_draft(
            session,
            posting_id=payload.job_posting_id,
            fact_ids=payload.fact_ids,
        )
    except ApplicationPreparationError as exc:
        if exc.code in {"POSTING_NOT_FOUND", "SNAPSHOT_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=exc.code)
        raise HTTPException(status_code=422, detail=exc.message)

    draft_dict = draft.model_dump()
    draft_dict["generation_mode"] = mode
    draft_dict["cost_usd"] = 0.00  # Local offline synthesis
    return draft_dict


def _fact_text(fact: Any) -> str:
    val = fact.value_json
    if isinstance(val, dict):
        if "text" in val and val["text"]:
            return str(val["text"]).strip()
        if "skill" in val and val["skill"]:
            return f"Skill: {val['skill']}"
        if "title" in val and val["title"]:
            org = f" at {val['organization']}" if val.get("organization") else ""
            return f"{val['title']}{org}"
        if "degree" in val and val["degree"]:
            school = f" from {val['institution']}" if val.get("institution") else ""
            return f"{val['degree']}{school}"
        return " ".join(f"{k}: {v}" for k, v in val.items() if isinstance(v, (str, int, float)))
    return str(val)


@router.post("/answer-question")
def answer_application_question(
    payload: AnswerQuestionRequest,
    session: Session = Depends(get_session),
    _guard: None = Depends(require_local_same_origin),
) -> dict[str, Any]:
    """Answer an application question using Answer Bank entries or candidate profile facts."""
    norm_q = payload.question.strip().lower()

    # 1. Search Answer Bank for exact or fuzzy match with explicit consent
    answers = answer_service.list_answer_items(
        session,
        category=payload.category,
        include_revoked=False,
        consent_only=True,
    )
    for ans in answers:
        if ans.reuse_consent and not ans.is_revoked:
            if ans.question.strip().lower() == norm_q or norm_q in ans.question.lower():
                return {
                    "source": "ANSWER_BANK",
                    "answer_id": ans.id,
                    "question": ans.question,
                    "answer": ans.answer,
                    "category": ans.category,
                    "is_pre_approved": True,
                    "fact_ids": ans.fact_ids or [],
                    "confidence": 1.0,
                    "provenance": [],
                    "evidence_gaps": [],
                    "verification_warning": None,
                }

    # 2. Check CandidateFact records and their verification states
    try:
        facts = evidence_service.list_facts(session)
    except Exception:
        facts = []
    valid_facts = [
        f for f in facts
        if f.verification_state in {
            FactVerificationState.USER_VERIFIED.value,
            FactVerificationState.DOCUMENT_SUPPORTED.value,
            FactVerificationState.UNREVIEWED.value,
        }
    ]
    verified_facts = [
        f for f in valid_facts
        if f.verification_state in {
            FactVerificationState.USER_VERIFIED.value,
            FactVerificationState.DOCUMENT_SUPPORTED.value,
        }
    ]
    unreviewed_facts = [
        f for f in valid_facts
        if f.verification_state == FactVerificationState.UNREVIEWED.value
    ]

    if verified_facts:
        fact_texts = [_fact_text(f) for f in verified_facts]
        answer_text = ". ".join(t.rstrip(".") for t in fact_texts if t) + "."
        fact_ids = [f.id for f in verified_facts]
        provenance = []
        for f in verified_facts:
            ev_list = evidence_service.list_fact_evidence(session, f.id)
            for ev in ev_list:
                provenance.append({
                    "fact_id": f.id,
                    "document_version_id": ev.document_version_id,
                    "byte_start": ev.byte_start,
                    "byte_end": ev.byte_end,
                    "evidence_hash": ev.evidence_hash,
                })
        return {
            "source": "VERIFIED_EVIDENCE",
            "answer_id": None,
            "question": payload.question,
            "answer": answer_text,
            "category": payload.category or "general",
            "is_pre_approved": False,
            "fact_ids": fact_ids,
            "confidence": 1.0,
            "provenance": provenance,
            "evidence_gaps": [],
            "verification_warning": "Synthesized from verified candidate evidence. Review required before submission.",
        }

    if unreviewed_facts:
        fact_texts = [_fact_text(f) for f in unreviewed_facts]
        answer_text = ". ".join(t.rstrip(".") for t in fact_texts if t) + "."
        fact_ids = [f.id for f in unreviewed_facts]
        provenance = []
        for f in unreviewed_facts:
            ev_list = evidence_service.list_fact_evidence(session, f.id)
            for ev in ev_list:
                provenance.append({
                    "fact_id": f.id,
                    "document_version_id": ev.document_version_id,
                    "byte_start": ev.byte_start,
                    "byte_end": ev.byte_end,
                    "evidence_hash": ev.evidence_hash,
                })
        return {
            "source": "UNREVIEWED_EVIDENCE",
            "answer_id": None,
            "question": payload.question,
            "answer": answer_text,
            "category": payload.category or "general",
            "is_pre_approved": False,
            "fact_ids": fact_ids,
            "confidence": 0.5,
            "provenance": provenance,
            "evidence_gaps": ["Candidate facts found but they remain unreviewed. Verification required before submission."],
            "verification_warning": "Generated from unreviewed candidate facts. Candidate review and verification required.",
        }

    # 3. Fallback to candidate profile user-entered text (if populated)
    profile = profile_service.get_or_create_profile(session)
    headline_part = f"{profile.headline.strip()}. " if profile.headline and profile.headline.strip() else ""
    summary_part = profile.summary.strip() if profile.summary else ""
    skills_names = [s.get("name") for s in (profile.skills or []) if isinstance(s, dict) and s.get("name")]

    if not summary_part and not skills_names and not headline_part:
        return {
            "source": "NONE",
            "answer_id": None,
            "question": payload.question,
            "answer": "",
            "category": payload.category or "general",
            "is_pre_approved": False,
            "fact_ids": [],
            "confidence": 0.0,
            "provenance": [],
            "evidence_gaps": ["No approved answer found in Answer Bank and insufficient verified candidate profile records."],
            "verification_warning": "No grounded evidence available to synthesize an answer.",
        }

    components = []
    if headline_part:
        components.append(headline_part.strip())
    if summary_part:
        components.append(summary_part)
    if skills_names:
        components.append(f"Key qualifications: {', '.join(skills_names[:5])}.")

    suggested_answer = " ".join(components)

    return {
        "source": "USER_ENTERED_PROFILE",
        "answer_id": None,
        "question": payload.question,
        "answer": suggested_answer,
        "category": payload.category or "general",
        "is_pre_approved": False,
        "fact_ids": [],
        "confidence": 0.5,
        "provenance": [],
        "evidence_gaps": ["No verified CandidateFact records exist. Answer synthesized from unverified user profile text."],
        "verification_warning": "Generated from unverified user profile text. Review required before submission.",
    }
