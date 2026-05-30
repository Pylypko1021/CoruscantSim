from __future__ import annotations

import argparse
import csv
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PARAM_BOUNDS = {
    "GREENHOUSE_FORCING_W_M2": (70.0, 180.0),
    "SURFACE_ALBEDO": (0.15, 0.45),
    "CLOUD_COOLING_COEFF": (0.25, 0.9),
    "ATMOSPHERE_MASS_KG": (2.5e18, 9e18),
}

BASE_STEPS = {
    "GREENHOUSE_FORCING_W_M2": 2.0,
    "SURFACE_ALBEDO": 0.004,
    "CLOUD_COOLING_COEFF": 0.012,
    "ATMOSPHERE_MASS_KG": 8.0e16,
}


@dataclass
class Params:
    greenhouse: float
    albedo: float
    cloud: float
    atmosphere: float


@dataclass
class RunResult:
    score: float
    params: Params


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stable autoresearch batch runner with early-stop.")
    parser.add_argument("--iters", type=int, default=20, help="Max iterations")
    parser.add_argument("--early-stop-reverts", type=int, default=10, help="Stop after this many consecutive reverts")
    parser.add_argument("--seed", type=int, default=23, help="Random seed for reproducibility")
    parser.add_argument(
        "--max-proposal-tries",
        type=int,
        default=30,
        help="Maximum attempts to generate a novel parameter proposal per iteration",
    )
    return parser.parse_args()


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def rounded_key(p: Params) -> tuple[float, float, float, float]:
    return (
        round(p.greenhouse, 4),
        round(p.albedo, 6),
        round(p.cloud, 6),
        round(p.atmosphere, 3),
    )


def read_train_params(train_path: Path) -> Params:
    text = train_path.read_text(encoding="utf-8")

    def pick(name: str) -> float:
        m = re.search(rf"^{name}\s*=\s*([^\n]+)$", text, flags=re.MULTILINE)
        if not m:
            raise ValueError(f"Missing parameter line for {name}")
        return float(m.group(1).strip())

    return Params(
        greenhouse=pick("GREENHOUSE_FORCING_W_M2"),
        albedo=pick("SURFACE_ALBEDO"),
        cloud=pick("CLOUD_COOLING_COEFF"),
        atmosphere=pick("ATMOSPHERE_MASS_KG"),
    )


def write_train_params(train_path: Path, p: Params) -> None:
    text = train_path.read_text(encoding="utf-8")
    replacements = {
        "GREENHOUSE_FORCING_W_M2": f"{p.greenhouse:.6f}".rstrip("0").rstrip("."),
        "SURFACE_ALBEDO": f"{p.albedo:.6f}".rstrip("0").rstrip("."),
        "CLOUD_COOLING_COEFF": f"{p.cloud:.6f}".rstrip("0").rstrip("."),
        "ATMOSPHERE_MASS_KG": f"{p.atmosphere:.6e}",
    }

    for key, value in replacements.items():
        text, n = re.subn(rf"^{key}\s*=\s*[^\n]+$", f"{key} = {value}", text, flags=re.MULTILINE)
        if n != 1:
            raise ValueError(f"Expected one replacement for {key}, got {n}")

    train_path.write_text(text, encoding="utf-8")


def read_results_state(results_path: Path) -> tuple[RunResult, set[tuple[float, float, float, float]]]:
    seen: set[tuple[float, float, float, float]] = set()

    with results_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        best_row: dict[str, str] | None = None
        best_score: float | None = None

        for row in reader:
            try:
                score = float(row["score"])
                p = Params(
                    greenhouse=float(row["greenhouse_forcing_w_m2"]),
                    albedo=float(row["surface_albedo"]),
                    cloud=float(row["cloud_cooling_coeff"]),
                    atmosphere=float(row["atmosphere_mass_kg"]),
                )
            except (KeyError, ValueError):
                continue

            seen.add(rounded_key(p))

            if best_score is None or score < best_score:
                best_score = score
                best_row = row

    if best_row is None or best_score is None:
        raise ValueError("results.tsv has no valid rows")

    best = RunResult(
        score=best_score,
        params=Params(
            greenhouse=float(best_row["greenhouse_forcing_w_m2"]),
            albedo=float(best_row["surface_albedo"]),
            cloud=float(best_row["cloud_cooling_coeff"]),
            atmosphere=float(best_row["atmosphere_mass_kg"]),
        ),
    )
    return best, seen


