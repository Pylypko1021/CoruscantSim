# CoruscantSim

## 🎮 Autonomous RTS (нове, рекомендований вхід)

Zero-player гранд-стратегія: 5 фракцій самостійно розвиваються, будують,
досліджують технології, торгують, укладають союзи і воюють на глобусі з **2592
регіонів** (сітка 36×72, 1 регіон = 1 клітинка фізичної моделі). Старт — п'ять
маленьких держав серед ~2300 нейтральних регіонів: епоха колонізації
(експедиції + мирна культурна асиміляція сусідів), потім епоха воєн за
поділений світ. Фізичне ядро планети живить клімат і катастрофи. Ви —
спостерігач.

Емерджентна політика:

- **Лідери поколінь** 👑 — кожна фракція має правителя з рисами martial /
  stewardship, що множать бій та економіку; правителі змінюються, історія
  пише імена.
- **Васалітет** ⛓ — розгромлена мала держава капітулює: платить данину,
  не веде власних воєн, чекає моменту для **війни за незалежність** 🔥.
- **Повстання** ✊ — регіони з високим невдоволенням піднімають прапор
  Free Coruscant; повстанці воюють лише з гнобителями, але можуть
  вирвати власну державу.
- **Торгові коридори** — торгівля вимагає фізичного шляху між столицями;
  ворожа територія **блокує** маршрути (червоний пунктир на глобусі) —
  війни за коридори стають реальністю.
- **Падіння столиць** 🏛 — уряд тікає в найбільший вцілілий регіон.

```bash
pip install -r requirements.txt

# живий сервер + 3D-в'ювер (Three.js)
python rts_server.py --port 8780 --speed 5
# відкрийте http://localhost:8780

# headless прогін без рендера + звіт
python -m strategy.headless --ticks 3000 --no-physics

# регресійні тести RTS-шару (очікуваний фінал: strategy_tests_ok)
python tests_strategy.py

# автотюнінг балансу (autoresearch-патерн)
python -m strategy.balance_tune --iters 15 --ticks 1200
```

Структура RTS-шару:

| Модуль | Відповідальність |
|---|---|
| `strategy/world.py` | 2592 регіони (36×72), родовища, клімат, граф сусідства, BFS-шляхи |
| `strategy/data.py` | будівлі, юніти, дерево технологій, фракції, баланс-константи |
| `strategy/state.py` | runtime-стан фракцій, армії (split/merge/втрати) |
| `strategy/engine.py` | головний цикл: економіка→будівництво→AI→рух→бої→дипломатія |
| `strategy/ai.py` | дворівневий AI: доктрини + build orders/армійські накази |
| `strategy/combat.py` | бої на виснаження, облоги, захоплення, розгроми |
| `strategy/diplomacy.py` | відносини, війни, втома від війни, мир, союзи, репарації |
| `strategy/headless.py` | швидкий прогін + звіт |
| `strategy/balance_tune.py` | автоматичний пошук параметрів балансу |
| `strategy/chronicle.py` | markdown-хроніка великих подій (`chronicle.md`) |
| `strategy/notify.py` | Discord/Telegram сповіщення про війни, повстання, капітуляції |
| `rts_server.py` | HTTP API + статика (`/api/state`, `/api/region`, `/api/timeline`, `/api/speed`, `/api/save`, `/api/reset`) |
| `web_viewer/rts.html` + `src/rts.js` | 3D-глобус, армії, спалахи битв, торгові дуги, графіки, стрічка подій |
| `run_rts_service.ps1` | фоновий запуск на тижні з автоперезапуском (інструкція schtasks усередині) |

Сервер у браузері: пауза/швидкість 1×–25×, клік по регіону — деталі,
**таймлайн-слайдер** — перемотка історії володінь, 💾 Save → `rts_save.json`
(відновлення: `StrategyEngine.load`).

Армії на глобусі — процедурні моделі за домінантним типом юніта (прапор
піхоти / танк / винищувач / лінкор). Покладіть власні GLB у
`web_viewer/models/{infantry,armor,aircraft,fleet}.glb` — підхопляться
автоматично.

Сповіщення: задайте `CORUSCANT_DISCORD_WEBHOOK` або
`CORUSCANT_TELEGRAM_TOKEN`+`CORUSCANT_TELEGRAM_CHAT` (env або CLI-прапорці
`--discord-webhook` / `--telegram-token` / `--telegram-chat`).

> Примітка для Windows: команди нижче в історичних розділах містять
> macOS-шляхи зразка `/Users/cyberdid/...` — замінюйте на `python <script>`
> у корені репозиторію.

---

## Realistic Planet Visualization (Fast Start)

1. Ensure diagnostics exist:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/export_diagnostics.py
```

1. Render a high-quality static frame:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/render_coruscant_planet.py \
  --fields CoruscantSim/output/final_fields.npz \
  --out-image CoruscantSim/output/coruscant_planet.png \
  --texture-scale 4 \
  --smooth-iterations 2
```

1. Render a rotating GIF:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/render_coruscant_planet.py \
  --fields CoruscantSim/output/final_fields.npz \
  --out-image CoruscantSim/output/coruscant_planet.png \
  --out-gif CoruscantSim/output/coruscant_planet.gif \
  --make-gif \
  --frames 120 \
  --fps 24 \
  --texture-scale 4 \
  --smooth-iterations 2
