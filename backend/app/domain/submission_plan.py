"""Domain logic and immutable data models for Submission Plans (Stage 6)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def compute_hash(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SubmissionAnswer:
    question: str
    answer: str
    category: str = "general"
    reuse_consent: bool = False
    fact_ids: tuple[str, ...] = field(default_factory=tuple)
    answer_id: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "category": self.category,
            "reuse_consent": self.reuse_consent,
            "fact_ids": list(self.fact_ids),
            "answer_id": self.answer_id,
            "version": self.version,
        }


@dataclass(frozen=True)
class SubmissionPlan:
    plan_id: str
    application_id: str
    job_posting_id: str
    employer_handle: str
    target_role: str
    resume_markdown: str
    resume_sha256: str
    cover_letter_markdown: str
    cover_letter_sha256: str
    answers: tuple[SubmissionAnswer, ...]
    is_compensation_eligible: bool = False
    is_cooldown_clear: bool = False
    packet_sha256: str = ""
    status: str = "PREPARED"  # "PREPARED", "DRY_RUN_PASSED", "DRY_RUN_FAILED", "READY_FOR_MANUAL_SUBMISSION"
    created_at: str = ""
    compensation_threshold_version: int = 1
    review_state: str = "UNREVIEWED"

    @classmethod
    def create(
        cls,
        plan_id: str,
        application_id: str,
        job_posting_id: str,
        employer_handle: str,
        target_role: str,
        resume_markdown: str,
        cover_letter_markdown: str,
        answers: list[dict[str, Any]] | list[SubmissionAnswer] | tuple[SubmissionAnswer, ...],
        is_compensation_eligible: bool = False,
        is_cooldown_clear: bool = False,
        compensation_threshold_version: int = 1,
        review_state: str = "UNREVIEWED",
    ) -> SubmissionPlan:
        r_hash = compute_hash(resume_markdown)
        cl_hash = compute_hash(cover_letter_markdown)

        # Convert answers to immutable tuple of SubmissionAnswer
        parsed_answers: list[SubmissionAnswer] = []
        for ans in answers:
            if isinstance(ans, SubmissionAnswer):
                parsed_answers.append(ans)
            elif isinstance(ans, dict):
                parsed_answers.append(
                    SubmissionAnswer(
                        question=str(ans.get("question", "")),
                        answer=str(ans.get("answer", "")),
                        category=str(ans.get("category", "general")),
                        reuse_consent=bool(ans.get("reuse_consent", False)),
                        fact_ids=tuple(ans.get("fact_ids", ())),
                        answer_id=ans.get("answer_id"),
                        version=int(ans.get("version", 1)),
                    )
                )
        answers_tuple = tuple(sorted(parsed_answers, key=lambda x: x.question))

        packet_components = {
            "application_id": application_id,
            "job_posting_id": job_posting_id,
            "employer_handle": employer_handle,
            "target_role": target_role,
            "resume_sha256": r_hash,
            "cover_letter_sha256": cl_hash,
            "answers": [a.to_dict() for a in answers_tuple],
            "is_compensation_eligible": is_compensation_eligible,
            "is_cooldown_clear": is_cooldown_clear,
            "compensation_threshold_version": compensation_threshold_version,
            "review_state": review_state,
        }
        canonical_str = json.dumps(packet_components, sort_keys=True, separators=(",", ":"))
        packet_hash = compute_hash(canonical_str)

        now_iso = datetime.now(timezone.utc).isoformat()
        return cls(
            plan_id=plan_id,
            application_id=application_id,
            job_posting_id=job_posting_id,
            employer_handle=employer_handle,
            target_role=target_role,
            resume_markdown=resume_markdown,
            resume_sha256=r_hash,
            cover_letter_markdown=cover_letter_markdown,
            cover_letter_sha256=cl_hash,
            answers=answers_tuple,
            is_compensation_eligible=is_compensation_eligible,
            is_cooldown_clear=is_cooldown_clear,
            packet_sha256=packet_hash,
            status="PREPARED",
            created_at=now_iso,
            compensation_threshold_version=compensation_threshold_version,
            review_state=review_state,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "application_id": self.application_id,
            "job_posting_id": self.job_posting_id,
            "employer_handle": self.employer_handle,
            "target_role": self.target_role,
            "resume_markdown": self.resume_markdown,
            "resume_sha256": self.resume_sha256,
            "cover_letter_markdown": self.cover_letter_markdown,
            "cover_letter_sha256": self.cover_letter_sha256,
            "answers": [a.to_dict() for a in self.answers],
            "is_compensation_eligible": self.is_compensation_eligible,
            "is_cooldown_clear": self.is_cooldown_clear,
            "packet_sha256": self.packet_sha256,
            "status": self.status,
            "created_at": self.created_at,
            "compensation_threshold_version": self.compensation_threshold_version,
            "review_state": self.review_state,
        }
