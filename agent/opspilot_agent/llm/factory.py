"""Build a chat model from a spec such as `groq:llama-3.3-70b-versatile` or `fake:playbook`.

Real providers go through `langchain-openai` against any OpenAI-compatible endpoint. Keys are
read from the environment (and `.env`); they are never logged or passed to tool servers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

DEFAULT_MODEL = "groq:llama-3.3-70b-versatile"


class ModelSpecError(ValueError):
    pass


@dataclass(frozen=True)
class Provider:
    base_url: str | None
    api_key_env: str | None


PROVIDERS: dict[str, Provider] = {
    "groq": Provider("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openai": Provider("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "openrouter": Provider("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": Provider("http://localhost:11434/v1", None),
    # Any other OpenAI-compatible server: OPSPILOT_LLM_BASE_URL + OPSPILOT_LLM_API_KEY.
    "custom": Provider(None, "OPSPILOT_LLM_API_KEY"),
}


def build_model(spec: str | None = None, *, temperature: float = 0.0) -> BaseChatModel:
    spec = spec or os.getenv("OPSPILOT_MODEL") or DEFAULT_MODEL
    provider_name, _, model_name = spec.partition(":")
    if not model_name:
        raise ModelSpecError(f"model spec must look like 'provider:model', got {spec!r}")

    if provider_name == "fake":
        from opspilot_agent.llm.fake import PlaybookChatModel

        if model_name != "playbook":
            raise ModelSpecError("the only fake model for runs is 'fake:playbook'")
        return PlaybookChatModel()

    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise ModelSpecError(f"unknown provider {provider_name!r}; use one of {sorted(PROVIDERS)}")
    load_dotenv()
    base_url = provider.base_url or os.getenv("OPSPILOT_LLM_BASE_URL")
    if not base_url:
        raise ModelSpecError("set OPSPILOT_LLM_BASE_URL for the custom provider")
    api_key = "not-needed"
    if provider.api_key_env:
        api_key = os.getenv(provider.api_key_env, "")
        if not api_key:
            raise ModelSpecError(
                f"{provider.api_key_env} is not set. Add it to .env (see .env.example)."
            )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=SecretStr(api_key),
        temperature=temperature,
        max_retries=6,
        timeout=90,
    )
