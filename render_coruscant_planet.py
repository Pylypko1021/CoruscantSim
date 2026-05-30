from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import animation
from matplotlib.colors import hsv_to_rgb


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Coruscant as a realistic 3D planet from physics fields.")
    parser.add_argument("--fields", default="CoruscantSim/output/final_fields.npz", help="Path to NPZ diagnostics")
    parser.add_argument("--out-image", default="CoruscantSim/output/coruscant_planet.png", help="Output PNG path")
    parser.add_argument("--out-gif", default="CoruscantSim/output/coruscant_planet.gif", help="Output GIF path")
    parser.add_argument("--make-gif", action="store_true", help="Also render rotating GIF")
    parser.add_argument("--frames", type=int, default=120, help="Number of animation frames")
    parser.add_argument("--fps", type=int, default=24, help="Frames per second for GIF")
    parser.add_argument("--dpi", type=int, default=170, help="Render DPI")
    parser.add_argument("--texture-scale", type=int, default=4, help="Upscale factor for smoother texture mapping")
    parser.add_argument("--smooth-iterations", type=int, default=2, help="Smoothing passes after upscaling")
    parser.add_argument("--daymap", default=None, help="Optional equirectangular day texture image (PNG/JPG)")
    parser.add_argument("--nightmap", default=None, help="Optional equirectangular night lights texture image")
    parser.add_argument("--cloudmap", default=None, help="Optional equirectangular cloud texture image")
    parser.add_argument("--texture-blend", type=float, default=0.78, help="Blend ratio of external daymap over procedural base")
    parser.add_argument("--orbits", type=int, default=14, help="How many satellite orbit tracks to overlay")
    parser.add_argument("--mesh-step", type=int, default=2, help="Decimation step for 3D surface mesh (higher = faster)")
    parser.add_argument("--realtime", action="store_true", help="Open interactive real-time rotating planet window")
    parser.add_argument("--realtime-fps", type=int, default=30, help="Target FPS for real-time mode")
    return parser.parse_args()


def normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    x_min = float(np.min(x))
    x_max = float(np.max(x))
    if x_max - x_min < eps:
        return np.zeros_like(x)
    return (x - x_min) / (x_max - x_min)


def smooth_wrap(x: np.ndarray, iterations: int) -> np.ndarray:
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


def upsample_field(x: np.ndarray, scale: int, smooth_iterations: int) -> np.ndarray:
    scale = max(1, int(scale))
    if scale == 1:
        return smooth_wrap(x, smooth_iterations)
    up = np.repeat(np.repeat(x, scale, axis=0), scale, axis=1)
    return smooth_wrap(up, smooth_iterations)


def _read_rgb_image(path: Path) -> np.ndarray:
    arr = np.array(plt.imread(path), dtype=float)
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=2)
    if arr.shape[2] == 4:
        arr = arr[..., :3]
    if arr.max() > 1.0:
        arr = arr / 255.0
    return np.clip(arr, 0.0, 1.0)


def resample_equirect_rgb(img: np.ndarray, n_lat: int, n_lon: int) -> np.ndarray:
    h, w, _ = img.shape
    yi = np.linspace(0, h - 1, n_lat).astype(int)
    xi = np.linspace(0, w - 1, n_lon, endpoint=False).astype(int)
    return img[np.ix_(yi, xi)]


def build_base_texture(fields: dict[str, np.ndarray]) -> np.ndarray:
    temp = fields["temperature_k"]
    cloud = fields["cloud_fraction"]
    precip = fields["precipitation_mm_day"]

    t_norm = normalize(temp)
    c_norm = np.clip(cloud, 0.0, 1.0)
    p_norm = normalize(precip)

    # Coruscant-inspired color direction: warm urban metal + atmospheric cyan highlights.
    hue = 0.10 + 0.08 * (1.0 - t_norm) + 0.03 * p_norm
    sat = np.clip(0.36 + 0.25 * p_norm + 0.12 * c_norm, 0.0, 1.0)
    val = np.clip(0.40 + 0.45 * t_norm + 0.15 * (1.0 - c_norm), 0.0, 1.0)

    hsv = np.stack([hue, sat, val], axis=-1)
    rgb = hsv_to_rgb(hsv)

    # Add subtle district-like variation to avoid flat gradients.
    n_lat, n_lon = temp.shape
    lon_wave = np.sin(np.linspace(0.0, 8.0 * np.pi, n_lon))[None, :]
    lat_wave = np.cos(np.linspace(-2.0 * np.pi, 2.0 * np.pi, n_lat))[:, None]
    district = 0.035 * lon_wave + 0.02 * lat_wave
    rgb = np.clip(rgb * (1.0 + district[..., None]), 0.0, 1.0)
    return rgb


