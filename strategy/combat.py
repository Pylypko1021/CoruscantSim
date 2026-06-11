"""Combat resolution: battles between armies, sieges and region capture.

A battle happens every tick in any region containing units of factions
that are at war (or an army attacking neutral militia). Resolution is
attritional: both sides take proportional casualties until one routs,
is destroyed, or the attacker captures the region.
"""

from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

from strategy.data import BALANCE, BUILDINGS
from strategy.state import Army, FactionRuntime
from strategy.world import Region

if TYPE_CHECKING:
    from strategy.engine import StrategyEngine


def resolve_region_combat(engine: "StrategyEngine", region: Region) -> Optional[Dict]:
    """Resolve one tick of combat in `region`. Returns a battle record or None."""
    armies_here = [a for a in engine.armies if a.location == region.rid and a.size() > 0]
    if not armies_here:
        _maybe_capture_empty(engine, region)
        return None

    # Group armies by faction
    by_fid: Dict[int, List[Army]] = {}
    for a in armies_here:
        by_fid.setdefault(a.fid, []).append(a)

    # Determine the defender side: region owner (or neutral militia)
    defender_fid = region.owner
    if defender_fid == -1:
        # neutral militia only fights armies that came here on purpose
        attacker_fids = sorted({
            a.fid for a in armies_here
            if a.stance in ("attack", "expand") and not a.path
        })
    else:
        attacker_fids = [
            fid for fid in by_fid
            if fid != defender_fid and engine.diplomacy.at_war(fid, defender_fid)
        ]
    if not attacker_fids:
        # peaceful presence: garrisons entrench
        if defender_fid in by_fid:
            region.entrenchment = min(0.3, region.entrenchment + BALANCE["entrench_per_tick"])
        _maybe_capture_empty(engine, region)
        return None

    # strongest attacker faction fights this tick (others wait)
    attacker_fid = max(
        attacker_fids,
        key=lambda f: sum(a.attack_power() for a in by_fid[f]),
    )
    if defender_fid == -1:
        attackers = [a for a in by_fid[attacker_fid]
                     if a.stance in ("attack", "expand") and not a.path]
    else:
        attackers = by_fid[attacker_fid]
    att_fac = engine.factions[attacker_fid]

    defenders = by_fid.get(defender_fid, []) if defender_fid >= 0 else []
    def_fac = engine.factions[defender_fid] if defender_fid >= 0 else None

    # --- power computation -------------------------------------------------
    att_power = sum(a.attack_power(att_fac.attack_mult()) for a in attackers)
    att_power *= 1.0 - 0.25 * region.devastation        # scorched ground hurts supply

    def_mult = def_fac.defense_mult() if def_fac else 1.0
    def_power = sum(a.defense_power(def_mult) for a in defenders)
    def_power += region.militia if defender_fid == -1 else 0.0
    static_def = _static_defense(region)
    if defenders or defender_fid == -1:
        def_power += static_def
    if defender_fid >= 0:
        def_power *= BALANCE["defender_home_bonus"] * (1.0 + region.entrenchment)

    if att_power <= 0.0:
        return None

    total = att_power + def_power
    intensity = BALANCE["combat_intensity"]

    # --- casualties ---------------------------------------------------------
    att_losses_frac = intensity * (def_power / total) if total > 0 else 0.0
    def_losses_frac = intensity * (att_power / total) if total > 0 else 0.0

    for a in attackers:
        a.apply_losses(att_losses_frac)
        a.in_battle = True
    for d in defenders:
        d.apply_losses(def_losses_frac)
        d.in_battle = True
    if defender_fid == -1:
        region.militia = max(0.0, region.militia * (1.0 - def_losses_frac * 1.5))

    # collateral damage
    region.devastation = min(1.0, region.devastation + 0.01)
    region.population = max(1.0, region.population * (1.0 - 0.002))

    # --- outcome ------------------------------------------------------------
    def_alive = (
        any(d.size() > 0 for d in defenders)
        or (defender_fid == -1 and region.militia > 2.0)
    )
    att_alive = any(a.size() > 0 for a in attackers)

    outcome = "ongoing"
    if att_alive and not def_alive:
        outcome = _capture(engine, region, attacker_fid)
    elif not att_alive:
        outcome = "attacker_destroyed"
    else:
        # rout checks
        if def_power > 0 and att_power / max(def_power, 1e-6) < BALANCE["rout_ratio"]:
            _retreat(engine, attackers, region)
            outcome = "attacker_routed"
        elif att_power > 0 and defenders and def_power / att_power < BALANCE["rout_ratio"]:
            _retreat(engine, defenders, region)
            outcome = _capture(engine, region, attacker_fid)

    # war score bookkeeping
    if def_fac is not None:
        engine.diplomacy.add_war_score(attacker_fid, defender_fid,
                                       def_losses_frac - att_losses_frac)

    return {
        "tick": engine.tick,
        "region": region.rid,
        "attacker": attacker_fid,
        "defender": defender_fid,
        "att_power": round(att_power, 1),
        "def_power": round(def_power, 1),
        "outcome": outcome,
    }


