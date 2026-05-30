"""
Coruscant Simulation HTTP Server

Runs CoruscantSim in a background thread and serves live state via HTTP.

Usage:
    python sim_server.py [--port 8765] [--steps-per-tick 1] [--tick-interval 1.0]

Endpoints:
    GET /             → web_viewer/index.html
    GET /api/state    → live simulation state JSON
    GET /api/reset    → restart simulation
    GET /*            → static files from web_viewer/
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Ensure CoruscantSim imports work
SIM_DIR = Path(__file__).parent
sys.path.insert(0, str(SIM_DIR))

from simulate_coruscant import CoruscantCivilization, GRID_LAT, GRID_LON

WEB_DIR = SIM_DIR / "web_viewer"

# ---------------------------------------------------------------------------
# Simulation state (shared between threads, protected by a lock)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_civ: CoruscantCivilization | None = None
_state_json: str = "{}"
_running = True


def _build_state(civ: CoruscantCivilization) -> dict:
    """Serialise the parts of civ state that the web viewer needs."""
    import numpy as np

    summary = civ.summary()
    fsummary = civ.faction_summary()
    esummary = civ.economy_summary()

    # Downsample faction_id to 36×72 for JSON transfer (factor 2)
    fid = civ.faction_id[::2, ::2].tolist()

    # Downsample specialization
    spec = None
    if civ.specialization is not None:
        spec = civ.specialization[::2, ::2].tolist()

    # Downsample happiness & unrest to same size
    happiness = np.round(civ.happiness[::2, ::2], 3).tolist()
    unrest    = np.round(civ.unrest[::2, ::2], 3).tolist()

    return {
        "step":       civ.step_count,
        "grid_lat":   GRID_LAT // 2,
        "grid_lon":   GRID_LON // 2,
        "faction_id": fid,
        "specialization": spec,
        "happiness":  happiness,
        "unrest":     unrest,
        "summary":    summary,
        "factions":   fsummary,
        "economy":    esummary,
    }


def _sim_loop(steps_per_tick: int, tick_interval: float, seed: int) -> None:
    global _civ, _state_json, _running

    with _lock:
        _civ = CoruscantCivilization(seed=seed)
        _state_json = json.dumps(_build_state(_civ))

    print(f"[sim] CoruscantSim started (seed={seed})", flush=True)

    while _running:
        t0 = time.monotonic()
        with _lock:
            for _ in range(steps_per_tick):
                _civ.step()
            _state_json = json.dumps(_build_state(_civ))
            step = _civ.step_count

        elapsed = time.monotonic() - t0
        sleep_t = max(0.0, tick_interval - elapsed)
        if step % 10 == 0:
            print(f"[sim] step={step}", flush=True)
        time.sleep(sleep_t)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

MIME = {
    ".html": "text/html",
    ".js":   "application/javascript",
    ".css":  "text/css",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".npz":  "application/octet-stream",
}


class SimHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence access log
        pass

    def _send_json(self, data: str, status: int = 200) -> None:
        b = data.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def _send_file(self, path: Path) -> None:
        suffix = path.suffix.lower()
        mime = MIME.get(suffix, "application/octet-stream")
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, f"Not found: {path.name}")
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # API endpoints
        if path == "/api/state":
            with _lock:
                payload = _state_json
            self._send_json(payload)
            return

        if path == "/api/reset":
            global _civ
            with _lock:
                _civ = CoruscantCivilization(seed=42)
            self._send_json('{"ok": true}')
            return

        # Static files
        if path == "/" or path == "/index.html":
            self._send_file(WEB_DIR / "index.html")
            return

        # Map URL paths to filesystem
        file_path = WEB_DIR / path.lstrip("/")
        if file_path.is_file():
            self._send_file(file_path)
        else:
            self.send_error(404, f"Not found: {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Coruscant Simulation Server")
    parser.add_argument("--port",            type=int,   default=8765)
    parser.add_argument("--steps-per-tick",  type=int,   default=1,
                        help="Simulation steps per server tick")
    parser.add_argument("--tick-interval",   type=float, default=1.0,
                        help="Seconds between ticks")
    parser.add_argument("--seed",            type=int,   default=42)
    args = parser.parse_args()

    # Start simulation thread
    sim_thread = threading.Thread(
        target=_sim_loop,
        args=(args.steps_per_tick, args.tick_interval, args.seed),
        daemon=True,
    )
    sim_thread.start()

    # Wait for first state
    for _ in range(50):
        with _lock:
            ready = _civ is not None
        if ready:
            break
        time.sleep(0.1)

    server = HTTPServer(("localhost", args.port), SimHandler)
    print(f"[server] Coruscant viewer at http://localhost:{args.port}", flush=True)
    print(f"[server] Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        global _running
        _running = False
        print("\n[server] stopped")


if __name__ == "__main__":
    main()
