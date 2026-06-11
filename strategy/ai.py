"""Two-level faction AI.

Strategic level: pick a doctrine (develop / expand / militarize / science /
defend) from the situation + personality.
Operational level: construction, recruitment, research, army orders,
war declarations.
"""

from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

import numpy as np

from strategy.data import BALANCE, BUILDINGS, UNITS, TECH_BRANCHES
from strategy.state import Army, FactionRuntime
from strategy.world import Region

if TYPE_CHECKING:
    from strategy.engine import StrategyEngine


DOCTRINES = ("develop", "expand", "militarize", "science", "defend")


def faction_ai_step(engine: "StrategyEngine", fac: FactionRuntime) -> None:
    if not fac.alive:
        return
    _update_doctrine(engine, fac)
    _research(engine, fac)
    _construct(engine, fac)
    _recruit(engine, fac)
    _consider_war(engine, fac)
    _army_orders(engine, fac)


# ---------------------------------------------------------------------------
# Strategic level
# ---------------------------------------------------------------------------

def _update_doctrine(engine: "StrategyEngine", fac: FactionRuntime) -> None:
    fac.doctrine_age += 1
    if fac.doctrine_age < BALANCE["doctrine_inertia"]:
        return

    threat = _threat_level(engine, fac)
    at_war = bool(engine.diplomacy.enemies_of(fac.fid))
    neutrals_nearby = _adjacent_neutrals(engine, fac.fid)
    my_regions = len(engine.world.owned_by(fac.fid))

    scores = {
        "develop": 0.45 + fac.greed * 0.4 + (0.35 if fac.food_balance < 0 else 0.0),
        "expand": (0.55 + 0.5 * fac.aggression) * (1.0 if neutrals_nearby else 0.1)
                  * (1.5 if my_regions < 14 else 0.5),
        "militarize": 0.2 + threat * 1.2 + (0.8 if at_war else 0.0) + fac.aggression * 0.3,
        "science": 0.25 + fac.curiosity * 0.8 - threat * 0.4,
        "defend": threat * 1.6 + (0.5 if at_war else 0.0) - fac.aggression * 0.2,
    }
    new_doc = max(scores, key=scores.get)
    if new_doc != fac.doctrine:
        fac.doctrine = new_doc
        fac.doctrine_age = 0
        engine.log("doctrine", f"{fac.name} shifts doctrine to {new_doc}", fid=fac.fid)


def _threat_level(engine: "StrategyEngine", fac: FactionRuntime) -> float:
    """0..1: enemy armies near borders + relative weakness."""
    my_power = max(fac.military_power, 1.0)
    hostile_near = 0.0
    my_region_ids = {r.rid for r in engine.world.owned_by(fac.fid)}
    border_zone = set()
    for rid in my_region_ids:
        border_zone.add(rid)
        border_zone.update(engine.world.neighbours(rid))
    for army in engine.armies:
        if army.fid == fac.fid or army.size() == 0:
            continue
        if engine.diplomacy.at_war(fac.fid, army.fid) and army.location in border_zone:
            hostile_near += army.attack_power()
    rel_weak = 0.0
    for other in engine.factions:
        if other.fid != fac.fid and other.alive and \
                engine.diplomacy.relations[fac.fid, other.fid] < -30.0:
            if other.military_power > my_power * 1.4:
                rel_weak += 0.25
    return float(np.clip(hostile_near / (my_power * 2.0) + rel_weak, 0.0, 1.0))


def _adjacent_neutrals(engine: "StrategyEngine", fid: int) -> List[int]:
    out = set()
    for reg in engine.world.owned_by(fid):
        for n in engine.world.neighbours(reg.rid):
            if engine.world.regions[n].owner == -1:
                out.add(n)
    return sorted(out)


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------