# ---------------------------------------------------------------------------


def _static_defense(region: Region) -> float:
    total = 0.0
    for key, count in region.buildings.items():
        total += BUILDINGS[key].defense * count
    return total


def _capture(engine: "StrategyEngine", region: Region, new_owner: int) -> str:
    old_owner = region.owner
    region.owner = new_owner
    region.militia = 0.0
    region.entrenchment = 0.0
    region.unrest = min(1.0, region.unrest + 0.35)
    region.devastation = min(1.0, region.devastation + BALANCE["capture_devastation"])
    region.population = max(1.0, region.population * 0.93)

    # some buildings are destroyed in the takeover
    rng = engine.rng
    for key in list(region.buildings.keys()):
        survivors = sum(1 for _ in range(region.buildings[key]) if rng.random() > 0.2)
        if survivors:
            region.buildings[key] = survivors
        else:
            del region.buildings[key]
    region.construction.clear()

    if old_owner >= 0:
        engine.diplomacy.add_war_score(new_owner, old_owner, 2.0)
        engine.log("capture",
                   f"{engine.factions[new_owner].name} captured region {region.rid} "
                   f"from {engine.factions[old_owner].name}",
                   fid=new_owner, region=region.rid)
        engine.check_faction_elimination(old_owner)
    else:
        engine.log("expand",
                   f"{engine.factions[new_owner].name} annexed neutral region {region.rid}",
                   fid=new_owner, region=region.rid)
    return "captured"


def _retreat(engine: "StrategyEngine", armies: List[Army], region: Region) -> None:
    """Routed armies fall back to the nearest friendly region (or die)."""
    for a in armies:
        if a.size() == 0:
            continue
        home = None
        for n in engine.world.neighbours(region.rid):
            if engine.world.regions[n].owner == a.fid:
                home = n
                break
        if home is None:
            a.apply_losses(0.5)     # cut off — heavy losses
            owned = engine.world.owned_by(a.fid)
            if owned:
                home = owned[0].rid
        if home is not None and a.size() > 0:
            a.location = home
            a.path = []
            a.move_progress = 0
            a.stance = "defend"
        else:
            a.composition.clear()


def _maybe_capture_empty(engine: "StrategyEngine", region: Region) -> None:
    """An army sitting alone in an enemy/neutral region with no resistance
    takes control (handles undefended regions without a formal battle)."""
    armies_here = [a for a in engine.armies if a.location == region.rid and a.size() > 0]
    if len({a.fid for a in armies_here}) != 1:
        return
    fid = armies_here[0].fid
    if region.owner == fid:
        return
    arrived = [a for a in armies_here
               if a.stance in ("attack", "expand") and not a.path]
    if not arrived:
        return
    if region.owner == -1 and region.militia <= 2.0:
        _capture(engine, region, fid)
        for a in arrived:
            a.stance = "garrison"
    elif region.owner >= 0 and engine.diplomacy.at_war(fid, region.owner):
        _capture(engine, region, fid)
        for a in arrived:
            a.stance = "garrison"
