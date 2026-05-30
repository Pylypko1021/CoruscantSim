import argparse
import csv
import json
from pathlib import Path

import numpy as np

try:
    from planet_physics import PlanetConfig, PlanetPhysicsSimulator
except ModuleNotFoundError:
    from CoruscantSim.planet_physics import PlanetConfig, PlanetPhysicsSimulator


def run_sim(days: int, n_lat: int, n_lon: int, seed: int) -> PlanetPhysicsSimulator:
    cfg = PlanetConfig(
        name="Coruscant",
        mass_kg=5.95e24,
        radius_m=6.15e6,
        rotation_period_s=24.2 * 3600.0,
        obliquity_deg=21.0,
        semi_major_axis_m=1.52e11,
        surface_albedo=0.22,
        greenhouse_forcing_w_m2=115.0,
        cloud_cooling_coeff=0.46,
        atmosphere_mass_kg=5.35e18,
    )

    sim = PlanetPhysicsSimulator(cfg, n_lat=n_lat, n_lon=n_lon, seed=seed)
    for day in range(days):
        sim.step(day_of_year=float(day % 365))
    return sim


def write_history_csv(sim: PlanetPhysicsSimulator, out_path: Path):
    keys = [k for k, v in sim.history.items() if len(v) > 0]
    rows = len(sim.history[keys[0]]) if keys else 0

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["day"] + keys)
        for i in range(rows):
            writer.writerow([i] + [sim.history[k][i] for k in keys])


def write_summary_json(sim: PlanetPhysicsSimulator, out_path: Path):
    summary = sim.summary_metrics()
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def write_fields_npz(sim: PlanetPhysicsSimulator, out_path: Path):
    np.savez_compressed(
        out_path,
        temperature_k=sim.temperature_k,
        lower_atmos_temperature_k=sim.lower_atmos_temperature_k,
        pressure_pa=sim.pressure_pa,
        density_kg_m3=sim.density_kg_m3,
        specific_humidity=sim.specific_humidity,
        cloud_fraction=sim.cloud_fraction,
        precipitation_mm_day=sim.precipitation_mm_day,
        u_wind_m_s=sim.u_wind_m_s,
        v_wind_m_s=sim.v_wind_m_s,
        u_wind_profile_m_s=sim.u_wind_profile_m_s,
        v_wind_profile_m_s=sim.v_wind_profile_m_s,
        temperature_profile_k=sim.temperature_profile_k,
        humidity_profile=sim.humidity_profile,
    )


def main():
    parser = argparse.ArgumentParser(description="Export Coruscant physics diagnostics")
    parser.add_argument("--days", type=int, default=220)
    parser.add_argument("--n-lat", type=int, default=72)
    parser.add_argument("--n-lon", type=int, default=144)
    parser.add_argument("--seed", type=int, default=21)
    parser.add_argument("--out-dir", default="CoruscantSim/output")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sim = run_sim(days=args.days, n_lat=args.n_lat, n_lon=args.n_lon, seed=args.seed)

    history_path = out_dir / "history.csv"
    summary_path = out_dir / "summary.json"
    fields_path = out_dir / "final_fields.npz"

    write_history_csv(sim, history_path)
    write_summary_json(sim, summary_path)
    write_fields_npz(sim, fields_path)

    print(f"export_ok history={history_path}")
    print(f"export_ok summary={summary_path}")
    print(f"export_ok fields={fields_path}")


if __name__ == "__main__":
    main()