def _research(engine: "StrategyEngine", fac: FactionRuntime) -> None:
    weights = {
        "military": 0.2 + fac.aggression * 0.6 + (0.6 if fac.doctrine in ("militarize", "defend") else 0.0),
        "economy": 0.25 + fac.greed * 0.5 + (0.4 if fac.doctrine == "develop" else 0.0),
        "science": 0.15 + fac.curiosity * 0.5 + (0.5 if fac.doctrine == "science" else 0.0),
        "infrastructure": 0.2 + (0.3 if fac.doctrine == "develop" else 0.0),
    }
    # don't over-invest in a maxed branch
    for b in TECH_BRANCHES:
        if fac.tech[b] >= 6:
            weights[b] = 0.0
    if all(w == 0.0 for w in weights.values()):
        return
    fac.research_target = max(weights, key=weights.get)

    cost = fac.tech_cost(fac.research_target)
    if fac.science >= cost:
        fac.science -= cost
        fac.tech[fac.research_target] += 1
        tier = fac.tech[fac.research_target]
        from strategy.data import TECH_NAMES
        name = TECH_NAMES[fac.research_target][min(tier - 1, 5)]
        engine.log("tech", f"{fac.name} researched {name} "
                           f"({fac.research_target} tier {tier})", fid=fac.fid)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def _construct(engine: "StrategyEngine", fac: FactionRuntime) -> None:
    regions = engine.world.owned_by(fac.fid)
    if not regions:
        return

    needs = _building_needs(engine, fac, regions)
    if not needs:
        return

    infra_bonus = sum(1 for t in (2, 4) if fac.tech["infrastructure"] >= t)

    for key in needs:
        bt = BUILDINGS[key]
        branch, tier = bt.tech_required
        if branch and fac.tech[branch] < tier:
            continue
        # pick best region: has slot, low devastation, relevant endowment
        candidates = [
            r for r in regions
            if r.used_slots() < r.slots(infra_bonus) and r.devastation < 0.6
        ]
        if not candidates:
            return
        scorer = {
            "mine": lambda r: r.materials_richness,
            "farm": lambda r: r.fertility,
            "reactor": lambda r: r.energy_potential,
            "defense": lambda r: 2.0 if _is_border(engine, r) else 0.3,
            "citadel": lambda r: 2.0 if _is_border(engine, r) else 0.5,
        }.get(key, lambda r: r.population / 100.0)
        best = max(candidates, key=scorer)

        if fac.treasury < bt.cost_credits or best.stock["materials"] < bt.cost_materials:
            continue
        fac.treasury -= bt.cost_credits
        best.stock["materials"] -= bt.cost_materials
        best.construction.append({"key": key, "ticks_left": bt.build_ticks})
        break   # one new project per tick keeps spending sane


