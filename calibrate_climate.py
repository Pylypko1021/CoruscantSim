import argparse
import csv
import json
from pathlib import Path

try:
    from planet_physics import PlanetConfig, PlanetPhysicsSimulator
except ModuleNotFoundError:
    from CoruscantSim.planet_physics import PlanetConfig, PlanetPhysicsSimulator


def run_case(cfg: PlanetConfig, days: int, n_lat: int, n_lon: int, seed: int):
    sim = PlanetPhysicsSimulator(cfg, n_lat=n_lat, n_lon=n_lon, seed=seed)
    for day in range(days):
        sim.step(day_of_year=float(day % 365))
    return sim.summary_metrics()


def build_config(greenhouse: float, albedo: float, cloud_coeff: float) -> PlanetConfig:
    return PlanetConfig(
        name="Coruscant",
        mass_kg=5.95e24,
        radius_m=6.15e6,
        rotation_period_s=24.2 * 3600.0,
        obliquity_deg=21.0,
        semi_major_axis_m=1.52e11,
        surface_albedo=albedo,
        greenhouse_forcing_w_m2=greenhouse,
        cloud_cooling_coeff=cloud_coeff,
        atmosphere_mass_kg=5.35e18,
    )


def objective(metrics, target_temp_k: float, target_pressure_pa: float):
    t_err = abs(metrics["mean_surface_temperature_k"] - target_temp_k)
    p_err = abs(metrics["mean_surface_pressure_pa"] - target_pressure_pa) / 10000.0
    e_res = abs(metrics["mean_energy_residual_w_m2"]) / 1000.0
    latent_res = abs(metrics["mean_latent_residual_w_m2"]) * 1000.0
    return t_err + 0.35 * p_err + 0.20 * e_res + 0.05 * latent_res


def main():
    parser = argparse.ArgumentParser(description="Calibrate Coruscant climate parameters")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--n-lat", type=int, default=36)
    parser.add_argument("--n-lon", type=int, default=72)
    parser.add_argument("--seed", type=int, default=19)
    parser.add_argument("--target-temp-k", type=float, default=250.0)
    parser.add_argument("--target-pressure-pa", type=float, default=112000.0)
    parser.add_argument("--out-dir", default="CoruscantSim/output")
    args = parser.parse_args()

    greenhouse_values = [105.0, 110.0, 115.0, 120.0, 125.0]
    albedo_values = [0.20, 0.22, 0.24, 0.26]
    cloud_coeff_values = [0.40, 0.44, 0.46, 0.48, 0.52]

    rows = []
    best = None

    for greenhouse in greenhouse_values:
        for albedo in albedo_values:
            for cloud_coeff in cloud_coeff_values:
                cfg = build_config(greenhouse, albedo, cloud_coeff)
                metrics = run_case(cfg, days=args.days, n_lat=args.n_lat, n_lon=args.n_lon, seed=args.seed)
                score = objective(metrics, args.target_temp_k, args.target_pressure_pa)

                row = {
                    "greenhouse_forcing_w_m2": greenhouse,
                    "surface_albedo": albedo,
                    "cloud_cooling_coeff": cloud_coeff,
                    "score": score,
                    "mean_surface_temperature_k": metrics["mean_surface_temperature_k"],
                    "mean_surface_pressure_pa": metrics["mean_surface_pressure_pa"],
                    "mean_energy_residual_w_m2": metrics["mean_energy_residual_w_m2"],
                    "mean_latent_residual_w_m2": metrics["mean_latent_residual_w_m2"],
                    "mean_hadley_index_k": metrics["mean_hadley_index_k"],
                }
                rows.append(row)

                if best is None or row["score"] < best["score"]:
                    best = row

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "calibration_results.csv"
    report_path = out_dir / "calibration_report.md"
    best_json_path = out_dir / "calibration_best.json"

    fieldnames = list(rows[0].keys()) if rows else []
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["score"]):
            writer.writerow(row)

    with report_path.open("w", encoding="utf-8") as f:
        f.write("# Coruscant Climate Calibration\n\n")
        f.write(f"Target temperature: {args.target_temp_k:.2f} K\\n\\n")
        f.write(f"Target pressure: {args.target_pressure_pa:.0f} Pa\\n\\n")
        if best:
            f.write("## Best Parameter Set\n\n")
            f.write(f"- greenhouse_forcing_w_m2: {best['greenhouse_forcing_w_m2']:.2f}\\n")
            f.write(f"- surface_albedo: {best['surface_albedo']:.3f}\\n")
            f.write(f"- cloud_cooling_coeff: {best['cloud_cooling_coeff']:.3f}\\n")
            f.write(f"- score: {best['score']:.4f}\\n")
            f.write(f"- mean_surface_temperature_k: {best['mean_surface_temperature_k']:.3f}\\n")
            f.write(f"- mean_surface_pressure_pa: {best['mean_surface_pressure_pa']:.1f}\\n")
            f.write(f"- mean_energy_residual_w_m2: {best['mean_energy_residual_w_m2']:.3f}\\n")
            f.write(f"- mean_latent_residual_w_m2: {best['mean_latent_residual_w_m2']:.6f}\\n")
            f.write(f"- mean_hadley_index_k: {best['mean_hadley_index_k']:.3f}\\n")

    if best:
        best_json_path.write_text(json.dumps(best, indent=2), encoding="utf-8")

    print(f"calibration_ok results={csv_path}")
    print(f"calibration_ok report={report_path}")
    print(f"calibration_ok best={best_json_path}")
    if best:
        print(
            "best_set "
            f"greenhouse={best['greenhouse_forcing_w_m2']:.2f} "
            f"albedo={best['surface_albedo']:.3f} "
            f"cloud={best['cloud_cooling_coeff']:.3f} "
            f"temp={best['mean_surface_temperature_k']:.2f} "
            f"pressure={best['mean_surface_pressure_pa']:.0f}"
        )


if __name__ == "__main__":
    main()
