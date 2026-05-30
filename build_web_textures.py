from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import hsv_to_rgb
from scipy.ndimage import zoom as ndimage_zoom, gaussian_filter


def normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    x_min = float(np.min(x))
    x_max = float(np.max(x))
    if x_max - x_min < eps:
        return np.zeros_like(x)
    return (x - x_min) / (x_max - x_min)


def smooth_wrap(x: np.ndarray, iterations: int = 1) -> np.ndarray:
    y = np.array(x, dtype=float, copy=True)
    for _ in range(max(0, iterations)):
        y = (
            4.0 * y
            + np.roll(y, 1, axis=0)
            + np.roll(y, -1, axis=0)
            + np.roll(y, 1, axis=1)
            + np.roll(y, -1, axis=1)
        ) / 8.0
    return y


def upsample(x: np.ndarray, scale: int = 2) -> np.ndarray:
    if scale <= 1:
        return x
    # Cubic interpolation yields smoother gradients for high-res texture exports.
    return ndimage_zoom(x, scale, order=3)


def make_noise_octaves(
    shape: tuple,
    octaves: int = 6,
    persistence: float = 0.58,
    lacunarity: float = 2.0,
    seed: int = 42,
) -> np.ndarray:
    """Fractal value-noise (no regular tiling artifacts), returns float32 in [0, 1]."""
    rng = np.random.default_rng(seed)
    h, w = shape

    result = np.zeros((h, w), dtype=np.float64)
    amp = 1.0
    base = 4.0
    total_amp = 0.0

    for oi in range(octaves):
        f = base * (lacunarity ** oi)
        gh = max(4, int(np.ceil(h / f)) + 3)
        gw = max(4, int(np.ceil(w / f)) + 3)
        grid = rng.random((gh, gw))
        layer = ndimage_zoom(grid, (h / gh, w / gw), order=3)
        layer = layer[:h, :w]
        layer = gaussian_filter(layer, sigma=max(0.2, 0.6 * (octaves - oi)))
        result += amp * layer
        total_amp += amp
        amp *= persistence

    n = result / total_amp
    return normalize(n).astype(np.float32)


def smooth_wrap_gaussian(x: np.ndarray, sigma_lat: float, sigma_lon: float) -> np.ndarray:
    return gaussian_filter(x, sigma=(sigma_lat, sigma_lon), mode=("nearest", "wrap"))