```

1. Open real-time interactive planet view (close window to stop):

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/render_coruscant_planet.py \
  --fields CoruscantSim/output/final_fields.npz \
  --realtime \
  --realtime-fps 30 \
  --texture-scale 4 \
  --smooth-iterations 2
```

1. NASA-like realistic mode (external day/night/cloud maps + orbit tracks):

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/render_coruscant_planet.py \
  --fields CoruscantSim/output/final_fields.npz \
  --daymap CoruscantSim/assets/earth_day.jpg \
  --nightmap CoruscantSim/assets/earth_night.jpg \
  --cloudmap CoruscantSim/assets/earth_clouds.png \
  --texture-blend 0.85 \
  --orbits 20 \
  --realtime \
  --realtime-fps 30
```

If any map file is missing, renderer falls back to procedural Coruscant textures.

## Three.js Realtime Viewer (recommended)

1. Build web textures from latest physics fields:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/build_web_textures.py \
  --fields CoruscantSim/output/final_fields.npz \
  --out-dir CoruscantSim/web_viewer/data \
  --scale 3
```

1. Start local static server from workspace root:

```bash
cd "/Users/cyberdid/projects/solar system" && python -m http.server 8787
```

1. Open viewer in browser:

`http://localhost:8787/CoruscantSim/web_viewer/`

Мінімальний прототип моделювання Корусанта як планети-міста.

## Що моделюється

- Щільність населення по районах
- Інфраструктура
- Енергетичне навантаження
- Температура (ефект "теплового острова")
- Водний стрес
- Індекс безпеки
- Соціальні заворушення
- Продуктивність

## Запуск

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/simulate_coruscant.py
```

## Запуск детальної фізики планети (без екосистеми)

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/simulate_coruscant_planet.py
```

Цей режим моделює:

- радіаційний баланс
- гідростатику атмосфери
- прогностичні вітри з термінами pressure-gradient force + Coriolis + drag
- двошарову атмосферу (surface + lower atmosphere)
- вологість, конденсацію, хмарність і проксі опадів
- багаторівневий вертикальний профіль температури/вологості
- явний вертикальний transport (eddy-diffusion) для тепла і вологи між рівнями
- двосторонній зв'язок вертикального профілю з surface/lower atmosphere шарами
- stability-aware перемішування на основі Richardson-подібного критерію
- вертикальний профіль вітру з shear-динамікою та Ri-обмеженим змішуванням
- flux-form вертикальна адвекція тепла/вологи з upwind-схемою та stability limiter
- column moisture fixer для зменшення чисельного дрейфу вологи в довгих прогонах
- energy-balance closure з drift guard (residual + temperature correction diagnostics)
- latent moisture-energy closure (evap/cond phase-change flux + residual audit)
- circulation-aware vertical velocity proxy (Hadley/convergence driven w-diagnostics)
- автоматична калібровка параметрів climate-core (greenhouse/albedo/cloud cooling)
- adaptive time step на основі CFL-подібного критерію
- аерофізичні індикатори (Mach, Reynolds, Rossby, vorticity, divergence, bulk Ri, N^2, vertical shear, vertical fluxes)
- кумулятивні budget-метрики (energy input, latent energy, correction energy, moisture correction)

## Експорт діагностик

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/export_diagnostics.py --days 120 --out-dir CoruscantSim/output
```

Скрипт створює:

- CoruscantSim/output/history.csv
- CoruscantSim/output/summary.json
- CoruscantSim/output/final_fields.npz

## Калібрування кліматичних параметрів

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/calibrate_climate.py --days 120 --out-dir CoruscantSim/output
```

Скрипт створює:

- CoruscantSim/output/calibration_results.csv
- CoruscantSim/output/calibration_report.md
- CoruscantSim/output/calibration_best.json

## Autoresearch-style parameter tuning

Для автономного пошуку параметрів у стилі `karpathy/autoresearch` використовуйте:

- `CoruscantSim/autoresearch_planet/program.md`
- `CoruscantSim/autoresearch_planet/train.py`
- `CoruscantSim/autoresearch_planet/results.tsv`

Швидкий запуск одного експерименту:

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/autoresearch_planet/train.py
```

## Regression-тести фізики (обов'язковий gate)

```bash
cd "/Users/cyberdid/projects/solar system/CoruscantSim" && \
"/Users/cyberdid/projects/solar system/.venv/bin/python" tests_physics.py
```

Очікуваний результат у консолі: `physics_tests_ok`.

## Автотест сценаріїв фізики (sweep)

```bash
"/Users/cyberdid/projects/solar system/.venv/bin/python" CoruscantSim/run_physics_sweep.py
```

Результат зберігається у `CoruscantSim/physics_sweep_results.csv`.
Додатковий порівняльний звіт: `CoruscantSim/physics_sweep_report.md`.

## Сценарії sweep

Сценарії в `run_physics_sweep.py`:

- `baseline`
- `high_greenhouse`
- `thin_atmosphere`
- `fast_rotation`
- `high_albedo`
- `industrial_surge`
- `albedo_engineering`
- `atmosphere_recovery`

## Поточний calibrated baseline

Поточний baseline конфіг за замовчуванням:

- `greenhouse_forcing_w_m2 = 115.0`
- `surface_albedo = 0.22`
- `cloud_cooling_coeff = 0.46`
