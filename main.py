"""
main.py
Root entrypoint for running the DYNAFIT application.
"""

import os
import sys

# Fix Windows console encoding for structlog/Unicode output
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import uvicorn

from api.server import create_app

app = create_app()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            log_level="info",
            workers=1,
        )
    else:
        print("Usage: python main.py run")
        sys.exit(1)


if __name__ == "__main__":
    main()
