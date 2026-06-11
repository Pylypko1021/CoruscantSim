"""StrategyEngine — the autonomous RTS core.

One tick = one planetary day:
  1. physics step (optional) -> climate, disasters
  2. economy: production, consumption, taxes, trade, market
  3. construction progress
  4. faction AI (doctrine, research, building, recruiting, orders)
  5. army movement
  6. combat resolution
  7. diplomacy drift, wars and peace
  8. bookkeeping: charts, eliminations, events
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import numpy as np

from strategy.data import (
    BALANCE, BUILDINGS, UNITS, FACTIONS, REBEL_FID, PLAYABLE_FIDS,
    ECO_INCOME_PER_TIER, ECO_TRADE_PER_TIER, SCI_RATE_PER_TIER,
    INFRA_PROD_PER_TIER,
)
from strategy.world import WorldMap, Region, N_REGIONS, REGION_COLS
from strategy.state import FactionRuntime, Army, Leader, make_factions
from strategy.diplomacy import Diplomacy
from strategy import combat as combat_mod
from strategy import ai as ai_mod


@dataclass
class EngineConfig:
    seed: int = 42
    use_physics: bool = True
    physics_lat: int = 36
    physics_lon: int = 72
    start_regions_per_faction: int = 6
    chart_every: int = 5


class StrategyEngine:
    def __init__(self, config: Optional[EngineConfig] = None):
        self.cfg = config or EngineConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        self.tick = 0

        self.world = WorldMap(self.rng)
        self.factions: List[FactionRuntime] = make_factions()
        self.armies: List[Army] = []
        self.diplomacy = Diplomacy(self.rng)
        self.events: deque = deque(maxlen=2000)
        self.event_seq = 0                      # monotonic id for consumers
        self.battles_recent: deque = deque(maxlen=60)
        self.timeline: deque = deque(maxlen=400)   # ownership keyframes
        self.charts: Dict[str, List] = {
            "tick": [],
            "regions": [[] for _ in self.factions],
            "power": [[] for _ in self.factions],
            "gdp": [[] for _ in self.factions],
            "population": [[] for _ in self.factions],
        }
        self.physics = None
        self._physics_temp = None
        self._physics_precip = None
        if self.cfg.use_physics:
            self._init_physics()

        self._seed_world()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_physics(self) -> None:
        from planet_physics import PlanetConfig, PlanetPhysicsSimulator
        self.physics = PlanetPhysicsSimulator(
            PlanetConfig(), n_lat=self.cfg.physics_lat,
            n_lon=self.cfg.physics_lon, seed=self.cfg.seed,
        )
        # short warm-up so climate fields are sane from tick 0
        for day in range(10):
            self.physics.step(day_of_year=float(day))
        self._cache_climate()

    def _cache_climate(self) -> None:
        if self.physics is None:
            return
        self._physics_temp = np.asarray(self.physics.temperature_k)
        self._physics_precip = np.asarray(self.physics.precipitation_mm_day)
        self.world.apply_climate(self._physics_temp, self._physics_precip)

    def _seed_world(self) -> None:
        """Give each faction a capital + nearby starting regions and a small army."""
        for fac in self.factions:
            fac.leader = Leader.generate(self.rng)
        for fdef, fac in zip(FACTIONS, self.factions):
            if fdef.fid not in PLAYABLE_FIDS:
                continue
            # nearest region to the lore seed point
            best = min(
                self.world.regions,
                key=lambda r: (r.lat - fdef.seed_lat) ** 2 +
                              min(abs(r.lon - fdef.seed_lon),
                                  360 - abs(r.lon - fdef.seed_lon)) ** 2,
            )
            fac.capital = best.rid
            claimed = [best.rid]
            frontier = list(self.world.neighbours(best.rid))
            while len(claimed) < self.cfg.start_regions_per_faction and frontier:
                rid = frontier.pop(0)
                if self.world.regions[rid].owner == -1 and rid not in claimed:
                    claimed.append(rid)
                    frontier.extend(self.world.neighbours(rid))
            for rid in claimed:
                reg = self.world.regions[rid]
                reg.owner = fac.fid
                reg.militia = 0.0
                reg.unrest = 0.1

            capital = self.world.regions[best.rid]
            capital.buildings = {"factory": 1, "mine": 1, "farm": 1, "reactor": 1, "lab": 1}
            capital.infrastructure = 2
            capital.population *= 2.0
            self.armies.append(Army.new(fac.fid, best.rid, {"infantry": 6}, "garrison"))

        self.log("genesis", "Five powers rise from the endless city of Coruscant")

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, etype: str, text: str, **meta) -> None:
        self.event_seq += 1
        self.events.append({"id": self.event_seq, "tick": self.tick,
                            "type": etype, "text": text, **meta})

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def step(self) -> None:
        self.tick += 1

        if self.physics is not None:
            self.physics.step(day_of_year=float(self.tick % 365))
            if self.tick % 5 == 0:
                self._cache_climate()
                self._climate_events()

        self._economy_tick()
        self._construction_tick()

        for fac in self.factions:
            ai_mod.faction_ai_step(self, fac)

        self._movement_tick()
        self._combat_tick()
        self.diplomacy.step(self)
        self._rebellion_tick()
        self._leader_tick()
        self._cleanup()

        if self.tick % self.cfg.chart_every == 0:
            self._record_charts()
        if self.tick % 25 == 0:
            self.timeline.append({
                "tick": self.tick,
                "owner": [r.owner for r in self.world.regions],
            })

    # ------------------------------------------------------------------
    # Economy
    # ------------------------------------------------------------------

    def _economy_tick(self) -> None:
        B = BALANCE
        for fac in self.factions:
            if not fac.alive:
                continue
            regions = self.world.owned_by(fac.fid)
            income = 0.0
            food_balance_total = 0.0
            science_gain = 0.0
            prod_gain = 0.0
            trade_capacity = 0.0

            eco_mult = 1.0 + ECO_INCOME_PER_TIER * fac.tech["economy"]
            infra_mult = 1.0 + INFRA_PROD_PER_TIER * fac.tech["infrastructure"]
            sci_mult = 1.0 + SCI_RATE_PER_TIER * fac.tech["science"]

            for reg in regions:
                wreck = 1.0 - 0.5 * reg.devastation
                # building + baseline energy production
                energy_prod = sum(BUILDINGS[k].energy * n for k, n in reg.buildings.items())
                energy_prod *= reg.energy_potential * infra_mult
                energy_prod += B["base_energy_per_potential"] * reg.energy_potential * wreck
                energy_need = sum(BUILDINGS[k].upkeep_energy * n for k, n in reg.buildings.items())
                reg.stock["energy"] = float(np.clip(
                    reg.stock["energy"] + energy_prod - energy_need, 0.0, 200.0))
                eff = 1.0 if energy_prod >= energy_need else \
                    float(np.clip(0.4 + 0.6 * energy_prod / max(energy_need, 1e-6), 0.4, 1.0))
                eff *= wreck

                materials = sum(BUILDINGS[k].materials * n for k, n in reg.buildings.items())
                materials_in = (materials * reg.materials_richness * eff
                                + B["base_materials_per_richness"] * reg.materials_richness * wreck)
                reg.stock["materials"] = float(np.clip(
                    reg.stock["materials"] + materials_in * infra_mult, 0.0, 500.0))

                food = sum(BUILDINGS[k].food * n for k, n in reg.buildings.items())
                food_in = (food * reg.fertility * eff
                           + B["base_food_per_fertility"] * reg.fertility * wreck) * infra_mult
                food_out = reg.population * B["food_per_pop"]
                reg.stock["food"] = float(np.clip(
                    reg.stock["food"] + food_in - food_out, 0.0, 400.0))
                food_balance_total += food_in - food_out

                # starvation / growth with soft population cap
                pop_cap = B["pop_soft_cap"] * (1.0 + 0.5 * reg.infrastructure)
                if reg.stock["food"] <= 0.5:
                    reg.population = max(1.0, reg.population * (1.0 - B["starvation_rate"]))
                    reg.unrest = min(1.0, reg.unrest + 0.01)
                else:
                    growth = B["pop_growth_rate"] * (1.0 - reg.unrest) * (1.0 - reg.devastation)
                    growth *= max(0.0, 1.0 - reg.population / pop_cap)
                    reg.population *= 1.0 + growth
                    reg.unrest = max(0.0, reg.unrest - 0.004)
                reg.devastation = max(0.0, reg.devastation - 0.002)   # slow repair

                income += reg.population * B["tax_per_pop"] * (1.0 - reg.unrest) * eco_mult
                science_gain += sum(BUILDINGS[k].science * n for k, n in reg.buildings.items()) * eff * sci_mult
                prod_gain += sum(BUILDINGS[k].prod_points * n for k, n in reg.buildings.items()) * eff
                trade_capacity += sum(BUILDINGS[k].trade * n for k, n in reg.buildings.items())

                # market: auto-sell material surplus above 300
                surplus = reg.stock["materials"] - 300.0
                if surplus > 0:
                    reg.stock["materials"] -= surplus
                    income += surplus * B["market_price_materials"]

            # building + army upkeep
            upkeep = sum(
                BUILDINGS[k].upkeep_credits * n
                for reg in regions for k, n in reg.buildings.items()
            )
            for army in self.armies:
                if army.fid != fac.fid or army.size() == 0:
                    continue
                up = army.upkeep()
                upkeep += up["credits"]
                # армія їсть з регіону, де стоїть
                reg = self.world.regions[army.location]
                reg.stock["food"] = max(0.0, reg.stock["food"] - up["food"])

            trade_income = 0.0
            routes = self.trade_pairs()
            for (a, b) in routes:
                if fac.fid in (a, b):
                    trade_income += B["trade_income_per_route"] * \
                        (1.0 + ECO_TRADE_PER_TIER * fac.tech["economy"]) * \
                        min(trade_capacity / 10.0 + 0.5, 3.0)

            income *= fac.stewardship_mult()

            # war exhaustion: long wars erode civilian patience
            if self.diplomacy.enemies_of(fac.fid):
                for reg in regions:
                    reg.unrest = min(1.0, reg.unrest + B["war_unrest_per_tick"]
                                     + 0.0015 * reg.devastation)

            fac.income = income + trade_income - upkeep
            fac.treasury = max(0.0, fac.treasury + fac.income)
            fac.science += science_gain
            fac.prod_pool = min(fac.prod_pool + prod_gain, 600.0)
            fac.food_balance = food_balance_total
            fac.gdp = income + trade_income
            fac.military_power = sum(
                a.attack_power(fac.attack_mult())
                for a in self.armies if a.fid == fac.fid
            )

            # bankruptcy pressure: cannot pay upkeep -> units desert
            if fac.treasury <= 0.0 and fac.income < 0:
                for a in self.armies:
                    if a.fid == fac.fid and a.size() > 0:
                        a.apply_losses(0.05)
                        break

        # vassal tribute flows after everyone's income is settled
        for vassal_fid, suzerain_fid in list(self.diplomacy.vassals.items()):
            fv, fs = self.factions[vassal_fid], self.factions[suzerain_fid]
            if fv.alive and fs.alive and fv.income > 0:
                tribute = fv.income * BALANCE["vassal_tribute"]
                fv.treasury = max(0.0, fv.treasury - tribute)
                fs.treasury += tribute

    def trade_pairs(self) -> List[tuple]:
        """Active trade routes (friendly pair + open physical corridor)."""
        return self._trade_routes()[0]

    def blocked_routes(self) -> List[tuple]:
        """Friendly pairs whose corridor is cut by hostile territory."""
        return self._trade_routes()[1]

    def _trade_routes(self) -> tuple:
        if getattr(self, "_trade_cache_tick", -1) == self.tick:
            return self._trade_cache
        active, blocked = [], []
        for a in self.factions:
            for b in self.factions:
                if a.fid >= b.fid or not (a.alive and b.alive):
                    continue
                if self.diplomacy.at_war(a.fid, b.fid):
                    continue
                if not (self.diplomacy.allied(a.fid, b.fid)
                        or self.diplomacy.relations[a.fid, b.fid] > 20.0):
                    continue
                if a.capital < 0 or b.capital < 0:
                    continue
                if self._corridor_open(a.fid, b.fid):
                    active.append((a.fid, b.fid))
                else:
                    blocked.append((a.fid, b.fid))
        self._trade_cache = (active, blocked)
        self._trade_cache_tick = self.tick
        return self._trade_cache

    def _corridor_open(self, fid_a: int, fid_b: int) -> bool:
        """True if a path of non-hostile regions links the two capitals.
        Hostile = owned by anyone at war with either trading partner."""
        def passable(rid: int) -> bool:
            owner = self.world.regions[rid].owner
            if owner == -1 or owner in (fid_a, fid_b):
                return True
            return not (self.diplomacy.at_war(owner, fid_a)
                        or self.diplomacy.at_war(owner, fid_b))
        path = self.world.shortest_path(
            self.factions[fid_a].capital, self.factions[fid_b].capital, passable)
        return path is not None

    def border_pairs(self) -> set:
        pairs = set()
        for reg in self.world.regions:
            if reg.owner < 0:
                continue
            for n in self.world.neighbours(reg.rid):
                other = self.world.regions[n].owner
                if other >= 0 and other != reg.owner:
                    pairs.add((min(reg.owner, other), max(reg.owner, other)))
        return pairs

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _construction_tick(self) -> None:
        for reg in self.world.regions:
            if not reg.construction:
                continue
            done = []
            for proj in reg.construction:
                proj["ticks_left"] -= 1
                if proj["ticks_left"] <= 0:
                    done.append(proj)
            for proj in done:
                reg.construction.remove(proj)
                key = proj["key"]
                reg.buildings[key] = reg.buildings.get(key, 0) + 1
                if reg.owner >= 0:
                    self.log("built",
                             f"{self.factions[reg.owner].name} completed "
                             f"{BUILDINGS[key].name} in region {reg.rid}",
                             fid=reg.owner, region=reg.rid)

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def _movement_tick(self) -> None:
        for army in self.armies:
            if army.size() == 0 or not army.path:
                continue
            if army.in_battle:
                continue
            army.move_progress += 1
            if army.move_progress >= army.move_ticks_per_link():
                army.move_progress = 0
                army.location = army.path.pop(0)
                # arriving at hostile region triggers combat next phase
                reg = self.world.regions[army.location]
                if not army.path and army.stance in ("attack", "expand") and \
                        reg.owner == army.fid:
                    army.stance = "garrison"

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------

    def _combat_tick(self) -> None:
        contested = set()
        for army in self.armies:
            if army.size() > 0:
                contested.add(army.location)
            army.in_battle = False
        for rid in contested:
            record = combat_mod.resolve_region_combat(self, self.world.regions[rid])
            if record is not None:
                self.battles_recent.append(record)
                if record["outcome"] != "ongoing":
                    self.log("battle",
                             f"Battle in region {rid}: "
                             f"{self.factions[record['attacker']].name} vs "
                             f"{(self.factions[record['defender']].name if record['defender'] >= 0 else 'militia')} "
                             f"-> {record['outcome']}",
                             region=rid, fid=record["attacker"])

    # ------------------------------------------------------------------
    # Climate / disasters
    # ------------------------------------------------------------------

    def _climate_events(self) -> None:
        if self._physics_temp is None:
            return
        temps = self.world.region_temp(self._physics_temp)
        hot_threshold = float(np.percentile(temps, 97))
        for reg in self.world.regions:
            if reg.owner < 0:
                continue
            t = temps[reg.rid]
            if t > hot_threshold and t > 300.0 and self.rng.random() < 0.10:
                reg.stock["energy"] = max(0.0, reg.stock["energy"] - 15.0)
                reg.unrest = min(1.0, reg.unrest + 0.05)
                self.log("heatwave",
                         f"Heatwave strains region {reg.rid} "
                         f"({self.factions[reg.owner].name})",
                         region=reg.rid, fid=reg.owner)
        # rare storm: destroys a building somewhere wet
        if self.rng.random() < 0.04:
            owned = [r for r in self.world.regions if r.owner >= 0 and r.buildings]
            if owned:
                reg = owned[int(self.rng.integers(len(owned)))]
                key = list(reg.buildings.keys())[int(self.rng.integers(len(reg.buildings)))]
                reg.buildings[key] -= 1
                if reg.buildings[key] <= 0:
                    del reg.buildings[key]
                self.log("storm",
                         f"Hyperstorm destroyed {BUILDINGS[key].name} in region {reg.rid}",
                         region=reg.rid, fid=reg.owner)

    # ------------------------------------------------------------------
    # Rebellions
    # ------------------------------------------------------------------

    def _rebellion_tick(self) -> None:
        B = BALANCE
        if self.tick < B["rebellion_grace_ticks"]:
            return
        rebels = self.factions[REBEL_FID]
        for reg in self.world.regions:
            if reg.owner < 0 or reg.owner == REBEL_FID:
                continue
            if reg.unrest < B["rebellion_unrest"]:
                continue
            if self.rng.random() >= B["rebellion_chance"]:
                continue

            old_owner = reg.owner
            reg.owner = REBEL_FID
            reg.unrest = 0.25                  # hope of freedom
            reg.entrenchment = 0.15
            reg.construction.clear()

            n_rebels = max(4, int(reg.population * B["rebel_army_per_pop"]))
            self.armies.append(Army.new(
                REBEL_FID, reg.rid, {"infantry": n_rebels}, "defend"))

            if not rebels.alive:
                rebels.alive = True
                rebels.capital = reg.rid
                rebels.treasury = 200.0
                rebels.leader = Leader.generate(self.rng)
                self.log("rebellion",
                         f"UPRISING! {rebels.leader.name} raises the banner of "
                         f"Free Coruscant in region {reg.rid}, torn from "
                         f"{self.factions[old_owner].name}",
                         fid=REBEL_FID, region=reg.rid, target=old_owner)
            else:
                if self.world.regions[rebels.capital].owner != REBEL_FID:
                    rebels.capital = reg.rid
                self.log("rebellion",
                         f"Region {reg.rid} joins the Free Coruscant uprising "
                         f"against {self.factions[old_owner].name}",
                         fid=REBEL_FID, region=reg.rid, target=old_owner)

            self.diplomacy.declare_war(self, REBEL_FID, old_owner, "uprising")
            self.check_faction_elimination(old_owner)

    # ------------------------------------------------------------------
    # Leaders
    # ------------------------------------------------------------------

    def _leader_tick(self) -> None:
        for fac in self.factions:
            if not fac.alive or fac.leader is None:
                continue
            fac.leader.tenure_left -= 1
            if fac.leader.tenure_left <= 0:
                old = fac.leader.name
                fac.leader = Leader.generate(self.rng)
                self.log("leader",
                         f"{old} of {fac.name} steps down; "
                         f"{fac.leader.name} takes power "
                         f"(martial {fac.leader.martial:.2f}, "
                         f"stewardship {fac.leader.stewardship:.2f})",
                         fid=fac.fid)

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    def handle_capital_loss(self, fid: int, lost_rid: int) -> None:
        fac = self.factions[fid]
        if fac.capital != lost_rid:
            return
        owned = self.world.owned_by(fid)
        owned = [r for r in owned if r.rid != lost_rid]
        if owned:
            new_cap = max(owned, key=lambda r: r.population)
            fac.capital = new_cap.rid
            self.log("capital",
                     f"The capital of {fac.name} falls! Government flees "
                     f"to region {new_cap.rid}", fid=fid, region=new_cap.rid)

    def check_faction_elimination(self, fid: int) -> None:
        fac = self.factions[fid]
        if fac.alive and not self.world.owned_by(fid):
            fac.alive = False
            fac.capital = -1
            for a in self.armies:
                if a.fid == fid:
                    a.composition.clear()
            for other in self.factions:
                if other.fid == fid:
                    continue
                pair = self.diplomacy._pair(fid, other.fid)
                self.diplomacy.wars.discard(pair)
                self.diplomacy.alliances.discard(pair)
            self.diplomacy.vassals.pop(fid, None)
            for v in self.diplomacy.vassals_of(fid):
                self.diplomacy.free_vassal(self, v, "the suzerain has fallen")
            if fid == REBEL_FID:
                self.log("elimination",
                         "The Free Coruscant uprising has been crushed... for now",
                         fid=fid)
            else:
                self.log("elimination",
                         f"{fac.name} has been wiped from the planet", fid=fid)

    def _cleanup(self) -> None:
        self.armies = [a for a in self.armies if a.size() > 0]
        # neutral militias slowly atrophy — late-game expansion gets easier
        if self.tick % 10 == 0:
            for reg in self.world.regions:
                if reg.owner == -1 and reg.militia > 4.0:
                    reg.militia = max(4.0, reg.militia - 0.15)

    def _record_charts(self) -> None:
        self.charts["tick"].append(self.tick)
        for fac in self.factions:
            regions = self.world.owned_by(fac.fid)
            self.charts["regions"][fac.fid].append(len(regions))
            self.charts["power"][fac.fid].append(round(fac.military_power, 1))
            self.charts["gdp"][fac.fid].append(round(fac.gdp, 1))
            self.charts["population"][fac.fid].append(
                round(sum(r.population for r in regions), 1))
        # cap chart length
        max_len = 400
        if len(self.charts["tick"]) > max_len:
            self.charts["tick"] = self.charts["tick"][-max_len:]
            for key in ("regions", "power", "gdp", "population"):
                for i in range(len(self.factions)):
                    self.charts[key][i] = self.charts[key][i][-max_len:]

    # ------------------------------------------------------------------
    # Snapshot / persistence
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict:
        regions_compact = {
            "owner": [r.owner for r in self.world.regions],
            "devastation": [round(r.devastation, 2) for r in self.world.regions],
            "population": [round(r.population, 1) for r in self.world.regions],
            "unrest": [round(r.unrest, 2) for r in self.world.regions],
        }
        armies = [
            {
                "aid": a.aid, "fid": a.fid, "rid": a.location,
                "lat": self.world.regions[a.location].lat,
                "lon": self.world.regions[a.location].lon,
                "size": a.size(),
                "power": round(a.attack_power(), 1),
                "stance": a.stance,
                "moving": bool(a.path),
                "in_battle": a.in_battle,
                "comp": a.composition,
            }
            for a in self.armies if a.size() > 0
        ]
        factions = [
            {
                "fid": f.fid, "name": f.name, "colour": f.colour, "alive": f.alive,
                "regions": len(self.world.owned_by(f.fid)),
                "treasury": round(f.treasury, 0),
                "income": round(f.income, 1),
                "gdp": round(f.gdp, 1),
                "power": round(f.military_power, 1),
                "doctrine": f.doctrine,
                "tech": f.tech,
                "science": round(f.science, 0),
                "research_target": f.research_target,
                "at_war_with": self.diplomacy.enemies_of(f.fid),
                "capital": f.capital,
                "leader": ({"name": f.leader.name,
                            "martial": round(f.leader.martial, 2),
                            "stewardship": round(f.leader.stewardship, 2)}
                           if f.leader else None),
                "suzerain": self.diplomacy.suzerain_of(f.fid),
            }
            for f in self.factions
        ]
        return {
            "tick": self.tick,
            "n_regions": N_REGIONS,
            "region_cols": REGION_COLS,
            "regions": regions_compact,
            "armies": armies,
            "factions": factions,
            "diplomacy": self.diplomacy.snapshot(),
            "battles": list(self.battles_recent)[-25:],
            "events": list(self.events)[-40:],
            "charts": self.charts,
            "trade_routes": self.trade_pairs(),
            "blocked_routes": self.blocked_routes(),
        }

    def timeline_snapshot(self) -> Dict:
        return {
            "keyframes": list(self.timeline),
            "factions": [{"fid": f.fid, "colour": f.colour, "name": f.name}
                         for f in self.factions],
        }

    def region_detail(self, rid: int) -> Dict:
        r = self.world.regions[rid]
        return {
            "rid": r.rid, "lat": r.lat, "lon": r.lon,
            "owner": r.owner,
            "owner_name": self.factions[r.owner].name if r.owner >= 0 else "Neutral",
            "population": round(r.population, 1),
            "unrest": round(r.unrest, 2),
            "devastation": round(r.devastation, 2),
            "fertility": round(r.fertility, 2),
            "materials_richness": round(r.materials_richness, 2),
            "energy_potential": round(r.energy_potential, 2),
            "infrastructure": r.infrastructure,
            "militia": round(r.militia, 1),
            "buildings": r.buildings,
            "construction": r.construction,
            "stock": {k: round(v, 1) for k, v in r.stock.items()},
            "armies": [
                {"fid": a.fid, "size": a.size(), "stance": a.stance, "comp": a.composition}
                for a in self.armies if a.location == rid and a.size() > 0
            ],
        }

    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        data = {
            "tick": self.tick,
            "seed": self.cfg.seed,
            "regions": [
                {
                    "rid": r.rid, "owner": r.owner,
                    "population": r.population,
                    "infrastructure": r.infrastructure,
                    "unrest": r.unrest, "devastation": r.devastation,
                    "militia": r.militia, "entrenchment": r.entrenchment,
                    "fertility": r.fertility,
                    "materials_richness": r.materials_richness,
                    "energy_potential": r.energy_potential,
                    "buildings": r.buildings,
                    "construction": r.construction,
                    "stock": r.stock,
                }
                for r in self.world.regions
            ],
            "factions": [
                {
                    "fid": f.fid, "alive": f.alive, "treasury": f.treasury,
                    "science": f.science, "prod_pool": f.prod_pool,
                    "tech": f.tech, "doctrine": f.doctrine,
                    "capital": f.capital,
                    "war_weariness": {str(k): v for k, v in f.war_weariness.items()},
                    "leader": ({"name": f.leader.name, "martial": f.leader.martial,
                                "stewardship": f.leader.stewardship,
                                "tenure_left": f.leader.tenure_left}
                               if f.leader else None),
                }
                for f in self.factions
            ],
            "armies": [
                {
                    "aid": a.aid, "fid": a.fid, "location": a.location,
                    "composition": a.composition, "path": a.path,
                    "stance": a.stance,
                }
                for a in self.armies if a.size() > 0
            ],
            "diplomacy": {
                "relations": self.diplomacy.relations.tolist(),
                "wars": sorted(list(self.diplomacy.wars)),
                "alliances": sorted(list(self.diplomacy.alliances)),
                "truces": {f"{k[0]},{k[1]}": v for k, v in self.diplomacy.truces.items()},
                "war_score": {f"{k[0]},{k[1]}": v for k, v in self.diplomacy.war_score.items()},
                "vassals": {str(k): v for k, v in self.diplomacy.vassals.items()},
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    @staticmethod
    def load(path: str, config: Optional[EngineConfig] = None) -> "StrategyEngine":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = config or EngineConfig()
        cfg.seed = data.get("seed", cfg.seed)
        engine = StrategyEngine(cfg)
        engine.tick = data["tick"]
        engine.armies.clear()

        for rdata in data["regions"]:
            r = engine.world.regions[rdata["rid"]]
            for key in ("owner", "population", "infrastructure", "unrest",
                        "devastation", "militia", "entrenchment", "fertility",
                        "materials_richness", "energy_potential"):
                setattr(r, key, rdata[key])
            r.buildings = {k: int(v) for k, v in rdata["buildings"].items()}
            r.construction = rdata["construction"]
            r.stock = rdata["stock"]

        for fdata in data["factions"]:
            f = engine.factions[fdata["fid"]]
            f.alive = fdata["alive"]
            f.treasury = fdata["treasury"]
            f.science = fdata["science"]
            f.prod_pool = fdata["prod_pool"]
            f.tech = fdata["tech"]
            f.doctrine = fdata["doctrine"]
            f.capital = fdata["capital"]
            f.war_weariness = {int(k): v for k, v in fdata["war_weariness"].items()}
            ld = fdata.get("leader")
            f.leader = Leader(name=ld["name"], martial=ld["martial"],
                              stewardship=ld["stewardship"],
                              tenure_left=ld["tenure_left"]) if ld else None

        for adata in data["armies"]:
            army = Army(aid=adata["aid"], fid=adata["fid"],
                        location=adata["location"],
                        composition={k: int(v) for k, v in adata["composition"].items()},
                        path=adata["path"], stance=adata["stance"])
            engine.armies.append(army)

        d = data["diplomacy"]
        engine.diplomacy.relations = np.array(d["relations"], dtype=np.float64)
        engine.diplomacy.wars = {tuple(p) for p in d["wars"]}
        engine.diplomacy.alliances = {tuple(p) for p in d["alliances"]}
        engine.diplomacy.truces = {
            tuple(int(x) for x in k.split(",")): v for k, v in d["truces"].items()
        }
        engine.diplomacy.war_score = {
            tuple(int(x) for x in k.split(",")): v for k, v in d["war_score"].items()
        }
        engine.diplomacy.vassals = {
            int(k): v for k, v in d.get("vassals", {}).items()
        }
        return engine
