"""Chronicle: turns the event stream into a readable markdown history.

Major events (wars, peace, capitulations, uprisings, eliminations,
leader successions, capital falls, alliances) are appended to a markdown
file as they happen — a living history of the planet you can read later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy.engine import StrategyEngine

MAJOR_TYPES = {
    "genesis", "war", "peace", "vassal", "independence", "rebellion",
    "elimination", "leader", "capital", "alliance", "alliance_end", "schism",
    "heritage",
}

ICONS = {
    "genesis": "🌍", "war": "⚔️", "peace": "🕊️", "vassal": "⛓️",
    "independence": "🔥", "rebellion": "✊", "elimination": "💀",
    "leader": "👑", "capital": "🏛️", "alliance": "🤝", "alliance_end": "💔",
    "schism": "🪓", "heritage": "📜", "city_state": "🏙️",
}


class Chronicle:
    """Appends major events to a markdown chronicle file."""

    def __init__(self, path: str, flush_every: int = 20):
        self.path = Path(path)
        self.flush_every = flush_every
        self._last_event_id = 0
        self._buffer: List[str] = []
        self._year_written = -1
        if not self.path.exists():
            self.path.write_text(
                "# Chronicle of Coruscant\n\n"
                "*An automatic history, written as it happens.*\n",
                encoding="utf-8",
            )

    def collect(self, engine: "StrategyEngine") -> int:
        """Pull unseen major events from the engine. Returns count added."""
        added = 0
        for ev in engine.events:
            if ev.get("id", 0) <= self._last_event_id:
                continue
            self._last_event_id = max(self._last_event_id, ev.get("id", 0))
            if ev["type"] not in MAJOR_TYPES:
                continue
            self._buffer.append(self.format_event(ev))
            added += 1
        if len(self._buffer) >= self.flush_every:
            self.flush()
        return added

    @staticmethod
    def format_event(ev: Dict) -> str:
        icon = ICONS.get(ev["type"], "•")
        year, day = divmod(int(ev["tick"]), 365)
        stamp = f"Year {year + 1}, day {day + 1}"
        return f"- {icon} **{stamp}** — {ev['text']}"

    def flush(self) -> None:
        if not self._buffer:
            return
        with self.path.open("a", encoding="utf-8") as f:
            f.write("\n".join(self._buffer) + "\n")
        self._buffer.clear()


def drain_major_events(engine: "StrategyEngine", after_id: int) -> List[Dict]:
    """Major events with id > after_id (for notifiers)."""
    return [ev for ev in engine.events
            if ev.get("id", 0) > after_id and ev["type"] in MAJOR_TYPES]