def build_cloud_texture(fields: dict[str, np.ndarray]) -> np.ndarray:
    cloud = np.clip(fields["cloud_fraction"], 0.0, 1.0)
    precip = normalize(fields["precipitation_mm_day"])

    alpha = np.clip(0.05 + 0.55 * cloud + 0.25 * precip, 0.0, 0.86)
    rgb = np.stack(
        [
            np.clip(0.82 + 0.18 * cloud, 0.0, 1.0),
            np.clip(0.86 + 0.14 * cloud, 0.0, 1.0),
            np.clip(0.92 + 0.08 * cloud, 0.0, 1.0),
            alpha,
        ],
        axis=-1,
    )
    return rgb


def build_city_lights(fields: dict[str, np.ndarray]) -> np.ndarray:
    temp = fields["temperature_k"]
    pressure = fields["pressure_pa"]
    humidity = fields["specific_humidity"]

    # Proxy: denser/stable regions + warmer surfaces correlate with brighter urban activity.
    t_norm = normalize(temp)
    p_norm = normalize(pressure)
    h_norm = normalize(humidity)

    activity = np.clip(0.65 * t_norm + 0.35 * p_norm - 0.20 * h_norm, 0.0, 1.0)
    gamma = activity**1.8

    lights = np.stack(
        [
            np.clip(1.20 * gamma, 0.0, 1.0),
            np.clip(0.95 * gamma, 0.0, 1.0),
            np.clip(0.65 * gamma, 0.0, 1.0),
        ],
        axis=-1,
    )
    return lights


def build_orbit_tracks(n_orbits: int, n_points: int = 360) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    rng = np.random.default_rng(29)
    tracks: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    if n_orbits <= 0:
        return tracks

    t = np.linspace(0.0, 2.0 * np.pi, n_points)
    circle = np.stack([np.cos(t), np.sin(t), np.zeros_like(t)], axis=0)

    for _ in range(n_orbits):
        r = rng.uniform(1.08, 1.30)
        inc = rng.uniform(0.0, np.pi)
        raan = rng.uniform(0.0, 2.0 * np.pi)

        ci, si = np.cos(inc), np.sin(inc)
        cr, sr = np.cos(raan), np.sin(raan)

        rot_x = np.array([[1, 0, 0], [0, ci, -si], [0, si, ci]], dtype=float)
        rot_z = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], dtype=float)

        pts = r * (rot_z @ (rot_x @ circle))
        tracks.append((pts[0], pts[1], pts[2]))

    return tracks


