"""Regression tests for the autonomous RTS layer.

Run:  python tests_strategy.py
Expected final line:  strategy_tests_ok
"""

from __future__ import annotations

import json
import math
import os
import tempfile

import numpy as np

from strategy.engine import StrategyEngine, EngineConfig
from strategy.state import Army
from strategy.world import N_REGIONS


def assert_true(name: str, condition: bool):
    if not condition:
        raise AssertionError(name)


# ---------------------------------------------------------------------------
# 1. World generation
# ---------------------------------------------------------------------------

def test_world_setup():
    eng = StrategyEngine(EngineConfig(seed=1, use_physics=False))
    assert_true("region count", len(eng.world.regions) == N_REGIONS)
    assert_true("six factions (5 + rebels)", len(eng.factions) == 6)
    owned = [r for r in eng.world.regions if r.owner >= 0]
    assert_true("factions seeded", len(owned) == 5 * eng.cfg.start_regions_per_faction)
    playable = [f for f in eng.factions if f.fid != 5]
    assert_true("five capitals", len({f.capital for f in playable}) == 5)
    rebels = eng.factions[5]
    assert_true("rebels dormant", not rebels.alive and rebels.capital == -1)
    for f in playable:
        cap = eng.world.regions[f.capital]
        assert_true("capital owned", cap.owner == f.fid)
        assert_true("capital has factory", cap.buildings.get("factory", 0) >= 1)
        assert_true("has leader", f.leader is not None and len(f.leader.name) > 3)
    # adjacency sanity: every region has 3-4 neighbours, all valid
    for r in eng.world.regions:
        ns = eng.world.neighbours(r.rid)
        assert_true("neighbour count", 3 <= len(ns) <= 4)
        assert_true("neighbour ids valid", all(0 <= n < N_REGIONS for n in ns))


# ---------------------------------------------------------------------------
# 2. Long run: stability + liveliness invariants
# ---------------------------------------------------------------------------

def test_long_run_invariants():
    eng = StrategyEngine(EngineConfig(seed=42, use_physics=False))
    for _ in range(1500):
        eng.step()

    for r in eng.world.regions:
        assert_true("population finite", math.isfinite(r.population) and r.population >= 1.0)
        assert_true("unrest bounded", 0.0 <= r.unrest <= 1.0)
        assert_true("devastation bounded", 0.0 <= r.devastation <= 1.0)
        for k, v in r.stock.items():
            assert_true(f"stock {k} non-negative finite", math.isfinite(v) and v >= 0.0)
    for f in eng.factions:
        assert_true("treasury finite", math.isfinite(f.treasury) and f.treasury >= 0.0)
        assert_true("science finite", math.isfinite(f.science))
        for b, t in f.tech.items():
            assert_true("tech tier bounded", 0 <= t <= 6)

    counts = {}
    for ev in eng.events:
        counts[ev["type"]] = counts.get(ev["type"], 0) + 1
    assert_true("expansion happened", counts.get("expand", 0) > 5)
    assert_true("construction happened", counts.get("built", 0) > 20)
    assert_true("research happened", counts.get("tech", 0) > 10)
    assert_true("battles happened", counts.get("battle", 0) > 0)
    assert_true("no early total wipeout",
                sum(1 for f in eng.factions if f.alive) >= 3)


# ---------------------------------------------------------------------------
# 3. Combat: a strong army takes an undefended enemy region
# ---------------------------------------------------------------------------

def test_combat_capture():
    eng = StrategyEngine(EngineConfig(seed=3, use_physics=False))
    a_fid, b_fid = 0, 1
    eng.diplomacy.declare_war(eng, a_fid, b_fid, "test")
    assert_true("war registered", eng.diplomacy.at_war(a_fid, b_fid))

    target = next(r for r in eng.world.regions if r.owner == b_fid)
    target.buildings.clear()
    invader = Army.new(a_fid, target.rid, {"armor": 30}, "attack")
    eng.armies.append(invader)

    for _ in range(40):
        eng.step()
        if target.owner == a_fid:
            break
    assert_true("region captured", target.owner == a_fid)
    assert_true("war score moved",
                eng.diplomacy.war_score.get((a_fid, b_fid), 0.0) > 0.0)


# ---------------------------------------------------------------------------
# 4. Determinism: same seed -> same outcome
# ---------------------------------------------------------------------------

