import matplotlib.pyplot as plt
import numpy as np

try:
    from planet_physics import PlanetConfig, PlanetPhysicsSimulator
except ModuleNotFoundError:
    from CoruscantSim.planet_physics import PlanetConfig, PlanetPhysicsSimulator


def run_simulation(days=220):
    cfg = PlanetConfig(
        name="Coruscant",
        mass_kg=5.95e24,
        radius_m=6.15e6,
        rotation_period_s=24.2 * 3600.0,
        obliquity_deg=21.0,
        semi_major_axis_m=1.52e11,
        surface_albedo=0.31,
        greenhouse_forcing_w_m2=105.0,
        atmosphere_mass_kg=5.35e18,
    )

    sim = PlanetPhysicsSimulator(cfg, n_lat=72, n_lon=144, seed=21)

    for day in range(days):
        sim.step(day_of_year=float(day % 365))

    return sim


def plot_fields(sim: PlanetPhysicsSimulator):
    wind_speed = np.sqrt(sim.u_wind_m_s**2 + sim.v_wind_m_s**2)
    mach = sim.mach_number_field()
    abs_vorticity = np.abs(sim._flow_diagnostics()[1])

    fig, axes = plt.subplots(3, 3, figsize=(16, 11))
    fig.suptitle(f"{sim.cfg.name} Planet Physics - Detailed Core")

    im1 = axes[0, 0].imshow(sim.temperature_k, cmap="inferno")
    axes[0, 0].set_title("Surface Temperature (K)")

    im2 = axes[0, 1].imshow(sim.pressure_pa / 100.0, cmap="viridis")
    axes[0, 1].set_title("Surface Pressure (hPa)")

    im3 = axes[0, 2].imshow(wind_speed, cmap="plasma")
    axes[0, 2].set_title("Wind Speed (m/s)")

    im4 = axes[1, 0].imshow(sim.lower_atmos_temperature_k, cmap="coolwarm")
    axes[1, 0].set_title("Lower Atmos Temperature (K)")

    im5 = axes[1, 1].imshow(sim.specific_humidity * 1000.0, cmap="Blues")
    axes[1, 1].set_title("Specific Humidity (g/kg)")

    im6 = axes[1, 2].imshow(sim.cloud_fraction, cmap="bone")
    axes[1, 2].set_title("Cloud Fraction")

    im7 = axes[2, 0].imshow(sim.precipitation_mm_day, cmap="PuBuGn")
    axes[2, 0].set_title("Precipitation Proxy (mm/day)")

    im8 = axes[2, 1].imshow(mach, cmap="magma")
    axes[2, 1].set_title("Mach Number")

    im9 = axes[2, 2].imshow(abs_vorticity, cmap="cividis")
    axes[2, 2].set_title("Abs Vorticity (1/s)")

    for ax in axes.ravel():
        ax.set_xticks([])
        ax.set_yticks([])

    for ax, im in zip(axes.ravel(), [im1, im2, im3, im4, im5, im6, im7, im8, im9]):
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    plt.show()


