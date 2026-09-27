"""Shared start-up setup: every app start (Mac, iPhone, browser) opens with these layers, basemap, EMO state and map view.
Saved from any device with "Save this setup as the start-up default" in Map layers. Stored as JSON in the data dir."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/prefs", tags=["prefs"])
PATH = Path(os.environ.get("CYEM_DATA_DIR", "/data")) / "startup.json"
KEYS = ("cyem.layers", "cyem.layeropts", "cyem.groups", "cyem.basemap", "cyem-emo-on", "cyem-layers", "cyem.panels")


class View(BaseModel):
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-200, le=200)
    z: float = Field(ge=2, le=18)


class Startup(BaseModel):
    ls: dict[str, Optional[str]] = {}
    view: Optional[View] = None
    device: str = Field("", max_length=60)


def load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


@router.get("/startup")
async def get_startup():
    return load()


@router.put("/startup")
async def put_startup(s: Startup):
    d = {"ls": {k: v for k, v in s.ls.items() if k in KEYS and (v is None or len(v) < 8000)},
         "view": s.view.model_dump() if s.view else None, "device": s.device,
         "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    PATH.write_text(json.dumps(d))
    return d


@router.get("/startup.js")
async def startup_js():
    body = "window.CYEM_STARTUP = " + json.dumps(load()) + ";"
    return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-store"})
