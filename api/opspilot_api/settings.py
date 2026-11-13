"""API settings, read from the environment (and `.env`).

- OPSPILOT_MODEL: model for new investigations (`provider:model`); see `default_model()`.
- OPSPILOT_API_DATA_DIR: where the API keeps its SQLite files (default `.opspilot`):
  `investigations.sqlite` (records and trace events) and `checkpoints.sqlite` (LangGraph).
- OPSPILOT_BACKEND: telemetry backend of the MCP tool server, `live` (default) or `simulated`;
  OPSPILOT_SIMULATION optionally points at a SimulationSpec JSON for the latter.
- OPSPILOT_CHAOS_URL: control plane base URL. Enables the demo fault-injection endpoints.
- OPSPILOT_RESULTS_DIR: where benchmark runs (`*/results.json`) are read from
  (default `evals/results`).
- OPSPILOT_MAX_CONCURRENT (default 2) and OPSPILOT_MAX_TURNS (default 12): how many
  investigations run at once, and the model turn budget of each.
- OPSPILOT_PRICING_FILE: USD-per-million-token price table used to cost each investigation
  (default `evals/pricing.yaml`, the same file the benchmark prices its runs from). A model
  missing from it is reported with unknown cost rather than a guessed one.
- OPSPILOT_MAX_RESUMES (default 1): how many times an investigation cut off by an API restart
  before reaching the approval gate is picked up again from its last checkpoint. 0 marks such
  runs failed instead.
- OPSPILOT_API_KEYS: `name:role:sha256` entries that turn on API-key authentication with
  viewer, operator and approver roles (see `opspilot_api.auth`). Unset, the API runs open.
- OPSPILOT_ANONYMOUS_ROLE: what callers without a key may do (`none`, `viewer`, `operator`,
  `approver`). Defaults to `approver` without keys and `none` with them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from opspilot_agent.llm import DEFAULT_MODEL
from opspilot_api.auth import ApiKey, Role, parse_anonymous_role, parse_keys

BASELINE_MODEL = "fake:playbook"
REPO_ROOT = Path(__file__).resolve().parents[2]


def default_model() -> str:
    """OPSPILOT_MODEL if set, the default LLM when a Groq key exists, otherwise the playbook."""
    if spec := os.getenv("OPSPILOT_MODEL"):
        return spec
    if os.getenv("GROQ_API_KEY"):
        return DEFAULT_MODEL
    return BASELINE_MODEL


@dataclass(frozen=True)
class ApiSettings:
    data_dir: Path = Path(".opspilot")
    model: str = BASELINE_MODEL
    backend: str = "live"
    simulation: Path | None = None
    chaos_url: str | None = None
    results_dir: Path = field(default_factory=lambda: REPO_ROOT / "evals" / "results")
    pricing_file: Path = field(default_factory=lambda: REPO_ROOT / "evals" / "pricing.yaml")
    max_concurrent: int = 2
    max_turns: int = 12
    max_resumes: int = 1
    api_keys: tuple[ApiKey, ...] = ()
    # Raw OPSPILOT_ANONYMOUS_ROLE; unset picks the default for whether keys are configured.
    anonymous_role: str | None = None

    @property
    def anonymous_access(self) -> Role | None:
        """The role of a caller without a key, or None if such callers are refused."""
        return parse_anonymous_role(self.anonymous_role, self.api_keys)

    @property
    def records_db(self) -> Path:
        return self.data_dir / "investigations.sqlite"

    @property
    def checkpoints_db(self) -> Path:
        # A separate file: each SQLite file then has a single writing connection.
        return self.data_dir / "checkpoints.sqlite"

    @property
    def models(self) -> list[str]:
        """Models an investigation may ask for: the configured model and the baseline."""
        return list(dict.fromkeys([self.model, BASELINE_MODEL]))

    @classmethod
    def from_env(cls) -> ApiSettings:
        load_dotenv()
        defaults = cls()
        simulation = os.getenv("OPSPILOT_SIMULATION")
        results = os.getenv("OPSPILOT_RESULTS_DIR")
        pricing = os.getenv("OPSPILOT_PRICING_FILE")
        settings = cls(
            data_dir=Path(os.getenv("OPSPILOT_API_DATA_DIR", str(defaults.data_dir))),
            model=default_model(),
            backend=os.getenv("OPSPILOT_BACKEND", defaults.backend),
            simulation=Path(simulation) if simulation else None,
            chaos_url=os.getenv("OPSPILOT_CHAOS_URL") or None,
            results_dir=Path(results) if results else defaults.results_dir,
            pricing_file=Path(pricing) if pricing else defaults.pricing_file,
            max_concurrent=int(os.getenv("OPSPILOT_MAX_CONCURRENT", str(defaults.max_concurrent))),
            max_turns=int(os.getenv("OPSPILOT_MAX_TURNS", str(defaults.max_turns))),
            max_resumes=int(os.getenv("OPSPILOT_MAX_RESUMES", str(defaults.max_resumes))),
            api_keys=parse_keys(os.getenv("OPSPILOT_API_KEYS")),
            anonymous_role=os.getenv("OPSPILOT_ANONYMOUS_ROLE") or None,
        )
        settings.anonymous_access  # noqa: B018 - a bad combination fails here, at startup
        return settings
