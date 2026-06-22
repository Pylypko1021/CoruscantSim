"""Autoresearch-style balance tuner for the RTS layer.

Mirrors autoresearch_planet: mutate one balance constant at a time,
run headless simulations, keep the change if the "liveliness score"
improves, revert otherwise. Results are appended to
strategy/balance_results.tsv.

Score rewards a healthy autonomous drama:
  - factions survive the early game (no snowball wipeouts),
  - wars happen and end,
  - territory changes hands,
  - the map fills up over time,
  - no single faction dominates too early.

Usage:
    python -m strategy.balance_tune --iters 15 --ticks 1200
"""

from __future__ import annotations

import argparse
import copy
import random
from datetime import datetime, timezone
from pathlib import Path

from strategy import data as game_data
from strategy.engine import StrategyEngine, EngineConfig
from strategy import headless


TUNABLE = {
    "combat_intensity": (0.05, 0.4),
    "defender_home_bonus": (1.0, 2.0),
    "rout_ratio": (0.2, 0.6),
    "war_relation_threshold": (-70.0, -25.0),
    "war_advantage_required": (1.0, 1.8),
    "weariness_per_tick": (0.05, 0.5),
    "border_friction": (0.05, 0.5),
    "expansion_army_power": (10.0, 60.0),
    "tax_per_pop": (0.04, 0.3),
    "pop_growth_rate": (0.001, 0.006),
    "rebellion_unrest": (0.70, 0.95),
    "rebellion_chance": (0.002, 0.03),
}

RESULTS = Path(__file__).with_name("balance_results.tsv")


def evaluate(ticks: int, seeds: list[int]) -> dict:
    """Run headless sims and compute the liveliness score (higher = better)."""
    totals = {"score": 0.0}
    for seed in seeds:
        eng = StrategyEngine(EngineConfig(seed=seed, use_physics=False))
        eliminated_at = {}
        for t in range(ticks):
            eng.step()
            for f in eng.factions:
                if not f.alive and f.fid not in eliminated_at:
                    eliminated_at[f.fid] = eng.tick

        rep = headless.report(eng, verbose=False)
        counts = rep["event_counts"]

        score = 0.0
        # survival: heavy penalty for very early eliminations
        for fid, t in eliminated_at.items():
            score -= 30.0 * max(0.0, 1.0 - t / ticks)
        score += 10.0 * rep["alive"]
        # drama: wars should happen AND end
        wars = counts["war"]
        score += min(wars, 8) * 4.0 - max(0, wars - 12) * 2.0
        score += min(counts["peace"], 8) * 2.0
        score += min(counts["capture"], 30) * 0.8
        # uprisings: spice, not the main dish
        rebellions = counts.get("rebellion", 0)
        score += min(rebellions, 6) * 2.0 - max(0, rebellions - 10) * 3.0
        score += min(counts.get("vassal", 0), 3) * 3.0
        score += min(counts.get("independence", 0), 2) * 3.0
        # expansion: map should fill up
        claimed = 288 - rep["neutral_regions"]
        score += claimed * 0.15
        # dominance check: leader should not own >55% of claimed land early
        if claimed > 0:
            dominance = rep["leader_regions"] / claimed
            if dominance > 0.55:
                score -= (dominance - 0.55) * 120.0
        totals["score"] += score / len(seeds)
        totals[f"seed{seed}_wars"] = wars
        totals[f"seed{seed}_alive"] = rep["alive"]
        totals[f"seed{seed}_claimed"] = claimed
    return totals


def append_result(params: dict, result: dict) -> None:
    header_needed = not RESULTS.exists()
    with RESULTS.open("a", encoding="utf-8") as f:
        if header_needed:
            f.write("timestamp\tscore\t" + "\t".join(sorted(TUNABLE)) + "\n")
        f.write(
            datetime.now(timezone.utc).isoformat(timespec="seconds")
            + f"\t{result['score']:.3f}\t"
            + "\t".join(f"{params[k]:.5g}" for k in sorted(TUNABLE))
            + "\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="RTS balance autotuner")
    parser.add_argument("--iters", type=int, default=15)
    parser.add_argument("--ticks", type=int, default=1200)
    parser.add_argument("--seeds", type=str, default="42,7")
    parser.add_argument("--rng-seed", type=int, default=0)
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    rng = random.Random(args.rng_seed)

    best_params = {k: game_data.BALANCE[k] for k in TUNABLE}
    print("evaluating baseline...")
    best = evaluate(args.ticks, seeds)
    append_result(best_params, best)
    print(f"baseline score = {best['score']:.3f}")

    for it in range(args.iters):
        key = rng.choice(sorted(TUNABLE))
        lo, hi = TUNABLE[key]
        factor = rng.uniform(0.75, 1.35)
        candidate = dict(best_params)
        candidate[key] = float(min(hi, max(lo, best_params[key] * factor)))
        if abs(candidate[key] - best_params[key]) < 1e-12:
            continue

        game_data.BALANCE.update(candidate)
        result = evaluate(args.ticks, seeds)
        append_result(candidate, result)

        verdict = "KEEP" if result["score"] > best["score"] else "revert"
        print(f"[{it + 1}/{args.iters}] {key}: {best_params[key]:.4g} -> "
              f"{candidate[key]:.4g} | score {result['score']:.3f} "
              f"(best {best['score']:.3f}) -> {verdict}")
        if result["score"] > best["score"]:
            best = result
            best_params = candidate
        else:
            game_data.BALANCE.update(best_params)

    print("\nbest parameters:")
    for k in sorted(best_params):
        print(f"  {k} = {best_params[k]:.5g}")
    print(f"best score = {best['score']:.3f}")
    print(f"log: {RESULTS}")


if __name__ == "__main__":
    main()
