import math

from planet_physics import PlanetConfig, PlanetPhysicsSimulator


def run_case(name: str, **overrides):
    params = dict(
        name=name,
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
    params.update(overrides)
    cfg = PlanetConfig(**params)
    sim = PlanetPhysicsSimulator(cfg, n_lat=48, n_lon=96, seed=11)
    for day in range(180):
        sim.step(day_of_year=float(day % 365))
    return sim.summary_metrics()


def assert_true(name: str, condition: bool):
    if not condition:
        raise AssertionError(name)


if __name__ == "__main__":
    baseline = run_case("baseline")
    hot = run_case("hot", greenhouse_forcing_w_m2=140.0)
    thin = run_case("thin", atmosphere_mass_kg=3.2e18)
    fast = run_case("fast", rotation_period_s=16.0 * 3600.0)

    assert_true("temperature range", 205.0 < baseline["mean_surface_temperature_k"] < 320.0)
    assert_true("pressure range", 3.0e4 < baseline["mean_surface_pressure_pa"] < 2.0e5)
    assert_true("wind range", baseline["mean_wind_m_s"] < 300.0)
    assert_true("humidity range", 0.0 <= baseline["mean_specific_humidity"] < 0.08)
    assert_true("cloud range", 0.0 <= baseline["mean_cloud_fraction"] <= 1.0)

    assert_true(
        "warming response",
        hot["mean_surface_temperature_k"] > baseline["mean_surface_temperature_k"],
    )
    assert_true(
        "thin atmosphere pressure drop",
        thin["mean_surface_pressure_pa"] < baseline["mean_surface_pressure_pa"],
    )
    assert_true("fast rotation rossby drop", fast["mean_rossby"] < baseline["mean_rossby"])

    assert_true("adaptive dt lower bound", baseline["mean_dt_s"] >= 300.0)
    assert_true("adaptive dt upper bound", baseline["mean_dt_s"] <= 6.0 * 3600.0)
    assert_true("finite divergence", math.isfinite(baseline["mean_abs_divergence"]))
    assert_true("finite vorticity", math.isfinite(baseline["mean_abs_vorticity"]))
    assert_true("finite bulk ri", math.isfinite(baseline["mean_bulk_ri"]))
    assert_true("finite n2", math.isfinite(baseline["mean_brunt_vaisala_n2"]))
    assert_true("finite vertical shear", math.isfinite(baseline["mean_vertical_shear_s_1"]))
    assert_true("finite jet speed", math.isfinite(baseline["mean_jet_speed_m_s"]))
    assert_true("finite temp flux", math.isfinite(baseline["mean_vertical_temp_flux"]))
    assert_true("finite moisture flux", math.isfinite(baseline["mean_vertical_moisture_flux"]))
    assert_true("finite moisture correction", math.isfinite(baseline["mean_column_moisture_correction"]))
    assert_true("finite energy residual", math.isfinite(baseline["mean_energy_residual_w_m2"]))
    assert_true("finite energy correction", math.isfinite(baseline["mean_energy_correction_k"]))
    assert_true("finite latent flux", math.isfinite(baseline["mean_latent_flux_w_m2"]))
    assert_true("finite latent residual", math.isfinite(baseline["mean_latent_residual_w_m2"]))
    assert_true("finite vertical velocity", math.isfinite(baseline["mean_vertical_velocity_m_s"]))
    assert_true("finite hadley index", math.isfinite(baseline["mean_hadley_index_k"]))
    assert_true("finite cumulative energy", math.isfinite(baseline["cumulative_energy_input_j_m2"]))
    assert_true("finite cumulative latent", math.isfinite(baseline["cumulative_latent_j_m2"]))
    assert_true("finite cumulative correction", math.isfinite(baseline["cumulative_energy_correction_j_m2"]))
    assert_true(
        "finite cumulative moisture correction",
        math.isfinite(baseline["cumulative_moisture_correction_kg_m2"]),
    )
    assert_true("bulk ri bounds", -2.0 <= baseline["mean_bulk_ri"] <= 12.0)
    assert_true("n2 bounds", -5.0e-3 <= baseline["mean_brunt_vaisala_n2"] <= 5.0e-3)
    assert_true("vertical shear bounds", 0.0 <= baseline["mean_vertical_shear_s_1"] <= 0.5)
    assert_true("jet speed bounds", 0.0 <= baseline["mean_jet_speed_m_s"] <= 220.0)
    assert_true("temp flux non-negative", baseline["mean_vertical_temp_flux"] >= 0.0)
    assert_true("moisture flux non-negative", baseline["mean_vertical_moisture_flux"] >= 0.0)
    assert_true("moisture correction non-negative", baseline["mean_column_moisture_correction"] >= 0.0)
    assert_true("moisture correction bounded", baseline["mean_column_moisture_correction"] <= 0.02)
    assert_true("energy residual bounded", abs(baseline["mean_energy_residual_w_m2"]) <= 1.2e4)
    assert_true("energy correction bounded", baseline["mean_energy_correction_k"] <= 1.2)
    assert_true("latent flux bounded", abs(baseline["mean_latent_flux_w_m2"]) <= 1.5e3)
    assert_true("latent residual bounded", abs(baseline["mean_latent_residual_w_m2"]) <= 1.0e-3)
    assert_true("vertical velocity bounded", 0.0 <= baseline["mean_vertical_velocity_m_s"] <= 1.0)
    assert_true("hadley index bounded", 0.0 <= baseline["mean_hadley_index_k"] <= 90.0)
    assert_true("cumulative energy correction non-negative", baseline["cumulative_energy_correction_j_m2"] >= 0.0)
    assert_true("cumulative moisture correction non-negative", baseline["cumulative_moisture_correction_kg_m2"] >= 0.0)
    assert_true(
        "vertical temperature stratification",
        baseline["mean_upper_temperature_k"] < baseline["mean_lower_temperature_k"],
    )
    assert_true(
        "vertical humidity stratification",
        baseline["mean_upper_specific_humidity"] < baseline["mean_specific_humidity"],
    )

    print("physics_tests_ok")
    print(f"baseline_temp={baseline['mean_surface_temperature_k']:.4f}")
    print(f"baseline_pressure={baseline['mean_surface_pressure_pa']:.2f}")
    print(f"baseline_rossby={baseline['mean_rossby']:.6f}")
    print(f"baseline_abs_vorticity={baseline['mean_abs_vorticity']:.6e}")
    print(f"baseline_upper_temp={baseline['mean_upper_temperature_k']:.4f}")
    print(f"baseline_bulk_ri={baseline['mean_bulk_ri']:.6f}")
    print(f"baseline_vertical_shear={baseline['mean_vertical_shear_s_1']:.6e}")
    print(f"baseline_jet_speed={baseline['mean_jet_speed_m_s']:.4f}")
    print(f"baseline_temp_flux={baseline['mean_vertical_temp_flux']:.6e}")
    print(f"baseline_moisture_flux={baseline['mean_vertical_moisture_flux']:.6e}")
    print(f"baseline_moisture_correction={baseline['mean_column_moisture_correction']:.6e}")
    print(f"baseline_energy_residual={baseline['mean_energy_residual_w_m2']:.6e}")
    print(f"baseline_energy_correction={baseline['mean_energy_correction_k']:.6e}")
    print(f"baseline_latent_flux={baseline['mean_latent_flux_w_m2']:.6e}")
    print(f"baseline_latent_residual={baseline['mean_latent_residual_w_m2']:.6e}")
    print(f"baseline_vertical_velocity={baseline['mean_vertical_velocity_m_s']:.6e}")
    print(f"baseline_hadley_index={baseline['mean_hadley_index_k']:.6e}")
    print(f"baseline_cum_energy={baseline['cumulative_energy_input_j_m2']:.6e}")
    print(f"baseline_cum_latent={baseline['cumulative_latent_j_m2']:.6e}")
