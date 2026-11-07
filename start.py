import os
import sys
import traceback
import importlib
import uvicorn

if __name__ == "__main__":
    print("=== STUDYFLOW DIAGNOSTICS ===", flush=True)
    print("Python:", sys.version, flush=True)
    print("Current directory:", os.getcwd(), flush=True)
    print("Files:", os.listdir("."), flush=True)

    try:
        print("Importing app.py...", flush=True)
        module = importlib.import_module("app")
        application = getattr(module, "app")
        print("App imported successfully!", flush=True)

        uvicorn.run(
            application,
            host="0.0.0.0",
            port=int(os.getenv("PORT", "3000")),
            proxy_headers=True
        )

    except Exception:
        print("=== FULL ERROR ===", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        raise

