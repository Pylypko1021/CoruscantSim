# Coruscant Physics-First Roadmap

## Scope Now

Current focus is strictly planetary physics and aerophysics. Ecosystems, biology, and civilization are intentionally out of scope for this stage.

## Stage A - Planet Construction (Implemented)

Implemented in `planet_physics.py`:

- Planetary constants and configuration.
- Gravity, escape velocity, scale height, lapse rate.
- Latitude-longitude global grid.
- Topography initialization.
- Hydrostatic pressure and density fields.
- Radiative forcing and greenhouse correction.
- Coriolis-aware geostrophic wind approximation.
- Aerophysics diagnostics: Mach, Reynolds, Rossby-like numbers.

## Stage B - Numerical Fidelity (Next)

1. Upgrade from simple energy-balance tendency to two-layer atmosphere (surface + lower troposphere).
2. Replace isotropic diffusion with latitude-aware and pressure-aware diffusion tensors.
3. Add explicit moisture transport and latent heat release (still without ecosystem coupling).
4. Add cloud fraction parameterization linked to humidity and vertical velocity proxy.

## Stage C - Aerophysics Deepening

1. Boundary layer parameterization with Monin-Obukhov style stability classes.
2. Drag law refinement by roughness classes (urban megastructure vs open surfaces).
3. Jet and storm-track diagnostics by latitude bands.
4. Turbulence proxies (TKE-like index) and shear instability markers.

## Stage D - Validation and Verification

1. Numerical sanity checks:
   - temperature boundedness,
   - pressure positivity,
   - CFL-like stability criteria.
2. Regression suite on key global diagnostics.
3. Scenario tests:
   - high greenhouse forcing,
   - rapid rotation,
   - low atmosphere mass,
   - high albedo.

## Stage E - Visualization and Analysis

1. Diagnostic dashboard for maps + time series.
2. Multi-scenario comparison report generation (baseline vs stress scenarios).
3. Export pipeline to analysis-ready outputs (Parquet/Zarr planned).

## Success Criteria for Physics Stage

- Stable multi-hundred-day integrations without numerical blowup.
- Physically plausible directional behavior for key perturbations:
  - higher forcing -> higher mean temperature,
  - lower atmosphere mass -> lower mean pressure,
  - faster rotation -> lower Rossby number.
- Reproducible outputs with fixed seeds.
