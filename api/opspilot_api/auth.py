"""Optional API keys with roles, so only named approvers can let the agent change production.

OPSPILOT_API_KEYS holds comma-separated `name:role:sha256` entries, where `sha256` is the hex
SHA-256 digest of the key (the key itself is never stored). `python -m opspilot_api.keys new
<name> <role>` prints a fresh key and its entry. Roles are cumulative:

- viewer:   read investigations, traces, benchmarks and the demo fault list
- operator: also start investigations and inject or clear demo faults
- approver: also approve or reject the actions the agent proposes

Clients send `Authorization: Bearer <key>`. OPSPILOT_ANONYMOUS_ROLE sets what a caller without
a key may do: `none`, `viewer`, `operator` or `approver`. It defaults to `approver` with no keys
configured (the local demo, where every caller may do everything) and to `none` with keys
(every route needs one). `viewer` with keys suits a public demo that anyone may watch but only
named approvers may act on. Decisions made without a key are recorded as unauthenticated so the
dashboard and the trace can say so.
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
NO_ANONYMOUS = "none"


def parse_anonymous_role(raw: str | None, keys: tuple[ApiKey, ...]) -> Role | None:
    """Parse OPSPILOT_ANONYMOUS_ROLE. None means callers without a key are refused.

    Two combinations are startup errors: `none` without keys (nobody could use the API) and
    `approver` with keys (anyone could approve without one, which makes the keys pointless).
    """
    value = (raw or "").strip().lower()
    if not value:
        return None if keys else "approver"
    if value == NO_ANONYMOUS:
        if not keys:
            raise ValueError(
                "OPSPILOT_ANONYMOUS_ROLE=none needs OPSPILOT_API_KEYS; nobody could use the API"
            )
        return None
    if value not in ROLES:
        raise ValueError(
            f"OPSPILOT_ANONYMOUS_ROLE must be one of {NO_ANONYMOUS}, {', '.join(ROLES)}"
        )
    if value == "approver" and keys:
        raise ValueError(
            "OPSPILOT_ANONYMOUS_ROLE=approver with OPSPILOT_API_KEYS would let anyone approve "
            "without a key; use operator or lower"
        )
    return value  # type: ignore[return-value]


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
    def __init__(self, keys: tuple[ApiKey, ...], anonymous_role: str | None = None) -> None:
        """`anonymous_role` is the raw OPSPILOT_ANONYMOUS_ROLE; see `parse_anonymous_role`."""
        self._keys = keys
        role = parse_anonymous_role(anonymous_role, keys)
        self._anonymous = (
            None if role is None else Principal(name=None, role=role, authenticated=False)
        )

    @property
    def enabled(self) -> bool:
        return bool(self._keys)

    def identify(self, authorization: str | None) -> Principal:
        if not self.enabled:
            assert self._anonymous is not None
            return self._anonymous
        if not (authorization or "").strip() and self._anonymous is not None:
            return self._anonymous
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
            who = principal.name if principal.authenticated else "Without an API key you"
            verb = "has" if principal.authenticated else "have"
            raise ApiError(403, f"{who} {verb} the {principal.role} role; this needs {role}.")
        return principal
