"""Run the FastAPI app locally via Uvicorn."""
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'src' is importable
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Set CWD to project root so relative paths resolve correctly
os.chdir(project_root)

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=port, reload=True)