def make_day_texture(temp: np.ndarray, cloud: np.ndarray, precip: np.ndarray) -> np.ndarray:
    t = normalize(temp)
    c = np.clip(cloud, 0.0, 1.0)
    n_lat, n_lon = temp.shape

    noise_large = make_noise_octaves((n_lat, n_lon), octaves=5, persistence=0.64, lacunarity=1.92, seed=7)
    noise_fine  = make_noise_octaves((n_lat, n_lon), octaves=8, persistence=0.48, lacunarity=2.25, seed=13)
    noise_city  = make_noise_octaves((n_lat, n_lon), octaves=9, persistence=0.55, lacunarity=2.40, seed=31)
    streak_large = normalize(smooth_wrap_gaussian(noise_large, sigma_lat=1.8, sigma_lon=11.0))
    streak_fine  = normalize(smooth_wrap_gaussian(noise_fine,  sigma_lat=0.8, sigma_lon=5.5))
    warp_field   = normalize(smooth_wrap_gaussian(noise_large, sigma_lat=2.4, sigma_lon=18.0))
    # City block noise: high-contrast for canyon depth
    city_block   = normalize(smooth_wrap_gaussian(noise_city,  sigma_lat=0.5, sigma_lon=2.0))

    lat_abs    = np.abs(np.linspace(-1.0, 1.0, n_lat))[:, None]
    lat_signed = np.linspace(-1.0, 1.0, n_lat)[:, None]

    band_warp = lat_signed * 11.0 * np.pi + (warp_field - 0.5) * 4.2 + (streak_fine - 0.5) * 1.1
    bands = 0.5 + 0.5 * np.sin(band_warp)
    belts = normalize(0.65 * bands + 0.35 * streak_large)

    # Rust-brown urban canyon palette (closer to Mars/corroded steel)
    hue = np.clip(0.018 + 0.022 * t + 0.025 * belts, 0.005, 0.085)
    sat = np.clip(0.42 + 0.15 * t - 0.20 * lat_abs ** 2 + 0.12 * belts - 0.12 * c, 0.10, 0.75)

    # City blocks: dark canyons (low val) vs bright megastructure tops (high val)
    # city_block high = megastructure top (bright); low = canyon floor (dark)
    canyon_mask = city_block ** 1.8          # push lows toward 0
    val = np.clip(
        0.06                                  # dark canyon baseline
        + 0.52 * canyon_mask                  # main contrast from city blocks
        + 0.22 * belts                        # large-scale zone variation
        + 0.14 * t                            # thermal — hotter = more active/lit
        + 0.08 * streak_fine
        - 0.14 * c,                           # clouds shadow the surface
        0.02, 0.97,
    )

    rgb = hsv_to_rgb(np.stack([hue, sat, val], axis=-1))
    # Strong S-curve contrast: makes canyons very dark, tops very bright
    rgb = np.power(np.clip(rgb, 1e-6, 1.0), 1.35)
    rgb = np.clip((rgb - 0.5) * 1.70 + 0.5, 0.0, 1.0)

    # Fine city-grid overlay
    lat_grid = 0.5 + 0.5 * np.abs(np.sin(np.linspace(0, n_lat * np.pi * 10, n_lat)))[:, None]
    lon_grid = 0.5 + 0.5 * np.abs(np.sin(np.linspace(0, n_lon * np.pi * 14, n_lon)))[None, :]
    grid_overlay = 1.0 + 0.10 * (lat_grid * lon_grid)
    rgb = np.clip(rgb * grid_overlay[..., None], 0.0, 1.0)

    return rgb.astype(np.float32)


def make_detail_texture(temp: np.ndarray, pressure: np.ndarray, humidity: np.ndarray) -> np.ndarray:
    n_lat, n_lon = temp.shape
    base = make_noise_octaves((n_lat, n_lon), octaves=8, persistence=0.47, lacunarity=2.3, seed=123)
    streak = normalize(smooth_wrap_gaussian(base, sigma_lat=0.55, sigma_lon=4.0))
    pressure_n = normalize(pressure)
    humidity_n = normalize(humidity)
    detail = np.clip(0.45 * streak + 0.22 * pressure_n - 0.10 * humidity_n, 0.0, 1.0)
    detail = gaussian_filter(detail, sigma=0.8)
    detail = np.power(detail, 1.15)
    # Keep the map centered around mid-gray so it only adds subtle modulation.
    detail = np.clip(0.5 + (detail - 0.5) * 0.42, 0.0, 1.0)
    rgb = np.stack([detail, detail, detail], axis=-1)
    return rgb.astype(np.float32)


def make_specular_texture(temp: np.ndarray, pressure: np.ndarray, humidity: np.ndarray) -> np.ndarray:
    """Specular (shininess) map: high pressure + high temp = glassy city canopy, high humidity = wet floors."""
    t = normalize(temp)
    p = normalize(pressure)
    h = normalize(humidity)

    # Dense city zones are very reflective (glass canopy, energy shields)
    city_gloss = np.clip(0.55 * t + 0.35 * p - 0.15 * h, 0.0, 1.0) ** 1.4

    # Smooth the gloss map to avoid sharp block edges
    city_gloss = gaussian_filter(city_gloss, sigma=2.5)

    spec = np.clip(city_gloss, 0.0, 1.0)
    rgb = np.stack([spec, spec, spec], axis=-1)
    return rgb.astype(np.float32)


