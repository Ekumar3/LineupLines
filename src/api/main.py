from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import storage

app = FastAPI(title="LineupLines API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/lines/latest")
def get_latest_lines():
    try:
        data = storage.get_latest_lines()
        return data
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="latest data not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
