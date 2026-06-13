"""Static game data: buildings, units, technologies, factions.

All balance constants live here so the autoresearch tuner can mutate them
in one place (see strategy/balance_tune.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

RESOURCES = ("materials", "food", "energy")  # region-local stockpiles
# credits and science are faction-level


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BuildingType:
    key: str
    name: str
    cost_materials: float
    cost_credits: float
    build_ticks: int
    upkeep_energy: float
    upkeep_credits: float
    # production per tick (scaled by modifiers in engine)
    materials: float = 0.0
    food: float = 0.0
    energy: float = 0.0
    science: float = 0.0
    prod_points: float = 0.0      # unit production capacity
    defense: float = 0.0          # adds to defender power
    trade: float = 0.0            # trade capacity
    tech_required: Tuple[str, int] = ("", 0)   # (branch, tier)


BUILDINGS: Dict[str, BuildingType] = {
    b.key: b for b in [
        BuildingType("mine",      "Deep Core Mine",     60,  80, 6, 2.0, 1.0, materials=4.0),
        BuildingType("farm",      "Agri-Tower",         40,  60, 4, 1.5, 1.0, food=6.0),
        BuildingType("reactor",   "Fusion Reactor",     80, 120, 8, 0.0, 2.0, energy=10.0),
        BuildingType("factory",   "War Factory",       100, 150, 8, 3.0, 2.0, prod_points=5.0),
        BuildingType("lab",       "Research Spire",     90, 140, 8, 2.5, 2.0, science=3.0),
        BuildingType("defense",   "Defense Grid",       70, 100, 6, 2.0, 1.5, defense=30.0,
                     tech_required=("military", 1)),
        BuildingType("spaceport", "Orbital Spaceport", 120, 200, 10, 3.0, 2.0, trade=10.0,
                     tech_required=("economy", 1)),
        BuildingType("citadel",   "Planetary Citadel", 200, 300, 14, 4.0, 3.0, defense=80.0, prod_points=3.0,
                     tech_required=("military", 3)),
    ]
}


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UnitType:
    key: str
    name: str
    attack: float
    defense: float
    move_ticks: int               # ticks to traverse one region link
    cost_materials: float
    cost_credits: float
    prod_points: float            # factory points to produce one squad
    upkeep_food: float
    upkeep_credits: float
    tech_required: Tuple[str, int] = ("", 0)


UNITS: Dict[str, UnitType] = {
    u.key: u for u in [
        UnitType("infantry", "Clone Infantry Corps", 1.0, 1.6, 3, 10,  20,  20, 0.6, 0.4),
        UnitType("armor",    "Juggernaut Armor",     3.0, 2.0, 2, 40,  60,  60, 0.8, 1.0,
                 tech_required=("military", 1)),
        UnitType("aircraft", "Strike Wing",          4.5, 1.2, 1, 60, 100,  90, 0.4, 1.6,
                 tech_required=("military", 2)),
        UnitType("fleet",    "Orbital Fleet",        7.0, 4.0, 1, 120, 200, 150, 0.5, 2.5,
                 tech_required=("military", 4)),
    ]
}


# ---------------------------------------------------------------------------
# Technology tree: 4 branches x 6 tiers
# ---------------------------------------------------------------------------

TECH_BRANCHES = ("military", "economy", "science", "infrastructure")

# science cost to reach tier i (cumulative thresholds handled by engine)
TECH_COST_BASE = 120.0
TECH_COST_GROWTH = 1.8

TECH_NAMES: Dict[str, List[str]] = {
    "military": ["Blaster Doctrine", "Armored Columns", "Air Superiority",
                 "Shield Arrays", "Orbital Command", "Planetary Sieges"],
    "economy": ["Trade Charters", "Hyperlane Routes", "Galactic Banking",
                "Mass Replication", "Tibanna Refining", "Core World Markets"],
    "science": ["Data Archives", "Droid Researchers", "Holonet Labs",
                "Kyber Studies", "Deep Simulations", "Singularity Engineering"],
    "infrastructure": ["Mag-Lev Grids", "Vertical Farms", "Arcology Shells",
                       "Auto-Repair Swarms", "Climate Domes", "World Engines"],
}

# Multipliers applied per tier reached
MIL_ATTACK_PER_TIER = 0.12
MIL_DEFENSE_PER_TIER = 0.12
ECO_INCOME_PER_TIER = 0.15
ECO_TRADE_PER_TIER = 0.20
SCI_RATE_PER_TIER = 0.18
INFRA_PROD_PER_TIER = 0.10
INFRA_SLOTS_TIERS = (2, 4)        # tiers granting +1 building slot


# ---------------------------------------------------------------------------
# Factions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactionDef:
    fid: int
    name: str
    colour: str                    # hex for the viewer
    aggression: float              # 0..1 — war appetite
    greed: float                   # 0..1 — economy focus
    curiosity: float               # 0..1 — science focus
    seed_lat: float
    seed_lon: float


FACTIONS: List[FactionDef] = [
    FactionDef(0, "Senate Coalition",  "#3473d9", 0.15, 0.55, 0.75,  10.0,   0.0),
    FactionDef(1, "Industrial Combine","#d93434", 0.45, 0.80, 0.40, -20.0,  90.0),
    FactionDef(2, "Commerce Ring",     "#34bf4f", 0.25, 0.95, 0.50,  30.0, 180.0),
    FactionDef(3, "Underworld Cartel", "#cc9918", 0.75, 0.45, 0.25, -50.0, 270.0),
    FactionDef(4, "Military Junta",    "#8c1ac0", 0.65, 0.35, 0.45,  60.0, 135.0),
    # Dormant rebel faction: born from uprisings, can rise and fall repeatedly.
    FactionDef(5, "Free Coruscant",    "#e8e8e8", 0.90, 0.30, 0.20,   0.0,   0.0),
]

REBEL_FID = 5
PLAYABLE_FIDS = (0, 1, 2, 3, 4)


# ---------------------------------------------------------------------------
# Faction leaders (generational characters)
# ---------------------------------------------------------------------------

LEADER_FIRST = [
    "Adan", "Bryn", "Corin", "Daxa", "Eron", "Fenn", "Garek", "Hale",
    "Ilya", "Joren", "Kessa", "Lor", "Mira", "Nyx", "Orin", "Palla",
    "Quill", "Rancis", "Sela", "Tovan", "Ula", "Vex", "Wrenn", "Xara",
    "Yent", "Zorba",
]
LEADER_LAST = [
    "Antilles", "Bonteri", "Cassan", "Drayen", "Elaris", "Farr",
    "Greyshade", "Hask", "Iblis", "Jathmir", "Krennet", "Lassic",
    "Mothma", "Noor", "Organa", "Pamlo", "Quor", "Ransolm", "Sondiv",
    "Taa", "Ulgo", "Valor", "Wessex", "Xandel", "Yendar", "Zaarin",
]


# ---------------------------------------------------------------------------
# Tunable balance block (mutated by balance_tune.py)
# ---------------------------------------------------------------------------

BALANCE = {
    # economy
    "tax_per_pop": 0.1101,            # credits per million pop per tick
    "food_per_pop": 0.08,           # food consumed per million pop per tick
    "base_food_per_fertility": 2.5,  # subsistence hydroponics per region
    "base_energy_per_potential": 2.0,
    "base_materials_per_richness": 0.8,
    "pop_soft_cap": 200.0,          # millions, scaled by infrastructure
    "pop_growth_rate": 0.00258,      # per tick when fed and calm
    "starvation_rate": 0.012,       # pop loss per tick when starving
    "market_price_materials": 0.8,  # credits per surplus material auto-sold
    "trade_income_per_route": 6.0,  # credits per tick per active trade route

    # combat
    "combat_intensity": 0.16,       # casualty fraction scale per tick
    "defender_home_bonus": 1.60,
    "entrench_per_tick": 0.02,      # garrison entrenchment growth, cap 0.3
    "rout_ratio": 0.38,             # power ratio below which side retreats
    "capture_devastation": 0.30,
    "neutral_militia_base": 25.0,

    # diplomacy
    "war_relation_threshold": -45.0,
    "war_advantage_required": 1.27,
    "weariness_per_tick": 0.242,
    "weariness_losing_mult": 2.2,
    "peace_weariness": 62.0,
    "border_friction": 0.18,
    "trade_warmth": 0.08,

    # ai
    "garrison_fraction": 0.35,      # share of military kept home
    "expansion_army_power": 27.6,   # min power before claiming neutrals
    "doctrine_inertia": 25,         # ticks before doctrine can flip
    "absorption_chance": 0.010,     # neutral region joining a strong neighbour

    # vassalage
    "vassal_max_regions": 6,        # loser this small capitulates instead of peace
    "vassal_war_score": 4.0,        # min |war score| for capitulation
    "vassal_tribute": 0.20,         # share of vassal income paid to suzerain
    "independence_power_ratio": 0.9,  # vassal/suzerain power to dare revolt
    "independence_chance": 0.012,   # per-tick chance once strong enough

    # rebellions
    "rebellion_unrest": 0.94,       # unrest level that risks uprising
    "rebellion_chance": 0.008,      # per-tick chance in a boiling region
    "rebellion_grace_ticks": 200,   # no uprisings while societies settle
    "war_unrest_per_tick": 0.0006,  # war exhaustion felt by civilians
    "rebel_army_per_pop": 0.10,     # rebel infantry per million pop
    "uprising_cooldown_ticks": 25,  # min gap between separate uprisings planet-wide
    "rebel_war_weariness_mult": 1.6,  # irregular armies tire of war faster
    "rebel_governance_cap": 45,     # regions rebels can govern before fraying
    "rebel_fray_unrest": 0.004,     # extra unrest per tick when overextended (scaled)

    # economy sinks (late-game)
    "corruption_free_regions": 15,  # empire size with clean books
    "corruption_per_region": 0.012, # income share lost per region beyond that
    "corruption_max": 0.45,
    "hoard_cap": 20000.0,           # treasuries above this start leaking
    "hoard_decay": 0.012,           # fraction of the excess lost per tick

    # leaders
    "leader_tenure_min": 1200,
    "leader_tenure_max": 3500,

    # future tech (science sink once the tree is maxed)
    "future_tech_base_cost": 4000.0,
    "future_tech_growth": 1.18,
    "future_tech_income": 0.015,    # +1.5% income per future level
    "future_tech_power": 0.010,     # +1.0% military per future level

    # heritage / culture
    "heritage_per_pop": 0.00040,    # heritage points per million pop per tick
    "heritage_infra_bonus": 0.5,    # extra per infrastructure level
    "heritage_cultural_cs": 0.6,    # bonus per cultural city-state patronage

    # city-states
    "city_states": 14,              # base count (scaled by world size)
    "envoy_cost": 55.0,             # credits per envoy
    "envoy_influence": 6.0,         # influence gained per envoy
    "envoy_treasury_floor": 900.0,  # only send envoys above this treasury
    "cs_influence_decay": 0.004,    # per-tick influence decay
    "cs_suzerain_min": 25.0,        # min influence to be suzerain
    "cs_science": 2.2,              # per-tick patron bonus (science type)
    "cs_income": 4.0,               # (trade type)
    "cs_prod": 1.6,                 # (industrial type)
    "cs_heritage": 0.5,             # (cultural type)
    "cs_power_recruit": 0.6,        # (militarist type) infantry/tick to suzerain garrison
}


# ---------------------------------------------------------------------------
# Future tech names (cosmetic, for the event log)
# ---------------------------------------------------------------------------

FUTURE_TECH_NAMES = [
    "Fusion Lattices", "Sentient Grids", "Gravitic Engineering",
    "Quantum Logistics", "Exotic Matter", "Dyson Swarms",
    "Mind-Net Uplink", "Hyperspace Theory", "Nano-Forges",
    "Stellar Husbandry",
]


# ---------------------------------------------------------------------------
# Heritage / civics track — spend accumulated heritage to unlock perks.
# (key, cost, display name, one-line effect)
# ---------------------------------------------------------------------------

HERITAGE_TRACK = [
    ("civic_order",   220.0,  "Civic Order",       "unrest cools 80% faster"),
    ("golden_age",    420.0,  "Golden Age",        "+12% income"),
    ("martial_trad",  680.0,  "Martial Tradition", "+12% defense"),
    ("pioneer",       980.0,  "Pioneer Spirit",    "colonizes & absorbs faster"),
    ("enlightenment", 1380.0, "Enlightenment",     "+18% science"),
    ("manifest",      1900.0, "Manifest Destiny",  "+6% income, power & culture"),
]
HERITAGE_BY_KEY = {h[0]: h for h in HERITAGE_TRACK}


# ---------------------------------------------------------------------------
# City-state archetypes — independent minor powers a faction can patronize
# for a per-tick bonus (highest influence = suzerain).
# ---------------------------------------------------------------------------

CITY_STATE_TYPES = {
    "science":    {"colour": "#9b6cff", "title": "Academy"},
    "trade":      {"colour": "#33cc88", "title": "Free Port"},
    "industrial": {"colour": "#ff9933", "title": "Foundry"},
    "cultural":   {"colour": "#ffcc44", "title": "Sanctuary"},
    "militarist": {"colour": "#ff5555", "title": "Garrison"},
}

CITY_STATE_NAMES = [
    "Ord Mantell", "Taris", "Nar Shaddaa", "Corellia", "Sluis Van",
    "Bespin", "Kuat", "Fondor", "Eriadu", "Denon", "Bothawui",
    "Rodia", "Malastare", "Sullust", "Bestine", "Chandrila",
    "Commenor", "Ithor", "Telos", "Carida",
]