def plot_time_series(sim: PlanetPhysicsSimulator):
    t = np.arange(len(sim.history["mean_temperature_k"]))

    fig, axes = plt.subplots(2, 3, figsize=(15, 7.8))
    fig.suptitle("Coruscant Atmospheric Diagnostics (Global Means)")

    axes[0, 0].plot(t, sim.history["mean_temperature_k"])
    axes[0, 0].set_title("Mean Temperature (K)")

    axes[0, 1].plot(t, sim.history["mean_lower_temp_k"], color="tab:red")
    axes[0, 1].set_title("Mean Lower-Atmos Temp (K)")

    axes[0, 2].plot(t, np.array(sim.history["mean_pressure_pa"]) / 100.0)
    axes[0, 2].set_title("Mean Pressure (hPa)")

    axes[1, 0].plot(t, sim.history["mean_wind_m_s"])
    axes[1, 0].set_title("Mean Wind Speed (m/s)")

    axes[1, 1].plot(t, np.array(sim.history["mean_specific_humidity"]) * 1000.0, label="Humidity g/kg")
    axes[1, 1].plot(t, sim.history["mean_cloud_fraction"], label="Cloud frac")
    axes[1, 1].plot(t, sim.history["mean_precip_mm_day"], label="Precip mm/day")
    axes[1, 1].set_title("Moisture Diagnostics")
    axes[1, 1].legend()

    axes[1, 2].plot(t, sim.history["mean_mach"], label="Mach")
    axes[1, 2].plot(t, np.array(sim.history["mean_reynolds"]) / 1e8, label="Re / 1e8")
    axes[1, 2].plot(t, np.array(sim.history["mean_dt_s"]) / 3600.0, label="dt (hours)")
    axes[1, 2].plot(t, np.array(sim.history["mean_abs_vorticity"]) * 1e4, label="|zeta| x1e4")
    axes[1, 2].plot(t, np.array(sim.history["mean_abs_divergence"]) * 1e4, label="|div| x1e4")
    axes[1, 2].plot(t, np.array(sim.history["mean_energy_residual_w_m2"]) / 1e3, label="E residual / 1e3")
    axes[1, 2].plot(t, np.array(sim.history["mean_energy_correction_k"]) * 100.0, label="dT corr x100")
    axes[1, 2].plot(t, np.array(sim.history["mean_latent_flux_w_m2"]) / 1e3, label="Latent / 1e3")
    axes[1, 2].plot(t, np.array(sim.history["mean_latent_residual_w_m2"]) * 100.0, label="Lat res x100")
    axes[1, 2].plot(t, np.array(sim.history["mean_vertical_velocity_m_s"]) * 10.0, label="w x10")
    axes[1, 2].plot(t, np.array(sim.history["mean_hadley_index_k"]) / 10.0, label="Hadley K/10")
    axes[1, 2].set_title("Aerophysics Indicators")
    axes[1, 2].legend()

    for ax in axes.ravel():
        ax.grid(True, alpha=0.25)
        ax.set_xlabel("Simulation day")

    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    plt.show()


def plot_vertical_diagnostics(sim: PlanetPhysicsSimulator):
    # Zonal means over longitude for vertical structure checks.
    zonal_temp = np.mean(sim.temperature_profile_k, axis=2)
    zonal_q = np.mean(sim.humidity_profile, axis=2) * 1000.0  # g/kg
    zonal_wind = np.mean(np.sqrt(sim.u_wind_profile_m_s**2 + sim.v_wind_profile_m_s**2), axis=2)

    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.4))
    fig.suptitle("Vertical Atmospheric Structure (Zonal Means)")

    x_lat = sim.lats
    y_level = np.arange(sim.cfg.vertical_levels)

    im1 = axes[0].imshow(
        zonal_temp,
        aspect="auto",
        origin="lower",
        extent=[x_lat.min(), x_lat.max(), y_level.min(), y_level.max()],
        cmap="coolwarm",
    )
    axes[0].set_title("Temperature Profile (K)")
    axes[0].set_xlabel("Latitude")
    axes[0].set_ylabel("Vertical level index")
    plt.colorbar(im1, ax=axes[0], fraction=0.046, pad=0.04)

    im2 = axes[1].imshow(
        zonal_q,
        aspect="auto",
        origin="lower",
        extent=[x_lat.min(), x_lat.max(), y_level.min(), y_level.max()],
        cmap="Blues",
    )
    axes[1].set_title("Humidity Profile (g/kg)")
    axes[1].set_xlabel("Latitude")
    axes[1].set_ylabel("Vertical level index")
    plt.colorbar(im2, ax=axes[1], fraction=0.046, pad=0.04)

    im3 = axes[2].imshow(
        zonal_wind,
        aspect="auto",
        origin="lower",
        extent=[x_lat.min(), x_lat.max(), y_level.min(), y_level.max()],
        cmap="magma",
    )
    axes[2].set_title("Wind Speed Profile (m/s)")
    axes[2].set_xlabel("Latitude")
    axes[2].set_ylabel("Vertical level index")
    plt.colorbar(im3, ax=axes[2], fraction=0.046, pad=0.04)

    plt.tight_layout(rect=[0, 0.03, 1, 0.93])
    plt.show()


if __name__ == "__main__":
    sim = run_simulation(days=220)

    print("=== Coruscant Planet Summary ===")
    for key, value in sim.summary_metrics().items():
        print(f"{key}: {value:.6g}")

    plot_fields(sim)
    plot_time_series(sim)
    plot_vertical_diagnostics(sim)
