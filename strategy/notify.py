"""Optional webhook notifier: posts major events to Discord and/or Telegram.

No external dependencies — plain urllib. Configure via CLI flags of
rts_server.py or environment variables:

    CORUSCANT_DISCORD_WEBHOOK = https://discord.com/api/webhooks/...
    CORUSCANT_TELEGRAM_TOKEN  = 123456:ABC-DEF...
    CORUSCANT_TELEGRAM_CHAT   = -1001234567890

Events are batched (default: one message per 30 s max) so a busy war
doesn't flood the channel.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Dict, List, Optional

from strategy.chronicle import ICONS


def format_batch(events: List[Dict], tick: int) -> str:
    """Human-readable digest of a batch of major events."""
    lines = []
    for ev in events[:12]:
        icon = ICONS.get(ev["type"], "•")
        year, day = divmod(int(ev["tick"]), 365)
        lines.append(f"{icon} [Y{year + 1} d{day + 1}] {ev['text']}")
    if len(events) > 12:
        lines.append(f"... and {len(events) - 12} more events")
    return "\n".join(lines)


class Notifier:
    def __init__(self,
                 discord_webhook: Optional[str] = None,
                 telegram_token: Optional[str] = None,
                 telegram_chat: Optional[str] = None,
                 min_interval_s: float = 30.0):
        self.discord_webhook = discord_webhook or os.environ.get("CORUSCANT_DISCORD_WEBHOOK")
        self.telegram_token = telegram_token or os.environ.get("CORUSCANT_TELEGRAM_TOKEN")
        self.telegram_chat = telegram_chat or os.environ.get("CORUSCANT_TELEGRAM_CHAT")
        self.min_interval_s = min_interval_s
        self._pending: List[Dict] = []
        self._last_sent = 0.0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.discord_webhook or (self.telegram_token and self.telegram_chat))

    # ------------------------------------------------------------------

    def queue(self, events: List[Dict]) -> None:
        if not self.enabled or not events:
            return
        with self._lock:
            self._pending.extend(events)

    def maybe_send(self, tick: int) -> None:
        """Send the pending batch if the rate limit allows. Non-blocking."""
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            if not self._pending or now - self._last_sent < self.min_interval_s:
                return
            batch = self._pending[:]
            self._pending.clear()
            self._last_sent = now
        text = format_batch(batch, tick)
        threading.Thread(target=self._send_all, args=(text,), daemon=True).start()

    # ------------------------------------------------------------------

    def _send_all(self, text: str) -> None:
        if self.discord_webhook:
            self._post_json(self.discord_webhook, {"content": text[:1990]})
        if self.telegram_token and self.telegram_chat:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            self._post_json(url, {"chat_id": self.telegram_chat,
                                  "text": text[:4000]})

    @staticmethod
    def _post_json(url: str, payload: dict) -> None:
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "User-Agent": "CoruscantSim/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as exc:                      # never crash the sim
            print(f"[notify] delivery failed: {exc}", flush=True)
