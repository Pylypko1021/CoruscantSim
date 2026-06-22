"""World map: the planet partitioned into strategic regions.

The 72x144 physics grid is grouped into 2x2 cell blocks -> 36x72 = 2592
regions. Regions are the atomic unit of ownership, construction, combat
and movement. Adjacency wraps in longitude.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

REGION_ROWS = 36
REGION_COLS = 72
N_REGIONS = REGION_ROWS * REGION_COLS

# scale factor vs the original 288-region world: balance constants that
# represent "a share of the planet" are multiplied by this in the engine
WORLD_SCALE = N_REGIONS / 288.0

GRID_LAT = 72
GRID_LON = 144
BLOCK = GRID_LAT // REGION_ROWS  # grid cells per region side


@dataclass
class Region:
    rid: int
    row: int
    col: int
    lat: float
    lon: float
    # static endowment
    materials_richness: float = 1.0
    energy_potential: float = 1.0
    fertility: float = 1.0          # updated by climate each tick
    # dynamic state
    owner: int = -1                  # faction id, -1 = neutral
    population: float = 50.0         # millions
    infrastructure: int = 0          # 0..5, +1 building slot each
    unrest: float = 0.1
    devastation: float = 0.0
    militia: float = 25.0            # neutral defenders
    entrenchment: float = 0.0        # defender bonus, grows while calm
    is_city_state: bool = False      # independent minor power (see CityState)
    buildings: Dict[str, int] = field(default_factory=dict)
    construction: List[Dict] = field(default_factory=list)   # {key, ticks_left}
    stock: Dict[str, float] = field(default_factory=lambda: {
        "materials": 40.0, "food": 80.0, "energy": 0.0,
    })

    def slots(self, infra_bonus: int = 0) -> int:
        return 2 + self.infrastructure + infra_bonus

    def used_slots(self) -> int:
        return sum(self.buildings.values()) + len(self.construction)


class WorldMap:
    """Region container + adjacency graph + climate coupling."""

    def __init__(self, rng: np.random.Generator):
        self.regions: List[Region] = []
        lat_centers = np.linspace(-89.0, 89.0, GRID_LAT).reshape(REGION_ROWS, BLOCK).mean(axis=1)
        lon_centers = np.linspace(0.0, 360.0, GRID_LON, endpoint=False).reshape(REGION_COLS, BLOCK).mean(axis=1)

        richness = rng.lognormal(mean=0.0, sigma=0.45, size=N_REGIONS)
        energy_pot = rng.uniform(0.6, 1.5, size=N_REGIONS)

        for row in range(REGION_ROWS):
            for col in range(REGION_COLS):
                rid = row * REGION_COLS + col
                lat = float(lat_centers[row])
                # polar regions are poor and sparsely populated
                polar = abs(lat) > 70.0
                reg = Region(
                    rid=rid, row=row, col=col,
                    lat=lat, lon=float(lon_centers[col]),
                    materials_richness=float(np.clip(richness[rid], 0.3, 3.0)),
                    energy_potential=float(energy_pot[rid]),
                    population=float(rng.uniform(5, 20) if polar else rng.uniform(30, 120)),
                    militia=float(rng.uniform(15, 40) * (0.5 if polar else 1.0)),
                )
                self.regions.append(reg)

        self._adjacency: List[List[int]] = self._build_adjacency()

    # ------------------------------------------------------------------

    def _build_adjacency(self) -> List[List[int]]:
        adj: List[List[int]] = []
        for rid in range(N_REGIONS):
            row, col = divmod(rid, REGION_COLS)
            neigh = []
            if row > 0:
                neigh.append((row - 1) * REGION_COLS + col)
            if row < REGION_ROWS - 1:
                neigh.append((row + 1) * REGION_COLS + col)
            neigh.append(row * REGION_COLS + (col - 1) % REGION_COLS)
            neigh.append(row * REGION_COLS + (col + 1) % REGION_COLS)
            adj.append(neigh)
        return adj

    def neighbours(self, rid: int) -> List[int]:
        return self._adjacency[rid]

    # ------------------------------------------------------------------

    def shortest_path(self, src: int, dst: int,
                      passable=None) -> Optional[List[int]]:
        """BFS path src -> dst. `passable(rid) -> bool` filters transit
        regions (dst is always allowed)."""
        if src == dst:
            return [src]
        from collections import deque
        prev = {src: -1}
        q = deque([src])
        while q:
            cur = q.popleft()
            for nxt in self._adjacency[cur]:
                if nxt in prev:
                    continue
                if nxt != dst and passable is not None and not passable(nxt):
                    continue
                prev[nxt] = cur
                if nxt == dst:
                    path = [dst]
                    while path[-1] != src:
                        path.append(prev[path[-1]])
                    return list(reversed(path))
                q.append(nxt)
        return None

    # ------------------------------------------------------------------

    def apply_climate(self, temp_k: np.ndarray, precip: np.ndarray) -> None:
        """Update per-region fertility from physics fields.

        Fields may be any (lat, lon) shape divisible into the region grid.
        """
        t = _downsample(temp_k)
        p = _downsample(precip)
        # comfort around 288K, fertility boosted by precipitation
        comfort = np.clip(1.0 - np.abs(t - 288.0) / 45.0, 0.05, 1.0)
        moisture = np.clip(0.5 + p / 8.0, 0.4, 1.6)
        fert = comfort * moisture
        flat = fert.flatten()
        for reg in self.regions:
            reg.fertility = float(np.clip(flat[reg.rid], 0.05, 2.0))

    def region_temp(self, temp_k: np.ndarray) -> np.ndarray:
        return _downsample(temp_k).flatten()

    # ------------------------------------------------------------------

    def owned_by(self, fid: int) -> List[Region]:
        return [r for r in self.regions if r.owner == fid]

    def border_regions(self, fid: int) -> List[Region]:
        out = []
        for reg in self.regions:
            if reg.owner != fid:
                continue
            for n in self._adjacency[reg.rid]:
                if self.regions[n].owner != fid:
                    out.append(reg)
                    break
        return out


def _downsample(field2d: np.ndarray) -> np.ndarray:
    """Mean-pool any (lat, lon) field onto the 12x24 region grid."""
    h, w = field2d.shape
    rh, rw = h // REGION_ROWS, w // REGION_COLS
    trimmed = field2d[: rh * REGION_ROWS, : rw * REGION_COLS]
    return trimmed.reshape(REGION_ROWS, rh, REGION_COLS, rw).mean(axis=(1, 3))
