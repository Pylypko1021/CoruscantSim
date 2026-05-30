from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sys

THIS_DIR = Path(__file__).resolve().parent
CORUSCANT_DIR = THIS_DIR.parent
WORKSPACE_DIR = CORUSCANT_DIR.parent
for p in (CORUSCANT_DIR, WORKSPACE_DIR):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

try:
    from planet_physics import PlanetConfig, PlanetPhysicsSimulator
except ModuleNotFoundError:
    from CoruscantSim.planet_physics import PlanetConfig, PlanetPhysicsSimulator


# ====================
# Agent-edited section
# ====================
GREENHOUSE_FORCING_W_M2 = 180
SURFACE_ALBEDO = 0.2884
CLOUD_COOLING_COEFF = 0.36
ATMOSPHERE_MASS_KG = 5.2893e+18
# ====================

TARGET_TEMP_K = 250.0
TARGET_PRESSURE_PA = 112000.0
SIM_DAYS = 90
GRID_LAT = 36
GRID_LON = 72
SEED = 23


def evaluate_params() -> dict:
    cfg = PlanetConfig(
        name="Coruscant",
        mass_kg=5.95e24,
        radius_m=6.15e6,
        rotation_period_s=24.2 * 3600.0,
        obliquity_deg=21.0,
        semi_major_axis_m=1.52e11,
        greenhouse_forcing_w_m2=GREENHOUSE_FORCING_W_M2,
        surface_albedo=SURFACE_ALBEDO,
        cloud_cooling_coeff=CLOUD_COOLING_COEFF,
        atmosphere_mass_kg=ATMOSPHERE_MASS_KG,
    )

    sim = PlanetPhysicsSimulator(cfg, n_lat=GRID_LAT, n_lon=GRID_LON, seed=SEED)
    for day in range(SIM_DAYS):
        sim.step(day_of_year=float(day % 365))

    m = sim.summary_metrics()

    temp_err = abs(m["mean_surface_temperature_k"] - TARGET_TEMP_K)
    pressure_err = abs(m["mean_surface_pressure_pa"] - TARGET_PRESSURE_PA) / 10000.0
    energy_res = abs(m["mean_energy_residual_w_m2"]) / 1000.0
    latent_res = abs(m["mean_latent_residual_w_m2"]) * 1000.0
    hadley_penalty = abs(m["mean_hadley_index_k"] - 20.0) / 20.0

    score = temp_err + 0.35 * pressure_err + 0.20 * energy_res + 0.05 * latent_res + 0.10 * hadley_penalty

    return {
        "score": score,
        "mean_surface_temperature_k": m["mean_surface_temperature_k"],
        "mean_surface_pressure_pa": m["mean_surface_pressure_pa"],
        "mean_energy_residual_w_m2": m["mean_energy_residual_w_m2"],
        "mean_latent_residual_w_m2": m["mean_latent_residual_w_m2"],
        "mean_hadley_index_k": m["mean_hadley_index_k"],
        "params": asdict(cfg),
    }


def append_result(result: dict):
    path = Path(__file__).with_name("results.tsv")
    row = [
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        str(GREENHOUSE_FORCING_W_M2),
        str(SURFACE_ALBEDO),
        str(CLOUD_COOLING_COEFF),
        str(ATMOSPHERE_MASS_KG),
        f"{result['score']:.9f}",
        f"{result['mean_surface_temperature_k']:.6f}",
        f"{result['mean_surface_pressure_pa']:.6f}",
        f"{result['mean_energy_residual_w_m2']:.6f}",
        f"{result['mean_latent_residual_w_m2']:.9f}",
        f"{result['mean_hadley_index_k']:.6f}",
    ]
    with path.open("a", encoding="utf-8") as f:
        f.write("\t".join(row) + "\n")


def main():
    result = evaluate_params()
    append_result(result)

    print(f"score\t{result['score']:.9f}")
    print(f"mean_surface_temperature_k\t{result['mean_surface_temperature_k']:.6f}")
    print(f"mean_surface_pressure_pa\t{result['mean_surface_pressure_pa']:.6f}")
    print(f"mean_energy_residual_w_m2\t{result['mean_energy_residual_w_m2']:.6f}")
    print(f"mean_latent_residual_w_m2\t{result['mean_latent_residual_w_m2']:.9f}")
    print(f"mean_hadley_index_k\t{result['mean_hadley_index_k']:.6f}")


if __name__ == "__main__":
    main()
