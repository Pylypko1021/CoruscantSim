from dataclasses import dataclass
from typing import Dict, List

import numpy as np


SIGMA = 5.670374419e-8  # Stefan-Boltzmann constant, W m^-2 K^-4
G_CONST = 6.67430e-11  # gravitational constant, m^3 kg^-1 s^-2
R_UNIV = 8.314462618  # universal gas constant, J mol^-1 K^-1
L_V = 2.5e6  # latent heat of vaporization, J kg^-1


@dataclass
class PlanetConfig:
    name: str = "Coruscant"
    mass_kg: float = 5.972e24
    radius_m: float = 6.12e6
    rotation_period_s: float = 24.0 * 3600.0
    obliquity_deg: float = 23.0
    semi_major_axis_m: float = 1.496e11
    stellar_luminosity_w: float = 3.828e26
    surface_albedo: float = 0.22
    atmosphere_mass_kg: float = 5.15e18
    mean_molecular_weight_kg_per_mol: float = 0.02897
    cp_air_j_kg_k: float = 1004.0
    gamma_air: float = 1.4
    greenhouse_forcing_w_m2: float = 115.0
    cloud_cooling_coeff: float = 0.46
    emissivity: float = 0.98
    dyn_viscosity_pa_s: float = 1.8e-5
    roughness_length_m: float = 1.2
    simulation_dt_s: float = 6.0 * 3600.0
    cfl_target: float = 0.45
    min_dt_s: float = 15.0 * 60.0
    max_dt_s: float = 6.0 * 3600.0
    vertical_levels: int = 8


