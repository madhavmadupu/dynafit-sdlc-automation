"""
main.py
Root entrypoint for running the DYNAFIT application.
"""
import sys

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        # Start API server
        import uvicorn
        from api.server import create_app
        from core.config.settings import settings

        app = create_app()
        uvicorn.run(
            app,
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
