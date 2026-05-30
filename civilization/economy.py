"""
Economy Layer — Phase 3

Each grid cell has a specialization that drives resource production.
An EconomyController runs each step:
  1. Production: cells generate food/water/energy based on specialization + tech
  2. Consumption: population draws from local reserves
  3. Trade flow: surplus diffuses toward deficit cells across the grid
     (gradient flow — no explicit trade routes, emergent from diffusion)

Specialization enum
-------------------
AGRICULTURE  → high food production
INDUSTRY     → high energy production
COMMERCE     → trade efficiency bonus (amplifies diffusion)
MILITARY     → security bonus (dampens unrest, slight energy draw)
RESIDENTIAL  → balanced; moderate consumption, slight food draw

Units
-----
food_reserve   : days of supply at current consumption rate
water_avail    : litres per capita per day (stored surplus)
energy_avail   : kWh per capita per day (stored surplus)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, List

import numpy as np

if TYPE_CHECKING:
    from simulate_coruscant import CoruscantCivilization


# ---------------------------------------------------------------------------
# Specialization
# ---------------------------------------------------------------------------

class Spec(IntEnum):
    AGRICULTURE = 0
    INDUSTRY    = 1
    COMMERCE    = 2
    MILITARY    = 3
    RESIDENTIAL = 4


# Production rates per specialization [food_delta, water_delta, energy_delta]
# Units: increments per step per cell (averaged over pop)
_PROD = np.array([
    # food   water  energy
    [  2.0,   0.5,   0.5],   # AGRICULTURE
    [  0.2,   0.3,   3.0],   # INDUSTRY
    [  0.5,   0.5,   1.0],   # COMMERCE
    [  0.2,   0.3,   1.5],   # MILITARY
    [  0.8,   0.6,   0.8],   # RESIDENTIAL
], dtype=np.float64)

# Consumption rates per step (subtracted from reserves)
FOOD_CONSUMPTION   = 1.0    # days consumed per step
WATER_CONSUMPTION  = 0.8    # L/cap/day consumed per step
ENERGY_CONSUMPTION = 1.2    # kWh/cap/day consumed per step

# Trade diffusion parameters
TRADE_DIFFUSION_RATE  = 0.04   # fraction of surplus that spreads to neighbours per step
COMMERCE_BOOST        = 1.6    # multiplier on diffusion for COMMERCE cells

# Caps
FOOD_CAP   = 90.0
WATER_CAP  = 60.0
ENERGY_CAP = 300.0


# ---------------------------------------------------------------------------
# Economy state per faction (aggregated)
# ---------------------------------------------------------------------------

@dataclass
class FactionEconomy:
    faction_id: int
    name: str
    gdp_index: float = 1.0        # composite economic health 0..∞
    trade_volume: float = 0.0     # total resources traded this step
    food_produced: float = 0.0
    energy_produced: float = 0.0


# ---------------------------------------------------------------------------
# EconomyController
# ---------------------------------------------------------------------------

class EconomyController:
    """Manages per-cell specialization and economic flows."""

    def __init__(self, civ: "CoruscantCivilization", seed: int = 0) -> None:
        self.civ = civ
        rng = np.random.default_rng(seed)
        n_lat, n_lon = civ.n_lat, civ.n_lon

        # Assign specialization: faction's primary spec + local noise
        self.specialization: np.ndarray = self._init_specialization(rng)

        # Per-faction economy state
        self.faction_economies: List[FactionEconomy] = [
            FactionEconomy(faction_id=f.faction_id, name=f.name)
            for f in civ.factions
        ]

    # ------------------------------------------------------------------

    def _init_specialization(self, rng: np.random.Generator) -> np.ndarray:
        """Seed specialization from faction identity + spatial noise."""
        civ = self.civ
        # Map faction → primary spec (index into Spec enum)
        faction_primary = {
            0: Spec.RESIDENTIAL,    # Senate District
            1: Spec.INDUSTRY,       # Industrial Sector
            2: Spec.COMMERCE,       # Commerce Ring
            3: Spec.RESIDENTIAL,    # Underworld (crowded residential)
            4: Spec.MILITARY,       # Military Zone
        }
        spec = np.full((civ.n_lat, civ.n_lon), Spec.RESIDENTIAL, dtype=np.int32)
        for fid, primary in faction_primary.items():
            mask = civ.faction_id == fid
            spec[mask] = int(primary)

        # Add agriculture pockets (10% random cells)
        agri_mask = rng.random((civ.n_lat, civ.n_lon)) < 0.10
        spec[agri_mask] = int(Spec.AGRICULTURE)

        # Add commerce clusters near faction borders (approximate via erosion noise)
        commerce_noise = rng.random((civ.n_lat, civ.n_lon)) < 0.05
        spec[commerce_noise] = int(Spec.COMMERCE)

        return spec

    # ------------------------------------------------------------------

    def step(self) -> None:
        civ = self.civ
        self._produce()
        self._consume()
        self._trade_diffusion()
        self._military_security()
        self._update_faction_economies()

    # ------------------------------------------------------------------

    def _produce(self) -> None:
        """Each cell produces resources according to its specialization."""
        civ = self.civ
        spec = self.specialization

        # Vectorised lookup: production rates for each cell
        food_prod   = _PROD[spec, 0]
        water_prod  = _PROD[spec, 1]
        energy_prod = _PROD[spec, 2]

        # Scale by faction tech level
        tech = np.ones((civ.n_lat, civ.n_lon), dtype=np.float64)
        for f in civ.factions:
            tech[civ.faction_id == f.faction_id] = f.tech_level

        civ.food_reserve  = np.clip(civ.food_reserve  + food_prod   * tech, 0, FOOD_CAP)
        civ.water_avail   = np.clip(civ.water_avail   + water_prod  * tech, 0, WATER_CAP)
        civ.energy_avail  = np.clip(civ.energy_avail  + energy_prod * tech, 0, ENERGY_CAP)

    def _consume(self) -> None:
        """Population consumes resources; scales with log(pop) to avoid runaway."""
        civ = self.civ
        # Consumption is flat per cell (represents per-capita * avg density)
        civ.food_reserve  = np.clip(civ.food_reserve  - FOOD_CONSUMPTION,   0, FOOD_CAP)
        civ.water_avail   = np.clip(civ.water_avail   - WATER_CONSUMPTION,  0, WATER_CAP)
        civ.energy_avail  = np.clip(civ.energy_avail  - ENERGY_CONSUMPTION, 0, ENERGY_CAP)

    def _trade_diffusion(self) -> None:
        """
        Surplus resources diffuse toward deficit cells.
        COMMERCE cells have boosted diffusion rate.
        Diffusion is applied on each resource independently via
        a simple 4-neighbour Laplacian spread.
        """
        civ = self.civ
        commerce_mask = (self.specialization == int(Spec.COMMERCE)).astype(np.float64)
        rate_grid = TRADE_DIFFUSION_RATE * (1.0 + (COMMERCE_BOOST - 1.0) * commerce_mask)

        for arr, cap in (
            (civ.food_reserve,  FOOD_CAP),
            (civ.water_avail,   WATER_CAP),
            (civ.energy_avail,  ENERGY_CAP),
        ):
            lap = _laplacian(arr)
            # Only positive laplacian = flow from surplus → deficit
            flow = rate_grid * lap
            np.clip(arr + flow, 0, cap, out=arr)

    def _military_security(self) -> None:
        """MILITARY cells slowly reduce unrest and draw slight energy."""
        civ = self.civ
        mil_mask = self.specialization == int(Spec.MILITARY)
        if mil_mask.any():
            civ.unrest[mil_mask] = np.clip(civ.unrest[mil_mask] - 0.005, 0, 1)
            civ.energy_avail[mil_mask] = np.clip(
                civ.energy_avail[mil_mask] - 0.3, 0, ENERGY_CAP
            )

    def _update_faction_economies(self) -> None:
        """Compute GDP index and trade volume for each faction."""
        civ = self.civ
        for fe in self.faction_economies:
            mask = civ.faction_id == fe.faction_id
            if not mask.any():
                continue
            food_score   = float(civ.food_reserve[mask].mean())   / FOOD_CAP
            water_score  = float(civ.water_avail[mask].mean())    / WATER_CAP
            energy_score = float(civ.energy_avail[mask].mean())   / ENERGY_CAP
            fe.gdp_index = (food_score * 0.3 + water_score * 0.3 + energy_score * 0.4) * 2.0
            fe.food_produced   = float((_PROD[self.specialization[mask], 0]).sum())
            fe.energy_produced = float((_PROD[self.specialization[mask], 2]).sum())

    # ------------------------------------------------------------------

    def summary(self) -> list:
        return [
            {
                "id":             fe.faction_id,
                "name":           fe.name,
                "gdp_index":      round(fe.gdp_index, 3),
                "trade_volume":   round(fe.trade_volume, 1),
                "food_produced":  round(fe.food_produced, 1),
                "energy_produced": round(fe.energy_produced, 1),
            }
            for fe in self.faction_economies
        ]

    def specialization_counts(self) -> dict:
        """Returns cell count per specialization name."""
        counts = {}
        for s in Spec:
            counts[s.name] = int((self.specialization == int(s)).sum())
        return counts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _laplacian(arr: np.ndarray) -> np.ndarray:
    """4-neighbour discrete Laplacian with wrap-around on longitude axis."""
    n = np.roll(arr, 1, axis=0)
    s = np.roll(arr, -1, axis=0)
    w = np.roll(arr, 1, axis=1)
    e = np.roll(arr, -1, axis=1)
    # Clamp poles (no wrap)
    n[0]  = arr[1]
    s[-1] = arr[-2]
    return (n + s + w + e) / 4.0 - arr