class PlanetPhysicsSimulator:
    """High-detail planet physics core focused on atmosphere and surface forcing.

    This model is deliberately more physical than game-style city equations:
    - radiative heating/cooling,
    - hydrostatic pressure with topography,
    - Coriolis + geostrophic wind approximation,
    - thermal diffusion and simple advection,
    - aerophysics diagnostics (Mach, Reynolds, Rossby-like numbers).
    """

    def __init__(self, config: PlanetConfig, n_lat: int = 72, n_lon: int = 144, seed: int = 17):
        self.cfg = config
        self.n_lat = n_lat
        self.n_lon = n_lon
        self.rng = np.random.default_rng(seed)
        self.dt = config.simulation_dt_s

        self.lats = np.linspace(-89.0, 89.0, n_lat)
        self.lons = np.linspace(0.0, 360.0, n_lon, endpoint=False)
        self.lat2d, self.lon2d = np.meshgrid(self.lats, self.lons, indexing="ij")

        self.topography_m = self._build_topography()

        self.temperature_k = np.zeros((n_lat, n_lon), dtype=np.float64)
        self.lower_atmos_temperature_k = np.zeros((n_lat, n_lon), dtype=np.float64)
        self.pressure_pa = np.zeros((n_lat, n_lon), dtype=np.float64)
        self.density_kg_m3 = np.zeros((n_lat, n_lon), dtype=np.float64)
        self.specific_humidity = np.zeros((n_lat, n_lon), dtype=np.float64)
        self.cloud_fraction = np.zeros((n_lat, n_lon), dtype=np.float64)
        self.precipitation_mm_day = np.zeros((n_lat, n_lon), dtype=np.float64)
        self.u_wind_m_s = np.zeros((n_lat, n_lon), dtype=np.float64)
        self.v_wind_m_s = np.zeros((n_lat, n_lon), dtype=np.float64)

        self.pressure_levels_pa = np.zeros(config.vertical_levels, dtype=np.float64)
        self.temperature_profile_k = np.zeros((config.vertical_levels, n_lat, n_lon), dtype=np.float64)
        self.humidity_profile = np.zeros((config.vertical_levels, n_lat, n_lon), dtype=np.float64)
        self.u_wind_profile_m_s = np.zeros((config.vertical_levels, n_lat, n_lon), dtype=np.float64)
        self.v_wind_profile_m_s = np.zeros((config.vertical_levels, n_lat, n_lon), dtype=np.float64)

        self.current_dt_s = float(config.simulation_dt_s)
        self.current_column_moisture_correction = 0.0
        self.current_energy_residual_w_m2 = 0.0
        self.current_energy_correction_k = 0.0
        self.current_latent_flux_w_m2 = 0.0
        self.current_latent_residual_w_m2 = 0.0
        self.current_vertical_velocity_m_s = 0.0
        self.current_hadley_index_k = 0.0
        self.current_cumulative_energy_input_j_m2 = 0.0
        self.current_cumulative_latent_j_m2 = 0.0
        self.current_cumulative_energy_correction_j_m2 = 0.0
        self.current_cumulative_moisture_correction_kg_m2 = 0.0

        self._initialize_state()

        self.history: Dict[str, List[float]] = {
            "mean_temperature_k": [],
            "mean_pressure_pa": [],
            "mean_wind_m_s": [],
            "mean_mach": [],
            "mean_reynolds": [],
            "mean_lower_temp_k": [],
            "mean_specific_humidity": [],
            "mean_cloud_fraction": [],
            "mean_precip_mm_day": [],
            "mean_dt_s": [],
            "mean_abs_vorticity": [],
            "mean_abs_divergence": [],
            "mean_bulk_ri": [],
            "mean_brunt_vaisala_n2": [],
            "mean_vertical_shear_s_1": [],
            "mean_jet_speed_m_s": [],
            "mean_vertical_temp_flux": [],
            "mean_vertical_moisture_flux": [],
            "mean_column_moisture_correction": [],
            "mean_energy_residual_w_m2": [],
            "mean_energy_correction_k": [],
            "mean_latent_flux_w_m2": [],
            "mean_latent_residual_w_m2": [],
            "mean_vertical_velocity_m_s": [],
            "mean_hadley_index_k": [],
            "cumulative_energy_input_j_m2": [],
            "cumulative_latent_j_m2": [],
            "cumulative_energy_correction_j_m2": [],
            "cumulative_moisture_correction_kg_m2": [],
        }

    @property
    def omega(self) -> float:
        return 2.0 * np.pi / self.cfg.rotation_period_s

    @property
    def gravity_m_s2(self) -> float:
        return G_CONST * self.cfg.mass_kg / (self.cfg.radius_m**2)

    @property
    def surface_area_m2(self) -> float:
        return 4.0 * np.pi * self.cfg.radius_m**2

    @property
    def atmospheric_column_mass_kg_m2(self) -> float:
        return self.cfg.atmosphere_mass_kg / self.surface_area_m2

    @property
    def surface_pressure_ref_pa(self) -> float:
        return self.atmospheric_column_mass_kg_m2 * self.gravity_m_s2

    @property
    def solar_constant_w_m2(self) -> float:
        return self.cfg.stellar_luminosity_w / (4.0 * np.pi * self.cfg.semi_major_axis_m**2)

    @property
    def r_specific(self) -> float:
        return R_UNIV / self.cfg.mean_molecular_weight_kg_per_mol

    @property
    def dry_lapse_rate_k_m(self) -> float:
        return self.gravity_m_s2 / self.cfg.cp_air_j_kg_k

    @property
    def scale_height_m(self) -> float:
        return self.r_specific * np.mean(self.temperature_k) / self.gravity_m_s2

    @property
    def escape_velocity_m_s(self) -> float:
        return np.sqrt(2.0 * G_CONST * self.cfg.mass_kg / self.cfg.radius_m)

    @property
    def equatorial_rotation_speed_m_s(self) -> float:
        return self.omega * self.cfg.radius_m

    @property
    def equilibrium_temperature_k(self) -> float:
        q = self.solar_constant_w_m2 * (1.0 - self.cfg.surface_albedo) / 4.0
        return (q / SIGMA) ** 0.25

    def _build_topography(self) -> np.ndarray:
        lat_rad = np.deg2rad(self.lat2d)
        lon_rad = np.deg2rad(self.lon2d)

        long_wave = 1800.0 * np.sin(2.0 * lat_rad) * np.cos(1.5 * lon_rad)
        city_shell = 700.0 * np.cos(lat_rad) ** 2
        high_freq = 220.0 * (
            np.sin(8.0 * lon_rad + 0.7) * np.cos(6.0 * lat_rad - 0.3)
            + 0.5 * np.sin(13.0 * lon_rad) * np.sin(9.0 * lat_rad)
        )
        noise = self.rng.normal(0.0, 50.0, size=(self.n_lat, self.n_lon))

        topo = long_wave + city_shell + high_freq + noise
        return np.clip(topo, -1200.0, 4200.0)

    def _initialize_state(self):
        lat_rad = np.deg2rad(self.lat2d)
        base_t = self.equilibrium_temperature_k + 33.0
        meridional = -38.0 * np.sin(lat_rad) ** 2
        lapse_term = -self.dry_lapse_rate_k_m * np.maximum(self.topography_m, 0.0)
        urban_heat = 4.5 * np.exp(-(self.topography_m - np.mean(self.topography_m)) ** 2 / (2.0 * 1200.0**2))

        self.temperature_k = base_t + meridional + lapse_term + urban_heat
        self.temperature_k = np.clip(self.temperature_k, 195.0, 335.0)
        self.lower_atmos_temperature_k = np.clip(self.temperature_k - 6.0, 185.0, 325.0)

        # Initialize humidity by latitude with stochastic meso-scale structure.
        humid_lat = 0.018 + 0.010 * np.cos(np.deg2rad(self.lat2d)) ** 2
        humid_noise = self.rng.normal(0.0, 0.0015, size=(self.n_lat, self.n_lon))
        self.specific_humidity = np.clip(humid_lat + humid_noise, 0.001, 0.04)
        self.cloud_fraction = np.clip(0.25 + 7.0 * (self.specific_humidity - 0.012), 0.0, 1.0)
        self.precipitation_mm_day = np.zeros_like(self.specific_humidity)

        self._update_pressure_density()
        self._initialize_winds()
        self._initialize_vertical_profiles()

    def _update_pressure_density(self):
        h = np.maximum(self.topography_m, -1500.0)
        h_scale = np.maximum(self.scale_height_m, 1000.0)
        self.pressure_pa = self.surface_pressure_ref_pa * np.exp(-h / h_scale)
        self.pressure_pa = np.clip(self.pressure_pa, 8.0e3, 1.5e5)

        self.density_kg_m3 = self.pressure_pa / (self.r_specific * self.temperature_k)
        self.density_kg_m3 = np.clip(self.density_kg_m3, 0.08, 3.2)

    def _latlon_spacings_m(self):
        dlat = np.deg2rad(180.0 / max(self.n_lat - 1, 1))
        dlon = np.deg2rad(360.0 / self.n_lon)

        dy = self.cfg.radius_m * dlat
        dx = self.cfg.radius_m * np.cos(np.deg2rad(self.lat2d)) * dlon
        dx = np.clip(dx, 1500.0, None)
        return dx, dy

    def _compute_adaptive_dt(self):
        dx, dy = self._latlon_spacings_m()
        wind_speed = np.sqrt(self.u_wind_m_s**2 + self.v_wind_m_s**2)
        max_speed = float(np.max(np.clip(wind_speed, 0.05, None)))

        dx_min = float(np.min(dx))
        dy_min = float(np.min(np.full_like(dx, dy)))
        d_char = min(dx_min, dy_min)

        cfl_dt = self.cfg.cfl_target * d_char / max_speed
        cfl_dt = float(np.clip(cfl_dt, self.cfg.min_dt_s, self.cfg.max_dt_s))
        self.current_dt_s = cfl_dt

    def _initialize_vertical_profiles(self):
        # Pressure grid from near-surface to upper troposphere/stratosphere lower bound.
        p_top = 1.0e4
        p_bot = max(self.surface_pressure_ref_pa * 0.98, 8.0e4)
        self.pressure_levels_pa = np.geomspace(p_bot, p_top, self.cfg.vertical_levels)

        for k in range(self.cfg.vertical_levels):
            level_frac = k / max(self.cfg.vertical_levels - 1, 1)
            self.temperature_profile_k[k] = np.clip(
                self.lower_atmos_temperature_k - 35.0 * level_frac,
                145.0,
                335.0,
            )
            self.humidity_profile[k] = np.clip(
                self.specific_humidity * np.exp(-2.2 * level_frac),
                1e-6,
                0.08,
            )
            # Winds generally weaken upward in lower layers before jet-core shaping.
            decay = np.exp(-0.9 * level_frac)
            self.u_wind_profile_m_s[k] = self.u_wind_m_s * decay
            self.v_wind_profile_m_s[k] = self.v_wind_m_s * decay

    def _update_vertical_profiles(self):
        # Couple vertical profile to current lower-atmos state and enforce lapse consistency.
        for k in range(self.cfg.vertical_levels):
            level_frac = k / max(self.cfg.vertical_levels - 1, 1)

            target_temp = self.lower_atmos_temperature_k - 42.0 * level_frac
            self.temperature_profile_k[k] = 0.85 * self.temperature_profile_k[k] + 0.15 * target_temp

            # Moisture decays with altitude, plus weak mixing.
            target_q = self.specific_humidity * np.exp(-2.4 * level_frac)
            mixed = 0.90 * self.humidity_profile[k] + 0.10 * target_q
            if 0 < k < self.cfg.vertical_levels - 1:
                mixed += 0.02 * (self.humidity_profile[k - 1] + self.humidity_profile[k + 1] - 2.0 * self.humidity_profile[k])

            self.humidity_profile[k] = np.clip(mixed, 1e-6, 0.08)

        # Explicit vertical transport (eddy diffusion) for heat and moisture.
        # This makes vertical levels prognostic rather than a pure diagnostic profile.
        dz = 1400.0
        k_temp = 0.32
        k_moist = 0.18

        ri_bulk, n2_field = self._stability_diagnostics(dz=dz)
        # Stable stratification (larger Ri) suppresses turbulent exchange.
        mix_factor = 1.0 / (1.0 + np.clip(ri_bulk, 0.0, 6.0) / 0.25)
        mix_factor = np.clip(mix_factor, 0.10, 1.0)

        k_temp_eff = k_temp * mix_factor
        k_moist_eff = k_moist * mix_factor

        t_tendency = np.zeros_like(self.temperature_profile_k)
        q_tendency = np.zeros_like(self.humidity_profile)

        t_tendency[1:-1] = (
            k_temp_eff
            * (self.temperature_profile_k[2:] - 2.0 * self.temperature_profile_k[1:-1] + self.temperature_profile_k[:-2])
            / (dz * dz)
        )
        q_tendency[1:-1] = (
            k_moist_eff
            * (self.humidity_profile[2:] - 2.0 * self.humidity_profile[1:-1] + self.humidity_profile[:-2])
            / (dz * dz)
        )

        # Zero-flux boundaries at top and bottom in finite-difference form.
        t_tendency[0] = k_temp_eff * (self.temperature_profile_k[1] - self.temperature_profile_k[0]) / (dz * dz)
        t_tendency[-1] = k_temp_eff * (self.temperature_profile_k[-2] - self.temperature_profile_k[-1]) / (dz * dz)
        q_tendency[0] = k_moist_eff * (self.humidity_profile[1] - self.humidity_profile[0]) / (dz * dz)
        q_tendency[-1] = k_moist_eff * (self.humidity_profile[-2] - self.humidity_profile[-1]) / (dz * dz)

        self.temperature_profile_k += self.dt * t_tendency
        self.humidity_profile += self.dt * q_tendency

        self._update_vertical_wind_profiles(ri_bulk=ri_bulk, dz=dz)
        temp_flux, moist_flux, moist_corr = self._apply_vertical_flux_advection(dz=dz, ri_bulk=ri_bulk)

        # Two-way coupling with lower-model layers.
        lower_relax = np.clip(self.dt / (20.0 * 3600.0), 0.0, 1.0)
        self.lower_atmos_temperature_k = (
            (1.0 - lower_relax) * self.lower_atmos_temperature_k + lower_relax * self.temperature_profile_k[1]
        )
        self.specific_humidity = (1.0 - lower_relax) * self.specific_humidity + lower_relax * self.humidity_profile[1]

        surface_relax = np.clip(self.dt / (30.0 * 3600.0), 0.0, 1.0)
        self.temperature_k = (1.0 - surface_relax) * self.temperature_k + surface_relax * self.temperature_profile_k[0]

        # Convective adjustment: enforce monotonic non-inversion tendency in tropospheric range.
        for k in range(1, self.cfg.vertical_levels):
            too_warm_aloft = self.temperature_profile_k[k] > self.temperature_profile_k[k - 1] - 0.2
            self.temperature_profile_k[k][too_warm_aloft] = self.temperature_profile_k[k - 1][too_warm_aloft] - 0.2

        self.temperature_profile_k = np.clip(self.temperature_profile_k, 140.0, 340.0)
        self.humidity_profile = np.clip(self.humidity_profile, 1e-6, 0.08)
        self.u_wind_profile_m_s = np.clip(self.u_wind_profile_m_s, -180.0, 180.0)
        self.v_wind_profile_m_s = np.clip(self.v_wind_profile_m_s, -180.0, 180.0)

        return temp_flux, moist_flux, moist_corr

    def _apply_vertical_flux_advection(self, dz: float, ri_bulk: np.ndarray):
        levels = self.cfg.vertical_levels
        if levels < 2:
            zeros = np.zeros((self.n_lat, self.n_lon), dtype=np.float64)
            return zeros, zeros, zeros

        w = self._diagnose_vertical_velocity(ri_bulk=ri_bulk, dz=dz)

        # Conservative flux-form update with first-order upwind reconstruction.
        flux_t = np.zeros((levels - 1, self.n_lat, self.n_lon), dtype=np.float64)
        flux_q = np.zeros((levels - 1, self.n_lat, self.n_lon), dtype=np.float64)
        for k in range(levels - 1):
            t_up = np.where(w > 0.0, self.temperature_profile_k[k], self.temperature_profile_k[k + 1])
            q_up = np.where(w > 0.0, self.humidity_profile[k], self.humidity_profile[k + 1])
            flux_t[k] = w * t_up
            flux_q[k] = w * q_up

        # Zero net boundary flux at top and bottom.
        flux_t_b = np.zeros((levels + 1, self.n_lat, self.n_lon), dtype=np.float64)
        flux_q_b = np.zeros((levels + 1, self.n_lat, self.n_lon), dtype=np.float64)
        flux_t_b[1:-1] = flux_t
        flux_q_b[1:-1] = flux_q

        t_adv = -(flux_t_b[1:] - flux_t_b[:-1]) / max(dz, 1.0)
        q_adv = -(flux_q_b[1:] - flux_q_b[:-1]) / max(dz, 1.0)

        # Positivity and stability limiter.
        max_dt = 0.8 * max(dz, 1.0) / max(float(np.max(np.abs(w))), 1e-5)
        dt_eff = min(self.dt, max_dt)
        self.temperature_profile_k += dt_eff * t_adv
        q_before = np.sum(self.humidity_profile, axis=0)
        self.humidity_profile += dt_eff * q_adv
        self.humidity_profile = np.clip(self.humidity_profile, 1e-6, 0.08)

        corr_abs = self._apply_column_moisture_fixer(target_column=q_before)

        return np.mean(np.abs(flux_t), axis=0), np.mean(np.abs(flux_q), axis=0), corr_abs

    def _diagnose_vertical_velocity(self, ri_bulk: np.ndarray, dz: float) -> np.ndarray:
        # Thermally direct circulation proxy: equatorial heating + low-level convergence.
        dtemp_dy = np.gradient(self.temperature_k, axis=0) / max(dz, 1.0)
        hadley_drive = -0.06 * dtemp_dy

        divergence, _ = self._flow_diagnostics()
        convergence_drive = -260.0 * divergence

        stability_term = 0.35 * np.clip(-ri_bulk, 0.0, 1.2) - 0.10 * np.clip(ri_bulk, 0.0, 2.0)
        w = hadley_drive + convergence_drive + stability_term
        w = np.clip(w, -0.7, 0.9)

        self.current_vertical_velocity_m_s = float(np.mean(np.abs(w)))

        eq_mask = np.abs(self.lat2d) <= 20.0
        mid_mask = (np.abs(self.lat2d) >= 35.0) & (np.abs(self.lat2d) <= 60.0)
        eq_t = float(np.mean(self.temperature_k[eq_mask])) if np.any(eq_mask) else float(np.mean(self.temperature_k))
        mid_t = float(np.mean(self.temperature_k[mid_mask])) if np.any(mid_mask) else float(np.mean(self.temperature_k))
        self.current_hadley_index_k = eq_t - mid_t

        return w

    def _apply_column_moisture_fixer(self, target_column: np.ndarray) -> np.ndarray:
        """Conserve column-integrated moisture after transport under bounded humidity.

        Applies a minimal uniform correction per column while respecting [q_min, q_max]
        constraints, then performs one residual pass if room remains.
        """
        q_min = 1e-6
        q_max = 0.08

        q = self.humidity_profile.copy()
        q_before_fix = q.copy()
        levels = q.shape[0]
        current = np.sum(q, axis=0)
        delta = target_column - current

        up_room = np.sum(q_max - q, axis=0)
        down_room = np.sum(q - q_min, axis=0)
        limited_delta = np.where(delta > 0.0, np.minimum(delta, up_room), np.maximum(delta, -down_room))

        q += limited_delta[None, :] / max(levels, 1)
        q = np.clip(q, q_min, q_max)

        residual = target_column - np.sum(q, axis=0)
        mask = np.abs(residual) > 1e-12
        if np.any(mask):
            up_room2 = np.sum(q_max - q, axis=0)
            down_room2 = np.sum(q - q_min, axis=0)
            residual = np.where(residual > 0.0, np.minimum(residual, up_room2), np.maximum(residual, -down_room2))
            q += residual[None, :] / max(levels, 1)
            q = np.clip(q, q_min, q_max)

        correction_abs = np.mean(np.abs(q - q_before_fix), axis=0)
        self.humidity_profile = q
        return correction_abs

    def _update_vertical_wind_profiles(self, ri_bulk: np.ndarray, dz: float = 1400.0):
        levels = self.cfg.vertical_levels
        if levels < 2:
            self.u_wind_profile_m_s[0] = self.u_wind_m_s
            self.v_wind_profile_m_s[0] = self.v_wind_m_s
            return

        self.u_wind_profile_m_s[0] = self.u_wind_m_s
        self.v_wind_profile_m_s[0] = self.v_wind_m_s

        dtemp_dy = np.gradient(self.lower_atmos_temperature_k, axis=0) / max(dz, 1.0)
        thermal_wind = -2.0e-2 * dtemp_dy

        mix_factor = 1.0 / (1.0 + np.clip(ri_bulk, 0.0, 8.0) / 0.25)
        mix_factor = np.clip(mix_factor, 0.08, 1.0)
        k_wind = 0.24 * mix_factor

        u_tendency = np.zeros_like(self.u_wind_profile_m_s)
        v_tendency = np.zeros_like(self.v_wind_profile_m_s)

        u_tendency[1:-1] = (
            k_wind
            * (self.u_wind_profile_m_s[2:] - 2.0 * self.u_wind_profile_m_s[1:-1] + self.u_wind_profile_m_s[:-2])
            / (dz * dz)
        )
        v_tendency[1:-1] = (
            k_wind
            * (self.v_wind_profile_m_s[2:] - 2.0 * self.v_wind_profile_m_s[1:-1] + self.v_wind_profile_m_s[:-2])
            / (dz * dz)
        )

        u_tendency[0] = k_wind * (self.u_wind_profile_m_s[1] - self.u_wind_profile_m_s[0]) / (dz * dz)
        u_tendency[-1] = k_wind * (self.u_wind_profile_m_s[-2] - self.u_wind_profile_m_s[-1]) / (dz * dz)
        v_tendency[0] = k_wind * (self.v_wind_profile_m_s[1] - self.v_wind_profile_m_s[0]) / (dz * dz)
        v_tendency[-1] = k_wind * (self.v_wind_profile_m_s[-2] - self.v_wind_profile_m_s[-1]) / (dz * dz)

        self.u_wind_profile_m_s += self.dt * u_tendency
        self.v_wind_profile_m_s += self.dt * v_tendency

        for k in range(1, levels):
            frac = k / max(levels - 1, 1)
            jet_shape = 1.0 + 0.35 * np.sin(np.pi * frac)
            self.u_wind_profile_m_s[k] += self.dt * (thermal_wind * jet_shape)

        # Keep level 0 tied to prognostic near-surface winds.
        self.u_wind_profile_m_s[0] = self.u_wind_m_s
        self.v_wind_profile_m_s[0] = self.v_wind_m_s

    def _stability_diagnostics(self, dz: float = 1400.0):
        p0 = self.pressure_levels_pa[0]
        p1 = self.pressure_levels_pa[min(1, self.cfg.vertical_levels - 1)]
        kappa = self.r_specific / self.cfg.cp_air_j_kg_k

        theta0 = self.temperature_profile_k[0] * (p0 / np.clip(self.pressure_levels_pa[0], 1.0, None)) ** kappa
        theta1 = self.temperature_profile_k[min(1, self.cfg.vertical_levels - 1)] * (p0 / np.clip(p1, 1.0, None)) ** kappa
        dtheta_dz = (theta1 - theta0) / max(dz, 1.0)

        du = self.u_wind_profile_m_s[min(1, self.cfg.vertical_levels - 1)] - self.u_wind_profile_m_s[0]
        dv = self.v_wind_profile_m_s[min(1, self.cfg.vertical_levels - 1)] - self.v_wind_profile_m_s[0]
        shear2 = (du * du + dv * dv) / (max(dz, 1.0) ** 2) + 1.0e-8

        n2 = (self.gravity_m_s2 / np.clip(theta0, 120.0, None)) * dtheta_dz
        ri_bulk = n2 / shear2
        return np.clip(ri_bulk, -2.0, 12.0), np.clip(n2, -5.0e-3, 5.0e-3)

    def _initialize_winds(self):
        dx, dy = self._latlon_spacings_m()
        dp_dlat = np.gradient(self.pressure_pa, axis=0) / dy
        dp_dlon = np.gradient(self.pressure_pa, axis=1) / dx

        f = 2.0 * self.omega * np.sin(np.deg2rad(self.lat2d))
        f = np.where(np.abs(f) < 3.0e-5, np.sign(f) * 3.0e-5 + (f == 0.0) * 3.0e-5, f)

        self.u_wind_m_s = -(1.0 / (self.density_kg_m3 * f)) * dp_dlat
        self.v_wind_m_s = (1.0 / (self.density_kg_m3 * f)) * dp_dlon

        self.u_wind_m_s = np.clip(self.u_wind_m_s, -120.0, 120.0)
        self.v_wind_m_s = np.clip(self.v_wind_m_s, -120.0, 120.0)

    def _pressure_gradients(self):
        dx, dy = self._latlon_spacings_m()
        dp_dy = np.gradient(self.pressure_pa, axis=0) / dy
        dp_dx = np.gradient(self.pressure_pa, axis=1) / dx
        return dp_dx, dp_dy, dx, dy

    def _flow_diagnostics(self):
        dx, dy = self._latlon_spacings_m()
        du_dx = np.gradient(self.u_wind_m_s, axis=1) / dx
        dv_dy = np.gradient(self.v_wind_m_s, axis=0) / dy
        dv_dx = np.gradient(self.v_wind_m_s, axis=1) / dx
        du_dy = np.gradient(self.u_wind_m_s, axis=0) / dy

        divergence = du_dx + dv_dy
        vorticity = dv_dx - du_dy
        return divergence, vorticity

    def _update_winds_prognostic(self):
        # Momentum equation tendency terms in shallow-atmosphere approximation.
        dp_dx, dp_dy, _, _ = self._pressure_gradients()
        dx, dy = self._latlon_spacings_m()
        rho = np.clip(self.density_kg_m3, 0.08, None)

        f = 2.0 * self.omega * np.sin(np.deg2rad(self.lat2d))
        # Avoid singularity near equator while keeping sign continuity.
        f = np.where(np.abs(f) < 2.5e-5, np.sign(f) * 2.5e-5 + (f == 0.0) * 2.5e-5, f)

        drag_coeff = 3.5e-5 + 1.1e-5 * np.clip(self.cfg.roughness_length_m / 2.0, 0.2, 2.0)
        visc = 3.0e-2

        lap_u = self._laplacian(self.u_wind_m_s)
        lap_v = self._laplacian(self.v_wind_m_s)

        du_dx = np.gradient(self.u_wind_m_s, axis=1) / dx
        du_dy = np.gradient(self.u_wind_m_s, axis=0) / dy
        dv_dx = np.gradient(self.v_wind_m_s, axis=1) / dx
        dv_dy = np.gradient(self.v_wind_m_s, axis=0) / dy

        adv_u = self.u_wind_m_s * du_dx + self.v_wind_m_s * du_dy
        adv_v = self.u_wind_m_s * dv_dx + self.v_wind_m_s * dv_dy

        du_dt = -(1.0 / rho) * dp_dx + f * self.v_wind_m_s - drag_coeff * self.u_wind_m_s + visc * lap_u - adv_u
        dv_dt = -(1.0 / rho) * dp_dy - f * self.u_wind_m_s - drag_coeff * self.v_wind_m_s + visc * lap_v - adv_v

        self.u_wind_m_s += self.dt * du_dt
        self.v_wind_m_s += self.dt * dv_dt

        # Geostrophic relaxation keeps large-scale balance and suppresses runaway drift.
        ug = -(1.0 / (rho * f)) * dp_dy
        vg = (1.0 / (rho * f)) * dp_dx
        relax = np.clip(self.dt / (10.0 * 3600.0), 0.0, 1.0)

        self.u_wind_m_s = (1.0 - relax) * self.u_wind_m_s + relax * ug
        self.v_wind_m_s = (1.0 - relax) * self.v_wind_m_s + relax * vg

        self.u_wind_m_s = np.clip(self.u_wind_m_s, -140.0, 140.0)
        self.v_wind_m_s = np.clip(self.v_wind_m_s, -140.0, 140.0)

    def _declination_angle_rad(self, day_of_year: float) -> float:
        return np.deg2rad(self.cfg.obliquity_deg) * np.sin(2.0 * np.pi * (day_of_year - 80.0) / 365.0)

    def _daily_mean_insolation(self, day_of_year: float) -> np.ndarray:
        phi = np.deg2rad(self.lat2d)
        delta = self._declination_angle_rad(day_of_year)

        cos_h0 = -np.tan(phi) * np.tan(delta)
        cos_h0 = np.clip(cos_h0, -1.0, 1.0)
        h0 = np.arccos(cos_h0)

        s0 = self.solar_constant_w_m2
        q = (s0 / np.pi) * (
            h0 * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(h0)
        )
        return np.clip(q, 0.0, None)

    def _laplacian(self, field: np.ndarray) -> np.ndarray:
        north = np.roll(field, 1, axis=0)
        south = np.roll(field, -1, axis=0)
        east = np.roll(field, 1, axis=1)
        west = np.roll(field, -1, axis=1)
        return north + south + east + west - 4.0 * field

    def _saturation_vapor_pressure_pa(self, temp_k: np.ndarray) -> np.ndarray:
        temp_c = temp_k - 273.15
        es = 610.94 * np.exp((17.625 * temp_c) / np.clip(temp_c + 243.04, 1.0, None))
        return np.clip(es, 10.0, 6.0e4)

    def _saturation_specific_humidity(self, temp_k: np.ndarray, pressure_pa: np.ndarray) -> np.ndarray:
        es = self._saturation_vapor_pressure_pa(temp_k)
        qsat = 0.622 * es / np.clip(pressure_pa - 0.378 * es, 100.0, None)
        return np.clip(qsat, 1.0e-5, 0.12)

    def step(self, day_of_year: float):
        self._compute_adaptive_dt()
        self.dt = self.current_dt_s

        q_sw = self._daily_mean_insolation(day_of_year)

        local_albedo = np.clip(
            self.cfg.surface_albedo + 0.10 * (self.topography_m > 2500.0).astype(np.float64),
            0.05,
            0.82,
        )

        absorbed = q_sw * (1.0 - local_albedo)
        olr = self.cfg.emissivity * SIGMA * self.temperature_k**4 - self.cfg.greenhouse_forcing_w_m2
        net_radiation_surface = absorbed - np.clip(olr, 15.0, None)

        total_heat_capacity = self.atmospheric_column_mass_kg_m2 * self.cfg.cp_air_j_kg_k
        heat_capacity_surface = 0.65 * total_heat_capacity
        heat_capacity_lower = 0.35 * total_heat_capacity

        energy_before = (
            heat_capacity_surface * self.temperature_k + heat_capacity_lower * self.lower_atmos_temperature_k
        )

        # Two-layer coupling: exchange between surface thermal reservoir and lower atmosphere.
        exchange_coeff = 9.0e-6
        exchange_flux = exchange_coeff * (self.temperature_k - self.lower_atmos_temperature_k)

        dtemp_rad_surface = ((net_radiation_surface - exchange_flux) / heat_capacity_surface) * self.dt
        dtemp_rad_lower = (exchange_flux / heat_capacity_lower) * self.dt

        thermal_diffusion = 1.4e-2 * self._laplacian(self.temperature_k)
        lower_diffusion = 1.0e-2 * self._laplacian(self.lower_atmos_temperature_k)
        wind_speed = np.sqrt(self.u_wind_m_s**2 + self.v_wind_m_s**2)
        advective_cooling = -1.2e-5 * wind_speed * (self.temperature_k - np.mean(self.temperature_k))

        self.temperature_k += dtemp_rad_surface + thermal_diffusion + advective_cooling

        # Moisture cycle on lower layer.
        qsat = self._saturation_specific_humidity(self.lower_atmos_temperature_k, self.pressure_pa)
        rel_humidity = np.clip(self.specific_humidity / np.clip(qsat, 1e-6, None), 0.0, 2.0)

        evap_flux = 1.4e-7 * wind_speed * np.clip(qsat - self.specific_humidity, 0.0, None)
        moist_diffusion = 3.0e-2 * self._laplacian(self.specific_humidity)
        moist_advection = -7.0e-6 * wind_speed * (self.specific_humidity - np.mean(self.specific_humidity))

        self.specific_humidity += self.dt * (evap_flux + moist_diffusion + moist_advection)

        supersat = np.clip(self.specific_humidity - qsat, 0.0, None)
        cond_frac = np.clip(0.45 * supersat / np.clip(qsat, 1e-6, None), 0.0, 0.7)
        condensed_specific = cond_frac * self.specific_humidity
        self.specific_humidity -= condensed_specific

        condensed_mass_kg_m2 = condensed_specific * self.atmospheric_column_mass_kg_m2
        evap_mass_kg_m2 = np.clip(evap_flux, 0.0, None) * self.dt * self.atmospheric_column_mass_kg_m2
        phase_change_mass_kg_m2 = condensed_mass_kg_m2 - evap_mass_kg_m2

        latent_flux_w_m2 = L_V * phase_change_mass_kg_m2 / np.clip(self.dt, 1.0, None)
        latent_flux_w_m2 = np.clip(latent_flux_w_m2, -1500.0, 1500.0)
        dtemp_latent_lower = (latent_flux_w_m2 * self.dt) / heat_capacity_lower
        self.current_cumulative_latent_j_m2 += float(np.mean(latent_flux_w_m2 * self.dt))

        # Latent-energy closure metric using moisture tendency source term.
        diagnosed_phase_change_kg_m2 = np.clip(condensed_mass_kg_m2, 0.0, None) - np.clip(evap_mass_kg_m2, 0.0, None)
        diagnosed_latent_flux_w_m2 = L_V * diagnosed_phase_change_kg_m2 / np.clip(self.dt, 1.0, None)
        diagnosed_latent_flux_w_m2 = np.clip(diagnosed_latent_flux_w_m2, -1500.0, 1500.0)
        self.current_latent_flux_w_m2 = float(np.mean(latent_flux_w_m2))
        self.current_latent_residual_w_m2 = float(np.mean(latent_flux_w_m2 - diagnosed_latent_flux_w_m2))

        # Precipitation proxy from condensed water.
        precip_kg_m2_s = condensed_mass_kg_m2 / np.clip(self.dt, 1.0, None)
        self.precipitation_mm_day = np.clip(precip_kg_m2_s * 86400.0, 0.0, 500.0)

        self.cloud_fraction = np.clip(1.0 - np.exp(-2.2 * np.clip(rel_humidity - 0.55, 0.0, None)), 0.0, 1.0)

        self.lower_atmos_temperature_k += dtemp_rad_lower + lower_diffusion + dtemp_latent_lower

        # Cloud albedo feedback at end of step (moderated for calibration stability).
        cloud_cooling = self.cfg.cloud_cooling_coeff * self.cloud_fraction
        self.temperature_k -= cloud_cooling

        self.current_cumulative_energy_input_j_m2 += float(np.mean(net_radiation_surface * self.dt))

        self.temperature_k = np.clip(self.temperature_k, 170.0, 350.0)
        self.lower_atmos_temperature_k = np.clip(self.lower_atmos_temperature_k, 160.0, 340.0)
        self.specific_humidity = np.clip(self.specific_humidity, 1.0e-5, 0.08)

        self._update_pressure_density()
        self._update_winds_prognostic()
        temp_flux_abs, moist_flux_abs, moist_corr_abs = self._update_vertical_profiles()
        self.current_cumulative_moisture_correction_kg_m2 += float(
            np.mean(moist_corr_abs) * self.cfg.vertical_levels * self.atmospheric_column_mass_kg_m2
        )

        self._apply_energy_drift_guard(
            energy_before=energy_before,
            expected_radiative_flux=net_radiation_surface,
            cloud_cooling_k=cloud_cooling,
            heat_capacity_surface=heat_capacity_surface,
            heat_capacity_lower=heat_capacity_lower,
        )

        self._record_history(
            temp_flux_abs=temp_flux_abs,
            moist_flux_abs=moist_flux_abs,
            moist_corr_abs=moist_corr_abs,
        )

    def _apply_energy_drift_guard(
        self,
        energy_before: np.ndarray,
        expected_radiative_flux: np.ndarray,
        cloud_cooling_k: np.ndarray,
        heat_capacity_surface: float,
        heat_capacity_lower: float,
    ):
        total_heat_capacity = heat_capacity_surface + heat_capacity_lower

        energy_after = heat_capacity_surface * self.temperature_k + heat_capacity_lower * self.lower_atmos_temperature_k
        expected_delta = expected_radiative_flux * self.dt - cloud_cooling_k * heat_capacity_surface
        residual = energy_after - energy_before - expected_delta

        residual_w_m2 = residual / max(self.dt, 1.0)
        self.current_energy_residual_w_m2 = float(np.mean(residual_w_m2))

        # Relax residual energy toward zero with bounded temperature correction.
        relax = np.clip(self.dt / (16.0 * 3600.0), 0.0, 1.0)
        correction_j_m2 = -relax * residual
        dtemp_common = np.clip(correction_j_m2 / max(total_heat_capacity, 1.0), -1.2, 1.2)

        self.temperature_k += dtemp_common
        self.lower_atmos_temperature_k += dtemp_common
        self.current_energy_correction_k = float(np.mean(np.abs(dtemp_common)))
        self.current_cumulative_energy_correction_j_m2 += float(
            np.mean(np.abs(dtemp_common) * total_heat_capacity)
        )

        self.temperature_k = np.clip(self.temperature_k, 170.0, 350.0)
        self.lower_atmos_temperature_k = np.clip(self.lower_atmos_temperature_k, 160.0, 340.0)

    def _record_history(self, temp_flux_abs: np.ndarray, moist_flux_abs: np.ndarray, moist_corr_abs: np.ndarray):
        wind = np.sqrt(self.u_wind_m_s**2 + self.v_wind_m_s**2)
        mach = self.mach_number_field()
        reynolds = self.reynolds_number_field()

        self.history["mean_temperature_k"].append(float(np.mean(self.temperature_k)))
        self.history["mean_pressure_pa"].append(float(np.mean(self.pressure_pa)))
        self.history["mean_wind_m_s"].append(float(np.mean(wind)))
        self.history["mean_mach"].append(float(np.mean(mach)))
        self.history["mean_reynolds"].append(float(np.mean(reynolds)))
        self.history["mean_lower_temp_k"].append(float(np.mean(self.lower_atmos_temperature_k)))
        self.history["mean_specific_humidity"].append(float(np.mean(self.specific_humidity)))
        self.history["mean_cloud_fraction"].append(float(np.mean(self.cloud_fraction)))
        self.history["mean_precip_mm_day"].append(float(np.mean(self.precipitation_mm_day)))
        self.history["mean_dt_s"].append(float(self.current_dt_s))

        divergence, vorticity = self._flow_diagnostics()
        self.history["mean_abs_divergence"].append(float(np.mean(np.abs(divergence))))
        self.history["mean_abs_vorticity"].append(float(np.mean(np.abs(vorticity))))

        ri_bulk, n2 = self._stability_diagnostics()
        self.history["mean_bulk_ri"].append(float(np.mean(ri_bulk)))
        self.history["mean_brunt_vaisala_n2"].append(float(np.mean(n2)))

        du = self.u_wind_profile_m_s[min(1, self.cfg.vertical_levels - 1)] - self.u_wind_profile_m_s[0]
        dv = self.v_wind_profile_m_s[min(1, self.cfg.vertical_levels - 1)] - self.v_wind_profile_m_s[0]
        shear = np.sqrt(du * du + dv * dv) / 1400.0
        jet_speed = np.sqrt(self.u_wind_profile_m_s[-1] ** 2 + self.v_wind_profile_m_s[-1] ** 2)
        self.history["mean_vertical_shear_s_1"].append(float(np.mean(shear)))
        self.history["mean_jet_speed_m_s"].append(float(np.mean(jet_speed)))
        self.history["mean_vertical_temp_flux"].append(float(np.mean(temp_flux_abs)))
        self.history["mean_vertical_moisture_flux"].append(float(np.mean(moist_flux_abs)))
        self.current_column_moisture_correction = float(np.mean(moist_corr_abs))
        self.history["mean_column_moisture_correction"].append(self.current_column_moisture_correction)
        self.history["mean_energy_residual_w_m2"].append(self.current_energy_residual_w_m2)
        self.history["mean_energy_correction_k"].append(self.current_energy_correction_k)
        self.history["mean_latent_flux_w_m2"].append(self.current_latent_flux_w_m2)
        self.history["mean_latent_residual_w_m2"].append(self.current_latent_residual_w_m2)
        self.history["mean_vertical_velocity_m_s"].append(self.current_vertical_velocity_m_s)
        self.history["mean_hadley_index_k"].append(self.current_hadley_index_k)
        self.history["cumulative_energy_input_j_m2"].append(self.current_cumulative_energy_input_j_m2)
        self.history["cumulative_latent_j_m2"].append(self.current_cumulative_latent_j_m2)
        self.history["cumulative_energy_correction_j_m2"].append(self.current_cumulative_energy_correction_j_m2)
        self.history["cumulative_moisture_correction_kg_m2"].append(self.current_cumulative_moisture_correction_kg_m2)

    def coriolis_parameter(self) -> np.ndarray:
        return 2.0 * self.omega * np.sin(np.deg2rad(self.lat2d))

    def speed_of_sound_field(self) -> np.ndarray:
        return np.sqrt(self.cfg.gamma_air * self.r_specific * self.temperature_k)

    def mach_number_field(self) -> np.ndarray:
        wind = np.sqrt(self.u_wind_m_s**2 + self.v_wind_m_s**2)
        a = np.clip(self.speed_of_sound_field(), 40.0, None)
        return wind / a

    def reynolds_number_field(self, characteristic_length_m: float = 1.0e5) -> np.ndarray:
        wind = np.sqrt(self.u_wind_m_s**2 + self.v_wind_m_s**2)
        return (self.density_kg_m3 * wind * characteristic_length_m) / self.cfg.dyn_viscosity_pa_s

    def rossby_number_field(self, characteristic_length_m: float = 1.0e6) -> np.ndarray:
        wind = np.sqrt(self.u_wind_m_s**2 + self.v_wind_m_s**2)
        f = np.abs(self.coriolis_parameter())
        f = np.clip(f, 1.0e-5, None)
        return wind / (f * characteristic_length_m)

    def summary_metrics(self) -> Dict[str, float]:
        lapse_01 = self.temperature_profile_k[0] - self.temperature_profile_k[min(1, self.cfg.vertical_levels - 1)]
        lapse_07 = self.temperature_profile_k[0] - self.temperature_profile_k[-1]

        return {
            "gravity_m_s2": self.gravity_m_s2,
            "escape_velocity_m_s": self.escape_velocity_m_s,
            "equatorial_rotation_speed_m_s": self.equatorial_rotation_speed_m_s,
            "solar_constant_w_m2": self.solar_constant_w_m2,
            "equilibrium_temperature_k": self.equilibrium_temperature_k,
            "mean_surface_temperature_k": float(np.mean(self.temperature_k)),
            "mean_surface_pressure_pa": float(np.mean(self.pressure_pa)),
            "mean_density_kg_m3": float(np.mean(self.density_kg_m3)),
            "scale_height_m": self.scale_height_m,
            "dry_lapse_rate_k_m": self.dry_lapse_rate_k_m,
            "mean_lower_temperature_k": float(np.mean(self.lower_atmos_temperature_k)),
            "mean_specific_humidity": float(np.mean(self.specific_humidity)),
            "mean_cloud_fraction": float(np.mean(self.cloud_fraction)),
            "mean_precip_mm_day": float(np.mean(self.precipitation_mm_day)),
            "mean_vertical_lapse_01_k": float(np.mean(lapse_01)),
            "mean_vertical_lapse_full_k": float(np.mean(lapse_07)),
            "mean_upper_temperature_k": float(np.mean(self.temperature_profile_k[-1])),
            "mean_upper_specific_humidity": float(np.mean(self.humidity_profile[-1])),
            "mean_dt_s": float(np.mean(self.current_dt_s)),
            "mean_wind_m_s": float(np.mean(np.sqrt(self.u_wind_m_s**2 + self.v_wind_m_s**2))),
            "mean_mach": float(np.mean(self.mach_number_field())),
            "mean_reynolds": float(np.mean(self.reynolds_number_field())),
            "mean_rossby": float(np.mean(self.rossby_number_field())),
            "mean_abs_divergence": float(np.mean(np.abs(self._flow_diagnostics()[0]))),
            "mean_abs_vorticity": float(np.mean(np.abs(self._flow_diagnostics()[1]))),
            "mean_bulk_ri": float(np.mean(self._stability_diagnostics()[0])),
            "mean_brunt_vaisala_n2": float(np.mean(self._stability_diagnostics()[1])),
            "mean_vertical_shear_s_1": float(np.mean(np.sqrt(
                (self.u_wind_profile_m_s[min(1, self.cfg.vertical_levels - 1)] - self.u_wind_profile_m_s[0]) ** 2
                + (self.v_wind_profile_m_s[min(1, self.cfg.vertical_levels - 1)] - self.v_wind_profile_m_s[0]) ** 2
            ) / 1400.0)),
            "mean_jet_speed_m_s": float(np.mean(np.sqrt(self.u_wind_profile_m_s[-1] ** 2 + self.v_wind_profile_m_s[-1] ** 2))),
            "mean_vertical_temp_flux": float(np.mean(np.abs(np.gradient(self.temperature_profile_k, axis=0)))),
            "mean_vertical_moisture_flux": float(np.mean(np.abs(np.gradient(self.humidity_profile, axis=0)))),
            "mean_column_moisture_correction": float(self.current_column_moisture_correction),
            "mean_energy_residual_w_m2": float(self.current_energy_residual_w_m2),
            "mean_energy_correction_k": float(self.current_energy_correction_k),
            "mean_latent_flux_w_m2": float(self.current_latent_flux_w_m2),
            "mean_latent_residual_w_m2": float(self.current_latent_residual_w_m2),
            "mean_vertical_velocity_m_s": float(self.current_vertical_velocity_m_s),
            "mean_hadley_index_k": float(self.current_hadley_index_k),
            "cumulative_energy_input_j_m2": float(self.current_cumulative_energy_input_j_m2),
            "cumulative_latent_j_m2": float(self.current_cumulative_latent_j_m2),
            "cumulative_energy_correction_j_m2": float(self.current_cumulative_energy_correction_j_m2),
            "cumulative_moisture_correction_kg_m2": float(self.current_cumulative_moisture_correction_kg_m2),
        }
