"""Run the agent API.

opspilot-api                      # 127.0.0.1:8180
opspilot-api --host 0.0.0.0 --port 8180 --reload
"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="opspilot-api", description="OpsPilot agent API")
    parser.add_argument("--host", default=os.getenv("OPSPILOT_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("OPSPILOT_API_PORT", "8180")))
    parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(
        "opspilot_api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
