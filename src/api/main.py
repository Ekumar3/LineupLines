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


@app.get("/props/season/latest")
def get_latest_season_props(sport: str = "nfl", season: str = "2026"):
    """Get all latest season-long player props."""
    try:
        data = storage.get_season_props(sport=sport, season=season)
        return data
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="season props data not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/props/season/player/{player_name}")
def get_player_season_props(player_name: str, sport: str = "nfl", season: str = "2026"):
    """Get all season props for a specific player."""
    try:
        data = storage.get_season_props(sport=sport, season=season)
        props = storage.get_player_props(player_name, sport=sport, season=season)
        if not props:
            raise HTTPException(status_code=404, detail=f"no props found for player {player_name}")
        return {
            "player_name": player_name,
            "fetched_at": data.get("fetched_at"),
            "props": props,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/props/season/category/{category}")
def get_category_props(category: str, sport: str = "nfl", season: str = "2026"):
    """Get all players for a specific stat category."""
    try:
        data = storage.get_season_props(sport=sport, season=season)
        props = storage.get_props_by_category(category, sport=sport, season=season)
        if not props:
            raise HTTPException(status_code=404, detail=f"no props found for category {category}")
        return {
            "category": category,
            "fetched_at": data.get("fetched_at"),
            "count": len(props),
            "props": props,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
