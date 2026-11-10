"""Unit tests for submission plan immutability, simulation validation, and persistence safety."""

import pytest
from dataclasses import FrozenInstanceError

from backend.app.adapters.simulated_ats import SimulatedAtsAdapter, VALID_SIMULATION_MODES
from backend.app.domain.submission_plan import SubmissionPlan, SubmissionAnswer


def test_submission_plan_and_answers_are_immutable():
    answer = SubmissionAnswer(
        question="Why Hire-Steward?",
        answer="Autonomous local-first job search assistant.",
        category="general",
        reuse_consent=True,
        fact_ids=("fact-1", "fact-2"),
    )
    plan = SubmissionPlan.create(
        plan_id="plan-123",
        application_id="app-1",
        job_posting_id="job-1",
        employer_handle="acme",
        target_role="Platform Engineer",
        resume_markdown="# Resume",
        cover_letter_markdown="# Cover Letter",
        answers=[answer],
        is_compensation_eligible=False,
        is_cooldown_clear=False,
    )

    # 1. Eligibility defaults to False unless explicitly proven
    default_plan = SubmissionPlan.create(
        plan_id="plan-456",
        application_id="app-2",
        job_posting_id="job-2",
        employer_handle="beta",
        target_role="Backend Engineer",
        resume_markdown="# Resume",
        cover_letter_markdown="# Cover Letter",
        answers=[],
    )
    assert default_plan.is_compensation_eligible is False
    assert default_plan.is_cooldown_clear is False

    # 2. Plan is frozen
    with pytest.raises(FrozenInstanceError):
        plan.status = "MUTATED"  # type: ignore

    # 3. Answers is an immutable tuple
    assert isinstance(plan.answers, tuple)
    with pytest.raises(FrozenInstanceError):
        plan.answers[0].question = "Changed?"  # type: ignore

    # 4. Answers tuple cannot be appended
    with pytest.raises(AttributeError):
        plan.answers.append(answer)  # type: ignore


def test_simulated_ats_rejects_invalid_modes():
    adapter = SimulatedAtsAdapter()

    # Valid modes run without error
    for mode in VALID_SIMULATION_MODES:
        res = adapter.simulate_dispatch(
            {
                "is_compensation_eligible": True,
                "is_cooldown_clear": True,
            },
            mode=mode,
        )
        assert res.mode_used == mode

    # Invalid mode raises ValueError with descriptive message (never silently defaults to SUCCESS)
    with pytest.raises(ValueError) as excinfo:
        adapter.simulate_dispatch({}, mode="SUCESS")  # Typo
    assert "Invalid simulation mode 'SUCESS'" in str(excinfo.value)

    with pytest.raises(ValueError):
        adapter.simulate_dispatch({}, mode="LIVE_EXTERNAL_DISPATCH")