def make_bump_texture(temp: np.ndarray, pressure: np.ndarray, humidity: np.ndarray) -> np.ndarray:
    """Heightmap for bumpMap: physics base + multi-octave noise for surface depth."""
    t = normalize(temp)
    p = normalize(pressure)
    h = normalize(humidity)
    n_lat, n_lon = temp.shape

    phys = np.clip(0.5 * t + 0.4 * p - 0.1 * h, 0.0, 1.0)
    noise_med = normalize(smooth_wrap_gaussian(make_noise_octaves((n_lat, n_lon), octaves=6, persistence=0.55, lacunarity=2.10, seed=77), sigma_lat=1.4, sigma_lon=8.0))
    noise_fine = normalize(smooth_wrap_gaussian(make_noise_octaves((n_lat, n_lon), octaves=9, persistence=0.42, lacunarity=2.50, seed=99), sigma_lat=0.7, sigma_lon=3.0))

    bump = np.clip(0.66 * phys + 0.22 * noise_med + 0.12 * noise_fine, 0.0, 1.0)
    bump = gaussian_filter(bump, sigma=1.1)
    bump = np.power(bump, 0.95)
    rgb = np.stack([bump, bump, bump], axis=-1)
    return rgb.astype(np.float32)


def make_normal_texture(bump: np.ndarray, strength: float = 3.6) -> np.ndarray:
    """Build tangent-space normal map from grayscale bump map."""
    h = bump[..., 0]
    dy, dx = np.gradient(h)
    nx = -dx * strength
    ny = -dy * strength
    nz = np.ones_like(h)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-12
    nx /= norm
    ny /= norm
    nz /= norm
    normal = np.stack([(nx * 0.5 + 0.5), (ny * 0.5 + 0.5), (nz * 0.5 + 0.5)], axis=-1)
    return normal.astype(np.float32)


def make_night_texture(temp: np.ndarray, pressure: np.ndarray, humidity: np.ndarray) -> np.ndarray:
    """Night city lights for AdditiveBlending — must be MOSTLY BLACK with bright hotspots.
    Use percentile thresholding so only the densest city cores light up."""
    t = normalize(temp)
    p = normalize(pressure)
    h = normalize(humidity)

    activity_raw = np.clip(0.62 * t + 0.36 * p - 0.16 * h, 0.0, 1.0)

    # Only top 5% of values produce any light; rest is pure black
    thresh = float(np.percentile(activity_raw, 95))
    above = np.clip(activity_raw - thresh, 0.0, None)
    span = (activity_raw.max() - thresh) + 1e-8
    activity = np.clip(above / span, 0.0, 1.0) ** 2.0

    # Warm white-yellow city lights (no blue — looks unnatural for a megacity)
    r = np.clip(1.00 * activity, 0.0, 1.0)
    g = np.clip(0.85 * activity, 0.0, 1.0)
    b = np.clip(0.50 * activity, 0.0, 1.0)

    lights = np.stack([r, g, b], axis=-1)

    peak = float(np.max(lights))
    if peak > 0.01:
        lights = lights * (0.90 / peak)

    return lights.astype(np.float32)


def make_cloud_texture(cloud: np.ndarray, precip: np.ndarray) -> np.ndarray:
    c = np.clip(cloud, 0.0, 1.0)
    p = normalize(precip)
    n_lat, n_lon = cloud.shape

    # Build soft cloud systems from smoothed physics fields plus low-frequency streaks.
    c_soft = normalize(smooth_wrap_gaussian(c, sigma_lat=2.8, sigma_lon=10.0))
    p_soft = normalize(smooth_wrap_gaussian(p, sigma_lat=2.2, sigma_lon=8.0))
    cloud_noise = make_noise_octaves((n_lat, n_lon), octaves=5, persistence=0.56, lacunarity=1.9, seed=211)
    cloud_streak = normalize(smooth_wrap_gaussian(cloud_noise, sigma_lat=1.6, sigma_lon=12.0))

    coverage = np.clip(0.58 * c_soft + 0.22 * p_soft + 0.20 * cloud_streak, 0.0, 1.0)
    coverage = gaussian_filter(coverage, sigma=1.4)
    # Push most pixels toward clear sky and keep only thicker systems visible.
    alpha = np.clip((coverage - 0.52) * 1.35, 0.0, 0.42)

    brightness = np.clip(0.78 + 0.15 * coverage, 0.0, 1.0)
    rgb = np.stack(
        [
            np.clip(brightness * 0.96, 0.0, 1.0),
            np.clip(brightness * 0.99, 0.0, 1.0),
            np.clip(brightness * 1.04, 0.0, 1.0),
            alpha,
        ],
        axis=-1,
    )
    return rgb.astype(np.float32)