def test_determinism():
    def fingerprint(seed: int) -> str:
        eng = StrategyEngine(EngineConfig(seed=seed, use_physics=False))
        for _ in range(300):
            eng.step()
        snap = eng.snapshot()
        return json.dumps({
            "owners": snap["regions"]["owner"],
            "treasuries": [f["treasury"] for f in snap["factions"]],
            "armies": sorted((a["fid"], a["rid"], a["size"]) for a in snap["armies"]),
        }, sort_keys=True)

    assert_true("deterministic", fingerprint(99) == fingerprint(99))


# ---------------------------------------------------------------------------
# 5. Save / load roundtrip
# ---------------------------------------------------------------------------

def test_save_load():
    eng = StrategyEngine(EngineConfig(seed=5, use_physics=False))
    for _ in range(400):
        eng.step()

    path = os.path.join(tempfile.gettempdir(), "coruscant_rts_test_save.json")
    eng.save(path)
    loaded = StrategyEngine.load(path, EngineConfig(seed=5, use_physics=False))

    assert_true("tick restored", loaded.tick == eng.tick)
    for r1, r2 in zip(eng.world.regions, loaded.world.regions):
        assert_true("owner restored", r1.owner == r2.owner)
        assert_true("pop restored", abs(r1.population - r2.population) < 1e-9)
        assert_true("buildings restored", r1.buildings == r2.buildings)
    for f1, f2 in zip(eng.factions, loaded.factions):
        assert_true("treasury restored", abs(f1.treasury - f2.treasury) < 1e-9)
        assert_true("tech restored", f1.tech == f2.tech)
    assert_true("wars restored", eng.diplomacy.wars == loaded.diplomacy.wars)
    assert_true("armies restored",
                sorted((a.fid, a.location, a.size()) for a in eng.armies)
                == sorted((a.fid, a.location, a.size()) for a in loaded.armies))
    # loaded engine must keep running
    for _ in range(50):
        loaded.step()
    os.remove(path)


# ---------------------------------------------------------------------------
# 6. Snapshot is JSON-serializable and complete
# ---------------------------------------------------------------------------

def test_snapshot_schema():
    eng = StrategyEngine(EngineConfig(seed=8, use_physics=False))
    for _ in range(120):
        eng.step()
    snap = eng.snapshot()
    encoded = json.dumps(snap)            # must not raise
    assert_true("snapshot has factions", len(snap["factions"]) == 6)
    json.dumps(eng.timeline_snapshot())   # timeline endpoint payload
    assert_true("timeline keyframes", len(eng.timeline) > 0)
    assert_true("snapshot owners", len(snap["regions"]["owner"]) == N_REGIONS)
    assert_true("snapshot armies list", isinstance(snap["armies"], list))
    assert_true("snapshot charts", len(snap["charts"]["tick"]) > 0)
    detail = eng.region_detail(0)
    json.dumps(detail)
    assert_true("region detail keys",
                {"rid", "owner", "population", "buildings", "stock"} <= set(detail))


# ---------------------------------------------------------------------------
# 7. Vassalization: crushing defeat of a small power -> capitulation
# ---------------------------------------------------------------------------

def test_vassalization():
    eng = StrategyEngine(EngineConfig(seed=13, use_physics=False))
    eng.diplomacy.declare_war(eng, 0, 1, "test")
    # faction 1 is small and badly losing
    regions_1 = eng.world.owned_by(1)
    for r in regions_1[3:]:
        r.owner = 0
    eng.diplomacy.war_score[(0, 1)] = 10.0
    eng.diplomacy.war_score[(1, 0)] = -10.0
    eng.diplomacy.make_peace(eng, 0, 1)
    assert_true("vassalized", eng.diplomacy.suzerain_of(1) == 0)
    assert_true("war ended", not eng.diplomacy.at_war(0, 1))
    assert_true("vassal cannot be re-vassalized pair", 1 in eng.diplomacy.vassals)
    # tribute flows
    f1 = eng.factions[1]
    f0 = eng.factions[0]
    f1.income = 100.0
    t0 = f0.treasury
    for _ in range(3):
        eng.step()
    assert_true("suzerain treasury grew", f0.treasury > t0)


# ---------------------------------------------------------------------------
# 8. Rebellion: a boiling region rises up
# ---------------------------------------------------------------------------

