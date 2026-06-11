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
    owned = [r for r in eng.world.regions if r.owner >= 0]
    assert_true("factions seeded", len(owned) == 5 * eng.cfg.start_regions_per_faction)
    assert_true("five capitals", len({f.capital for f in eng.factions}) == 5)
    for f in eng.factions:
        cap = eng.world.regions[f.capital]
        assert_true("capital owned", cap.owner == f.fid)
        assert_true("capital has factory", cap.buildings.get("factory", 0) >= 1)
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
    assert_true("snapshot has factions", len(snap["factions"]) == 5)
    assert_true("snapshot owners", len(snap["regions"]["owner"]) == N_REGIONS)
    assert_true("snapshot armies list", isinstance(snap["armies"], list))
    assert_true("snapshot charts", len(snap["charts"]["tick"]) > 0)
    detail = eng.region_detail(0)
    json.dumps(detail)
    assert_true("region detail keys",
                {"rid", "owner", "population", "buildings", "stock"} <= set(detail))


# ---------------------------------------------------------------------------
# 7. Physics coupling smoke test
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
    test_physics_coupling()
    print("ok: physics coupling")
    test_long_run_invariants()
    print("ok: long run invariants")
    print("strategy_tests_ok")
