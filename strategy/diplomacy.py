"""Diplomacy: relations, wars, truces, alliances and peace deals."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple, TYPE_CHECKING

import numpy as np

from strategy.data import BALANCE, FACTIONS, REBEL_FID

if TYPE_CHECKING:
    from strategy.engine import StrategyEngine

N_FACTIONS = len(FACTIONS)


class Diplomacy:
    def __init__(self, rng: np.random.Generator):
        self.rng = rng
        # relations matrix, symmetric, -100..100
        self.relations = np.zeros((N_FACTIONS, N_FACTIONS), dtype=np.float64)
        for i in range(N_FACTIONS):
            for j in range(i + 1, N_FACTIONS):
                base = rng.uniform(-15.0, 25.0)
                self.relations[i, j] = self.relations[j, i] = base
        self.wars: Set[Tuple[int, int]] = set()          # normalized (lo, hi)
        self.truces: Dict[Tuple[int, int], int] = {}     # pair -> ticks left
        self.war_score: Dict[Tuple[int, int], float] = {}  # (a, b): score for a
        self.alliances: Set[Tuple[int, int]] = set()
        self.vassals: Dict[int, int] = {}                # vassal fid -> suzerain fid

    # ------------------------------------------------------------------

    @staticmethod
    def _pair(a: int, b: int) -> Tuple[int, int]:
        return (a, b) if a < b else (b, a)

    def at_war(self, a: int, b: int) -> bool:
        return self._pair(a, b) in self.wars

    def allied(self, a: int, b: int) -> bool:
        return self._pair(a, b) in self.alliances

    def at_peace(self, a: int, b: int) -> bool:
        return not self.at_war(a, b)

    def enemies_of(self, fid: int) -> List[int]:
        out = []
        for (a, b) in self.wars:
            if a == fid:
                out.append(b)
            elif b == fid:
                out.append(a)
        return out

    def suzerain_of(self, fid: int) -> int:
        """Suzerain fid or -1 if independent."""
        return self.vassals.get(fid, -1)

    def vassals_of(self, fid: int) -> List[int]:
        return [v for v, s in self.vassals.items() if s == fid]

    def vassalize(self, engine: "StrategyEngine", vassal: int, suzerain: int) -> None:
        # flatten chains: my vassal's vassals become my vassals
        for v in self.vassals_of(vassal):
            self.vassals[v] = suzerain
        # the new vassal cannot itself be a suzerain target loop
        self.vassals[vassal] = suzerain
        pair = self._pair(vassal, suzerain)
        self.wars.discard(pair)
        self.truces[pair] = 400
        self.relations[vassal, suzerain] = self.relations[suzerain, vassal] = 40.0
        engine.factions[vassal].war_weariness.pop(suzerain, None)
        engine.factions[suzerain].war_weariness.pop(vassal, None)
        engine.log("vassal",
                   f"{engine.factions[vassal].name} capitulated and became "
                   f"a vassal of {engine.factions[suzerain].name}",
                   fid=suzerain, target=vassal)

    def free_vassal(self, engine: "StrategyEngine", vassal: int, reason: str) -> None:
        suzerain = self.vassals.pop(vassal, -1)
        if suzerain >= 0:
            engine.log("independence",
                       f"{engine.factions[vassal].name} broke free from "
                       f"{engine.factions[suzerain].name} ({reason})",
                       fid=vassal, target=suzerain)

    # ------------------------------------------------------------------

    def declare_war(self, engine: "StrategyEngine", a: int, b: int, reason: str) -> None:
        pair = self._pair(a, b)
        if pair in self.wars or pair in self.truces:
            return
        self.wars.add(pair)
        self.alliances.discard(pair)
        self.war_score[(a, b)] = 0.0
        self.war_score[(b, a)] = 0.0
        engine.factions[a].war_weariness[b] = 0.0
        engine.factions[b].war_weariness[a] = 0.0
        self.relations[a, b] = self.relations[b, a] = -80.0
        engine.log("war",
                   f"{engine.factions[a].name} declared war on {engine.factions[b].name} ({reason})",
                   fid=a, target=b)

    def make_peace(self, engine: "StrategyEngine", a: int, b: int) -> None:
        pair = self._pair(a, b)
        if pair not in self.wars:
            return
        score = self.war_score.get((a, b), 0.0)
        winner, loser = (a, b) if score > 0 else (b, a)

        # crushing defeat of a small power -> capitulation, not peace
        from strategy.world import WORLD_SCALE
        loser_regions = len(engine.world.owned_by(loser))
        if (abs(score) >= BALANCE["vassal_war_score"]
                and 0 < loser_regions <= int(BALANCE["vassal_max_regions"] * WORLD_SCALE)
                and loser not in self.vassals
                and winner not in self.vassals):
            self.wars.discard(pair)
            self.vassalize(engine, loser, winner)
            return

        self.wars.discard(pair)
        self.truces[pair] = 250
        reparations = min(engine.factions[loser].treasury * 0.25, 800.0)
        if abs(score) > 1.0 and reparations > 0:
            engine.factions[loser].treasury -= reparations
            engine.factions[winner].treasury += reparations
            engine.log("peace",
                       f"{engine.factions[a].name} and {engine.factions[b].name} signed peace; "
                       f"{engine.factions[loser].name} pays {reparations:.0f} reparations",
                       fid=winner, target=loser)
        else:
            engine.log("peace",
                       f"{engine.factions[a].name} and {engine.factions[b].name} "
                       f"signed a white peace", fid=a, target=b)
        self.relations[a, b] = self.relations[b, a] = -20.0
        engine.factions[a].war_weariness.pop(b, None)
        engine.factions[b].war_weariness.pop(a, None)

    def form_alliance(self, engine: "StrategyEngine", a: int, b: int) -> None:
        pair = self._pair(a, b)
        if pair in self.alliances or pair in self.wars:
            return
        self.alliances.add(pair)
        engine.log("alliance",
                   f"{engine.factions[a].name} and {engine.factions[b].name} formed an alliance",
                   fid=a, target=b)

    def add_war_score(self, winner: int, loser: int, amount: float) -> None:
        if (winner, loser) in self.war_score:
            self.war_score[(winner, loser)] += amount
            self.war_score[(loser, winner)] -= amount

    # ------------------------------------------------------------------

    def step(self, engine: "StrategyEngine") -> None:
        B = BALANCE
        alive = [f for f in engine.factions if f.alive]

        # truce countdown
        for pair in list(self.truces.keys()):
            self.truces[pair] -= 1
            if self.truces[pair] <= 0:
                del self.truces[pair]

        # relation drift
        borders = engine.border_pairs()
        trade = engine.trade_pairs()
        for fa in alive:
            for fb in alive:
                a, b = fa.fid, fb.fid
                if a >= b:
                    continue
                drift = 0.3  # slow regression to neutral
                cur = self.relations[a, b]
                drift_dir = -np.sign(cur) * drift * 0.1
                delta = drift_dir
                if (a, b) in borders or (b, a) in borders:
                    friction = B["border_friction"] * (fa.aggression + fb.aggression)
                    delta -= friction
                if (a, b) in trade or (b, a) in trade:
                    delta += B["trade_warmth"]
                # shared enemy warms relations
                if set(self.enemies_of(a)) & set(self.enemies_of(b)):
                    delta += 0.05
                self.relations[a, b] = self.relations[b, a] = float(
                    np.clip(cur + delta, -100.0, 100.0)
                )

        # war weariness + peace
        for (a, b) in list(self.wars):
            fa, fb = engine.factions[a], engine.factions[b]
            if not (fa.alive and fb.alive):
                self.wars.discard((a, b))
                continue
            sa = self.war_score.get((a, b), 0.0)
            for fid, other, score in ((a, b, sa), (b, a, -sa)):
                f = engine.factions[fid]
                rate = B["weariness_per_tick"]
                if score < -0.5:
                    rate *= B["weariness_losing_mult"]
                if fid == REBEL_FID:
                    rate *= B["rebel_war_weariness_mult"]
                f.war_weariness[other] = f.war_weariness.get(other, 0.0) + rate
            if (fa.war_weariness.get(b, 0) > B["peace_weariness"]
                    and fb.war_weariness.get(a, 0) > B["peace_weariness"] * 0.6) or \
               (fb.war_weariness.get(a, 0) > B["peace_weariness"]
                    and fa.war_weariness.get(b, 0) > B["peace_weariness"] * 0.6):
                self.make_peace(engine, a, b)

        # vassal politics
        for vassal_fid in list(self.vassals.keys()):
            suzerain_fid = self.vassals[vassal_fid]
            fv = engine.factions[vassal_fid]
            fs = engine.factions[suzerain_fid]
            if not fv.alive:
                self.vassals.pop(vassal_fid, None)
                continue
            if not fs.alive:
                self.free_vassal(engine, vassal_fid, "the suzerain has fallen")
                continue
            # wars of independence: dare to revolt once strong enough,
            # or when the suzerain is bogged down in war
            ratio = fv.military_power / max(fs.military_power, 1.0)
            suzerain_at_war = bool(self.enemies_of(suzerain_fid))
            chance = BALANCE["independence_chance"]
            if suzerain_at_war:
                chance *= 2.5
            if ratio >= BALANCE["independence_power_ratio"] and \
                    self.rng.random() < chance:
                self.free_vassal(engine, vassal_fid, "war of independence")
                pair = self._pair(vassal_fid, suzerain_fid)
                self.truces.pop(pair, None)
                self.declare_war(engine, vassal_fid, suzerain_fid,
                                 "war of independence")

        # alliances: very friendly + shared threat
        for fa in alive:
            for fb in alive:
                a, b = fa.fid, fb.fid
                if a >= b or self.allied(a, b) or self.at_war(a, b):
                    continue
                if self.relations[a, b] > 65.0 and (
                        set(self.enemies_of(a)) & set(self.enemies_of(b))):
                    self.form_alliance(engine, a, b)
        # alliances dissolve if relations sour
        for pair in list(self.alliances):
            a, b = pair
            if self.relations[a, b] < 30.0:
                self.alliances.discard(pair)
                engine.log("alliance_end",
                           f"Alliance between {engine.factions[a].name} and "
                           f"{engine.factions[b].name} dissolved", fid=a, target=b)

    # ------------------------------------------------------------------

    def snapshot(self) -> Dict:
        return {
            "wars": sorted(list(self.wars)),
            "alliances": sorted(list(self.alliances)),
            "vassals": dict(self.vassals),
            "relations": np.round(self.relations, 1).tolist(),
        }