def save_png(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(path, np.clip(arr, 0.0, 1.0))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build web textures for Coruscant Three.js viewer")
    parser.add_argument("--fields", default="CoruscantSim/output/final_fields.npz")
    parser.add_argument("--out-dir", default="CoruscantSim/web_viewer/data")
    parser.add_argument("--scale", type=int, default=3, help="Texture upscale factor")
    args = parser.parse_args()

    fields_path = Path(args.fields)
    if not fields_path.is_absolute():
        fields_path = Path.cwd() / fields_path

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir

    if not fields_path.exists():
        print(f"texture_error missing_fields={fields_path}")
        return 2

    npz = np.load(fields_path)
    required = ["temperature_k", "pressure_pa", "specific_humidity", "cloud_fraction", "precipitation_mm_day"]
    for key in required:
        if key not in npz:
            print(f"texture_error missing_key={key}")
            return 2

    temp = smooth_wrap(upsample(np.array(npz["temperature_k"]), args.scale), 2)
    pressure = smooth_wrap(upsample(np.array(npz["pressure_pa"]), args.scale), 2)
    humidity = smooth_wrap(upsample(np.array(npz["specific_humidity"]), args.scale), 2)
    cloud = smooth_wrap(upsample(np.array(npz["cloud_fraction"]), args.scale), 2)
    precip = smooth_wrap(upsample(np.array(npz["precipitation_mm_day"]), args.scale), 2)

    day = make_day_texture(temp, cloud, precip)
    night = make_night_texture(temp, pressure, humidity)
    clouds = make_cloud_texture(cloud, precip)
    specular = make_specular_texture(temp, pressure, humidity)
    bump = make_bump_texture(temp, pressure, humidity)
    normal = make_normal_texture(bump, strength=4.0)
    detail = make_detail_texture(temp, pressure, humidity)

    day_path = out_dir / "daymap.png"
    night_path = out_dir / "nightmap.png"
    cloud_path = out_dir / "cloudmap.png"
    spec_path = out_dir / "specularmap.png"
    bump_path = out_dir / "bumpmap.png"
    detail_path = out_dir / "detailmap.png"
    normal_path = out_dir / "normalmap.png"
    metrics_path = out_dir / "metrics.json"

    save_png(day_path, day)
    save_png(night_path, night)
    save_png(cloud_path, clouds)
    save_png(spec_path, specular)
    save_png(bump_path, bump)
    save_png(detail_path, detail)
    save_png(normal_path, normal)

    metrics = {
        "resolution": {"lat": int(temp.shape[0]), "lon": int(temp.shape[1])},
        "temperature_k": {"min": float(np.min(temp)), "max": float(np.max(temp)), "mean": float(np.mean(temp))},
        "pressure_pa": {"min": float(np.min(pressure)), "max": float(np.max(pressure)), "mean": float(np.mean(pressure))},
        "cloud_fraction": {"min": float(np.min(cloud)), "max": float(np.max(cloud)), "mean": float(np.mean(cloud))},
        "precipitation_mm_day": {
            "min": float(np.min(precip)),
            "max": float(np.max(precip)),
            "mean": float(np.mean(precip)),
        },
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"texture_ok day={day_path}")
    print(f"texture_ok night={night_path}")
    print(f"texture_ok cloud={cloud_path}")
    print(f"texture_ok specular={spec_path}")
    print(f"texture_ok bump={bump_path}")
    print(f"texture_ok detail={detail_path}")
    print(f"texture_ok normal={normal_path}")
    print(f"texture_ok metrics={metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
