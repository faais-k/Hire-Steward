"""Hire-Steward offline job quality and matching evaluation package."""

from backend.app.evaluation.adapters import (
    AnthropicAdapterConfig,
    AnthropicProviderAdapter,
    BaseProviderAdapter,
    MockAdapterConfig,
    MockProviderAdapter,
    ModelInferenceResponse,
    OpenAIAdapterConfig,
    OpenAIProviderAdapter,
)
from backend.app.evaluation.blinded_serializer import (
    BlindedCasePayload,
    BlindedEvaluationSerializer,
)
from backend.app.evaluation.budget import (
    BudgetExceededError,
    BudgetSummary,
    BudgetTracker,
    ModelPricing,
    calculate_actual_cost,
    estimate_call_cost,
)
from backend.app.evaluation.coordinator import (
    CaseEvaluationPairResult,
    CommittedAssessmentResult,
    OfflineEvaluationCoordinator,
)
from backend.app.evaluation.credentials import (
    ProviderCredentials,
    get_anthropic_api_key,
    get_openai_api_key,
    load_provider_credentials,
)
from backend.app.evaluation.ledger import (
    AuditIntegrityError,
    EvaluationLedger,
    LedgerConstraintError,
    LedgerIntegrityError,
    verify_audit_chain,
)
from backend.app.evaluation.models import (
    CaseExecutionResult,
    EvaluationBenchmarkMetrics,
    EvaluationCase,
    EvaluationReport,
)
from backend.app.evaluation.pii_mapper import (
    CitationResolution,
    MaskingResult,
    PIICoordinateMapper,
    PIISegment,
    SectionMaskingRegistry,
)
from backend.app.evaluation.schema import (
    EVALUATION_OUTPUT_JSON_SCHEMA,
    ParsedEvaluationOutput,
)

__all__ = [
    "AnthropicAdapterConfig",
    "AnthropicProviderAdapter",
    "AuditIntegrityError",
    "BaseProviderAdapter",
    "BlindedCasePayload",
    "BlindedEvaluationSerializer",
    "BudgetExceededError",
    "BudgetSummary",
    "BudgetTracker",
    "CaseEvaluationPairResult",
    "CaseExecutionResult",
    "CitationResolution",
    "CommittedAssessmentResult",
    "EVALUATION_OUTPUT_JSON_SCHEMA",
    "EvaluationBenchmarkMetrics",
    "EvaluationCase",
    "EvaluationLedger",
    "EvaluationReport",
    "LedgerConstraintError",
    "LedgerIntegrityError",
    "MaskingResult",
    "MockAdapterConfig",
    "MockProviderAdapter",
    "ModelInferenceResponse",
    "ModelPricing",
    "OfflineEvaluationCoordinator",
    "OpenAIAdapterConfig",
    "OpenAIProviderAdapter",
    "PIICoordinateMapper",
    "PIISegment",
    "ParsedEvaluationOutput",
    "ProviderCredentials",
    "SectionMaskingRegistry",
    "calculate_actual_cost",
    "estimate_call_cost",
    "get_anthropic_api_key",
    "get_openai_api_key",
    "load_provider_credentials",
    "verify_audit_chain",
]
