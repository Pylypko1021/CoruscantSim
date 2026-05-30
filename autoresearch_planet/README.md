# Coruscant Autoresearch Loop

This folder adapts the autoresearch pattern to planet parameter tuning.

## Files

- `train.py`: fixed-time-like single experiment objective run with editable parameter block.
- `program.md`: autonomous loop instructions for the agent.
- `results.tsv`: append-only experiment history.

## Run one experiment

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/autoresearch_planet/train.py
```

## Run stable autonomous batch (recommended)

This runs bounded local mutations around the best-known row in `results.tsv`,
applies keep/revert automatically, and early-stops after too many consecutive reverts.

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/autoresearch_planet/run_stable_batch.py \
  --iters 20 \
  --early-stop-reverts 10 \
  --seed 23
```

## Interactive agent monitoring (separate terminal)

Run this in a dedicated terminal pane:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/autoresearch_planet/monitor_agents.py
```

Controls inside monitor:

- `q` quit
- `p` or `space` pause/resume refresh
- `+` faster refresh
- `-` slower refresh
- `f` cycle process filter (`all` -> `train` -> `copilot`)
- `tab` switch focus between Recent Results/Processes/Events panels
- `j`/`k` or arrows scroll focused panel
- `g` jump to top of focused panel
- `G` jump to bottom of focused panel
- `r` force refresh now

If your shell is non-interactive, use one-shot mode:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/autoresearch_planet/monitor_agents.py --plain
```

Optional flags:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/autoresearch_planet/monitor_agents.py \
  --interval 1.0 \
  --recent 10 \
  --target-iters 30 \
  --process-filter "coruscant|train.py|copilot"
```

## How to use with `autoresearch` / `autoresearch-mlx`

You can point your coding agent at this folder exactly like Karpathy's repo:

1. open `program.md`
2. iterate parameter edits in `train.py`
3. run one experiment
4. keep or revert based on score
5. repeat

This gives the same autonomous-search workflow, but the target metric is Coruscant climate fit.

## Agent-command workflow (Copilot Chat)

You can run the same flow via prompt commands in this workspace:

- `/coruscant-run-stable-batch`: launch stable 20-iteration coordinator run with subagents.
- `/coruscant-status-and-summary`: check current status, best row, last rows, and run recommendation.

Prompt files:

- `.github/prompts/coruscant-run-stable-batch.prompt.md`
- `.github/prompts/coruscant-status-and-summary.prompt.md`