def test_rebellion():
    from strategy.data import BALANCE
    old_chance = BALANCE["rebellion_chance"]
    old_grace = BALANCE["rebellion_grace_ticks"]
    BALANCE["rebellion_chance"] = 1.0
    BALANCE["rebellion_grace_ticks"] = 0
    try:
        eng = StrategyEngine(EngineConfig(seed=21, use_physics=False))
        reg = eng.world.owned_by(2)[1]
        reg.unrest = 0.95
        eng.step()
        assert_true("region defected", reg.owner == 5)
        rebels = eng.factions[5]
        assert_true("rebels alive", rebels.alive)
        assert_true("rebels at war", eng.diplomacy.at_war(5, 2))
        assert_true("rebel army spawned",
                    any(a.fid == 5 and a.location == reg.rid for a in eng.armies))
        assert_true("rebellion logged",
                    any(ev["type"] == "rebellion" for ev in eng.events))
    finally:
        BALANCE["rebellion_chance"] = old_chance
        BALANCE["rebellion_grace_ticks"] = old_grace


# ---------------------------------------------------------------------------
# 9. Trade corridor blockade
# ---------------------------------------------------------------------------

def test_trade_blockade():
    eng = StrategyEngine(EngineConfig(seed=17, use_physics=False))
    eng.diplomacy.relations[0, 2] = eng.diplomacy.relations[2, 0] = 60.0
    assert_true("route open through neutrals",
                (0, 2) in eng.trade_pairs())
    # wall the planet: everything except the two capitals belongs to faction 3,
    # which is at war with faction 0
    cap0 = eng.factions[0].capital
    cap2 = eng.factions[2].capital
    for r in eng.world.regions:
        if r.rid not in (cap0, cap2):
            r.owner = 3
    eng.diplomacy.declare_war(eng, 0, 3, "test wall")
    eng._trade_cache_tick = -1          # invalidate cache
    assert_true("route blocked by hostile wall",
                (0, 2) in eng.blocked_routes() and (0, 2) not in eng.trade_pairs())


# ---------------------------------------------------------------------------
# 9b. Economy sinks: hoard decay + corruption, rebel schism
# ---------------------------------------------------------------------------

def test_balance_sinks():
    from strategy.data import BALANCE
    eng = StrategyEngine(EngineConfig(seed=11, use_physics=False))

    # hoarded wealth far above the cap leaks faster than income flows in
    f0 = eng.factions[0]
    f0.treasury = BALANCE["hoard_cap"] * 50
    t_before = f0.treasury
    eng.step()
    assert_true("hoard decay", f0.treasury < t_before)

    # an oversized rebel state frays and sheds regions
    old = {k: BALANCE[k] for k in
           ("rebellion_chance", "rebellion_grace_ticks", "rebel_governance_cap")}
    BALANCE["rebellion_chance"] = 1.0
    BALANCE["rebellion_grace_ticks"] = 0
    BALANCE["rebel_governance_cap"] = 5
    try:
        rebels = eng.factions[5]
        rebels.alive = True
        grabbed = [r for r in eng.world.regions if r.owner == -1][:12]
        for r in grabbed:
            r.owner = 5
            r.unrest = 0.95
        rebels.capital = grabbed[0].rid
        eng.step()
        still_rebel = sum(1 for r in grabbed if r.owner == 5)
        assert_true("schism sheds regions", still_rebel < len(grabbed))
        assert_true("schism logged",
                    any(ev["type"] == "schism" for ev in eng.events))
    finally:
        BALANCE.update(old)


# ---------------------------------------------------------------------------
# 9c. City-states, heritage track, future tech (science sink)
# ---------------------------------------------------------------------------

