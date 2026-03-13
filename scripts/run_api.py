"""Run the FastAPI app locally via Uvicorn."""
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'src' is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=port, reload=True)
