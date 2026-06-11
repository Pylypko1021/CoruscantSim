"""Coruscant Autonomous RTS — live server.

Runs the StrategyEngine in a background thread and serves the
web viewer + JSON state API.

Usage:
    python rts_server.py [--port 8780] [--seed 42] [--no-physics] [--speed 2]

Endpoints:
    GET /                  -> web_viewer/rts.html
    GET /api/state         -> full live snapshot
    GET /api/region?id=N   -> region detail
    GET /api/speed?value=N -> set ticks per second (0 = pause)
    GET /api/save          -> save game to rts_save.json
    GET /api/reset?seed=N  -> restart simulation
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

SIM_DIR = Path(__file__).parent
sys.path.insert(0, str(SIM_DIR))

from strategy.engine import StrategyEngine, EngineConfig

WEB_DIR = SIM_DIR / "web_viewer"
SAVE_PATH = SIM_DIR / "rts_save.json"

_lock = threading.Lock()
_engine: StrategyEngine | None = None
_state_json: str = "{}"
_speed: float = 2.0          # ticks per second
_running = True
_restart_seed: int | None = None


def _refresh_state() -> None:
    global _state_json
    _state_json = json.dumps(_engine.snapshot())


def _sim_loop(seed: int, use_physics: bool) -> None:
    global _engine, _restart_seed
    with _lock:
        _engine = StrategyEngine(EngineConfig(seed=seed, use_physics=use_physics))
        _refresh_state()
    print(f"[sim] engine started (seed={seed}, physics={use_physics})", flush=True)

    while _running:
        speed = _speed
        if _restart_seed is not None:
            with _lock:
                _engine = StrategyEngine(
                    EngineConfig(seed=_restart_seed, use_physics=use_physics))
                _refresh_state()
                print(f"[sim] engine restarted (seed={_restart_seed})", flush=True)
                _restart_seed = None
            continue
        if speed <= 0:
            time.sleep(0.2)
            continue
        t0 = time.monotonic()
        with _lock:
            _engine.step()
            _refresh_state()
        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, 1.0 / speed - elapsed))


MIME = {
    ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
    ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".glb": "model/gltf-binary",
}


class RTSHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, payload: str, status: int = 200) -> None:
        b = payload.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def _file(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except (FileNotFoundError, PermissionError):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        global _speed, _restart_seed
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/api/state":
            with _lock:
                payload = _state_json
            self._json(payload)
            return

        if path == "/api/region":
            try:
                rid = int(qs.get("id", ["0"])[0])
                with _lock:
                    detail = _engine.region_detail(rid)
                self._json(json.dumps(detail))
            except (ValueError, IndexError):
                self._json('{"error": "bad region id"}', 400)
            return

        if path == "/api/speed":
            try:
                _speed = max(0.0, min(50.0, float(qs.get("value", ["2"])[0])))
                self._json(json.dumps({"ok": True, "speed": _speed}))
            except ValueError:
                self._json('{"error": "bad speed"}', 400)
            return

        if path == "/api/save":
            with _lock:
                _engine.save(str(SAVE_PATH))
            self._json(json.dumps({"ok": True, "path": SAVE_PATH.name}))
            return

        if path == "/api/reset":
            try:
                _restart_seed = int(qs.get("seed", ["42"])[0])
            except ValueError:
                _restart_seed = 42
            self._json(json.dumps({"ok": True, "seed": _restart_seed}))
            return

        if path == "/":
            self._file(WEB_DIR / "rts.html")
            return

        fpath = WEB_DIR / path.lstrip("/")
        if fpath.is_file() and WEB_DIR in fpath.resolve().parents:
            self._file(fpath)
        else:
            self.send_error(404)


def main() -> None:
    global _speed
    parser = argparse.ArgumentParser(description="Coruscant autonomous RTS server")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--speed", type=float, default=2.0, help="ticks per second")
    parser.add_argument("--no-physics", action="store_true")
    args = parser.parse_args()
    _speed = args.speed

    thread = threading.Thread(
        target=_sim_loop, args=(args.seed, not args.no_physics), daemon=True)
    thread.start()

    for _ in range(100):
        with _lock:
            if _engine is not None:
                break
        time.sleep(0.1)

    server = ThreadingHTTPServer(("localhost", args.port), RTSHandler)
    print(f"[server] Coruscant RTS at http://localhost:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        global _running
        _running = False
        print("\n[server] stopped")


if __name__ == "__main__":
    main()
