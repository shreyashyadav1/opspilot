"""Create API keys for OPSPILOT_API_KEYS.

    python -m opspilot_api.keys new alice approver

prints a new key (shown once; hand it to the person) and the `name:role:sha256` entry to add
to OPSPILOT_API_KEYS. Only the digest goes into the API's configuration.
"""

from __future__ import annotations

import argparse
import secrets

from opspilot_api.auth import NAME_PATTERN, ROLES, digest


def new_key() -> str:
    return "ops_" + secrets.token_urlsafe(32)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m opspilot_api.keys")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("new", help="create a key and print its OPSPILOT_API_KEYS entry")
    create.add_argument("name")
    create.add_argument("role", choices=ROLES)
    args = parser.parse_args(argv)
    if not NAME_PATTERN.fullmatch(args.name):
        parser.error("name must be 1-64 of A-Z a-z 0-9 . _ @ -")
    key = new_key()
    print(f"key:   {key}")
    print(f"entry: {args.name}:{args.role}:{digest(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
