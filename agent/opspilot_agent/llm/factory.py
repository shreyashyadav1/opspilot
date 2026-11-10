"""Build a chat model from a spec such as `groq:openai/gpt-oss-120b` or `fake:playbook`.

Real providers go through `langchain-openai` against any OpenAI-compatible endpoint. Keys are
read from the environment (and `.env`); they are never logged or passed to tool servers.

Requests to gateways we run ourselves (`switchyard`, `custom`) carry the W3C `traceparent` of the
current span, so the gateway's spans join the investigation's trace. Hosted providers never get
it: trace ids stay inside our own systems.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from opentelemetry.propagate import inject
from pydantic import SecretStr

# Groq shut down llama-3.3-70b-versatile for free and developer tiers on 2026-08-16;
# gpt-oss-120b is its recommended replacement (https://console.groq.com/docs/deprecations).
DEFAULT_MODEL = "groq:openai/gpt-oss-120b"
# gpt-oss-120b is a reasoning model: its reasoning tokens are billed and counted against
# max_tokens just like the visible answer, so a request can be cut off before it ever reaches
# the tool call or submit_diagnosis if the budget is too tight. 8192 leaves real headroom
# without approaching the model's 65536-token ceiling.
DEFAULT_MAX_TOKENS = 8192


class ModelSpecError(ValueError):
    pass


@dataclass(frozen=True)
class Provider:
    base_url: str | None
    api_key_env: str | None
    # Environment variable that overrides base_url (required when base_url is None).
    base_url_env: str | None = None
    propagate_trace: bool = False


PROVIDERS: dict[str, Provider] = {
    "groq": Provider("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openai": Provider("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "openrouter": Provider("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": Provider("http://localhost:11434/v1", None),
    # The Switchyard LLM gateway: model names are the gateway's own (e.g. gpt-oss-120b), and it
    # handles provider keys, retries, fallback, rate limits and budgets.
    "switchyard": Provider(
        "http://localhost:8080/v1",
        "SWITCHYARD_API_KEY",
        base_url_env="SWITCHYARD_URL",
        propagate_trace=True,
    ),
    # Any other OpenAI-compatible server: OPSPILOT_LLM_BASE_URL + OPSPILOT_LLM_API_KEY.
    "custom": Provider(
        None, "OPSPILOT_LLM_API_KEY", base_url_env="OPSPILOT_LLM_BASE_URL", propagate_trace=True
    ),
}


def _inject_trace_context(request: httpx.Request) -> None:
    inject(request.headers)


async def _ainject_trace_context(request: httpx.Request) -> None:
    inject(request.headers)


def _tracing_http_clients() -> dict[str, httpx.Client | httpx.AsyncClient]:
    """httpx clients that add the current span's trace context to every request. The OpenAI
    client still sets the timeout on each request, so only the hooks differ from its defaults."""
    return {
        "http_client": httpx.Client(event_hooks={"request": [_inject_trace_context]}),
        "http_async_client": httpx.AsyncClient(event_hooks={"request": [_ainject_trace_context]}),
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
    base_url = (provider.base_url_env and os.getenv(provider.base_url_env)) or provider.base_url
    if not base_url:
        raise ModelSpecError(f"set {provider.base_url_env} for the {provider_name} provider")
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
        max_tokens=DEFAULT_MAX_TOKENS,
        max_retries=6,
        timeout=90,
        **(_tracing_http_clients() if provider.propagate_trace else {}),
    )
