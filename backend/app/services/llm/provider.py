"""Swappable LLM provider abstraction.

The application depends on this narrow interface, never on a vendor SDK, so the
provider can be changed by configuration alone. Phase 1 ships the interface and
the null provider; concrete providers arrive in Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.config import Settings
from app.core.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """A single, non-conversational generation request.

    There is no message history: the explanation service is stateless and every
    call carries its full factual context. That prevents the LLM from carrying
    over values from an earlier zone.
    """

    system_prompt: str
    user_prompt: str
    max_output_tokens: int
    #: Low by default — this is a summarisation task, not a creative one.
    temperature: float = 0.2


@dataclass(frozen=True, slots=True)
class CompletionResult:
    text: str
    provider: str
    model: str


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


class NullLLMProvider:
    """Used when no provider is configured.

    Raises rather than returning placeholder prose, so an unconfigured
    deployment cannot present machine-written filler as a real briefing.
    """

    name = "none"
    model = "none"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise ConfigurationError(
            "No LLM provider is configured. Set LLM_PROVIDER and LLM_API_KEY to enable "
            "natural-language explanations.",
            details={"required_env": ["LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL"]},
        )


#: Provider slug -> factory. Concrete providers register themselves here in
#: Phase 5; the rest of the application is unaffected by what is in this map.
PROVIDER_FACTORIES: dict[str, object] = {}


def build_provider(settings: Settings) -> LLMProvider:
    slug = settings.llm_provider.lower()
    if slug in ("", "none") or not settings.llm_api_key:
        return NullLLMProvider()

    factory = PROVIDER_FACTORIES.get(slug)
    if factory is None:
        raise ConfigurationError(
            f"Unknown LLM provider '{settings.llm_provider}'.",
            details={"known_providers": sorted(PROVIDER_FACTORIES) or ["none"]},
        )
    return factory(settings)  # type: ignore[operator]