def sphere_geometry(n_lat: int, n_lon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    lats = np.linspace(-0.5 * np.pi, 0.5 * np.pi, n_lat)
    lons = np.linspace(0.0, 2.0 * np.pi, n_lon, endpoint=False)
    lat2, lon2 = np.meshgrid(lats, lons, indexing="ij")

    x = np.cos(lat2) * np.cos(lon2)
    y = np.cos(lat2) * np.sin(lon2)
    z = np.sin(lat2)
    return x, y, z, lat2, lon2


def lit_texture(
    base_rgb: np.ndarray,
    city_lights: np.ndarray,
    normals: tuple[np.ndarray, np.ndarray, np.ndarray],
    sun_dir: np.ndarray,
) -> np.ndarray:
    x, y, z = normals
    lambert = np.clip(x * sun_dir[0] + y * sun_dir[1] + z * sun_dir[2], 0.0, 1.0)

    day = base_rgb * (0.18 + 0.82 * lambert[..., None])
    night_mask = np.clip(1.0 - lambert, 0.0, 1.0) ** 1.45
    night = city_lights * (0.03 + 0.90 * night_mask[..., None])

    rim = (1.0 - np.clip(np.abs(z), 0.0, 1.0)) ** 2
    atmosphere_tint = np.stack([0.08 * rim, 0.15 * rim, 0.24 * rim], axis=-1)

    rgb = np.clip(day + night + atmosphere_tint, 0.0, 1.0)
    return rgb


def render_scene(
    out_image: Path,
    out_gif: Path,
    make_gif: bool,
    realtime: bool,
    realtime_fps: int,
    frames: int,
    fps: int,
    dpi: int,
    base_rgb: np.ndarray,
    cloud_rgba: np.ndarray,
    city_lights: np.ndarray,
    geometry: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    orbit_tracks: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    mesh_step: int,
) -> None:
    x, y, z, _, _ = geometry

    fig = plt.figure(figsize=(8.6, 8.6), facecolor="#060b1a")
    ax = fig.add_subplot(111, projection="3d", facecolor="#060b1a")

    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.35, 1.35)
    ax.set_zlim(-1.35, 1.35)
    ax.set_axis_off()
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=20.0, azim=35.0)

    # Faint star-like background points for depth.
    rng = np.random.default_rng(7)
    stars = rng.uniform(-1.8, 1.8, size=(800, 3))
    far = np.linalg.norm(stars, axis=1) > 1.3
    stars = stars[far]
    ax.scatter(stars[:, 0], stars[:, 1], stars[:, 2], s=0.4, c="#9cb4ff", alpha=0.18)

    sun_angle0 = np.deg2rad(24.0)
    sun_dir0 = np.array([np.cos(sun_angle0), np.sin(sun_angle0), 0.22], dtype=float)
    sun_dir0 = sun_dir0 / np.linalg.norm(sun_dir0)

    cloud_shell = 1.012

    # Atmosphere glow shell.
    glow = np.zeros((*x.shape, 4), dtype=float)
    rim = (1.0 - np.abs(z)) ** 1.8
    glow[..., 0] = 0.10 * rim
    glow[..., 1] = 0.24 * rim
    glow[..., 2] = 0.48 * rim
    glow[..., 3] = 0.09 + 0.10 * rim

    atmo_shell = 1.04
    step = max(1, int(mesh_step))
    xs = x[::step, ::step]
    ys = y[::step, ::step]
    zs = z[::step, ::step]

    cloud_shell = 1.012
    atmo_shell = 1.04

    def draw_frame(frame_idx: int, total_frames: int):
        for coll in list(ax.collections):
            coll.remove()
        for ln in list(ax.lines):
            ln.remove()
        ax.scatter(stars[:, 0], stars[:, 1], stars[:, 2], s=0.4, c="#9cb4ff", alpha=0.18)

        for ox, oy, oz in orbit_tracks:
            ax.plot(ox, oy, oz, color="#e6ecff", alpha=0.22, linewidth=0.8)

        phase = 2.0 * np.pi * (frame_idx / max(1, total_frames))
        sun_dir = np.array([np.cos(sun_angle0 + phase), np.sin(sun_angle0 + phase), 0.22], dtype=float)
        sun_dir /= np.linalg.norm(sun_dir)

        surface_rgb = lit_texture(base_rgb, city_lights, (x, y, z), sun_dir)

        surf_rgb = surface_rgb[::step, ::step]
        cloud_rgba_ds = cloud_rgba[::step, ::step]
        glow_ds = glow[::step, ::step]

        ax.plot_surface(
            xs,
            ys,
            zs,
            rstride=1,
            cstride=1,
            facecolors=surf_rgb,
            linewidth=0.0,
            antialiased=False,
            shade=False,
        )
        ax.plot_surface(
            cloud_shell * xs,
            cloud_shell * ys,
            cloud_shell * zs,
            rstride=1,
            cstride=1,
            facecolors=cloud_rgba_ds,
            linewidth=0.0,
            antialiased=True,
            shade=False,
        )
        ax.plot_surface(
            atmo_shell * xs,
            atmo_shell * ys,
            atmo_shell * zs,
            rstride=1,
            cstride=1,
            facecolors=glow_ds,
            linewidth=0.0,
            antialiased=True,
            shade=False,
        )

        ax.view_init(elev=20.0, azim=35.0 + 360.0 * frame_idx / max(1, total_frames))

    draw_frame(0, max(1, frames))

    fig.tight_layout(pad=0.0)
    out_image.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_image, dpi=dpi, facecolor=fig.get_facecolor())
    print(f"render_ok image={out_image}")

    if realtime:
        interval_ms = max(10, int(round(1000.0 / max(1, realtime_fps))))

        def rt_update(frame_idx: int):
            draw_frame(frame_idx, max(1, frames))
            return []

        anim = animation.FuncAnimation(
            fig,
            rt_update,
            frames=None,
            interval=interval_ms,
            blit=False,
            repeat=True,
        )
        fig._realtime_anim = anim
        print("render_live start=ok close_window_to_stop=true")
        plt.show()
        plt.close(fig)
        return

    if not make_gif:
        plt.close(fig)
        return

    def update(frame_idx: int):
        draw_frame(frame_idx, max(1, frames))
        return []

    anim = animation.FuncAnimation(fig, update, frames=frames, interval=1000.0 / fps, blit=False)
    out_gif.parent.mkdir(parents=True, exist_ok=True)

    try:
        writer = animation.PillowWriter(fps=fps)
        anim.save(out_gif, writer=writer, dpi=dpi)
        print(f"render_ok gif={out_gif}")
    except Exception as exc:  # pragma: no cover
        print(f"render_warn gif_failed={exc}")

    plt.close(fig)


