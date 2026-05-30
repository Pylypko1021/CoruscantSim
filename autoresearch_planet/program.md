# program.md (Coruscant Planet Parameter Autoresearch)

Goal: minimize `score` reported by `train.py`.

## Rules

- Edit only the parameter block in `train.py`:
  - `GREENHOUSE_FORCING_W_M2`
  - `SURFACE_ALBEDO`
  - `CLOUD_COOLING_COEFF`
  - `ATMOSPHERE_MASS_KG`
- Keep all other code untouched unless there is a bug that blocks execution.
- Run one experiment with:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/autoresearch_planet/train.py
```

- If `score` improves over previous best in `results.tsv`, keep the change.
- If `score` gets worse, revert parameter edit and try a different proposal.

## Suggested Search Policy

1. Start with coarse moves:
   - greenhouse +/- 5 to 15
   - albedo +/- 0.01 to 0.03
   - cloud coeff +/- 0.01 to 0.04
   - atmosphere mass +/- (2e17 to 8e17)
2. Once score improves, do local refinement with smaller step sizes.
3. Avoid unrealistic ranges:
   - `0.15 <= SURFACE_ALBEDO <= 0.45`
   - `70 <= GREENHOUSE_FORCING_W_M2 <= 180`
   - `0.25 <= CLOUD_COOLING_COEFF <= 0.9`
   - `2.5e18 <= ATMOSPHERE_MASS_KG <= 9e18`

## Stable Batch Policy

- Prefer local, one-parameter mutations around current best.
- Keep if `new_score < best_previous_score`, otherwise revert to best params.
- Use early stop when search stalls; stop after `N` consecutive reverts (recommended `N=10`).

## Success Criteria

- Lower score is better.
- Prefer improvements that also reduce `mean_energy_residual_w_m2` and keep `mean_hadley_index_k` in a plausible band.

## Notes

- This is the same autoresearch idea, but objective is Coruscant climate parameter fitting instead of LLM training bpb.
- `results.tsv` is the experiment log.