def _one_coord_mutation(base: Params, coord: str, step_scale: float, direction: float) -> Params:
    g, a, c, m = base.greenhouse, base.albedo, base.cloud, base.atmosphere

    if coord == "g":
        lo, hi = PARAM_BOUNDS["GREENHOUSE_FORCING_W_M2"]
        g = clamp(g + direction * BASE_STEPS["GREENHOUSE_FORCING_W_M2"] * step_scale, lo, hi)
    elif coord == "a":
        lo, hi = PARAM_BOUNDS["SURFACE_ALBEDO"]
        a = clamp(a + direction * BASE_STEPS["SURFACE_ALBEDO"] * step_scale, lo, hi)
    elif coord == "c":
        lo, hi = PARAM_BOUNDS["CLOUD_COOLING_COEFF"]
        c = clamp(c + direction * BASE_STEPS["CLOUD_COOLING_COEFF"] * step_scale, lo, hi)
    elif coord == "m":
        lo, hi = PARAM_BOUNDS["ATMOSPHERE_MASS_KG"]
        m = clamp(m + direction * BASE_STEPS["ATMOSPHERE_MASS_KG"] * step_scale, lo, hi)

    return Params(greenhouse=g, albedo=a, cloud=c, atmosphere=m)


def propose_novel(
    base: Params,
    seen: set[tuple[float, float, float, float]],
    rng: random.Random,
    revert_streak: int,
    max_tries: int,
) -> tuple[Params, bool]:
    # Increase exploration radius when we are stuck in consecutive reverts.
    step_scale = 1.0 + 0.22 * revert_streak

    for _ in range(max_tries):
        coord = rng.choice(["g", "a", "c", "m"])
        direction = rng.choice([-1.0, 1.0])
        proposal = _one_coord_mutation(base, coord, step_scale=step_scale, direction=direction)
        if rounded_key(proposal) not in seen:
            return proposal, False

    # Escape mode: mutate two coordinates with larger step if local neighborhood is exhausted.
    coords = ["g", "a", "c", "m"]
    rng.shuffle(coords)
    proposal = base
    for coord in coords[:2]:
        proposal = _one_coord_mutation(
            proposal,
            coord,
            step_scale=max(1.5, step_scale * 1.4),
            direction=rng.choice([-1.0, 1.0]),
        )

    return proposal, True


def run_one(train_path: Path) -> float:
    proc = subprocess.run(
        [sys.executable, str(train_path)],
        cwd=str(train_path.parent),
        capture_output=True,
        text=True,
        check=True,
    )

    score: float | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("score"):
            parts = line.split()
            if len(parts) >= 2:
                score = float(parts[-1])
                break

    if score is None:
        raise ValueError("score not found in train.py output")

    return score


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)

    here = Path(__file__).resolve().parent
    train_path = here / "train.py"
    results_path = here / "results.tsv"

    best, seen = read_results_state(results_path)
    write_train_params(train_path, best.params)

    print(f"baseline best score={best.score:.9f}")
    print(
        "baseline params: "
        f"g={best.params.greenhouse} a={best.params.albedo} c={best.params.cloud} m={best.params.atmosphere:.3e}"
    )
    print(f"seen_param_points={len(seen)}")

    consecutive_reverts = 0
    completed = 0

    for i in range(1, args.iters + 1):
        proposal, used_escape = propose_novel(
            base=best.params,
            seen=seen,
            rng=rng,
            revert_streak=consecutive_reverts,
            max_tries=args.max_proposal_tries,
        )

        write_train_params(train_path, proposal)
        score = run_one(train_path)
        completed += 1

        key = rounded_key(proposal)
        seen.add(key)

        if score < best.score:
            best = RunResult(score=score, params=proposal)
            consecutive_reverts = 0
            verdict = "KEEP"
        else:
            consecutive_reverts += 1
            write_train_params(train_path, best.params)
            verdict = "REVERT"

        print(
            f"iter={i:02d} score={score:.9f} best={best.score:.9f} {verdict} "
            f"streak_revert={consecutive_reverts} escape={'yes' if used_escape else 'no'}"
        )

        if consecutive_reverts >= args.early_stop_reverts:
            print(f"early-stop: {consecutive_reverts} consecutive reverts")
            break

    write_train_params(train_path, best.params)

    print("done")
    print(f"completed_iters={completed}")
    print(f"final_best_score={best.score:.9f}")
    print(
        "final_best_params: "
        f"g={best.params.greenhouse} a={best.params.albedo} c={best.params.cloud} m={best.params.atmosphere:.3e}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