def test_culture_systems():
    eng = StrategyEngine(EngineConfig(seed=7, use_physics=False))

    # city-states seeded as independent neutral minor powers
    assert_true("city-states exist", len(eng.city_states) >= 5)
    for cs in eng.city_states:
        reg = eng.world.regions[cs.rid]
        assert_true("city-state region neutral", reg.owner == -1)
        assert_true("city-state flagged", reg.is_city_state)
        assert_true("city-state kind valid",
                    cs.kind in ("science", "trade", "industrial", "cultural", "militarist"))

    # patronage forms over time and grants the suzerain something
    for _ in range(1500):
        eng.step()
    patroned = [c for c in eng.city_states if c.suzerain >= 0]
    assert_true("some city-states patroned", len(patroned) > 0)

    # heritage accumulates and the civics track unlocks in order
    any_heritage = any(f.heritage_unlocked for f in eng.factions if f.alive)
    assert_true("heritage unlocked somewhere", any_heritage)
    from strategy.data import HERITAGE_TRACK
    order = [h[0] for h in HERITAGE_TRACK]
    for f in eng.factions:
        if not f.heritage_unlocked:
            continue
        idxs = sorted(order.index(k) for k in f.heritage_unlocked)
        assert_true("heritage unlocked as a prefix", idxs == list(range(len(idxs))))

    # future tech only after the whole tree is maxed, and it drains science
    for f in eng.factions:
        if f.future_tech > 0:
            assert_true("future tech needs maxed tree",
                        all(v >= 6 for v in f.tech.values()))

    # absorption never eats a city-state
    for cs in eng.city_states:
        reg = eng.world.regions[cs.rid]
        assert_true("city-state not absorbed (still neutral or conquered, never absorbed-neutral)",
                    reg.owner != -1 or reg.is_city_state)

    # serialization round-trips the new state
    import os, tempfile
    p = os.path.join(tempfile.gettempdir(), "coruscant_culture_save.json")
    eng.save(p)
    eng2 = StrategyEngine.load(p)
    assert_true("city-states reload", len(eng2.city_states) == len(eng.city_states))
    assert_true("future tech reload",
                [f.future_tech for f in eng2.factions] == [f.future_tech for f in eng.factions])
    assert_true("heritage reload",
                [sorted(f.heritage_unlocked) for f in eng2.factions]
                == [sorted(f.heritage_unlocked) for f in eng.factions])
    os.remove(p)


# ---------------------------------------------------------------------------
# 10. Chronicle + notifier formatting
# ---------------------------------------------------------------------------

def test_chronicle_and_notify():
    from strategy.chronicle import Chronicle, drain_major_events
    from strategy.notify import format_batch

    eng = StrategyEngine(EngineConfig(seed=31, use_physics=False))
    path = os.path.join(tempfile.gettempdir(), "coruscant_chronicle_test.md")
    if os.path.exists(path):
        os.remove(path)
    chron = Chronicle(path, flush_every=1)
    for _ in range(300):
        eng.step()
    chron.collect(eng)
    chron.flush()
    text = open(path, encoding="utf-8").read()
    assert_true("chronicle has header", "Chronicle of Coruscant" in text)
    assert_true("chronicle has entries", text.count("**Year") >= 1)
    os.remove(path)

    major = drain_major_events(eng, 0)
    assert_true("major events exist", len(major) > 0)
    msg = format_batch(major, eng.tick)
    assert_true("notify message non-empty", len(msg) > 10)
    assert_true("notify message capped", len(msg.splitlines()) <= 13)


# ---------------------------------------------------------------------------
# 11. Physics coupling smoke test
# ---------------------------------------------------------------------------

def test_physics_coupling():
    eng = StrategyEngine(EngineConfig(seed=11, use_physics=True))
    ferts = [r.fertility for r in eng.world.regions]
    assert_true("fertility varies", float(np.std(ferts)) > 0.01)
    for _ in range(30):
        eng.step()
    assert_true("physics ticked", eng.physics is not None and len(eng.physics.history["mean_temperature_k"]) > 30)


if __name__ == "__main__":
    test_world_setup()
    print("ok: world setup")
    test_combat_capture()
    print("ok: combat capture")
    test_determinism()
    print("ok: determinism")
    test_save_load()
    print("ok: save/load")
    test_snapshot_schema()
    print("ok: snapshot schema")
    test_vassalization()
    print("ok: vassalization")
    test_rebellion()
    print("ok: rebellion")
    test_trade_blockade()
    print("ok: trade blockade")
    test_balance_sinks()
    print("ok: balance sinks (hoard decay + schism)")
    test_culture_systems()
    print("ok: culture systems (city-states + heritage + future tech)")
    test_chronicle_and_notify()
    print("ok: chronicle + notify")
    test_physics_coupling()
    print("ok: physics coupling")
    test_long_run_invariants()
    print("ok: long run invariants")
    print("strategy_tests_ok")
