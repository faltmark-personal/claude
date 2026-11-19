"""Local web app: FastAPI backend + static single-page UI.

Run with ``runna-playlist`` (or ``python -m runna_playlist.app``) and open
http://localhost:8765. Single user, local only: it binds to 127.0.0.1 and keeps
tokens in the data directory (~/.runna-playlist).
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .fit_import import workout_from_fit
from .models import Track
from .service import AppState, export_csv
from .workout import parse_spec, workout_from_dict
from .zones import ZONE_LABELS, ranges_from_cadence

STATIC = Path(__file__).parent / "static"


def _workout(payload: dict):
    w = payload.get("workout")
    if not w:
        raise HTTPException(400, "workout missing")
    try:
        return workout_from_dict(w)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, f"Bad workout: {e}")


def create_app(state: AppState | None = None) -> FastAPI:
    app = FastAPI(title="Runna → YouTube Music playlist")
    st = state or AppState()
    app.state.svc = st

    @app.exception_handler(PermissionError)
    async def _perm(request: Request, exc: PermissionError):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def _val(request: Request, exc: ValueError):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ---- settings & status ----------------------------------------------
    @app.get("/api/settings")
    def get_settings():
        from dataclasses import asdict

        return {"settings": asdict(st.settings), "zone_labels": ZONE_LABELS, "auth": st.auth_status()}

    @app.put("/api/settings")
    def put_settings(patch: dict = Body(...)):
        from dataclasses import asdict

        return {"settings": asdict(st.update_settings(patch)), "auth": st.auth_status()}

    @app.get("/api/zones/from-cadence")
    def zones_from_cadence(spm: int):
        if not 120 <= spm <= 220:
            raise HTTPException(400, "cadence should be 120-220")
        return {"ranges": {str(z): list(r) for z, r in ranges_from_cadence(spm).items()}}

    # ---- auth -----------------------------------------------------------
    @app.post("/api/auth/google/client")
    async def google_client(file: UploadFile = File(...)):
        data = json.loads(await file.read())
        c = data.get("web") or data.get("installed") or {}
        if not c.get("client_id") or not c.get("client_secret"):
            raise HTTPException(400, "That doesn't look like a Google OAuth client JSON file")
        p = st.dir / "google_client.json"
        p.write_text(json.dumps(data))
        p.chmod(0o600)
        return st.auth_status()

    @app.get("/api/auth/google/start")
    def google_start():
        return RedirectResponse(st.oauth.start_url())

    @app.get("/api/auth/google/callback")
    def google_callback(code: str = "", state: str = "", error: str = ""):
        if error:
            return RedirectResponse(f"/#settings?auth_error={error}")
        st.oauth.finish(code, state)
        st.update_settings({"mode": "youtube_data"})
        return RedirectResponse("/#settings?connected=google")

    @app.post("/api/auth/ytmusic")
    def ytmusic_setup(payload: dict = Body(...)):
        from .sources.ytmusic import setup_from_headers

        headers = payload.get("headers_raw", "")
        if "cookie" not in headers.lower():
            raise HTTPException(400, "Paste the full request headers, including the cookie line")
        setup_from_headers(headers, st.dir / "ytmusic_browser.json")
        st._sources.pop("ytmusic", None)
        st.update_settings({"mode": "ytmusic"})
        return st.auth_status()

    @app.post("/api/auth/intervals")
    def intervals_key(payload: dict = Body(...)):
        key = (payload.get("api_key") or "").strip()
        p = st.dir / "intervals_key.json"
        if not key:
            p.unlink(missing_ok=True)
        else:
            p.write_text(json.dumps({"api_key": key, "athlete_id": payload.get("athlete_id") or "0"}))
            p.chmod(0o600)
        return st.auth_status()

    @app.post("/api/auth/disconnect")
    def disconnect(payload: dict = Body(...)):
        which = payload.get("which")
        if which == "google":
            st.oauth.disconnect()
        elif which == "ytmusic":
            (st.dir / "ytmusic_browser.json").unlink(missing_ok=True)
            st._sources.pop("ytmusic", None)
        return st.auth_status()

    # ---- workouts -------------------------------------------------------
    @app.post("/api/workout/parse")
    def workout_parse(payload: dict = Body(...)):
        try:
            if "spec" in payload:
                w = parse_spec(payload["spec"], payload.get("name") or "Workout")
            else:
                w = workout_from_dict(payload["workout"])
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e))
        return {"workout": w.to_dict(), "blocks": _blocks(w)}

    def _blocks(w):
        from .planner import build_blocks

        return [b.to_dict() for b in build_blocks(w, st.settings.plan_options())]

    @app.post("/api/workout/fit")
    async def workout_fit(file: UploadFile = File(...)):
        try:
            w = workout_from_fit(await file.read(), st.settings.import_settings())
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"workout": w.to_dict(), "blocks": _blocks(w)}

    def _intervals():
        from .intervals_icu import IntervalsIcu

        p = st.dir / "intervals_key.json"
        if not p.exists():
            raise HTTPException(409, "Add your Intervals.icu API key in Settings first")
        cfg = json.loads(p.read_text())
        return IntervalsIcu(cfg["api_key"], cfg.get("athlete_id", "0"))

    @app.get("/api/intervals/events")
    def intervals_events(days: int = 14):
        return {"events": _intervals().planned_runs(days)}

    @app.get("/api/intervals/events/{event_id}")
    def intervals_workout(event_id: str):
        w = _intervals().workout(event_id, st.settings.import_settings())
        return {"workout": w.to_dict(), "blocks": _blocks(w)}

    # ---- library --------------------------------------------------------
    @app.post("/api/library/sync")
    def library_sync(payload: dict = Body(default={})):
        st.source()  # surfaces auth errors immediately
        st.start_sync(bool(payload.get("refresh_unknown")))
        return st.sync_status

    @app.get("/api/library/status")
    def library_status():
        return st.sync_status

    @app.get("/api/library")
    def library():
        zones = st.settings.zone_map()
        out = []
        for t in st.liked_tracks():
            d = t.to_dict()
            d["zones"] = [z for z in range(1, 6) if zones.effective_bpm(t.bpm, z)]
            out.append(d)
        cov = {str(z): sum(t.duration_s for t in st.liked_tracks() if zones.effective_bpm(t.bpm, z))
               for z in range(1, 6)}
        return {"tracks": out, "coverage_s": cov, "mode": st.settings.mode,
                "recommendations": len(st.recs)}

    @app.put("/api/library/bpm")
    def set_bpm(payload: dict = Body(...)):
        bpm = payload.get("bpm")
        st.set_bpm(payload["key"], float(bpm) if bpm not in (None, "") else None)
        t = st.track(payload["key"])
        return {"track": t.to_dict()}

    # ---- planning -------------------------------------------------------
    @app.post("/api/plan")
    def plan(payload: dict = Body(...)):
        w = _workout(payload)
        p = st.make_plan(w, payload.get("locked"), payload.get("seed"))
        return p.to_dict()

    @app.post("/api/plan/retime")
    def plan_retime(payload: dict = Body(...)):
        return st.retime(_workout(payload), payload["items"]).to_dict()

    @app.post("/api/plan/alternatives")
    def plan_alternatives(payload: dict = Body(...)):
        return {"alternatives": st.alternatives(_workout(payload), payload["items"], int(payload["index"]))}

    @app.post("/api/plan/search")
    def plan_search(payload: dict = Body(...)):
        """Search your liked songs and recommendations by text, for manual replacement."""
        q = (payload.get("q") or "").lower().strip()
        zones = st.settings.zone_map()
        res = [t for t in st.pool() if q and (q in t.title.lower() or q in t.artist.lower())][:30]
        return {"results": [dict(t.to_dict(), zones=[z for z in range(1, 6) if zones.effective_bpm(t.bpm, z)])
                            for t in res]}

    @app.post("/api/plan/export.csv", response_class=PlainTextResponse)
    def plan_export(payload: dict = Body(...)):
        return PlainTextResponse(export_csv(st.retime(_workout(payload), payload["items"])), media_type="text/csv")

    @app.post("/api/playlist/save")
    def playlist_save(payload: dict = Body(...)):
        return st.save_playlist(_workout(payload), payload["items"], payload.get("title"))

    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description="Runna → YouTube Music workout playlist web app")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data-dir", help="where settings, caches and tokens are kept (default ~/.runna-playlist)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    state = AppState(args.data_dir, base_url=f"http://localhost:{args.port}")
    print(f"\n  Open http://localhost:{args.port}\n")
    uvicorn.run(create_app(state), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
