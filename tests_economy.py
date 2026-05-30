"""
Regression tests for Phase 3 — EconomyController.
Run from CoruscantSim/ directory:
    python tests_economy.py
Expected output: economy_tests_ok
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from simulate_coruscant import CoruscantCivilization, GRID_LAT, GRID_LON
from civilization.economy import EconomyController, Spec, FOOD_CAP, WATER_CAP, ENERGY_CAP


def assert_true(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(f"FAIL: {name}")


def assert_finite(name: str, value: float) -> None:
    assert_true(f"finite({name})", math.isfinite(value))


def make_civ(**kwargs) -> CoruscantCivilization:
    return CoruscantCivilization(seed=17, **kwargs)


# ---------------------------------------------------------------------------
# 1. EconomyController initialisation
# ---------------------------------------------------------------------------

def test_economy_ctrl_exists():
    civ = make_civ()
    assert_true("_economy_ctrl is not None", civ._economy_ctrl is not None)


def test_specialization_shape():
    civ = make_civ()
    assert_true(
        f"specialization.shape == ({GRID_LAT},{GRID_LON})",
        civ.specialization.shape == (GRID_LAT, GRID_LON),
    )


def test_specialization_valid_values():
    civ = make_civ()
    spec = civ.specialization
    valid = set(int(s) for s in Spec)
    unique = set(spec.ravel().tolist())
    assert_true("all spec values valid", unique.issubset(valid))


def test_all_spec_types_present():
    civ = make_civ()
    counts = civ._economy_ctrl.specialization_counts()
    for s in Spec:
        assert_true(f"spec {s.name} present", counts.get(s.name, 0) > 0)


def test_faction_economies_count():
    civ = make_civ()
    assert_true(
        "faction_economies count == factions count",
        len(civ._economy_ctrl.faction_economies) == len(civ.factions),
    )


# ---------------------------------------------------------------------------
# 2. Step stability
# ---------------------------------------------------------------------------

def test_economy_step_runs():
    civ = make_civ()
    for _ in range(20):
        civ.step()
    assert_true("step_count == 20", civ.step_count == 20)


def test_resources_stay_finite_and_bounded():
    civ = make_civ()
    for _ in range(50):
        civ.step()
    assert_true("food finite",    np.isfinite(civ.food_reserve).all())
    assert_true("water finite",   np.isfinite(civ.water_avail).all())
    assert_true("energy finite",  np.isfinite(civ.energy_avail).all())
    assert_true("food >= 0",      (civ.food_reserve >= 0).all())
    assert_true("water >= 0",     (civ.water_avail >= 0).all())
    assert_true("energy >= 0",    (civ.energy_avail >= 0).all())
    assert_true("food <= cap",    (civ.food_reserve <= FOOD_CAP + 1e-9).all())
    assert_true("water <= cap",   (civ.water_avail <= WATER_CAP + 1e-9).all())
    assert_true("energy <= cap",  (civ.energy_avail <= ENERGY_CAP + 1e-9).all())


# ---------------------------------------------------------------------------
# 3. Production raises resources
# ---------------------------------------------------------------------------

def test_production_raises_food():
    """Agriculture cells should push food up from a depleted state."""
    civ = make_civ()
    # Deplete food everywhere
    civ.food_reserve[:] = 0.0
    food_before = float(civ.food_reserve.mean())

    # Run one economy step only
    civ._economy_ctrl._produce()

    food_after = float(civ.food_reserve.mean())
    assert_true("production raises food", food_after > food_before)


def test_production_raises_energy():
    civ = make_civ()
    civ.energy_avail[:] = 0.0
    civ._economy_ctrl._produce()
    assert_true("production raises energy", float(civ.energy_avail.mean()) > 0.0)


# ---------------------------------------------------------------------------
# 4. Consumption depletes resources
# ---------------------------------------------------------------------------

def test_consumption_depletes_food():
    civ = make_civ()
    civ.food_reserve[:] = 10.0
    food_before = float(civ.food_reserve.mean())
    civ._economy_ctrl._consume()
    food_after = float(civ.food_reserve.mean())
    assert_true("consumption depletes food", food_after < food_before)


# ---------------------------------------------------------------------------
# 5. Trade diffusion equalises surplus / deficit
# ---------------------------------------------------------------------------

def test_trade_diffusion_moves_food():
    """Half of grid at 80 food, other half at 0 → diffusion should reduce gap."""
    civ = make_civ()
    civ.food_reserve[:, :GRID_LON // 2] = 80.0
    civ.food_reserve[:, GRID_LON // 2:] = 0.0

    gap_before = float(civ.food_reserve[:, :GRID_LON // 2].mean()) - float(civ.food_reserve[:, GRID_LON // 2:].mean())
    civ._economy_ctrl._trade_diffusion()
    gap_after  = float(civ.food_reserve[:, :GRID_LON // 2].mean()) - float(civ.food_reserve[:, GRID_LON // 2:].mean())

    assert_true(
        f"diffusion reduces food gap ({gap_before:.2f} -> {gap_after:.2f})",
        gap_after < gap_before,
    )


def test_trade_diffusion_preserves_approximate_total():
    """Total resources should be roughly conserved by diffusion (within 1%)."""
    civ = make_civ()
    civ.food_reserve[:] = 30.0
    total_before = float(civ.food_reserve.sum())
    civ._economy_ctrl._trade_diffusion()
    total_after = float(civ.food_reserve.sum())
    rel_change = abs(total_after - total_before) / (total_before + 1e-9)
    assert_true(
        f"diffusion approx conserves total food (rel_change={rel_change:.4f})",
        rel_change < 0.01,
    )


# ---------------------------------------------------------------------------
# 6. Military cells reduce unrest
# ---------------------------------------------------------------------------

def test_military_reduces_unrest():
    civ = make_civ()
    mil_mask = civ.specialization == int(Spec.MILITARY)
    if not mil_mask.any():
        return   # no military cells in this seed, skip
    civ.unrest[mil_mask] = 0.8
    unrest_before = float(civ.unrest[mil_mask].mean())
    civ._economy_ctrl._military_security()
    unrest_after = float(civ.unrest[mil_mask].mean())
    assert_true("military reduces unrest", unrest_after < unrest_before)


# ---------------------------------------------------------------------------
# 7. economy_summary() API
# ---------------------------------------------------------------------------

def test_economy_summary_structure():
    civ = make_civ()
    for _ in range(5):
        civ.step()
    summary = civ.economy_summary()
    assert_true("economy summary length == n_factions", len(summary) == len(civ.factions))
    for entry in summary:
        for key in ("id", "name", "gdp_index", "food_produced", "energy_produced"):
            assert_true(f"economy summary has '{key}'", key in entry)


def test_economy_gdp_in_range():
    civ = make_civ()
    for _ in range(10):
        civ.step()
    for entry in civ.economy_summary():
        assert_finite(f"gdp_index[{entry['name']}]", entry["gdp_index"])
        assert_true(f"gdp_index[{entry['name']}] >= 0", entry["gdp_index"] >= 0.0)


# ---------------------------------------------------------------------------
# 8. Industry faction has higher energy production
# ---------------------------------------------------------------------------

def test_industry_faction_produces_more_energy():
    """Industrial Sector (faction 1) cells should produce more energy per cell
    than Residential cells on average."""
    civ = make_civ()
    spec = civ.specialization
    from civilization.economy import _PROD, Spec as S
    industry_prod = float(_PROD[int(S.INDUSTRY), 2])   # energy column
    residential_prod = float(_PROD[int(S.RESIDENTIAL), 2])
    assert_true(
        f"industry energy prod ({industry_prod}) > residential ({residential_prod})",
        industry_prod > residential_prod,
    )


# ---------------------------------------------------------------------------
# 9. Agriculture cells produce more food than industry cells
# ---------------------------------------------------------------------------

def test_agriculture_produces_more_food():
    from civilization.economy import _PROD, Spec as S
    agri_food = float(_PROD[int(S.AGRICULTURE), 0])
    industry_food = float(_PROD[int(S.INDUSTRY), 0])
    assert_true(
        f"agriculture food ({agri_food}) > industry food ({industry_food})",
        agri_food > industry_food,
    )


# ---------------------------------------------------------------------------
# 10. Long-run stability with economy enabled
# ---------------------------------------------------------------------------

def test_long_run_stable_with_economy():
    civ = make_civ()
    for _ in range(100):
        civ.step()
    assert_true("happiness in [0,1]", ((civ.happiness >= 0) & (civ.happiness <= 1)).all())
    assert_true("unrest in [0,1]",    ((civ.unrest >= 0) & (civ.unrest <= 1)).all())
    assert_true("food >= 0",          (civ.food_reserve >= 0).all())


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    test_economy_ctrl_exists,
    test_specialization_shape,
    test_specialization_valid_values,
    test_all_spec_types_present,
    test_faction_economies_count,
    test_economy_step_runs,
    test_resources_stay_finite_and_bounded,
    test_production_raises_food,
    test_production_raises_energy,
    test_consumption_depletes_food,
    test_trade_diffusion_moves_food,
    test_trade_diffusion_preserves_approximate_total,
    test_military_reduces_unrest,
    test_economy_summary_structure,
    test_economy_gdp_in_range,
    test_industry_faction_produces_more_energy,
    test_agriculture_produces_more_food,
    test_long_run_stable_with_economy,
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
        print("economy_tests_ok")
    else:
        sys.exit(1)
