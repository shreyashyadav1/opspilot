"""Optional API keys with roles, so only named approvers can let the agent change production.

OPSPILOT_API_KEYS holds comma-separated `name:role:sha256` entries, where `sha256` is the hex
SHA-256 digest of the key (the key itself is never stored). `python -m opspilot_api.keys new
<name> <role>` prints a fresh key and its entry. Roles are cumulative:

- viewer:   read investigations, traces, benchmarks and the demo fault list
- operator: also start investigations and inject or clear demo faults
- approver: also approve or reject the actions the agent proposes

Clients send `Authorization: Bearer <key>`. With no keys configured the API runs open, as in
the local demo: every caller may do everything, and decisions are recorded as unauthenticated
so the dashboard and the trace can say so.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Literal

from opspilot_api.errors import ApiError

Role = Literal["viewer", "operator", "approver"]
ROLES: tuple[Role, ...] = ("viewer", "operator", "approver")

NAME_PATTERN = re.compile(r"[A-Za-z0-9._@-]{1,64}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    """Who is calling. `authenticated` is False only when the API runs without keys."""

    name: str | None
    role: Role
    authenticated: bool

    def allows(self, role: Role) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


ANONYMOUS = Principal(name=None, role="approver", authenticated=False)


@dataclass(frozen=True)
class ApiKey:
    name: str
    role: Role
    sha256: str


def parse_keys(raw: str | None) -> tuple[ApiKey, ...]:
    """Parse OPSPILOT_API_KEYS. A malformed entry is a startup error, never silently skipped:
    dropping a key could otherwise leave the API open."""
    keys: list[ApiKey] = []
    for position, entry in enumerate((raw or "").split(","), start=1):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3:
            raise ValueError(f"OPSPILOT_API_KEYS entry {position}: expected name:role:sha256")
        name, role, sha = (part.strip() for part in parts)
        if not NAME_PATTERN.fullmatch(name):
            raise ValueError(
                f"OPSPILOT_API_KEYS entry {position}: name must be 1-64 of A-Z a-z 0-9 . _ @ -"
            )
        if role not in ROLES:
            raise ValueError(
                f"OPSPILOT_API_KEYS entry {position}: role must be one of {', '.join(ROLES)}"
            )
        sha = sha.lower()
        if not _DIGEST.fullmatch(sha):
            raise ValueError(
                f"OPSPILOT_API_KEYS entry {position}: expected a 64-character hex SHA-256 digest"
            )
        keys.append(ApiKey(name=name, role=role, sha256=sha))
    if len({key.sha256 for key in keys}) != len(keys):
        raise ValueError("OPSPILOT_API_KEYS: two entries share the same key")
    if len({key.name for key in keys}) != len(keys):
        raise ValueError("OPSPILOT_API_KEYS: two entries share the same name")
    return tuple(keys)


class Authenticator:
    def __init__(self, keys: tuple[ApiKey, ...]) -> None:
        self._keys = keys

    @property
    def enabled(self) -> bool:
        return bool(self._keys)

    def identify(self, authorization: str | None) -> Principal:
        if not self.enabled:
            return ANONYMOUS
        scheme, _, token = (authorization or "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise ApiError(401, "Send an API key as 'Authorization: Bearer <key>'.", _CHALLENGE)
        presented = digest(token)
        # Compare against every entry so the time taken does not depend on which one matches.
        match: ApiKey | None = None
        for key in self._keys:
            if hmac.compare_digest(presented, key.sha256):
                match = key
        if match is None:
            raise ApiError(401, "Unknown API key.", _CHALLENGE)
        return Principal(name=match.name, role=match.role, authenticated=True)

    def require(self, authorization: str | None, role: Role) -> Principal:
        principal = self.identify(authorization)
        if not principal.allows(role):
            raise ApiError(
                403, f"{principal.name} has the {principal.role} role; this needs {role}."
            )
        return principal
