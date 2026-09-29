"""Human-readable descriptions of model specs, so no one mistakes the baseline for an LLM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

PROVIDERS = {
    "groq": "Groq",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
    "custom": "a custom OpenAI-compatible endpoint",
}


class ModelInfo(BaseModel):
    spec: str
    kind: Literal["baseline", "llm"]
    label: str
    description: str


def describe_model(spec: str) -> ModelInfo:
    provider, _, name = spec.partition(":")
    if provider == "fake":
        return ModelInfo(
            spec=spec,
            kind="baseline",
            label="Rule-based playbook",
            description=(
                "A fixed triage runbook with simple rules over the tool results. "
                "A deterministic baseline, not an LLM."
            ),
        )
    return ModelInfo(
        spec=spec,
        kind="llm",
        label=name or spec,
        description=f"LLM served by {PROVIDERS.get(provider, provider)}.",
    )
