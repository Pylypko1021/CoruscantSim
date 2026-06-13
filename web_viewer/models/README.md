# 3D models

Low-poly GLB models by **Quaternius** (https://quaternius.com), licensed
**CC0 1.0** (public domain) — free for any use, no attribution required
(noted here out of courtesy). Pulled from the trebeljahr/quaternius-showcase
mirror, which ships them as ready glTF/GLB (some Draco/Meshopt-compressed —
the viewer loads all three decoders).

## `units/` — army markers (cloned per army, faction-tinted)

The viewer maps each army to a type by its dominant unit and picks a variant
deterministically by army id (see `UNIT_VARIANTS` in `../src/rts.js`).

| Type | Files | Source pack |
|---|---|---|
| infantry | `infantry_a/b.glb` | Cyberpunk — Enemy_2Legs, Enemy_2Legs_Gun |
| armor | `armor_a/b.glb` | Cyberpunk — Enemy_Large, Enemy_Large_Gun |
| aircraft | `aircraft_a/b/c.glb` | Ultimate Spaceships — Striker, Spitfire, Insurgent |
| fleet | `fleet_a/b/c/d.glb` | Ultimate Spaceships — Executioner, Imperial, Omen, Zenith |

Add more GLBs and extend the lists in `rts.js` to grow the roster; any that
fail to load fall back to procedural shapes.

## `buildings/` — region landmark silhouettes (instanced, LOD-capped)

Loaded once, baked into normalized position-only geometry, and drawn as
faction-tinted `InstancedMesh`. Only the nearest `LANDMARK_CAP` to the camera
render per type, so the triangle budget stays bounded on the 2592-region world.

| Landmark | File | Source (Ultimate Space Kit) |
|---|---|---|
| factory | `factory.glb` | Building_L |
| defense grid | `dome.glb` | GeodesicDome |
| spaceport / citadel | `platform.glb` | Base_Large |
| research lab | `tower_b.glb` | House_Long |
| (skyline) | `spire.glb`, `tower_a.glb`, `tower_c.glb` | House_Cylinder / Single / Open |

## `preview/` (gitignored)

Download dump of review candidates. Open `../models.html` to compare any of
them in a rotating 3D grid before promoting one into `units/` or `buildings/`.
