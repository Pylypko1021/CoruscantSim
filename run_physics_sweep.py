import csv
from pathlib import Path

try:
    from planet_physics import PlanetConfig, PlanetPhysicsSimulator
except ModuleNotFoundError:
    from CoruscantSim.planet_physics import PlanetConfig, PlanetPhysicsSimulator


def run_case(case_name: str, cfg: PlanetConfig, days: int = 180):
    sim = PlanetPhysicsSimulator(cfg, n_lat=48, n_lon=96, seed=13)
    for d in range(days):
        sim.step(day_of_year=float(d % 365))

    metrics = sim.summary_metrics()
    metrics["case"] = case_name
    return metrics


def main():
    baseline = PlanetConfig()

    cases = {
        "baseline": baseline,
        "high_greenhouse": PlanetConfig(greenhouse_forcing_w_m2=baseline.greenhouse_forcing_w_m2 + 40.0),
        "thin_atmosphere": PlanetConfig(atmosphere_mass_kg=0.55 * baseline.atmosphere_mass_kg),
        "fast_rotation": PlanetConfig(rotation_period_s=0.60 * baseline.rotation_period_s),
        "high_albedo": PlanetConfig(surface_albedo=0.42),
        "industrial_surge": PlanetConfig(
            greenhouse_forcing_w_m2=baseline.greenhouse_forcing_w_m2 + 65.0,
            surface_albedo=max(0.18, baseline.surface_albedo - 0.05),
        ),
        "albedo_engineering": PlanetConfig(
            greenhouse_forcing_w_m2=baseline.greenhouse_forcing_w_m2 + 15.0,
            surface_albedo=min(0.58, baseline.surface_albedo + 0.10),
        ),
        "atmosphere_recovery": PlanetConfig(
            atmosphere_mass_kg=1.15 * baseline.atmosphere_mass_kg,
            greenhouse_forcing_w_m2=baseline.greenhouse_forcing_w_m2 + 8.0,
        ),
    }

    results = [run_case(name, cfg) for name, cfg in cases.items()]

    out_path = Path(__file__).with_name("physics_sweep_results.csv")
    fields = [
        "case",
        "mean_surface_temperature_k",
        "mean_lower_temperature_k",
        "mean_surface_pressure_pa",
        "mean_density_kg_m3",
        "mean_specific_humidity",
        "mean_cloud_fraction",
        "mean_precip_mm_day",
        "mean_wind_m_s",
        "mean_mach",
        "mean_reynolds",
        "mean_rossby",
        "mean_energy_residual_w_m2",
        "mean_latent_flux_w_m2",
        "mean_vertical_velocity_m_s",
        "mean_hadley_index_k",
        "cumulative_energy_input_j_m2",
        "cumulative_latent_j_m2",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k) for k in fields})

    print(f"Saved scenario sweep to: {out_path}")
    print("\nSummary:")
    for row in results:
        print(
            f"- {row['case']}: T={row['mean_surface_temperature_k']:.2f} K, "
            f"P={row['mean_surface_pressure_pa']:.0f} Pa, "
            f"Wind={row['mean_wind_m_s']:.2f} m/s, "
            f"Ro={row['mean_rossby']:.3f}"
        )

    baseline_row = next(r for r in results if r["case"] == "baseline")
    report_path = Path(__file__).with_name("physics_sweep_report.md")
    with report_path.open("w", encoding="utf-8") as f:
        f.write("# Coruscant Physics Sweep Report\n\n")
        f.write("Comparative deltas relative to baseline after 180 simulated days.\n\n")
        f.write("| Case | dT (K) | dP (Pa) | dWind (m/s) | dRo | dLatent (W/m^2) | dHadley (K) |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for row in results:
            d_t = row["mean_surface_temperature_k"] - baseline_row["mean_surface_temperature_k"]
            d_p = row["mean_surface_pressure_pa"] - baseline_row["mean_surface_pressure_pa"]
            d_w = row["mean_wind_m_s"] - baseline_row["mean_wind_m_s"]
            d_ro = row["mean_rossby"] - baseline_row["mean_rossby"]
            d_lat = row["mean_latent_flux_w_m2"] - baseline_row["mean_latent_flux_w_m2"]
            d_had = row["mean_hadley_index_k"] - baseline_row["mean_hadley_index_k"]
            f.write(
                f"| {row['case']} | {d_t:+.2f} | {d_p:+.0f} | {d_w:+.2f} | {d_ro:+.3f} | {d_lat:+.2f} | {d_had:+.2f} |\n"
            )

    print(f"Saved scenario report to: {report_path}")


if __name__ == "__main__":
    main()
