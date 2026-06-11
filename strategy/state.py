"""Mutable runtime state: factions and armies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from strategy.data import (
    BALANCE, FACTIONS, TECH_BRANCHES, TECH_COST_BASE, TECH_COST_GROWTH,
    MIL_ATTACK_PER_TIER, MIL_DEFENSE_PER_TIER, UNITS,
)


@dataclass
class FactionRuntime:
    fid: int
    name: str
    colour: str
    aggression: float
    greed: float
    curiosity: float

    alive: bool = True
    treasury: float = 600.0
    science: float = 0.0
    prod_pool: float = 0.0                 # accumulated factory points
    tech: Dict[str, int] = field(default_factory=lambda: {b: 0 for b in TECH_BRANCHES})
    research_target: str = "economy"
    doctrine: str = "develop"              # develop|expand|militarize|science|defend
    doctrine_age: int = 0
    capital: int = -1                      # region id
    war_weariness: Dict[int, float] = field(default_factory=dict)  # per enemy fid

    # rolling metrics for AI + charts
    income: float = 0.0
    food_balance: float = 0.0
    military_power: float = 0.0
    gdp: float = 0.0

    def tech_cost(self, branch: str) -> float:
        tier = self.tech[branch]
        return TECH_COST_BASE * (TECH_COST_GROWTH ** tier)

    def attack_mult(self) -> float:
        return 1.0 + MIL_ATTACK_PER_TIER * self.tech["military"]

    def defense_mult(self) -> float:
        return 1.0 + MIL_DEFENSE_PER_TIER * self.tech["military"]


def make_factions() -> List[FactionRuntime]:
    return [
        FactionRuntime(
            fid=f.fid, name=f.name, colour=f.colour,
            aggression=f.aggression, greed=f.greed, curiosity=f.curiosity,
        )
        for f in FACTIONS
    ]


# ---------------------------------------------------------------------------
# Armies
# ---------------------------------------------------------------------------

_ARMY_SEQ = [0]


@dataclass
class Army:
    aid: int
    fid: int
    location: int                          # current region id
    composition: Dict[str, int] = field(default_factory=dict)
    path: List[int] = field(default_factory=list)   # remaining regions to visit
    move_progress: int = 0                 # ticks spent on current link
    stance: str = "garrison"               # garrison|attack|expand|defend
    in_battle: bool = False

    @staticmethod
    def new(fid: int, location: int, composition: Dict[str, int],
            stance: str = "garrison") -> "Army":
        _ARMY_SEQ[0] += 1
        return Army(aid=_ARMY_SEQ[0], fid=fid, location=location,
                    composition=dict(composition), stance=stance)

    # ------------------------------------------------------------------

    def size(self) -> int:
        return sum(self.composition.values())

    def attack_power(self, mult: float = 1.0) -> float:
        return mult * sum(UNITS[k].attack * n for k, n in self.composition.items())

    def defense_power(self, mult: float = 1.0) -> float:
        return mult * sum(UNITS[k].defense * n for k, n in self.composition.items())

    def move_ticks_per_link(self) -> int:
        if not self.composition:
            return 1
        return max(UNITS[k].move_ticks for k, n in self.composition.items() if n > 0)

    def upkeep(self) -> Dict[str, float]:
        food = sum(UNITS[k].upkeep_food * n for k, n in self.composition.items())
        credits = sum(UNITS[k].upkeep_credits * n for k, n in self.composition.items())
        return {"food": food, "credits": credits}

    def apply_losses(self, fraction: float) -> int:
        """Remove `fraction` of the army (proportional). Returns units lost."""
        lost = 0
        for k in list(self.composition.keys()):
            n = self.composition[k]
            dead = int(round(n * fraction))
            # at high fractions always lose at least one of the stack
            if dead == 0 and fraction > 0.25 and n > 0:
                dead = 1
            self.composition[k] = max(0, n - dead)
            lost += dead
            if self.composition[k] == 0:
                del self.composition[k]
        return lost

    def merge(self, other: "Army") -> None:
        for k, n in other.composition.items():
            self.composition[k] = self.composition.get(k, 0) + n

    def split_half(self) -> "Army":
        """Detach roughly half of this army into a new field army."""
        detached: Dict[str, int] = {}
        for k in list(self.composition.keys()):
            n = self.composition[k]
            take = n // 2
            if take > 0:
                detached[k] = take
                self.composition[k] = n - take
                if self.composition[k] == 0:
                    del self.composition[k]
        return Army.new(self.fid, self.location, detached, "expand")
