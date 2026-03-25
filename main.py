"""
main.py
Root entrypoint for running the DYNAFIT application.
"""
import sys
import uvicorn
from api.routes import router

from api.server import create_app
from core.config.settings import settings

app = create_app()
app.include_router(router, prefix="/api")

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        # Start API server
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
