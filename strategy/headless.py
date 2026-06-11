"""Headless fast-forward runner: simulate N ticks without rendering,
print a report. Used for development, balance scoring and regression.

Usage:
    python -m strategy.headless --ticks 2000 [--seed 42] [--no-physics]
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Dict

from strategy.engine import StrategyEngine, EngineConfig


def run(ticks: int, seed: int = 42, use_physics: bool = True,
        verbose: bool = True) -> Dict:
    engine = StrategyEngine(EngineConfig(seed=seed, use_physics=use_physics))
    t0 = time.perf_counter()
    for i in range(ticks):
        engine.step()
        if verbose and (i + 1) % max(ticks // 10, 1) == 0:
            alive = [f.name for f in engine.factions if f.alive]
            wars = len(engine.diplomacy.wars)
            print(f"tick {engine.tick:5d} | alive={len(alive)} wars={wars} "
                  f"armies={len(engine.armies)} events={len(engine.events)}")
    elapsed = time.perf_counter() - t0

    return report(engine, elapsed, verbose=verbose)


def report(engine: StrategyEngine, elapsed: float = 0.0,
           verbose: bool = True) -> Dict:
    counts = {"war": 0, "peace": 0, "battle": 0, "capture": 0, "tech": 0,
              "built": 0, "expand": 0, "elimination": 0, "alliance": 0}
    for ev in engine.events:
        if ev["type"] in counts:
            counts[ev["type"]] += 1

    factions = []
    for f in engine.factions:
        regions = engine.world.owned_by(f.fid)
        factions.append({
            "name": f.name,
            "alive": f.alive,
            "regions": len(regions),
            "power": round(f.military_power, 1),
            "gdp": round(f.gdp, 1),
            "treasury": round(f.treasury, 0),
            "tech": dict(f.tech),
            "doctrine": f.doctrine,
            "population": round(sum(r.population for r in regions), 0),
        })

    leader = max(factions, key=lambda x: x["regions"])
    result = {
        "ticks": engine.tick,
        "elapsed_s": round(elapsed, 2),
        "ticks_per_s": round(engine.tick / elapsed, 1) if elapsed > 0 else None,
        "alive": sum(1 for f in factions if f["alive"]),
        "leader": leader["name"],
        "leader_regions": leader["regions"],
        "neutral_regions": sum(1 for r in engine.world.regions if r.owner == -1),
        "event_counts": counts,
        "active_wars": len(engine.diplomacy.wars),
        "alliances": len(engine.diplomacy.alliances),
        "factions": factions,
    }

    if verbose:
        print()
        print("=" * 64)
        print(f"  CoruscantSim RTS — headless report after {engine.tick} ticks")
        print(f"  speed: {result['ticks_per_s']} ticks/s")
        print("=" * 64)
        for f in factions:
            status = "ALIVE" if f["alive"] else "DEAD "
            print(f"  [{status}] {f['name']:<20} regions={f['regions']:<3} "
                  f"power={f['power']:<8} gdp={f['gdp']:<8} doctrine={f['doctrine']}")
        print("-" * 64)
        print(f"  events: {counts}")
        print(f"  active wars: {result['active_wars']}, "
              f"alliances: {result['alliances']}, "
              f"neutral regions left: {result['neutral_regions']}")
        print("=" * 64)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Headless RTS run")
    parser.add_argument("--ticks", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-physics", action="store_true")
    parser.add_argument("--json-out", type=str, default="")
    args = parser.parse_args()

    result = run(args.ticks, seed=args.seed, use_physics=not args.no_physics)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
