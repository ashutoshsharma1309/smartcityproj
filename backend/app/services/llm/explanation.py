"""LLM explanation service — the last stage of the pipeline."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, ExternalServiceError
from app.core.logging import get_logger
from app.schemas.risk import ExplanationRequest, ExplanationResponse
from app.services.llm.prompts import SYSTEM_PROMPT, build_user_prompt, grounding_payload
from app.services.llm.provider import CompletionRequest, LLMProvider

logger = get_logger(__name__)


class GroundedExplanationService:
    """Implements :class:`~app.services.interfaces.ExplanationService`.

    The service is provider-agnostic: it builds a grounded prompt from
    already-computed facts and delegates the call. With the null provider
    configured it raises a configuration error, which the API surfaces as a
    clear "not configured" response rather than inventing a summary.
    """

    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def explain(self, request: ExplanationRequest) -> ExplanationResponse:
        completion = CompletionRequest(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_user_prompt(request),
            max_output_tokens=self._settings.llm_max_output_tokens,
        )

        logger.info(
            "llm_explanation_requested",
            provider=self._provider.name,
            zone_id=str(request.prediction.zone_id),
            audience=request.audience,
        )

        try:
            result = await self._provider.complete(completion)
        except (ConfigurationError, ExternalServiceError):
            # A missing provider is a configuration problem, not an upstream
            # failure; keeping them distinct lets the caller react correctly.
            raise
        except Exception as exc:
            raise ExternalServiceError(
                "The LLM provider failed to produce an explanation.",
                details={"provider": self._provider.name, "error": str(exc)},
            ) from exc

        return ExplanationResponse(
            summary=result.text.strip(),
            audience=request.audience,
            provider=result.provider,
            model=result.model,
            generated_at=datetime.now(UTC),
            grounded_on=grounding_payload(request),
        )
