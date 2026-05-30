"""
Coruscant Macro Population Layer — Phase 1 + 2 + 3

Phase 1: macro population, needs, happiness, unrest, migration.
Phase 2: faction Behavior Tree AI via FactionController.
Phase 3: economy layer — specialization, production, trade diffusion.

Units
-----
population       : people / km²  (macro density)
food_reserve     : days of supply per capita
energy_kwh_cap   : kWh per capita per day available
water_l_cap      : litres per capita per day available
happiness        : dimensionless  0..1
unrest           : dimensionless  0..1  (1 = revolution)
faction_id       : int  0..N-1 = faction index
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CORUSCANT_TOTAL_POP = 1_000_000_000_000  # 1 trillion — lore figure
GRID_LAT = 72
GRID_LON = 144
EARTH_RADIUS_KM = 6_371.0

# Needs thresholds (per capita per day)
FOOD_CRITICAL_DAYS = 3.0       # days of reserve below which starvation begins
WATER_CRITICAL_L = 2.0         # litres/day below which health collapses
ENERGY_CRITICAL_KWH = 5.0      # kWh/day below which infrastructure fails

# Comfort temperature band (Kelvin) — Coruscant is heavily climate-controlled
TEMP_COMFORT_MIN_K = 283.0     # 10 °C
TEMP_COMFORT_MAX_K = 303.0     # 30 °C

# Migration parameters
MIGRATION_RATE = 0.008         # fraction of pop that can move per step
MIGRATION_FLOW_CLIP = 0.25     # max fraction of cell pop that leaves per step

# Unrest dynamics
UNREST_DECAY = 0.94
UNREST_MEMORY = 0.06

# Faction colours for visualisation (R, G, B) 0..1
FACTION_COLOURS = [
    (0.20, 0.45, 0.85),   # 0 Senate District — blue
    (0.85, 0.20, 0.20),   # 1 Industrial Sector — red
    (0.20, 0.75, 0.30),   # 2 Commerce Ring — green
    (0.80, 0.60, 0.10),   # 3 Underworld — gold
    (0.55, 0.10, 0.75),   # 4 Military Zone — purple
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cell_area_km2(lats_deg: np.ndarray, dlat_deg: float, dlon_deg: float) -> np.ndarray:
    """Area of each lat/lon cell in km²."""
    lat_rad = np.radians(lats_deg)
    dlat_rad = np.radians(dlat_deg)
    dlon_rad = np.radians(dlon_deg)
    return EARTH_RADIUS_KM ** 2 * np.abs(np.cos(lat_rad)) * dlat_rad * dlon_rad


def _gradient_pressure(field: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Central-difference gradient (lat, lon), periodic in lon."""
    dlat = np.gradient(field, axis=0)
    dlon = np.gradient(np.roll(field, -1, axis=1), axis=1)
    return dlat, dlon


def _neighbour_mean(arr: np.ndarray) -> np.ndarray:
    """4-neighbour average; periodic in longitude."""
    n = np.roll(arr, 1, axis=0)
    s = np.roll(arr, -1, axis=0)
    w = np.roll(arr, 1, axis=1)
    e = np.roll(arr, -1, axis=1)
    n[0] = arr[1]
    s[-1] = arr[-2]
    return (n + s + w + e) / 4.0


# ---------------------------------------------------------------------------
# Faction definition
# ---------------------------------------------------------------------------

@dataclass
class Faction:
    faction_id: int
    name: str
    colour: Tuple[float, float, float]
    aggression: float = 0.3      # 0=pacifist, 1=war-hungry
    trade_openness: float = 0.7  # willingness to trade resources
    tech_level: float = 0.5      # affects energy/food production efficiency
    seed_lat: float = 0.0        # initial centre latitude
    seed_lon: float = 0.0        # initial centre longitude


def _default_factions() -> List[Faction]:
    return [
        Faction(0, "Senate District",   FACTION_COLOURS[0], aggression=0.1, trade_openness=0.9, tech_level=0.8,  seed_lat=10.0,  seed_lon=0.0),
        Faction(1, "Industrial Sector", FACTION_COLOURS[1], aggression=0.4, trade_openness=0.5, tech_level=0.6,  seed_lat=-20.0, seed_lon=90.0),
        Faction(2, "Commerce Ring",     FACTION_COLOURS[2], aggression=0.2, trade_openness=0.95,tech_level=0.7,  seed_lat=30.0,  seed_lon=180.0),
        Faction(3, "Underworld",        FACTION_COLOURS[3], aggression=0.7, trade_openness=0.3, tech_level=0.4,  seed_lat=-50.0, seed_lon=270.0),
        Faction(4, "Military Zone",     FACTION_COLOURS[4], aggression=0.6, trade_openness=0.4, tech_level=0.75, seed_lat=60.0,  seed_lon=135.0),
    ]