def _building_needs(engine: "StrategyEngine", fac: FactionRuntime,
                    regions: List[Region]) -> List[str]:
    """Ordered list of building keys the faction wants most."""
    count: Dict[str, int] = {}
    for r in regions:
        for k, n in r.buildings.items():
            count[k] = count.get(k, 0) + n
        for c in r.construction:
            count[c["key"]] = count.get(c["key"], 0) + 1

    n_reg = len(regions)
    needs: List[str] = []

    if fac.food_balance < n_reg * 0.5:
        needs.append("farm")
    energy_total = sum(r.stock["energy"] for r in regions)
    if energy_total < n_reg * 2.0:
        needs.append("reactor")
    if count.get("mine", 0) < max(2, n_reg // 3):
        needs.append("mine")
    if fac.doctrine in ("militarize", "defend"):
        if count.get("factory", 0) < max(1, n_reg // 4):
            needs.append("factory")
        needs.append("defense")
        if fac.tech["military"] >= 3:
            needs.append("citadel")
    if fac.doctrine == "science" or fac.curiosity > 0.6:
        if count.get("lab", 0) < max(1, n_reg // 3):
            needs.append("lab")
    if fac.doctrine == "develop":
        if count.get("spaceport", 0) < max(1, n_reg // 5):
            needs.append("spaceport")
        needs.append("mine")
    if count.get("factory", 0) == 0:
        needs.insert(0, "factory")
    if count.get("lab", 0) == 0:
        needs.append("lab")
    return needs


def _is_border(engine: "StrategyEngine", region: Region) -> bool:
    for n in engine.world.neighbours(region.rid):
        if engine.world.regions[n].owner != region.owner:
            return True
    return False


# ---------------------------------------------------------------------------
# Recruitment
# ---------------------------------------------------------------------------

def _recruit(engine: "StrategyEngine", fac: FactionRuntime) -> None:
    if fac.prod_pool < 20.0:
        return
    want_military = fac.doctrine in ("militarize", "defend", "expand") \
        or bool(engine.diplomacy.enemies_of(fac.fid))
    if not want_military and fac.military_power > 150.0:
        return

    # best unit the faction can afford and has tech for
    order = ["fleet", "aircraft", "armor", "infantry"]
    factories = [
        r for r in engine.world.owned_by(fac.fid)
        if r.buildings.get("factory", 0) or r.buildings.get("citadel", 0)
    ]
    if not factories:
        return
    site = max(factories, key=lambda r: r.buildings.get("factory", 0))

    for key in order:
        ut = UNITS[key]
        branch, tier = ut.tech_required
        if branch and fac.tech[branch] < tier:
            continue
        if fac.prod_pool < ut.prod_points or fac.treasury < ut.cost_credits \
                or site.stock["materials"] < ut.cost_materials:
            continue
        n = int(min(
            fac.prod_pool // ut.prod_points,
            fac.treasury // ut.cost_credits,
            site.stock["materials"] // ut.cost_materials,
            4,
        ))
        if n <= 0:
            continue
        fac.prod_pool -= ut.prod_points * n
        fac.treasury -= ut.cost_credits * n
        site.stock["materials"] -= ut.cost_materials * n

        garrison = _garrison_at(engine, fac.fid, site.rid)
        if garrison is not None:
            garrison.composition[key] = garrison.composition.get(key, 0) + n
        else:
            engine.armies.append(Army.new(fac.fid, site.rid, {key: n}, "garrison"))
        break


def _garrison_at(engine: "StrategyEngine", fid: int, rid: int) -> Optional[Army]:
    for a in engine.armies:
        if a.fid == fid and a.location == rid and not a.path and \
                a.stance in ("garrison", "defend"):
            return a
    return None


# ---------------------------------------------------------------------------
# War declarations
# ---------------------------------------------------------------------------

def _consider_war(engine: "StrategyEngine", fac: FactionRuntime) -> None:
    if engine.diplomacy.enemies_of(fac.fid):
        return                                  # one war at a time
    B = BALANCE
    for other in engine.factions:
        if other.fid == fac.fid or not other.alive:
            continue
        rel = engine.diplomacy.relations[fac.fid, other.fid]
        if rel > B["war_relation_threshold"]:
            continue
        if engine.diplomacy._pair(fac.fid, other.fid) in engine.diplomacy.truces:
            continue
        advantage = fac.military_power / max(other.military_power, 1.0)
        # allies of the target deter aggression
        for ally in engine.factions:
            if ally.alive and ally.fid not in (fac.fid, other.fid) and \
                    engine.diplomacy.allied(other.fid, ally.fid):
                advantage *= 0.6
        threshold = B["war_advantage_required"] * (1.0 - 0.3 * fac.aggression)
        if advantage >= threshold and _shares_border(engine, fac.fid, other.fid):
            engine.diplomacy.declare_war(engine, fac.fid, other.fid,
                                         "border dispute" if rel > -70 else "deep hostility")
            return


def _shares_border(engine: "StrategyEngine", a: int, b: int) -> bool:
    for reg in engine.world.owned_by(a):
        for n in engine.world.neighbours(reg.rid):
            if engine.world.regions[n].owner == b:
                return True
    return False


# ---------------------------------------------------------------------------
# Army orders
# ---------------------------------------------------------------------------

def _army_orders(engine: "StrategyEngine", fac: FactionRuntime) -> None:
    my_armies = [a for a in engine.armies if a.fid == fac.fid and a.size() > 0]
    if not my_armies:
        return
    enemies = engine.diplomacy.enemies_of(fac.fid)
    idle = [a for a in my_armies if not a.path and not a.in_battle]

    # 1) defense: send idle armies toward threatened own regions
    threatened = _threatened_regions(engine, fac.fid)
    if threatened:
        for a in idle[:]:
            if a.stance == "garrison" and a.location in threatened:
                continue
            target = threatened[0]
            if a.location != target:
                _send(engine, a, target, "defend")
                idle.remove(a)
            if len(idle) <= 1:
                break

    # 2) offense: at war -> attack adjacent enemy regions
    if enemies:
        field_armies = [a for a in idle if a.attack_power() > 25.0]
        targets = _attack_targets(engine, fac.fid, enemies)
        for a in field_armies:
            if not targets:
                break
            target = min(targets, key=lambda t: _path_len(engine, a, t[0]) - t[1] * 0.1)
            targets.remove(target)
            _send(engine, a, target[0], "attack")

    # 3) expansion: at peace, claim adjacent neutral regions (any doctrine,
    #    but keep a garrison at the capital)
    else:
        neutrals = _adjacent_neutrals(engine, fac.fid)
        threshold = BALANCE["expansion_army_power"] * 0.6
        expeditions: List[Army] = []
        for a in idle:
            if a.attack_power() < threshold:
                continue
            if a.location == fac.capital and a.stance == "garrison":
                # keep half home, send half out
                if a.attack_power() >= threshold * 2.5:
                    detachment = a.split_half()
                    engine.armies.append(detachment)
                    expeditions.append(detachment)
            else:
                expeditions.append(a)
        if fac.doctrine != "expand":
            expeditions = expeditions[:1]      # cautious trickle expansion
        for a in expeditions:
            if not neutrals:
                break
            target = min(neutrals, key=lambda rid: _path_len(engine, a, rid))
            neutrals.remove(target)
            _send(engine, a, target, "expand")

    # 4) consolidation: merge tiny garrisons sitting in the same region
    _merge_colocated(engine, fac.fid)


def _threatened_regions(engine: "StrategyEngine", fid: int) -> List[int]:
    out = []
    for reg in engine.world.owned_by(fid):
        for army in engine.armies:
            if army.size() > 0 and army.fid != fid and \
                    engine.diplomacy.at_war(fid, army.fid) and \
                    (army.location == reg.rid or
                     reg.rid in engine.world.neighbours(army.location)):
                out.append(reg.rid)
                break
    return out


def _attack_targets(engine: "StrategyEngine", fid: int,
                    enemies: List[int]) -> List[tuple]:
    """(rid, value) of enemy regions adjacent to our territory or armies."""
    targets = []
    frontier = {r.rid for r in engine.world.owned_by(fid)}
    for army in engine.armies:
        if army.fid == fid:
            frontier.add(army.location)
    seen = set()
    for rid in frontier:
        for n in engine.world.neighbours(rid):
            reg = engine.world.regions[n]
            if reg.owner in enemies and n not in seen:
                seen.add(n)
                value = reg.population / 50.0 + len(reg.buildings) \
                    - sum(BUILDINGS[k].defense * c for k, c in reg.buildings.items()) / 80.0
                targets.append((n, value))
    return targets


def _path_len(engine: "StrategyEngine", army: Army, dst: int) -> int:
    path = engine.world.shortest_path(army.location, dst)
    return len(path) if path else 999


def _send(engine: "StrategyEngine", army: Army, dst: int, stance: str) -> None:
    fid = army.fid

    def passable(rid: int) -> bool:
        owner = engine.world.regions[rid].owner
        return owner == fid or owner == -1 or engine.diplomacy.at_war(fid, owner)

    path = engine.world.shortest_path(army.location, dst, passable)
    if path and len(path) > 1:
        army.path = path[1:]
        army.move_progress = 0
        army.stance = stance


def _merge_colocated(engine: "StrategyEngine", fid: int) -> None:
    by_loc: Dict[int, List[Army]] = {}
    for a in engine.armies:
        if a.fid == fid and a.size() > 0 and not a.path:
            by_loc.setdefault(a.location, []).append(a)
    for armies in by_loc.values():
        if len(armies) > 1:
            base = armies[0]
            for extra in armies[1:]:
                base.merge(extra)
                extra.composition.clear()
