"""
Regression tests for CoruscantCivilization — Phase 1.
Run from CoruscantSim/ directory:
    python tests_civilization.py
Expected output: civilization_tests_ok
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from simulate_coruscant import (
    CoruscantCivilization,
    FOOD_CRITICAL_DAYS,
    WATER_CRITICAL_L,
    ENERGY_CRITICAL_KWH,
    GRID_LAT,
    GRID_LON,
)


def assert_true(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(f"FAIL: {name}")


def assert_finite(name: str, value: float) -> None:
    assert_true(f"finite({name})", math.isfinite(value))


def make_civ(**kwargs) -> CoruscantCivilization:
    return CoruscantCivilization(seed=7, **kwargs)


# ---------------------------------------------------------------------------
# 1. Grid shape and initialisation
# ---------------------------------------------------------------------------

def test_shapes():
    civ = make_civ()
    for arr_name in ("population", "food_reserve", "water_avail", "energy_avail",
                     "happiness", "unrest"):
        arr = getattr(civ, arr_name)
        assert_true(f"{arr_name}.shape == ({GRID_LAT},{GRID_LON})",
                    arr.shape == (GRID_LAT, GRID_LON))

    assert_true("faction_id.shape", civ.faction_id.shape == (GRID_LAT, GRID_LON))


def test_initial_ranges():
    civ = make_civ()
    assert_true("population > 0",         (civ.population > 0).all())
    assert_true("food_reserve >= 0",      (civ.food_reserve >= 0).all())
    assert_true("water_avail >= 0",       (civ.water_avail >= 0).all())
    assert_true("energy_avail >= 0",      (civ.energy_avail >= 0).all())
    assert_true("happiness in [0,1]",     ((civ.happiness >= 0) & (civ.happiness <= 1)).all())
    assert_true("unrest in [0,1]",        ((civ.unrest >= 0) & (civ.unrest <= 1)).all())
    assert_true("faction_id valid",       (civ.faction_id >= -1).all())


def test_faction_coverage():
    civ = make_civ()
    # every cell should be claimed by some faction (no -1 after Voronoi init)
    assert_true("all cells have faction", (civ.faction_id >= 0).all())
    # all 5 factions present
    unique = set(civ.faction_id.ravel().tolist())
    assert_true("5 factions present", len(unique) == 5)


# ---------------------------------------------------------------------------
# 2. Step runs without error and keeps fields in range
# ---------------------------------------------------------------------------

def test_step_stability_short():
    civ = make_civ()
    for day in range(30):
        civ.step()

    assert_true("population > 0 after 30 steps", (civ.population > 0).all())
    assert_true("happiness in [0,1] after 30",   ((civ.happiness >= 0) & (civ.happiness <= 1)).all())
    assert_true("unrest in [0,1] after 30",       ((civ.unrest >= 0) & (civ.unrest <= 1)).all())
    assert_true("food_reserve >= 0 after 30",     (civ.food_reserve >= 0).all())
    assert_true("water_avail >= 0 after 30",      (civ.water_avail >= 0).all())
    assert_true("energy_avail >= 0 after 30",     (civ.energy_avail >= 0).all())


def test_step_count():
    civ = make_civ()
    for _ in range(10):
        civ.step()
    assert_true("step_count == 10", civ.step_count == 10)


def test_history_length():
    civ = make_civ()
    N = 15
    for _ in range(N):
        civ.step()
    for key, vals in civ.history.items():
        assert_true(f"history[{key}] length == {N}", len(vals) == N)


def test_all_history_finite():
    civ = make_civ()
    for _ in range(20):
        civ.step()
    for key, vals in civ.history.items():
        for v in vals:
            assert_finite(f"history[{key}]", v)


# ---------------------------------------------------------------------------
# 3. Causal responses to shocks
# ---------------------------------------------------------------------------

def test_food_blockade_raises_unrest():
    civ = make_civ()
    for _ in range(20):
        civ.step()
    unrest_before = float(civ.unrest.mean())

    civ.apply_shock("food_blockade", magnitude=0.95, region=None)
    for _ in range(15):
        civ.step()
    unrest_after = float(civ.unrest.mean())

    assert_true("food blockade raises unrest", unrest_after > unrest_before)


def test_food_blockade_lowers_food():
    civ = make_civ()
    for _ in range(10):
        civ.step()
    food_before = float(civ.food_reserve.mean())

    civ.apply_shock("food_blockade", magnitude=0.8)
    food_after = float(civ.food_reserve.mean())

    assert_true("food blockade reduces food reserve", food_after < food_before)


def test_water_crisis_lowers_water():
    civ = make_civ()
    for _ in range(5):
        civ.step()
    water_before = float(civ.water_avail.mean())

    civ.apply_shock("water_crisis", magnitude=0.9)
    water_after = float(civ.water_avail.mean())

    assert_true("water crisis reduces water", water_after < water_before)


def test_power_outage_lowers_energy():
    civ = make_civ()
    for _ in range(5):
        civ.step()
    energy_before = float(civ.energy_avail.mean())

    civ.apply_shock("power_outage", magnitude=0.9)
    energy_after = float(civ.energy_avail.mean())

    assert_true("power outage reduces energy", energy_after < energy_before)


def test_heat_wave_raises_temp():
    civ = make_civ()
    temp_before = float(civ._surface_temp_k.mean())
    civ.apply_shock("heat_wave", magnitude=1.0)
    temp_after = float(civ._surface_temp_k.mean())
    assert_true("heat wave raises temperature", temp_after > temp_before)


def test_unrest_event_raises_unrest():
    civ = make_civ()
    unrest_before = float(civ.unrest.mean())
    civ.apply_shock("unrest_event", magnitude=0.5)
    unrest_after = float(civ.unrest.mean())
    assert_true("unrest event raises unrest", unrest_after > unrest_before)


# ---------------------------------------------------------------------------
# 4. Regional shocks affect only the right hemisphere
# ---------------------------------------------------------------------------

def test_regional_shock_north_only():
    civ = make_civ()
    south_food_before = float(civ.food_reserve[civ._lat2d < -30].mean())

    civ.apply_shock("food_blockade", magnitude=0.9, region="north")

    south_food_after = float(civ.food_reserve[civ._lat2d < -30].mean())
    north_food_after = float(civ.food_reserve[civ._lat2d > 30].mean())

    assert_true("north shock: north food drops",   north_food_after < south_food_before * 0.9)
    assert_true("north shock: south unchanged",    abs(south_food_after - south_food_before) < 1e-6)


# ---------------------------------------------------------------------------
# 5. Happiness is monotonically sensitive to resource abundance
# ---------------------------------------------------------------------------

def test_better_resources_higher_happiness():
    rich = make_civ()
    poor = make_civ()

    # Artificially boost rich, deplete poor
    rich.food_reserve[:] = 90.0
    rich.water_avail[:] = 50.0
    rich.energy_avail[:] = 200.0

    poor.food_reserve[:] = 0.1
    poor.water_avail[:] = 0.1
    poor.energy_avail[:] = 0.1

    for _ in range(5):
        rich.step()
        poor.step()

    assert_true(
        "rich civ happier than poor civ",
        rich.happiness.mean() > poor.happiness.mean(),
    )


# ---------------------------------------------------------------------------
# 6. Migration conserves total population (approximately)
# ---------------------------------------------------------------------------

def test_migration_conserves_population():
    civ = make_civ()
    total_before = float(civ.population.sum())

    for _ in range(50):
        civ.step()

    total_after = float(civ.population.sum())
    # allow small numerical drift (< 0.1 %)
    rel_change = abs(total_after - total_before) / (total_before + 1e-9)
    assert_true(
        f"migration conserves population (rel_change={rel_change:.6f} < 0.001)",
        rel_change < 0.001,
    )


# ---------------------------------------------------------------------------
# 7. Physics attachment
# ---------------------------------------------------------------------------

def test_physics_attach():
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from planet_physics import PlanetConfig, PlanetPhysicsSimulator

    cfg = PlanetConfig()
    phys = PlanetPhysicsSimulator(cfg, n_lat=GRID_LAT, n_lon=GRID_LON, seed=3)
    for day in range(5):
        phys.step(day_of_year=float(day % 365))

    civ = make_civ()
    civ.attach_physics(phys)
    civ.step()

    # after attach, surface_temp should equal physics temperature_k
    import numpy as np
    diff = float(np.abs(civ._surface_temp_k - phys.temperature_k).max())
    assert_true(f"physics temp synced (max_diff={diff:.4f})", diff < 1e-9)


# ---------------------------------------------------------------------------
# 8. Summary keys and finiteness
# ---------------------------------------------------------------------------

def test_summary_keys():
    civ = make_civ()
    for _ in range(3):
        civ.step()
    s = civ.summary()
    expected_keys = [
        "step", "total_pop_est", "mean_happiness", "mean_unrest",
        "mean_food_days", "mean_water_l", "mean_energy_kwh",
        "pct_critical_food", "pct_critical_water", "pct_high_unrest",
    ]
    for k in expected_keys:
        assert_true(f"summary has key '{k}'", k in s)
        assert_finite(f"summary[{k}]", float(s[k]))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    test_shapes,
    test_initial_ranges,
    test_faction_coverage,
    test_step_stability_short,
    test_step_count,
    test_history_length,
    test_all_history_finite,
    test_food_blockade_raises_unrest,
    test_food_blockade_lowers_food,
    test_water_crisis_lowers_water,
    test_power_outage_lowers_energy,
    test_heat_wave_raises_temp,
    test_unrest_event_raises_unrest,
    test_regional_shock_north_only,
    test_better_resources_higher_happiness,
    test_migration_conserves_population,
    test_physics_attach,
    test_summary_keys,
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
            print(f"  ERROR {test_fn.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{passed+failed} tests passed")
    if failed == 0:
        print("civilization_tests_ok")
    else:
        sys.exit(1)