def main() -> int:
    args = parse_args()

    fields_path = Path(args.fields)
    if not fields_path.is_absolute():
        fields_path = Path.cwd() / fields_path
    if not fields_path.exists():
        print(f"render_error missing_fields={fields_path}")
        return 2

    npz = np.load(fields_path)
    required = [
        "temperature_k",
        "pressure_pa",
        "specific_humidity",
        "cloud_fraction",
        "precipitation_mm_day",
    ]
    for key in required:
        if key not in npz:
            print(f"render_error missing_key={key}")
            return 2

    raw_fields = {k: np.array(npz[k]) for k in npz.files}

    fields: dict[str, np.ndarray] = {}
    for k in required:
        fields[k] = upsample_field(raw_fields[k], scale=args.texture_scale, smooth_iterations=args.smooth_iterations)

    n_lat, n_lon = fields["temperature_k"].shape

    base_rgb = build_base_texture(fields)
    cloud_rgba = build_cloud_texture(fields)
    city_lights = build_city_lights(fields)

    n_lat, n_lon = base_rgb.shape[:2]

    if args.daymap:
        day_path = Path(args.daymap)
        if not day_path.is_absolute():
            day_path = Path.cwd() / day_path
        if day_path.exists():
            day_img = _read_rgb_image(day_path)
            day_resampled = resample_equirect_rgb(day_img, n_lat=n_lat, n_lon=n_lon)
            blend = np.clip(args.texture_blend, 0.0, 1.0)
            base_rgb = np.clip((1.0 - blend) * base_rgb + blend * day_resampled, 0.0, 1.0)
        else:
            print(f"render_warn missing_daymap={day_path}")

    if args.nightmap:
        night_path = Path(args.nightmap)
        if not night_path.is_absolute():
            night_path = Path.cwd() / night_path
        if night_path.exists():
            night_img = _read_rgb_image(night_path)
            city_lights = np.clip(resample_equirect_rgb(night_img, n_lat=n_lat, n_lon=n_lon), 0.0, 1.0)
        else:
            print(f"render_warn missing_nightmap={night_path}")

    if args.cloudmap:
        cloud_path = Path(args.cloudmap)
        if not cloud_path.is_absolute():
            cloud_path = Path.cwd() / cloud_path
        if cloud_path.exists():
            cloud_img = _read_rgb_image(cloud_path)
            cloud_rgb = resample_equirect_rgb(cloud_img, n_lat=n_lat, n_lon=n_lon)
            cloud_strength = np.clip(np.mean(cloud_rgb, axis=2), 0.0, 1.0)
            cloud_rgba[..., :3] = np.clip(0.78 + 0.25 * cloud_rgb, 0.0, 1.0)
            cloud_rgba[..., 3] = np.clip(0.05 + 0.82 * cloud_strength, 0.0, 0.92)
        else:
            print(f"render_warn missing_cloudmap={cloud_path}")

    orbit_tracks = build_orbit_tracks(max(0, args.orbits), n_points=420)
    geometry = sphere_geometry(n_lat=n_lat, n_lon=n_lon)

    out_image = Path(args.out_image)
    if not out_image.is_absolute():
        out_image = Path.cwd() / out_image
    out_gif = Path(args.out_gif)
    if not out_gif.is_absolute():
        out_gif = Path.cwd() / out_gif

    render_scene(
        out_image=out_image,
        out_gif=out_gif,
        make_gif=args.make_gif,
        realtime=args.realtime,
        realtime_fps=args.realtime_fps,
        frames=args.frames,
        fps=args.fps,
        dpi=args.dpi,
        base_rgb=base_rgb,
        cloud_rgba=cloud_rgba,
        city_lights=city_lights,
        geometry=geometry,
        orbit_tracks=orbit_tracks,
        mesh_step=args.mesh_step,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
