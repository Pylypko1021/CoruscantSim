"""
Regression tests for Phase 2 — FactionController & Behavior Tree.
Run from CoruscantSim/ directory:
    python tests_factions.py
Expected output: faction_tests_ok
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from simulate_coruscant import CoruscantCivilization, GRID_LAT, GRID_LON
from civilization.factions import FactionController, FactionState, run_faction_bt


def assert_true(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(f"FAIL: {name}")


def assert_finite(name: str, value: float) -> None:
    assert_true(f"finite({name})", math.isfinite(value))


def make_civ(**kwargs) -> CoruscantCivilization:
    return CoruscantCivilization(seed=13, **kwargs)


# ---------------------------------------------------------------------------
# 1. FactionController initialisation
# ---------------------------------------------------------------------------

def test_controller_exists():
    civ = make_civ()
    assert_true("_faction_ctrl is not None", civ._faction_ctrl is not None)


def test_influence_shape():
    civ = make_civ()
    ctrl = civ._faction_ctrl
    n_f = len(civ.factions)
    assert_true(
        f"influence.shape == ({n_f},{GRID_LAT},{GRID_LON})",
        ctrl.influence.shape == (n_f, GRID_LAT, GRID_LON),
    )


def test_influence_non_negative():
    civ = make_civ()
    assert_true("influence >= 0", (civ._faction_ctrl.influence >= 0).all())


def test_states_count():
    civ = make_civ()
    assert_true(
        "states count == factions count",
        len(civ._faction_ctrl.states) == len(civ.factions),
    )


# ---------------------------------------------------------------------------
# 2. Step stability — factions + full civ
# ---------------------------------------------------------------------------

def test_faction_step_runs():
    civ = make_civ()
    for _ in range(20):
        civ.step()
    assert_true("step_count == 20", civ.step_count == 20)


def test_faction_id_valid_after_steps():
    civ = make_civ()
    for _ in range(30):
        civ.step()
    n_f = len(civ.factions)
    assert_true("faction_id in [0, n_f)", ((civ.faction_id >= 0) & (civ.faction_id < n_f)).all())


def test_faction_id_all_present_after_steps():
    civ = make_civ()
    for _ in range(30):
        civ.step()
    unique = set(civ.faction_id.ravel().tolist())
    assert_true("all factions still present after 30 steps", len(unique) == len(civ.factions))


def test_influence_stays_finite():
    civ = make_civ()
    for _ in range(50):
        civ.step()
    inf_arr = civ._faction_ctrl.influence
    assert_true("influence finite", np.isfinite(inf_arr).all())
    assert_true("influence non-negative", (inf_arr >= 0).all())


# ---------------------------------------------------------------------------
# 3. Faction state aggregation
# ---------------------------------------------------------------------------

def test_controlled_cells_sum():
    civ = make_civ()
    civ.step()
    ctrl = civ._faction_ctrl
    total = sum(fs.controlled_cells for fs in ctrl.states)
    assert_true(
        f"controlled_cells sum == grid cells ({GRID_LAT*GRID_LON})",
        total == GRID_LAT * GRID_LON,
    )


def test_strength_in_range():
    civ = make_civ()
    for _ in range(10):
        civ.step()
    for fs in civ._faction_ctrl.states:
        assert_true(f"strength[{fs.name}] in [0,1]", 0.0 <= fs.strength <= 1.0)


def test_per_cap_resources_finite():
    civ = make_civ()
    for _ in range(10):
        civ.step()
    for fs in civ._faction_ctrl.states:
        assert_finite(f"food_per_cap[{fs.name}]", fs.food_per_cap)
        assert_finite(f"water_per_cap[{fs.name}]", fs.water_per_cap)
        assert_finite(f"energy_per_cap[{fs.name}]", fs.energy_per_cap)


# ---------------------------------------------------------------------------
# 4. Behavior Tree logic
# ---------------------------------------------------------------------------

def test_survive_fires_when_food_critical():
    civ = make_civ()
    ctrl = civ._faction_ctrl
    fs = ctrl.states[0]
    fid = fs.faction_id

    # Force critical food in this faction's cells
    mask = civ.faction_id == fid
    civ.food_reserve[mask] = 1.0   # below FOOD_CRITICAL_DAYS=3
    ctrl._update_states()

    # Run BT
    action = run_faction_bt(fs, civ, ctrl.influence, ctrl.states)
    assert_true("survive action fires on critical food", action == "survive")


def test_consolidate_is_default():
    civ = make_civ()
    ctrl = civ._faction_ctrl
    fs = ctrl.states[1]  # Commerce Ring — low aggression, good resources
    fid = fs.faction_id

    # Give this faction abundant resources
    mask = civ.faction_id == fid
    civ.food_reserve[mask] = 60.0
    civ.water_avail[mask] = 40.0
    civ.energy_avail[mask] = 150.0
    ctrl._update_states()

    # Lower aggression so expand gate fails
    fs.aggression = 0.01
    fs.expansion_pressure = 0.0
    fs.strength = 0.2   # too weak to expand

    action = run_faction_bt(fs, civ, ctrl.influence, ctrl.states)
    assert_true(
        f"consolidate is default (got: {action})",
        action in ("consolidate", "trade"),
    )


def test_expand_fires_when_strong_and_aggressive():
    civ = make_civ()
    ctrl = civ._faction_ctrl
    fs = ctrl.states[3]  # Underworld — high aggression
    fid = fs.faction_id

    mask = civ.faction_id == fid
    civ.food_reserve[mask] = 50.0
    civ.water_avail[mask] = 30.0
    civ.energy_avail[mask] = 100.0
    ctrl._update_states()

    # Force strong + aggressive
    fs.strength = 0.9
    fs.aggression = 0.9
    fs.food_per_cap = 50.0

    action = run_faction_bt(fs, civ, ctrl.influence, ctrl.states)
    assert_true(f"expand fires when strong+aggressive (got: {action})", action == "expand")


def test_trade_reduces_donor_food():
    civ = make_civ()
    ctrl = civ._faction_ctrl

    donor = ctrl.states[2]   # Commerce Ring — high trade_openness
    needy = ctrl.states[3]   # Underworld
    donor.trade_openness = 0.95
    donor.trade_surplus = 100.0

    donor_mask = civ.faction_id == donor.faction_id
    needy_mask = civ.faction_id == needy.faction_id

    civ.food_reserve[donor_mask] = 60.0
    needy.food_per_cap = 2.0
    needy.trade_openness = 0.5
    ctrl._update_states()

    food_donor_before = float(civ.food_reserve[donor_mask].mean())

    from civilization.factions import _bt_trade
    _bt_trade(donor, civ, ctrl.states)

    food_donor_after = float(civ.food_reserve[donor_mask].mean())
    assert_true("trade reduces donor food", food_donor_after <= food_donor_before)


# ---------------------------------------------------------------------------
# 5. faction_summary() API
# ---------------------------------------------------------------------------

def test_faction_summary_structure():
    civ = make_civ()
    for _ in range(5):
        civ.step()
    summary = civ.faction_summary()
    assert_true("summary length == n_factions", len(summary) == len(civ.factions))
    for entry in summary:
        for key in ("id", "name", "cells", "strength", "food_per_cap", "last_action"):
            assert_true(f"summary has '{key}'", key in entry)


def test_faction_summary_cells_sum():
    civ = make_civ()
    for _ in range(5):
        civ.step()
    total_cells = sum(e["cells"] for e in civ.faction_summary())
    assert_true(
        f"summary cells sum == {GRID_LAT*GRID_LON}",
        total_cells == GRID_LAT * GRID_LON,
    )


# ---------------------------------------------------------------------------
# 6. Aggression affects territorial expansion over time
# ---------------------------------------------------------------------------

def test_aggressive_faction_gains_territory():
    """
    Run 60 steps with an artificially dominant aggressor.
    It should control more cells than at step 0.
    """
    civ = make_civ()
    ctrl = civ._faction_ctrl

    # Make faction 3 (Underworld) hyper-aggressive and give it resources
    underworld = ctrl.states[3]
    underworld.aggression = 1.0
    civ.factions[3].aggression = 1.0

    mask = civ.faction_id == 3
    civ.food_reserve[mask] = 80.0
    civ.energy_avail[mask] = 200.0

    cells_start = int((civ.faction_id == 3).sum())

    for _ in range(60):
        civ.step()

    cells_end = int((civ.faction_id == 3).sum())
    assert_true(
        f"aggressive faction gains territory ({cells_start} -> {cells_end})",
        cells_end >= cells_start,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

import numpy as np   # needed inside test functions

TESTS = [
    test_controller_exists,
    test_influence_shape,
    test_influence_non_negative,
    test_states_count,
    test_faction_step_runs,
    test_faction_id_valid_after_steps,
    test_faction_id_all_present_after_steps,
    test_influence_stays_finite,
    test_controlled_cells_sum,
    test_strength_in_range,
    test_per_cap_resources_finite,
    test_survive_fires_when_food_critical,
    test_consolidate_is_default,
    test_expand_fires_when_strong_and_aggressive,
    test_trade_reduces_donor_food,
    test_faction_summary_structure,
    test_faction_summary_cells_sum,
    test_aggressive_faction_gains_territory,
]

if __name__ == "__main__":
    passed = 0
    failed = 0
    for test_fn in TESTS:
        try:
            test_fn()
            print(f"  ok  {test_fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  ERROR {test_fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed}/{passed+failed} tests passed")
    if failed == 0:
        print("faction_tests_ok")
    else:
        sys.exit(1)