# ---------------------------------------------------------------------------
# Main simulation class
# ---------------------------------------------------------------------------

@dataclass
class CoruscantCivilization:
    """
    Macro population layer for Coruscant.

    Can run standalone (generates synthetic physics fields) or be driven by
    a live PlanetPhysicsSimulator instance via `attach_physics(sim)`.
    """

    n_lat: int = GRID_LAT
    n_lon: int = GRID_LON
    seed: int = 42
    factions: List[Faction] = field(default_factory=_default_factions)

    # internal state — initialised in __post_init__
    _rng: np.random.Generator = field(init=False, repr=False)
    _lats: np.ndarray = field(init=False, repr=False)
    _lons: np.ndarray = field(init=False, repr=False)
    _lat2d: np.ndarray = field(init=False, repr=False)
    _lon2d: np.ndarray = field(init=False, repr=False)
    _cell_area: np.ndarray = field(init=False, repr=False)

    # population grid  [people / km²]
    population: np.ndarray = field(init=False, repr=False)

    # resource grids  [per-capita per day]
    food_reserve: np.ndarray = field(init=False, repr=False)    # days of supply
    water_avail: np.ndarray = field(init=False, repr=False)     # l / cap / day
    energy_avail: np.ndarray = field(init=False, repr=False)    # kWh / cap / day

    # social grids  [0..1]
    happiness: np.ndarray = field(init=False, repr=False)
    unrest: np.ndarray = field(init=False, repr=False)

    # faction control  [int]
    faction_id: np.ndarray = field(init=False, repr=False)      # -1 = unclaimed

    # cached physics fields (updated each step or by physics sim)
    _surface_temp_k: np.ndarray = field(init=False, repr=False)
    _wind_u: np.ndarray = field(init=False, repr=False)
    _wind_v: np.ndarray = field(init=False, repr=False)
    _precipitation: np.ndarray = field(init=False, repr=False)

    # optional attached physics simulator
    _physics: Optional[object] = field(init=False, repr=False, default=None)

    # optional faction controller (Phase 2)
    _faction_ctrl: Optional[object] = field(init=False, repr=False, default=None)

    # optional economy controller (Phase 3)
    _economy_ctrl: Optional[object] = field(init=False, repr=False, default=None)

    # time counter
    step_count: int = field(init=False, default=0)

    # history for diagnostics
    history: Dict[str, List[float]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)

        self._lats = np.linspace(-89.0, 89.0, self.n_lat)
        self._lons = np.linspace(0.0, 360.0, self.n_lon, endpoint=False)
        self._lat2d, self._lon2d = np.meshgrid(self._lats, self._lons, indexing="ij")

        dlat = 178.0 / (self.n_lat - 1)
        dlon = 360.0 / self.n_lon
        self._cell_area = _cell_area_km2(self._lat2d, dlat, dlon)

        self._init_population()
        self._init_factions()
        self._init_resources()
        self._init_social()
        self._init_physics_cache()

        self.history = {
            "total_population": [],
            "mean_happiness": [],
            "mean_unrest": [],
            "mean_food_reserve_days": [],
            "mean_water_l_cap": [],
            "mean_energy_kwh_cap": [],
            "migration_flux": [],
        }

        # Auto-enable faction AI (Phase 2)
        self.enable_factions()

        # Auto-enable economy (Phase 3)
        self.enable_economy()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init_population(self) -> None:
        """
        Seed population with multi-modal distribution:
        high-density near equator + random hotspots (ecumenopolis pattern).
        """
        lat_factor = np.exp(-0.5 * (self._lat2d / 40.0) ** 2)  # equatorial bias

        # Several megacity seeds spread around the globe
        n_seeds = 12
        seeds_lat = self._rng.uniform(-60, 60, n_seeds)
        seeds_lon = self._rng.uniform(0, 360, n_seeds)
        city_map = np.zeros((self.n_lat, self.n_lon))
        for s_lat, s_lon in zip(seeds_lat, seeds_lon):
            dlat = self._lat2d - s_lat
            dlon = np.abs(self._lon2d - s_lon)
            dlon = np.minimum(dlon, 360.0 - dlon)   # wrap
            r2 = (dlat / 15.0) ** 2 + (dlon / 20.0) ** 2
            city_map += np.exp(-r2)

        city_map = city_map / city_map.max()
        base_density = 500_000.0  # people / km² — hyper-dense ecumenopolis

        noise = self._rng.normal(0.0, 0.05, (self.n_lat, self.n_lon))
        self.population = np.clip(
            base_density * (0.3 + 0.7 * city_map) * lat_factor + noise * 10_000,
            1.0,
            None,
        ).astype(np.float64)

    def _init_factions(self) -> None:
        """Assign faction control via Voronoi seeding."""
        self.faction_id = np.full((self.n_lat, self.n_lon), -1, dtype=np.int32)
        if not self.factions:
            return
        for lat_i, lat in enumerate(self._lats):
            for lon_j, lon in enumerate(self._lons):
                best_dist = np.inf
                best_fid = 0
                for f in self.factions:
                    dlat = lat - f.seed_lat
                    dlon = abs(lon - f.seed_lon)
                    dlon = min(dlon, 360.0 - dlon)
                    dist = dlat ** 2 + dlon ** 2
                    if dist < best_dist:
                        best_dist = dist
                        best_fid = f.faction_id
                self.faction_id[lat_i, lon_j] = best_fid

    def _init_resources(self) -> None:
        """
        Coruscant imports almost all food and water.
        Initial reserves proportional to infrastructure (faction tech level).
        """
        tech = self._tech_grid()
        self.food_reserve = np.clip(
            30.0 * tech + self._rng.normal(0, 2, (self.n_lat, self.n_lon)),
            1.0, 90.0,
        )
        self.water_avail = np.clip(
            20.0 * tech + self._rng.normal(0, 1, (self.n_lat, self.n_lon)),
            WATER_CRITICAL_L * 0.5, 50.0,
        )
        self.energy_avail = np.clip(
            80.0 * tech + self._rng.normal(0, 5, (self.n_lat, self.n_lon)),
            ENERGY_CRITICAL_KWH * 0.5, 200.0,
        )

    def _init_social(self) -> None:
        tech = self._tech_grid()
        self.happiness = np.clip(0.3 + 0.5 * tech, 0.0, 1.0)
        self.unrest = np.clip(0.1 + 0.3 * (1.0 - tech), 0.0, 1.0)

    def _init_physics_cache(self) -> None:
        """Synthetic physics fields used when no live simulator is attached."""
        lat_rad = np.radians(self._lat2d)
        self._surface_temp_k = (
            300.0 - 20.0 * np.abs(np.sin(lat_rad))
            + self._rng.normal(0, 2, (self.n_lat, self.n_lon))
        )
        self._wind_u = self._rng.normal(0, 5, (self.n_lat, self.n_lon))
        self._wind_v = self._rng.normal(0, 3, (self.n_lat, self.n_lon))
        self._precipitation = np.clip(
            self._rng.exponential(5.0, (self.n_lat, self.n_lon)), 0, 30
        )

    # ------------------------------------------------------------------
    # Utility grids derived from faction map
    # ------------------------------------------------------------------

    def _tech_grid(self) -> np.ndarray:
        grid = np.zeros((self.n_lat, self.n_lon))
        if not self.factions:
            return grid + 0.5
        tech_map = {f.faction_id: f.tech_level for f in self.factions}
        for fid, tech in tech_map.items():
            grid[self.faction_id == fid] = tech
        return grid

    def _aggression_grid(self) -> np.ndarray:
        grid = np.zeros((self.n_lat, self.n_lon))
        if not self.factions:
            return grid
        agg_map = {f.faction_id: f.aggression for f in self.factions}
        for fid, agg in agg_map.items():
            grid[self.faction_id == fid] = agg
        return grid

    # ------------------------------------------------------------------
    # Physics attachment
    # ------------------------------------------------------------------

    def enable_factions(self) -> None:
        """Initialise the Phase 2 FactionController."""
        from civilization.factions import FactionController
        self._faction_ctrl = FactionController(self)

    def enable_economy(self) -> None:
        """Initialise the Phase 3 EconomyController."""
        from civilization.economy import EconomyController
        self._economy_ctrl = EconomyController(self, seed=self.seed + 1)

    def attach_physics(self, sim: object) -> None:
        """
        Attach a live PlanetPhysicsSimulator.
        After this, each call to step() pulls fresh fields from the simulator.
        """
        self._physics = sim

    def _sync_physics(self) -> None:
        if self._physics is None:
            return
        p = self._physics
        self._surface_temp_k = np.asarray(p.temperature_k, dtype=np.float64)
        self._wind_u = np.asarray(p.u_wind_m_s, dtype=np.float64)
        self._wind_v = np.asarray(p.v_wind_m_s, dtype=np.float64)
        self._precipitation = np.asarray(p.precipitation_mm_day, dtype=np.float64)

    # ------------------------------------------------------------------
    # Step
    # ------------------------------------------------------------------

    def step(self) -> None:
        self._sync_physics()

        self._step_resources()

        if self._economy_ctrl is not None:
            self._economy_ctrl.step()

        self._step_happiness()
        self._step_unrest()
        self._step_migration()

        if self._faction_ctrl is not None:
            self._faction_ctrl.step()

        self._record_history()
        self.step_count += 1

    def faction_summary(self) -> list:
        if self._faction_ctrl is None:
            return []
        return self._faction_ctrl.summary()

    def economy_summary(self) -> list:
        """Per-faction economic snapshot (Phase 3)."""
        if self._economy_ctrl is None:
            return []
        return self._economy_ctrl.summary()

    @property
    def specialization(self) -> Optional[np.ndarray]:
        """Cell specialization grid [n_lat, n_lon] int (Spec enum values)."""
        if self._economy_ctrl is None:
            return None
        return self._economy_ctrl.specialization

    # ------------------------------------------------------------------
    # Resource dynamics
    # ------------------------------------------------------------------

    def _step_resources(self) -> None:
        tech = self._tech_grid()

        # --- Food ---
        # Coruscant grows nothing — food arrives via trade/import.
        # Import rate: base + tech bonus, hurt by unrest blocking logistics.
        import_rate_days = 2.5 * tech * (1.0 - 0.5 * self.unrest)
        consumption_days = 1.0  # 1 day consumed per step
        self.food_reserve = np.clip(
            self.food_reserve + import_rate_days - consumption_days,
            0.0, 180.0,
        )

        # --- Water ---
        # Precipitation adds to reserves (tiny on Coruscant — mostly recycled).
        precip_bonus = 0.01 * self._precipitation  # mm/day → l/cap rough proxy
        recycling = 15.0 * tech
        loss = 5.0 + 3.0 * (self._surface_temp_k - 288.0).clip(0) / 20.0
        self.water_avail = np.clip(
            self.water_avail + precip_bonus + recycling - loss,
            0.0, 60.0,
        )

        # --- Energy ---
        # Generated locally (fusion reactors), output scales with tech.
        # Heat-island from physics temperature raises cooling demand.
        temp_penalty = np.clip((self._surface_temp_k - 305.0) / 20.0, 0, 0.5)
        generation = 90.0 * tech
        demand = 60.0 + 20.0 * temp_penalty + 10.0 * self.unrest
        self.energy_avail = np.clip(
            generation - demand + self._rng.normal(0, 1, (self.n_lat, self.n_lon)),
            0.0, 300.0,
        )

    # ------------------------------------------------------------------
    # Happiness (Utility AI — continuous scoring)
    # ------------------------------------------------------------------

    def _step_happiness(self) -> None:
        # Each factor scores 0..1, then weighted sum.
        food_score = np.clip(self.food_reserve / 30.0, 0.0, 1.0)
        water_score = np.clip(self.water_avail / 15.0, 0.0, 1.0)
        energy_score = np.clip(self.energy_avail / 60.0, 0.0, 1.0)

        # Temperature comfort
        temp_dev = np.abs(self._surface_temp_k - 293.0)  # distance from 20 °C
        temp_score = np.clip(1.0 - temp_dev / 30.0, 0.0, 1.0)

        # Security (inverse of unrest)
        security_score = 1.0 - self.unrest

        target_happiness = (
            0.30 * food_score
            + 0.20 * water_score
            + 0.20 * energy_score
            + 0.15 * temp_score
            + 0.15 * security_score
        )

        # Slow EMA towards target
        self.happiness = np.clip(
            0.85 * self.happiness + 0.15 * target_happiness, 0.0, 1.0
        )

    # ------------------------------------------------------------------
    # Unrest (FSM-like threshold dynamics)
    # ------------------------------------------------------------------

    def _step_unrest(self) -> None:
        # Unrest drivers
        hunger = np.clip(1.0 - self.food_reserve / FOOD_CRITICAL_DAYS, 0.0, 1.0)
        thirst = np.clip(1.0 - self.water_avail / WATER_CRITICAL_L, 0.0, 1.0)
        dark = np.clip(1.0 - self.energy_avail / ENERGY_CRITICAL_KWH, 0.0, 1.0)
        misery = 1.0 - self.happiness
        aggression = self._aggression_grid()

        # Local inequality amplifier: cells with worse conditions next to
        # better-off neighbours feel relative deprivation
        h_nb = _neighbour_mean(self.happiness)
        deprivation = np.clip(h_nb - self.happiness, 0.0, 1.0)

        unrest_pressure = (
            0.30 * hunger
            + 0.20 * thirst
            + 0.15 * dark
            + 0.15 * misery
            + 0.10 * deprivation
            + 0.10 * aggression
        )

        # Unrest memory + new pressure
        self.unrest = np.clip(
            UNREST_DECAY * self.unrest + UNREST_MEMORY * unrest_pressure,
            0.0, 1.0,
        )

    # ------------------------------------------------------------------
    # Migration (Flow-field based)
    # ------------------------------------------------------------------

    def _step_migration(self) -> None:
        """
        People flow from low-happiness cells to high-happiness neighbours.
        Uses a simple gradient-descent flow on the happiness field,
        weighted by wind (carrying capacity proxy on Coruscant = transit).
        """
        # Build a 'pull' field = happiness weighted by resources
        pull = self.happiness * np.clip(self.food_reserve / 30.0, 0.1, 1.0)

        dlat, dlon = _gradient_pressure(pull)

        # Wind assists or opposes transit
        wind_lat_norm = np.tanh(self._wind_v / 10.0)
        wind_lon_norm = np.tanh(self._wind_u / 10.0)

        flow_lat = MIGRATION_RATE * (dlat + 0.1 * wind_lat_norm) * self.population
        flow_lon = MIGRATION_RATE * (dlon + 0.1 * wind_lon_norm) * self.population

        # Clip outflow to prevent negative populations
        total_outflow = np.abs(flow_lat) + np.abs(flow_lon)
        scale = np.where(
            total_outflow > MIGRATION_FLOW_CLIP * self.population,
            MIGRATION_FLOW_CLIP * self.population / (total_outflow + 1e-9),
            1.0,
        )
        flow_lat *= scale
        flow_lon *= scale

        # Divergence = net gain/loss per cell
        div_lat = flow_lat - np.roll(flow_lat, 1, axis=0)
        div_lon = flow_lon - np.roll(flow_lon, 1, axis=1)
        net_flow = -(div_lat + div_lon)

        self.population = np.clip(self.population + net_flow, 1.0, None)
        self._last_migration_flux = float(np.abs(net_flow).mean())

    # ------------------------------------------------------------------
    # History recording
    # ------------------------------------------------------------------

    def _record_history(self) -> None:
        flux = getattr(self, "_last_migration_flux", 0.0)
        self.history["total_population"].append(float(self.population.sum() * self._cell_area.mean()))
        self.history["mean_happiness"].append(float(self.happiness.mean()))
        self.history["mean_unrest"].append(float(self.unrest.mean()))
        self.history["mean_food_reserve_days"].append(float(self.food_reserve.mean()))
        self.history["mean_water_l_cap"].append(float(self.water_avail.mean()))
        self.history["mean_energy_kwh_cap"].append(float(self.energy_avail.mean()))
        self.history["migration_flux"].append(flux)

    # ------------------------------------------------------------------
    # Shocks
    # ------------------------------------------------------------------

    def apply_shock(self, shock_type: str, magnitude: float = 0.3, region: Optional[str] = None) -> None:
        """
        Apply an external shock to the civilization.

        Parameters
        ----------
        shock_type : 'food_blockade' | 'water_crisis' | 'power_outage' |
                     'heat_wave' | 'unrest_event'
        magnitude  : 0..1 severity
        region     : 'north' | 'south' | 'equatorial' | None (global)
        """
        mask = self._region_mask(region)

        if shock_type == "food_blockade":
            self.food_reserve[mask] = np.clip(
                self.food_reserve[mask] * (1.0 - magnitude), 0.0, None
            )
        elif shock_type == "water_crisis":
            self.water_avail[mask] = np.clip(
                self.water_avail[mask] * (1.0 - magnitude), 0.0, None
            )
        elif shock_type == "power_outage":
            self.energy_avail[mask] = np.clip(
                self.energy_avail[mask] * (1.0 - magnitude), 0.0, None
            )
        elif shock_type == "heat_wave":
            self._surface_temp_k[mask] += magnitude * 20.0
        elif shock_type == "unrest_event":
            self.unrest[mask] = np.clip(
                self.unrest[mask] + magnitude, 0.0, 1.0
            )
        else:
            raise ValueError(f"Unknown shock_type: {shock_type!r}")

    def _region_mask(self, region: Optional[str]) -> np.ndarray:
        if region is None:
            return np.ones((self.n_lat, self.n_lon), dtype=bool)
        if region == "north":
            return self._lat2d > 30.0
        if region == "south":
            return self._lat2d < -30.0
        if region == "equatorial":
            return np.abs(self._lat2d) < 30.0
        raise ValueError(f"Unknown region: {region!r}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, float]:
        return {
            "step": self.step_count,
            "total_pop_est": float(self.population.sum() * self._cell_area.mean()),
            "mean_happiness": float(self.happiness.mean()),
            "mean_unrest": float(self.unrest.mean()),
            "mean_food_days": float(self.food_reserve.mean()),
            "mean_water_l": float(self.water_avail.mean()),
            "mean_energy_kwh": float(self.energy_avail.mean()),
            "pct_critical_food": float((self.food_reserve < FOOD_CRITICAL_DAYS).mean()) * 100,
            "pct_critical_water": float((self.water_avail < WATER_CRITICAL_L).mean()) * 100,
            "pct_high_unrest": float((self.unrest > 0.7).mean()) * 100,
        }


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def visualize(
    civ: CoruscantCivilization,
    steps: int = 200,
    shock_step: int = 80,
    shock_type: str = "food_blockade",
    shock_region: Optional[str] = "equatorial",
) -> None:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.animation import FuncAnimation
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.gridspec import GridSpec

    BG = "#0a0a12"
    FG = "#cccccc"
    ACTION_COLOURS = {
        "survive":     "#ff4444",
        "expand":      "#ff9900",
        "trade":       "#44ff88",
        "consolidate": "#4488ff",
        "idle":        "#555555",
    }
    # Specialization colourmap (5 types)
    SPEC_COLOURS = ["#4caf50", "#e53935", "#ffa726", "#7b1fa2", "#90a4ae"]
    SPEC_NAMES   = ["Agri", "Indus", "Comm", "Mil", "Res"]

    # ── layout: 3×3 maps (row0-1) + spec map (row2 col0-1 span) + sidebar ─
    fig = plt.figure(figsize=(22, 11))
    fig.patch.set_facecolor(BG)
    gs = GridSpec(
        3, 4,
        figure=fig,
        width_ratios=[1, 1, 1, 0.40],
        height_ratios=[1, 1, 1],
        hspace=0.38,
        wspace=0.25,
        left=0.04, right=0.98, top=0.93, bottom=0.06,
    )

    # 6 standard map axes (rows 0-1)
    map_axes = [fig.add_subplot(gs[r, c]) for r in range(2) for c in range(3)]
    # row 2: specialization map spans cols 0-1, faction map col 2
    ax_spec    = fig.add_subplot(gs[2, 0:2])
    ax_faction = fig.add_subplot(gs[2, 2])
    ax_side    = fig.add_subplot(gs[:, 3])

    for ax in map_axes + [ax_spec, ax_faction]:
        ax.set_facecolor(BG)
        ax.set_xticks([])
        ax.set_yticks([])
    ax_side.set_facecolor(BG)
    ax_side.axis("off")

    # ── faction colourmap ─────────────────────────────────────────────────
    fcolours_hex = [
        "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))
        for r, g, b in FACTION_COLOURS
    ]
    faction_cmap = ListedColormap(fcolours_hex)
    faction_norm = BoundaryNorm(
        [-0.5 + i for i in range(len(FACTION_COLOURS) + 1)],
        faction_cmap.N,
    )

    # ── specialization colourmap ──────────────────────────────────────────
    spec_cmap = ListedColormap(SPEC_COLOURS)
    spec_norm = BoundaryNorm([-0.5 + i for i in range(len(SPEC_COLOURS) + 1)], spec_cmap.N)

    pop_log = np.log10(np.clip(civ.population, 1, None))
    spec_data = civ.specialization if civ.specialization is not None else np.zeros((civ.n_lat, civ.n_lon), dtype=np.int32)

    im_pop       = map_axes[0].imshow(pop_log,           cmap="hot",        vmin=0,   vmax=6,   aspect="auto")
    im_food      = map_axes[1].imshow(civ.food_reserve,  cmap="YlGn",       vmin=0,   vmax=90,  aspect="auto")
    im_unrest    = map_axes[2].imshow(civ.unrest,        cmap="magma",      vmin=0,   vmax=1,   aspect="auto")
    im_happiness = map_axes[3].imshow(civ.happiness,     cmap="RdYlGn",     vmin=0,   vmax=1,   aspect="auto")
    im_energy    = map_axes[4].imshow(civ.energy_avail,  cmap="plasma",     vmin=0,   vmax=200, aspect="auto")
    im_water     = map_axes[5].imshow(civ.water_avail,   cmap="Blues",      vmin=0,   vmax=50,  aspect="auto")
    im_spec      = ax_spec.imshow(spec_data,              cmap=spec_cmap,    norm=spec_norm,     aspect="auto")
    im_faction   = ax_faction.imshow(civ.faction_id,     cmap=faction_cmap, norm=faction_norm,  aspect="auto")

    map_titles = [
        "Population (log₁₀ ppl/km²)",
        "Food reserve (days)",
        "Unrest",
        "Happiness",
        "Energy (kWh/cap/day)",
        "Water (l/cap/day)",
    ]
    for ax, title in zip(map_axes, map_titles):
        ax.set_title(title, color=FG, fontsize=8, pad=3)
    ax_spec.set_title("Specialization", color=FG, fontsize=8, pad=3)
    ax_faction.set_title("Faction control", color=FG, fontsize=8, pad=3)

    cb_kwargs = dict(fraction=0.046, pad=0.03)
    for im, ax in zip([im_pop, im_food, im_unrest, im_happiness, im_energy, im_water], map_axes):
        cb = fig.colorbar(im, ax=ax, **cb_kwargs)
        cb.ax.tick_params(labelcolor="#888888", labelsize=6)

    # specialization legend
    spec_patches = [
        mpatches.Patch(color=SPEC_COLOURS[i], label=SPEC_NAMES[i])
        for i in range(len(SPEC_NAMES))
    ]
    ax_spec.legend(
        handles=spec_patches, loc="lower left", fontsize=6,
        framealpha=0.6, facecolor="#111122", labelcolor=FG,
        handlelength=1.0, borderpad=0.4, ncol=5,
    )

    # faction legend on faction map
    legend_patches = [
        mpatches.Patch(color=fcolours_hex[f.faction_id], label=f.name)
        for f in civ.factions
    ]
    ax_faction.legend(
        handles=legend_patches, loc="lower left", fontsize=5.5,
        framealpha=0.6, facecolor="#111122", labelcolor=FG,
        handlelength=1.0, borderpad=0.4,
    )

    # ── sidebar: faction status table ─────────────────────────────────────
    n_f = len(civ.factions)
    FACTION_SECTION_H = 0.52   # top 52% for faction table
    GDP_SECTION_Y     = 0.44   # GDP section starts here

    ax_side.set_xlim(0, 1)
    ax_side.set_ylim(0, 1)

    ax_side.text(0.5, 0.98, "FACTION STATUS", color=FG, fontsize=8,
                 ha="center", va="top", fontweight="bold")

    ROW_H = FACTION_SECTION_H / (n_f + 1)
    header_y = 0.98 - ROW_H * 0.9

    col_labels = ["Faction", "Cells%", "Str", "Food", "Act"]
    col_x      = [0.01, 0.37, 0.54, 0.70, 0.85]
    for cx, cl in zip(col_x, col_labels):
        ax_side.text(cx, header_y, cl, color="#888888", fontsize=6.5,
                     ha="left", va="center")
    ax_side.axhline(header_y - ROW_H * 0.5, color="#333355", linewidth=0.5)

    faction_row_texts: List[List] = []
    for i, f in enumerate(civ.factions):
        y = header_y - ROW_H * (i + 1)
        row = []
        for cx in col_x:
            t = ax_side.text(cx, y, "", color=fcolours_hex[f.faction_id],
                             fontsize=6.5, ha="left", va="center")
            row.append(t)
        faction_row_texts.append(row)

    # action colour legend
    ax_side.axhline(GDP_SECTION_Y + 0.06, color="#333355", linewidth=0.5)
    ax_side.text(0.01, GDP_SECTION_Y + 0.04, "Actions:", color="#888888", fontsize=6)
    for ai, (act, col) in enumerate(ACTION_COLOURS.items()):
        ax_side.text(
            0.01 + (ai % 3) * 0.33,
            GDP_SECTION_Y + 0.04 - 0.04 * (1 + ai // 3),
            f"■ {act[:4]}", color=col, fontsize=5.5,
        )

    # GDP section
    ax_side.axhline(GDP_SECTION_Y - 0.08, color="#333355", linewidth=0.5)
    ax_side.text(0.5, GDP_SECTION_Y - 0.10, "ECONOMY (GDP)", color=FG, fontsize=8,
                 ha="center", va="top", fontweight="bold")

    GDP_ROW_H = 0.28 / (n_f + 1)
    gdp_header_y = GDP_SECTION_Y - 0.10 - GDP_ROW_H * 1.0
    gdp_col_labels = ["Faction", "GDP", "FoodProd", "EnProd"]
    gdp_col_x      = [0.01, 0.38, 0.60, 0.82]
    for cx, cl in zip(gdp_col_x, gdp_col_labels):
        ax_side.text(cx, gdp_header_y, cl, color="#888888", fontsize=6,
                     ha="left", va="center")

    gdp_row_texts: List[List] = []
    for i, f in enumerate(civ.factions):
        y = gdp_header_y - GDP_ROW_H * (i + 1)
        row = []
        for cx in gdp_col_x:
            t = ax_side.text(cx, y, "", color=fcolours_hex[f.faction_id],
                             fontsize=6, ha="left", va="center")
            row.append(t)
        gdp_row_texts.append(row)

    # ── global status bar ─────────────────────────────────────────────────
    status_text = fig.text(
        0.39, 0.02, "", ha="center", color=FG, fontsize=8,
        bbox=dict(facecolor="#1a1a2e", edgecolor="none", alpha=0.85),
    )

    # ── shock label ───────────────────────────────────────────────────────
    shock_label = fig.text(
        0.39, 0.96, "", ha="center", color="#ff4444", fontsize=9, fontweight="bold",
    )

    # ── update callback ───────────────────────────────────────────────────
    def update(frame: int) -> list:
        is_shock = frame == shock_step
        if is_shock:
            civ.apply_shock(shock_type, magnitude=0.4, region=shock_region)
            shock_label.set_text(
                f"⚡ SHOCK: {shock_type.replace('_',' ')} [{shock_region or 'global'}]"
            )
        elif frame == shock_step + 1:
            shock_label.set_text("")

        civ.step()

        # update maps
        im_pop.set_data(np.log10(np.clip(civ.population, 1, None)))
        im_food.set_data(civ.food_reserve)
        im_unrest.set_data(civ.unrest)
        im_happiness.set_data(civ.happiness)
        im_energy.set_data(civ.energy_avail)
        im_water.set_data(civ.water_avail)
        # specialization is static — no update needed
        im_faction.set_data(civ.faction_id)

        # update faction sidebar
        total_cells = civ.n_lat * civ.n_lon
        fsummary = civ.faction_summary()
        for i, entry in enumerate(fsummary):
            row = faction_row_texts[i]
            act_col = ACTION_COLOURS.get(entry["last_action"], "#ffffff")
            pct = 100.0 * entry["cells"] / total_cells
            row[0].set_text(entry["name"][:12])
            row[1].set_text(f"{pct:.0f}%")
            row[2].set_text(f"{entry['strength']:.2f}")
            row[3].set_text(f"{entry['food_per_cap']:.0f}d")
            row[4].set_text(entry["last_action"][:4])
            row[4].set_color(act_col)

        # update GDP sidebar
        esummary = civ.economy_summary()
        for i, entry in enumerate(esummary):
            row = gdp_row_texts[i]
            row[0].set_text(entry["name"][:12])
            row[1].set_text(f"{entry['gdp_index']:.2f}")
            row[2].set_text(f"{entry['food_produced']:.0f}")
            row[3].set_text(f"{entry['energy_produced']:.0f}")

        # update status bar
        s = civ.summary()
        status_text.set_text(
            f"step={s['step']:04d}  |  "
            f"happiness={s['mean_happiness']:.3f}  |  "
            f"unrest={s['mean_unrest']:.3f}  |  "
            f"food={s['mean_food_days']:.1f}d  |  "
            f"energy={s['mean_energy_kwh']:.1f} kWh  |  "
            f"crisis-zones={s['pct_high_unrest']:.1f}%"
        )

        return [
            im_pop, im_food, im_unrest, im_happiness, im_energy, im_water,
            im_faction, status_text, shock_label,
            *[t for row in faction_row_texts for t in row],
            *[t for row in gdp_row_texts for t in row],
        ]

    anim = FuncAnimation(fig, update, frames=steps, interval=60, blit=False)
    plt.show()
    return anim


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Coruscant Civilization Simulation — Phase 1")
    parser.add_argument("--steps",        type=int,   default=200,           help="Number of simulation steps")
    parser.add_argument("--shock-step",   type=int,   default=80,            help="Step at which shock occurs")
    parser.add_argument("--shock-type",   type=str,   default="food_blockade",
                        choices=["food_blockade", "water_crisis", "power_outage", "heat_wave", "unrest_event"])
    parser.add_argument("--shock-region", type=str,   default="equatorial",
                        choices=["north", "south", "equatorial", "global"])
    parser.add_argument("--seed",         type=int,   default=42)
    parser.add_argument("--attach-physics", action="store_true",
                        help="Run with live PlanetPhysicsSimulator (slower but physically coupled)")
    args = parser.parse_args()

    civ = CoruscantCivilization(seed=args.seed)

    if args.attach_physics:
        from planet_physics import PlanetConfig, PlanetPhysicsSimulator
        cfg = PlanetConfig()
        phys = PlanetPhysicsSimulator(cfg, n_lat=GRID_LAT, n_lon=GRID_LON)
        # warm up physics
        for day in range(30):
            phys.step(day_of_year=float(day % 365))
        civ.attach_physics(phys)
        print("Physics simulator attached.")

    region = None if args.shock_region == "global" else args.shock_region
    visualize(civ, steps=args.steps, shock_step=args.shock_step,
              shock_type=args.shock_type, shock_region=region)
