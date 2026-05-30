"""
Faction AI — Phase 2

Each faction runs a lightweight Behavior Tree each tick:

  Root (Selector)
  ├── Sequence: Survive          if any_critical_need → address it
  ├── Sequence: Expand           if stable + strong → claim adjacent cells
  ├── Sequence: Trade            if surplus resource → offer trade to neighbours
  └── Sequence: Consolidate      default — reinforce control, reduce unrest

Faction control evolves on the grid via an "influence" field [n_factions, n_lat, n_lon].
The faction with the highest influence in a cell is its controller.

Units
-----
influence   : dimensionless 0..∞  (decays + gained via adjacency/pop/resources)
strength    : dimensionless 0..1  (military/economic power of the faction)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from simulate_coruscant import CoruscantCivilization


# ---------------------------------------------------------------------------
# BT node status
# ---------------------------------------------------------------------------

class BTStatus(Enum):
    SUCCESS = auto()
    FAILURE = auto()
    RUNNING = auto()


# ---------------------------------------------------------------------------
# Faction runtime state (per-faction scalars updated each step)
# ---------------------------------------------------------------------------

@dataclass
class FactionState:
    faction_id: int
    name: str

    # aggregate resource totals across controlled cells (updated externally)
    total_food: float = 0.0
    total_water: float = 0.0
    total_energy: float = 0.0
    total_population: float = 0.0
    controlled_cells: int = 0

    # derived per-capita averages
    food_per_cap: float = 30.0
    water_per_cap: float = 20.0
    energy_per_cap: float = 60.0

    # strategic state
    strength: float = 0.5          # 0..1
    expansion_pressure: float = 0.0
    trade_surplus: float = 0.0

    # BT memory
    last_action: str = "consolidate"
    action_count: Dict[str, int] = field(default_factory=dict)

    # personality (copied from Faction definition)
    aggression: float = 0.3
    trade_openness: float = 0.7
    tech_level: float = 0.5


# ---------------------------------------------------------------------------
# Behavior Tree nodes (simple functional implementation)
# ---------------------------------------------------------------------------

def _bt_survive(fs: FactionState, civ: "CoruscantCivilization") -> BTStatus:
    """Critical need response — boost imports/defences."""
    critical = (
        fs.food_per_cap < 5.0
        or fs.water_per_cap < 3.0
        or fs.energy_per_cap < 10.0
    )
    if not critical:
        return BTStatus.FAILURE

    # Survive action: dump resources into the most critical need
    mask = civ.faction_id == fs.faction_id
    if fs.food_per_cap < 5.0:
        civ.food_reserve[mask] = np.clip(
            civ.food_reserve[mask] + fs.tech_level * 3.0, 0, 90
        )
    if fs.water_per_cap < 3.0:
        civ.water_avail[mask] = np.clip(
            civ.water_avail[mask] + fs.tech_level * 2.0, 0, 60
        )
    if fs.energy_per_cap < 10.0:
        civ.energy_avail[mask] = np.clip(
            civ.energy_avail[mask] + fs.tech_level * 5.0, 0, 300
        )

    fs.last_action = "survive"
    fs.action_count["survive"] = fs.action_count.get("survive", 0) + 1
    return BTStatus.SUCCESS


def _bt_expand(
    fs: FactionState,
    civ: "CoruscantCivilization",
    influence: np.ndarray,
) -> BTStatus:
    """
    Expand into adjacent cells if faction is strong and aggressive.
    Influence bleeds outward from controlled territory proportional to
    strength × aggression.
    """
    # Gate: only expand when stable and strong
    if fs.strength < 0.4 or fs.food_per_cap < 10.0:
        return BTStatus.FAILURE
    if fs.aggression < 0.25 and fs.expansion_pressure < 0.3:
        return BTStatus.FAILURE

    fid = fs.faction_id
    own_influence = influence[fid]

    # Compute adjacency bleed: own influence spreads to 4-neighbours
    n = np.roll(own_influence, 1, axis=0)
    s = np.roll(own_influence, -1, axis=0)
    w = np.roll(own_influence, 1, axis=1)
    e = np.roll(own_influence, -1, axis=1)
    # Clamp poles
    n[0] = own_influence[1]
    s[-1] = own_influence[-2]

    bleed_rate = 0.02 * fs.strength * fs.aggression
    influence[fid] += bleed_rate * (n + s + w + e) / 4.0

    fs.last_action = "expand"
    fs.action_count["expand"] = fs.action_count.get("expand", 0) + 1
    return BTStatus.SUCCESS


def _bt_trade(
    fs: FactionState,
    civ: "CoruscantCivilization",
    all_states: List[FactionState],
) -> BTStatus:
    """
    If this faction has a resource surplus, share a fraction with the
    most deficit faction that borders it (simplified: global trade).
    """
    if fs.trade_openness < 0.4 or fs.trade_surplus < 5.0:
        return BTStatus.FAILURE

    # Find the most needy other faction
    most_needy: Optional[FactionState] = None
    worst_food = fs.food_per_cap
    for other in all_states:
        if other.faction_id == fs.faction_id:
            continue
        if other.food_per_cap < worst_food and other.trade_openness > 0.3:
            worst_food = other.food_per_cap
            most_needy = other

    if most_needy is None:
        return BTStatus.FAILURE

    # Transfer a fraction of surplus food
    transfer = min(fs.trade_surplus * 0.1 * fs.trade_openness, 5.0)
    donor_mask = civ.faction_id == fs.faction_id
    recv_mask = civ.faction_id == most_needy.faction_id

    if donor_mask.any() and recv_mask.any():
        civ.food_reserve[donor_mask] = np.clip(
            civ.food_reserve[donor_mask] - transfer * 0.5, 0, None
        )
        civ.food_reserve[recv_mask] = np.clip(
            civ.food_reserve[recv_mask] + transfer, 0, 90
        )

    fs.last_action = "trade"
    fs.action_count["trade"] = fs.action_count.get("trade", 0) + 1
    return BTStatus.SUCCESS


def _bt_consolidate(
    fs: FactionState,
    civ: "CoruscantCivilization",
    influence: np.ndarray,
) -> BTStatus:
    """Default: reinforce own cells, dampen unrest, decay border influence."""
    mask = civ.faction_id == fs.faction_id

    # Reduce unrest in controlled cells proportional to tech
    civ.unrest[mask] = np.clip(
        civ.unrest[mask] - 0.01 * fs.tech_level, 0, 1
    )

    # Strengthen own influence in controlled cells
    influence[fs.faction_id][mask] += 0.05 * fs.strength

    fs.last_action = "consolidate"
    fs.action_count["consolidate"] = fs.action_count.get("consolidate", 0) + 1
    return BTStatus.SUCCESS


def run_faction_bt(
    fs: FactionState,
    civ: "CoruscantCivilization",
    influence: np.ndarray,
    all_states: List[FactionState],
) -> str:
    """
    Execute the faction Behavior Tree.
    Selector: try each branch in priority order, return on first SUCCESS.
    """
    for branch in (
        lambda: _bt_survive(fs, civ),
        lambda: _bt_expand(fs, civ, influence),
        lambda: _bt_trade(fs, civ, all_states),
        lambda: _bt_consolidate(fs, civ, influence),
    ):
        status = branch()
        if status == BTStatus.SUCCESS:
            return fs.last_action

    return "idle"


# ---------------------------------------------------------------------------
# Influence field manager
# ---------------------------------------------------------------------------

class FactionController:
    """
    Manages the influence grid [n_factions, n_lat, n_lon] and
    updates faction_id on the civilization grid each step.
    """

    INFLUENCE_DECAY = 0.98        # per step decay
    INFLUENCE_POP_BONUS = 1e-6    # population drives influence growth

    def __init__(self, civ: "CoruscantCivilization") -> None:
        self.civ = civ
        n_f = len(civ.factions)
        n_lat, n_lon = civ.n_lat, civ.n_lon

        # Seed influence from initial Voronoi assignment
        self.influence = np.zeros((n_f, n_lat, n_lon), dtype=np.float64)
        for f in civ.factions:
            fid = f.faction_id
            self.influence[fid][civ.faction_id == fid] = 1.0

        # Build runtime states
        self.states: List[FactionState] = [
            FactionState(
                faction_id=f.faction_id,
                name=f.name,
                aggression=f.aggression,
                trade_openness=f.trade_openness,
                tech_level=f.tech_level,
            )
            for f in civ.factions
        ]

        # Action log for diagnostics
        self.action_log: List[Dict[str, str]] = []

    # ------------------------------------------------------------------

    def step(self) -> None:
        civ = self.civ
        self._update_states()
        self._decay_influence()
        self._population_pressure()

        actions: Dict[str, str] = {}
        for fs in self.states:
            action = run_faction_bt(fs, civ, self.influence, self.states)
            actions[fs.name] = action

        self._resolve_control()
        self.action_log.append(actions)

    # ------------------------------------------------------------------

    def _update_states(self) -> None:
        """Aggregate per-faction resource totals from the civilization grid."""
        civ = self.civ
        for fs in self.states:
            mask = civ.faction_id == fs.faction_id
            n_cells = int(mask.sum())
            if n_cells == 0:
                fs.controlled_cells = 0
                continue

            fs.controlled_cells = n_cells
            fs.total_population = float(civ.population[mask].sum())
            pop = max(fs.total_population, 1.0)

            fs.food_per_cap = float(civ.food_reserve[mask].mean())
            fs.water_per_cap = float(civ.water_avail[mask].mean())
            fs.energy_per_cap = float(civ.energy_avail[mask].mean())

            # Strength: composite of resources + tech - unrest
            res_score = (
                min(fs.food_per_cap / 30.0, 1.0) * 0.4
                + min(fs.water_per_cap / 20.0, 1.0) * 0.3
                + min(fs.energy_per_cap / 60.0, 1.0) * 0.3
            )
            unrest_penalty = float(civ.unrest[mask].mean())
            fs.strength = float(np.clip(
                0.7 * fs.strength + 0.3 * (res_score * (1.0 - unrest_penalty * 0.5)),
                0.0, 1.0,
            ))

            # Trade surplus: positive food above threshold
            surplus_cells = civ.food_reserve[mask] - 20.0
            fs.trade_surplus = float(surplus_cells.clip(0).sum())

            # Expansion pressure: happiness gradient across border
            own_happiness = float(civ.happiness[mask].mean())
            border_happiness = self._border_happiness(fs.faction_id)
            fs.expansion_pressure = float(np.clip(
                border_happiness - own_happiness + 0.1 * fs.aggression,
                0.0, 1.0,
            ))

    def _border_happiness(self, fid: int) -> float:
        """Mean happiness of cells adjacent to this faction's territory."""
        civ = self.civ
        own_mask = (civ.faction_id == fid)
        adj = (
            np.roll(own_mask, 1, axis=0)
            | np.roll(own_mask, -1, axis=0)
            | np.roll(own_mask, 1, axis=1)
            | np.roll(own_mask, -1, axis=1)
        )
        border = adj & ~own_mask
        if not border.any():
            return 0.5
        return float(civ.happiness[border].mean())

    def _decay_influence(self) -> None:
        self.influence *= self.INFLUENCE_DECAY
        # Clip to avoid runaway
        np.clip(self.influence, 0.0, 100.0, out=self.influence)

    def _population_pressure(self) -> None:
        """Dense population strengthens home faction influence."""
        civ = self.civ
        pop_norm = np.log1p(civ.population) / 15.0  # ~0..1 range
        for fs in self.states:
            mask = civ.faction_id == fs.faction_id
            self.influence[fs.faction_id][mask] += (
                self.INFLUENCE_POP_BONUS * pop_norm[mask] * fs.strength
            )

    def _resolve_control(self) -> None:
        """Assign each cell to the faction with highest influence."""
        # argmax over faction axis → new controller
        new_control = np.argmax(self.influence, axis=0).astype(np.int32)
        self.civ.faction_id[:] = new_control

    # ------------------------------------------------------------------

    def summary(self) -> List[Dict]:
        return [
            {
                "id": fs.faction_id,
                "name": fs.name,
                "cells": fs.controlled_cells,
                "strength": round(fs.strength, 3),
                "food_per_cap": round(fs.food_per_cap, 1),
                "last_action": fs.last_action,
                "trade_surplus": round(fs.trade_surplus, 1),
            }
            for fs in self.states
        ]
