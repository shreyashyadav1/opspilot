"""Chat model construction: OpenAI-compatible providers and deterministic fakes."""

from opspilot_agent.llm.factory import DEFAULT_MODEL, ModelSpecError, build_model

__all__ = ["DEFAULT_MODEL", "ModelSpecError", "build_model"]
