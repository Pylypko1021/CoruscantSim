import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import * as BufferGeometryUtils from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { KTX2Loader } from "three/examples/jsm/loaders/KTX2Loader.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REGION_ROWS = 36;
const REGION_COLS = 72;
const GLOBE_R = 1.0;
const POLL_MS = 450;

const NEUTRAL_COLOR = "#23253a";
const NEUTRAL_BRIGHT = "#2e3150";

// ---------------------------------------------------------------------------
// Renderer / scene
// ---------------------------------------------------------------------------

const canvas = document.getElementById("scene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x05050c);

const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.05, 100);
camera.position.set(0, 1.4, 2.6);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 1.08;     // dive close enough to read the cityscape
controls.maxDistance = 6.0;
controls.zoomSpeed = 1.2;

scene.add(new THREE.AmbientLight(0x8890c0, 0.5));
const sun = new THREE.DirectionalLight(0xfff2cc, 1.6);
sun.position.set(4, 2, 3);
scene.add(sun);
const fill = new THREE.DirectionalLight(0x4d66c4, 0.35);
fill.position.set(-4, -1.5, -2);
scene.add(fill);

// post-processing: subtle bloom makes city lights, beacons and lasers glow
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloomPass = new UnrealBloomPass(
  new THREE.Vector2(window.innerWidth / 2, window.innerHeight / 2), 0.55, 0.6, 0.72);
composer.addPass(bloomPass);
composer.addPass(new OutputPass());

// starfield
{
  const starGeo = new THREE.BufferGeometry();
  const n = 1500, pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const v = new THREE.Vector3().randomDirection().multiplyScalar(40 + Math.random() * 30);
    pos.set([v.x, v.y, v.z], i * 3);
  }
  starGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0x9aa3cc, size: 0.06, sizeAttenuation: true })));
}

// ---------------------------------------------------------------------------
// Globe with region ownership texture (canvas-painted)
// ---------------------------------------------------------------------------

const PX = 16;                       // pixels per region cell on the texture
const texCanvas = document.createElement("canvas");
texCanvas.width = REGION_COLS * PX;   // 1152
texCanvas.height = REGION_ROWS * PX;  // 576
const texCtx = texCanvas.getContext("2d");
const mapTexture = new THREE.CanvasTexture(texCanvas);
mapTexture.colorSpace = THREE.SRGBColorSpace;
mapTexture.magFilter = THREE.LinearFilter;
mapTexture.anisotropy = 4;

const globe = new THREE.Mesh(
  new THREE.SphereGeometry(GLOBE_R, 128, 96),
  new THREE.MeshStandardMaterial({ map: mapTexture, roughness: 0.78, metalness: 0.18 }),
);
scene.add(globe);

// ecumenopolis surface detail: city diffuse painted UNDER faction colors,
// bump relief + night lights as emissive (all best-effort)
const texLoader = new THREE.TextureLoader();
let cityImg = null;                  // HTMLImageElement once loaded
{
  const img = new Image();
  img.onload = () => { cityImg = img; if (latestState) paintRegions(latestState); };
  img.src = "/data/coruscant_diffuse.jpg";
}
texLoader.load("/data/coruscant_bump.jpg", (tex) => {
  globe.material.bumpMap = tex;
  globe.material.bumpScale = 0.012;
  globe.material.needsUpdate = true;
}, undefined, () => {});
texLoader.load("/data/coruscant_lights_metropolis.jpg", (tex) => {
  tex.colorSpace = THREE.SRGBColorSpace;
  globe.material.emissiveMap = tex;
  globe.material.emissive = new THREE.Color(0xffc878);
  globe.material.emissiveIntensity = 0.28;
  globe.material.needsUpdate = true;
}, undefined, () => {});

// fresnel atmosphere: blue rim glow that breathes with the bloom pass
{
  const atmoMat = new THREE.ShaderMaterial({
    uniforms: { glowColor: { value: new THREE.Color(0x4a7cff) } },
    vertexShader: `
      varying float vRim;
      void main() {
        vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
        vec3 n = normalize(normalMatrix * normal);
        vec3 v = normalize(-mvPos.xyz);
        vRim = 1.0 - abs(dot(n, v));
        gl_Position = projectionMatrix * mvPos;
      }`,
    fragmentShader: `
      uniform vec3 glowColor;
      varying float vRim;
      void main() {
        float a = pow(vRim, 3.2) * 0.85;
        gl_FragColor = vec4(glowColor, a);
      }`,
    side: THREE.BackSide,
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
  });
  scene.add(new THREE.Mesh(new THREE.SphereGeometry(GLOBE_R * 1.06, 64, 48), atmoMat));
}

// grid overlay (region boundaries)
{
  const gridMat = new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.18 });
  const group = new THREE.Group();
  for (let r = 1; r < REGION_ROWS; r++) {
    const lat = -90 + (180 * r) / REGION_ROWS;
    const pts = [];
    for (let i = 0; i <= 72; i++) pts.push(latLonToVec3(lat, (i * 360) / 72, GLOBE_R * 1.002));
    group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat));
  }
  for (let c = 0; c < REGION_COLS; c++) {
    const lon = (360 * c) / REGION_COLS;
    const pts = [];
    for (let i = 0; i <= 36; i++) pts.push(latLonToVec3(-90 + (i * 180) / 36, lon, GLOBE_R * 1.002));
    group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat));
  }
  scene.add(group);
}

function latLonToVec3(lat, lon, r) {
  const phi = THREE.MathUtils.degToRad(90 - lat);
  const theta = THREE.MathUtils.degToRad(-lon);   // matches texture u = lon/360
  return new THREE.Vector3(
    r * Math.sin(phi) * Math.cos(theta),
    r * Math.cos(phi),
    r * Math.sin(phi) * Math.sin(theta),
  );
}

function shade(hex, factor) {
  const c = new THREE.Color(hex);
  c.multiplyScalar(factor);
  return `#${c.getHexString()}`;
}

function paintCityBase() {
  if (cityImg) {
    texCtx.globalAlpha = 1.0;
    texCtx.drawImage(cityImg, 0, 0, texCanvas.width, texCanvas.height);
    // darken slightly so faction tints read clearly
    texCtx.fillStyle = "rgba(8, 9, 18, 0.35)";
    texCtx.fillRect(0, 0, texCanvas.width, texCanvas.height);
  } else {
    texCtx.fillStyle = NEUTRAL_COLOR;
    texCtx.fillRect(0, 0, texCanvas.width, texCanvas.height);
  }
}

function paintRegions(state) {
  const { owner, devastation, unrest } = state.regions;
  const colours = {};
  for (const f of state.factions) colours[f.fid] = f.colour;
  const capitals = new Set(state.factions.filter(f => f.alive).map(f => f.capital));

  paintCityBase();
  for (let row = 0; row < REGION_ROWS; row++) {
    for (let col = 0; col < REGION_COLS; col++) {
      const rid = row * REGION_COLS + col;
      const own = owner[rid];
      // texture v=0 is the top (lat +90) -> row 0 is lat -89..  flip rows
      const y = (REGION_ROWS - 1 - row) * PX;
      const x = col * PX;

      if (own >= 0) {
        let bright = 1.0 - 0.55 * (devastation[rid] || 0);
        bright *= 1.0 - 0.25 * (unrest[rid] || 0);
        texCtx.globalAlpha = 0.52;
        texCtx.fillStyle = shade(colours[own], bright);
        texCtx.fillRect(x, y, PX, PX);
        // crisp border ring so empires read as shapes, not noise
        texCtx.globalAlpha = 0.85;
        texCtx.strokeStyle = shade(colours[own], bright * 1.25);
        texCtx.lineWidth = 1;
        texCtx.strokeRect(x + 0.5, y + 0.5, PX - 1, PX - 1);
      } else if (devastation[rid] > 0.05) {
        texCtx.globalAlpha = 0.4 * devastation[rid];
        texCtx.fillStyle = "#000000";
        texCtx.fillRect(x, y, PX, PX);
      }

      if (capitals.has(rid)) {
        texCtx.globalAlpha = 1.0;
        texCtx.fillStyle = "#ffffff";
        texCtx.beginPath();
        texCtx.arc(x + PX / 2, y + PX / 2, PX * 0.22, 0, Math.PI * 2);
        texCtx.fill();
        texCtx.strokeStyle = colours[owner[rid]] || "#888";
        texCtx.lineWidth = 2;
        texCtx.stroke();
      }
    }
  }
  texCtx.globalAlpha = 1.0;
  mapTexture.needsUpdate = true;
}

// ---------------------------------------------------------------------------
// City architecture: instanced skylines + landmark buildings per region
// ---------------------------------------------------------------------------

const SURF = GLOBE_R * 1.001;
const buildGroup = new THREE.Group();
scene.add(buildGroup);

// deterministic per-region jitter so towers don't dance between repaints
function hash01(n) {
  let x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

function regionSurfacePos(rid, jx = 0, jy = 0) {
  const row = Math.floor(rid / REGION_COLS), col = rid % REGION_COLS;
  const lat = -89 + (178 * (row + 0.5 + jy * 0.72)) / REGION_ROWS;
  const lon = (360 * (col + 0.5 + jx * 0.72)) / REGION_COLS;
  return latLonToVec3(lat, lon, SURF);
}

// Shared GLB loader with every decoder (Meshopt + Draco + KTX2). Used for
// both building silhouettes and army unit models.
const gltfLoader = new GLTFLoader();
gltfLoader.setMeshoptDecoder(MeshoptDecoder);
{
  const draco = new DRACOLoader();
  draco.setDecoderPath("https://unpkg.com/three@0.164.1/examples/jsm/libs/draco/");
  gltfLoader.setDRACOLoader(draco);
  const ktx2 = new KTX2Loader()
    .setTranscoderPath("https://unpkg.com/three@0.164.1/examples/jsm/libs/basis/")
    .detectSupport(renderer);
  gltfLoader.setKTX2Loader(ktx2);
}

// Bake a GLB's meshes into ONE normalized geometry (base at y=0, centered in
// x/z, max dimension = 1) — position+normal only, ready for InstancedMesh.
function loadInstanceGeometry(url) {
  return new Promise((resolve) => {
    gltfLoader.load(url, (g) => {
      g.scene.updateMatrixWorld(true);
      const geos = [];
      g.scene.traverse((o) => {
        if (o.isMesh && o.geometry) {
          let geo = o.geometry.clone();
          geo.applyMatrix4(o.matrixWorld);
          if (geo.index) geo = geo.toNonIndexed();
          const keep = new THREE.BufferGeometry();
          keep.setAttribute("position", geo.getAttribute("position"));
          geos.push(keep);                      // position-only -> always mergeable
        }
      });
      if (!geos.length) return resolve(null);
      let merged = geos.length === 1 ? geos[0] : BufferGeometryUtils.mergeGeometries(geos);
      if (!merged) merged = geos[0];
      merged.computeVertexNormals();
      merged.computeBoundingBox();
      let bb = merged.boundingBox;
      merged.translate(-(bb.min.x + bb.max.x) / 2, -bb.min.y, -(bb.min.z + bb.max.z) / 2);
      merged.computeBoundingBox();
      const size = new THREE.Vector3();
      merged.boundingBox.getSize(size);
      const maxd = Math.max(size.x, size.y, size.z) || 1;
      merged.scale(1 / maxd, 1 / maxd, 1 / maxd);
      resolve(merged);
    }, undefined, () => resolve(null));
  });
}

// Landmark buildings: real Quaternius silhouettes, faction-tinted, LOD-capped
// to the nearest-to-camera instances so the triangle budget stays bounded no
// matter how huge the world grows.
const LANDMARKS = [
  { key: "factory",   bit: 1,  file: "factory.glb",  scale: 0.015, emissive: 0xff8855 },
  { key: "defense",   bit: 2,  file: "dome.glb",     scale: 0.016, emissive: 0x55ddff },
  { key: "spaceport", bit: 4,  file: "platform.glb", scale: 0.018, emissive: 0xffffff },
  { key: "lab",       bit: 8,  file: "tower_b.glb",  scale: 0.015, emissive: 0xcc88ff },
  { key: "citadel",   bit: 16, file: "platform.glb", scale: 0.024, emissive: 0xffcc44 },
];
const LANDMARK_CAP = 140;        // nearest instances rendered per type

const MAX_TOWERS = 7000;
const towerMesh = new THREE.InstancedMesh(
  new THREE.BoxGeometry(1, 1, 1),
  new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.4,
    emissive: 0xfff0c0, emissiveIntensity: 0.18 }),
  MAX_TOWERS,
);
towerMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
buildGroup.add(towerMesh);

const placeholderGeo = new THREE.BoxGeometry(1, 1, 1);
const landmarkMeshes = {};
for (const lm of LANDMARKS) {
  const mesh = new THREE.InstancedMesh(
    placeholderGeo,
    new THREE.MeshStandardMaterial({ roughness: 0.5, metalness: 0.45,
      emissive: lm.emissive, emissiveIntensity: 0.14 }),
    LANDMARK_CAP,
  );
  mesh.count = 0;
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  mesh.frustumCulled = false;
  buildGroup.add(mesh);
  landmarkMeshes[lm.key] = mesh;
}
// swap in the real silhouettes as they decode
for (const lm of LANDMARKS) {
  loadInstanceGeometry(`/models/buildings/${lm.file}`).then((geo) => {
    if (geo) { landmarkMeshes[lm.key].geometry = geo; landmarkLODDirty = true; }
  });
}

// capital beacons: vertical light pillars + glow sprite
const beaconGroup = new THREE.Group();
scene.add(beaconGroup);
const beacons = new Map();           // fid -> {beam, glow, rid}

function makeBeacon(colourHex) {
  const colour = new THREE.Color(colourHex);
  const g = new THREE.Group();
  const beam = new THREE.Mesh(
    new THREE.CylinderGeometry(0.006, 0.013, 0.6, 8, 1, true),
    new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }),
  );
  beam.position.y = 0.3;
  g.add(beam);
  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(0.02, 10, 10),
    new THREE.MeshBasicMaterial({ color: 0xffffff }),
  );
  glow.position.y = 0.012;
  g.add(glow);
  return g;
}

const dummy = new THREE.Object3D();
const upY = new THREE.Vector3(0, 1, 0);
const q = new THREE.Quaternion();
let buildingsKey = "";
let landmarkLODDirty = true;
const landmarkRegions = {};      // key -> [{ pos, colour }]
const WHITE = new THREE.Color(0xffffff);

function syncBuildings(state) {
  const { owner, buildings } = state.regions;
  if (!buildings) return;
  const key = owner.join("") + "|" + buildings.join(",");
  if (key === buildingsKey) return;          // nothing changed on the surface
  buildingsKey = key;

  const colours = {};
  for (const f of state.factions) colours[f.fid] = new THREE.Color(f.colour);
  for (const lm of LANDMARKS) landmarkRegions[lm.key] = [];
  let towerCount = 0;

  for (let rid = 0; rid < owner.length; rid++) {
    const own = owner[rid];
    if (own < 0) continue;
    const code = buildings[rid] || 0;
    const total = code & 15;
    const mask = code >> 4;
    const colour = colours[own] || new THREE.Color(0xffffff);

    // skyline towers: density follows development
    const n = Math.min(1 + Math.ceil(total / 2.5), 6);
    for (let i = 0; i < n && towerCount < MAX_TOWERS; i++) {
      const jx = hash01(rid * 7 + i * 13) - 0.5;
      const jy = hash01(rid * 11 + i * 17) - 0.5;
      const pos = regionSurfacePos(rid, jx, jy);
      const h = 0.008 + 0.018 * hash01(rid * 3 + i * 29) * (0.5 + total / 12);
      dummy.position.copy(pos);
      q.setFromUnitVectors(upY, pos.clone().normalize());
      dummy.quaternion.copy(q);
      dummy.scale.set(0.0045, h, 0.0045);
      dummy.translateY(h / 2);
      dummy.updateMatrix();
      towerMesh.setMatrixAt(towerCount, dummy.matrix);
      towerMesh.setColorAt(towerCount, colour.clone().lerp(new THREE.Color(0xcfd6ff), 0.35));
      towerCount++;
    }

    // record landmark sites (placed by the LOD pass, nearest-to-camera first)
    for (const lm of LANDMARKS) {
      if (!(mask & lm.bit)) continue;
      const jx = hash01(rid * 19 + lm.bit) - 0.5;
      const jy = hash01(rid * 23 + lm.bit * 3) - 0.5;
      const pos = regionSurfacePos(rid, jx * 0.6, jy * 0.6);
      landmarkRegions[lm.key].push({ pos, colour: colour.clone().lerp(WHITE, 0.22) });
    }
  }

  towerMesh.count = towerCount;
  towerMesh.instanceMatrix.needsUpdate = true;
  if (towerMesh.instanceColor) towerMesh.instanceColor.needsUpdate = true;
  landmarkLODDirty = true;

  // capital beacons follow living factions
  const aliveCaps = new Map();
  for (const f of state.factions) {
    if (f.alive && f.capital >= 0) aliveCaps.set(f.fid, f);
  }
  for (const [fid, b] of beacons) {
    if (!aliveCaps.has(fid)) { beaconGroup.remove(b.group); beacons.delete(fid); }
  }
  for (const [fid, f] of aliveCaps) {
    let b = beacons.get(fid);
    if (!b) {
      b = { group: makeBeacon(f.colour), rid: -1 };
      beaconGroup.add(b.group);
      beacons.set(fid, b);
    }
    if (b.rid !== f.capital) {
      b.rid = f.capital;
      const pos = regionSurfacePos(f.capital);
      b.group.position.copy(pos);
      b.group.quaternion.setFromUnitVectors(upY, pos.clone().normalize());
    }
  }
}

// Place each landmark type's nearest-to-camera instances (bounded triangle
// budget). Called when the building data changes or the camera moves.
function refreshLandmarkLOD() {
  const camPos = camera.position;
  for (const lm of LANDMARKS) {
    const list = landmarkRegions[lm.key] || [];
    let items = list;
    if (list.length > LANDMARK_CAP) {
      items = list
        .map((it) => ({ it, d: it.pos.distanceToSquared(camPos) }))
        .sort((a, b) => a.d - b.d)
        .slice(0, LANDMARK_CAP)
        .map((x) => x.it);
    }
    const mesh = landmarkMeshes[lm.key];
    let n = 0;
    for (const it of items) {
      dummy.position.copy(it.pos);
      q.setFromUnitVectors(upY, it.pos.clone().normalize());
      dummy.quaternion.copy(q);
      dummy.scale.setScalar(lm.scale);
      dummy.updateMatrix();
      mesh.setMatrixAt(n, dummy.matrix);
      mesh.setColorAt(n, it.colour);
      n++;
    }
    mesh.count = n;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }
  landmarkLODDirty = false;
}

// ---------------------------------------------------------------------------
// Army markers: Quaternius CC0 models with per-type variants
// ---------------------------------------------------------------------------

const armyGroup = new THREE.Group();
scene.add(armyGroup);
const armyMeshes = new Map();      // aid -> {group, target, from, t, ...}

// Per-type unit variants (Quaternius CC0). Add more GLBs to
// web_viewer/models/units/ and extend the lists; the procedural shapes cover
// any variant that fails to load.
const UNIT_VARIANTS = {
  infantry: ["infantry_a", "infantry_b"],
  armor:    ["armor_a", "armor_b"],
  aircraft: ["aircraft_a", "aircraft_b", "aircraft_c"],
  fleet:    ["fleet_a", "fleet_b", "fleet_c", "fleet_d"],
};
const glbVariants = { infantry: [], armor: [], aircraft: [], fleet: [] };
for (const kind in UNIT_VARIANTS) {
  UNIT_VARIANTS[kind].forEach((file, idx) => {
    gltfLoader.load(`/models/units/${file}.glb`, (g) => {
      const wrap = new THREE.Group();
      g.scene.rotation.x = -Math.PI / 2;     // lie tangent under marker lookAt()
      wrap.add(g.scene);
      glbVariants[kind][idx] = wrap;
    }, undefined, () => { /* procedural fallback */ });
  });
}

function dominantUnit(comp) {
  const ATK = { infantry: 1.0, armor: 3.0, aircraft: 4.5, fleet: 7.0 };
  let best = "infantry", bestScore = -1;
  for (const [k, n] of Object.entries(comp || {})) {
    const score = (ATK[k] || 1) * n;
    if (score > bestScore) { bestScore = score; best = k; }
  }
  return best;
}

function makeArmyModel(colourHex, power, kind = "infantry", variant = 0) {
  const colour = new THREE.Color(colourHex);
  const s = Math.min(0.016 + Math.sqrt(Math.max(power, 1)) * 0.0035, 0.06);

  const avail = (glbVariants[kind] || []).filter(Boolean);
  if (avail.length) {
    const model = avail[variant % avail.length].clone(true);
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    model.scale.setScalar((s * 4.2) / size);
    model.traverse((o) => {
      if (o.isMesh && o.material) {
        o.material = o.material.clone();
        if (o.material.color) o.material.color.lerp(colour, 0.32);
      }
    });
    return model;
  }

  const mat = new THREE.MeshStandardMaterial({ color: colour, roughness: 0.5, metalness: 0.35 });
  const dark = new THREE.MeshStandardMaterial({ color: colour.clone().multiplyScalar(0.55), roughness: 0.6 });
  const glowMat = new THREE.MeshBasicMaterial({ color: 0xffeeaa });
  const g = new THREE.Group();

  if (kind === "armor") {
    // low-poly tank: hull + turret + barrel
    const hull = new THREE.Mesh(new THREE.BoxGeometry(s * 1.6, s * 0.5, s * 2.2), mat);
    g.add(hull);
    const turret = new THREE.Mesh(new THREE.CylinderGeometry(s * 0.55, s * 0.65, s * 0.5, 8), dark);
    turret.position.y = s * 0.5;
    g.add(turret);
    const barrel = new THREE.Mesh(new THREE.CylinderGeometry(s * 0.1, s * 0.1, s * 1.6, 6), dark);
    barrel.rotation.x = Math.PI / 2;
    barrel.position.set(0, s * 0.5, s * 1.0);
    g.add(barrel);
  } else if (kind === "aircraft") {
    // strike wing: fuselage cone + swept wings
    const hull = new THREE.Mesh(new THREE.ConeGeometry(s * 0.55, s * 2.4, 6), mat);
    hull.rotation.x = Math.PI / 2;
    g.add(hull);
    const wing = new THREE.Mesh(new THREE.BoxGeometry(s * 2.4, s * 0.12, s * 0.7), dark);
    wing.position.z = -s * 0.35;
    g.add(wing);
    const glow = new THREE.Mesh(new THREE.SphereGeometry(s * 0.25, 8, 8), glowMat);
    glow.position.z = -s * 1.2;
    g.add(glow);
  } else if (kind === "fleet") {
    // capital ship: long hull + bridge + twin engines
    const hull = new THREE.Mesh(new THREE.BoxGeometry(s * 0.8, s * 0.45, s * 3.0), mat);
    g.add(hull);
    const bow = new THREE.Mesh(new THREE.ConeGeometry(s * 0.45, s * 1.0, 4), mat);
    bow.rotation.x = Math.PI / 2;
    bow.position.z = s * 1.9;
    g.add(bow);
    const bridge = new THREE.Mesh(new THREE.BoxGeometry(s * 0.45, s * 0.55, s * 0.6), dark);
    bridge.position.set(0, s * 0.45, -s * 0.7);
    g.add(bridge);
    for (const dx of [-0.3, 0.3]) {
      const eng = new THREE.Mesh(new THREE.SphereGeometry(s * 0.18, 8, 8), glowMat);
      eng.position.set(s * dx, 0, -s * 1.6);
      g.add(eng);
    }
  } else {
    // infantry corps: banner pole + flag + base block
    const base = new THREE.Mesh(new THREE.BoxGeometry(s * 1.1, s * 0.35, s * 1.1), dark);
    g.add(base);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(s * 0.07, s * 0.07, s * 1.9, 6), mat);
    pole.position.y = s * 1.1;
    g.add(pole);
    const flag = new THREE.Mesh(new THREE.BoxGeometry(s * 0.9, s * 0.55, s * 0.06), mat);
    flag.position.set(s * 0.5, s * 1.7, 0);
    g.add(flag);
  }
  return g;
}

function slerpVec(a, b, t) {
  const A = a.clone().normalize(), B = b.clone().normalize();
  const dot = THREE.MathUtils.clamp(A.dot(B), -1, 1);
  const th = Math.acos(dot);
  if (th < 1e-5) return B;
  const s = Math.sin(th);
  return A.multiplyScalar(Math.sin((1 - t) * th) / s)
          .add(B.multiplyScalar(Math.sin(t * th) / s));
}

function syncArmies(state) {
  const colours = {};
  for (const f of state.factions) colours[f.fid] = f.colour;
  const seen = new Set();

  for (const a of state.armies) {
    seen.add(a.aid);
    const pos = latLonToVec3(a.lat, a.lon, GLOBE_R * 1.045);
    const kind = dominantUnit(a.comp);
    let entry = armyMeshes.get(a.aid);
    if (!entry) {
      const model = makeArmyModel(colours[a.fid] || "#ffffff", a.power, kind, a.aid);
      armyGroup.add(model);
      model.position.copy(pos);
      entry = {
        group: model, target: pos.clone(), from: pos.clone(), t: 1,
        power: a.power, fid: a.fid, kind, phase: Math.random() * Math.PI * 2,
      };
      armyMeshes.set(a.aid, entry);
    }
    if (entry.target.distanceToSquared(pos) > 1e-8) {
      // new destination: start a great-circle hop from wherever we are now
      entry.from = entry.group.position.clone();
      entry.target.copy(pos);
      entry.t = 0;
    }
    entry.battle = a.in_battle;
    if (Math.abs(entry.power - a.power) > entry.power * 0.3 || entry.kind !== kind) {
      armyGroup.remove(entry.group);
      entry.group = makeArmyModel(colours[a.fid] || "#ffffff", a.power, kind, a.aid);
      entry.group.position.copy(entry.target).normalize().multiplyScalar(GLOBE_R * 1.045);
      armyGroup.add(entry.group);
      entry.power = a.power;
      entry.kind = kind;
      entry.t = 1;
    }
  }
  for (const [aid, entry] of armyMeshes) {
    if (!seen.has(aid)) {
      armyGroup.remove(entry.group);
      armyMeshes.delete(aid);
    }
  }
}

// ---------------------------------------------------------------------------
// Battle flashes
// ---------------------------------------------------------------------------

const flashGroup = new THREE.Group();
scene.add(flashGroup);
let flashes = [];
const seenBattles = new Set();

function spawnBattleFlashes(state, regionLatLon) {
  for (const b of state.battles) {
    const key = `${b.tick}:${b.region}:${b.attacker}`;
    if (seenBattles.has(key)) continue;
    seenBattles.add(key);
    if (seenBattles.size > 600) {
      const it = seenBattles.values();
      for (let i = 0; i < 200; i++) seenBattles.delete(it.next().value);
    }
    const [lat, lon] = regionLatLon(b.region);
    const pos = latLonToVec3(lat, lon, GLOBE_R * 1.012);

    // shockwave ring
    const mesh = new THREE.Mesh(
      new THREE.RingGeometry(0.012, 0.05, 24),
      new THREE.MeshBasicMaterial({ color: 0xff5533, transparent: true, opacity: 0.95,
        side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    mesh.position.copy(pos);
    mesh.lookAt(pos.clone().multiplyScalar(2));
    flashGroup.add(mesh);
    flashes.push({ mesh, age: 0 });

    // core flash that blooms
    const core = new THREE.Mesh(
      new THREE.SphereGeometry(0.012, 8, 8),
      new THREE.MeshBasicMaterial({ color: 0xffd9a0, transparent: true, opacity: 1.0,
        blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    core.position.copy(pos);
    flashGroup.add(core);
    flashes.push({ mesh: core, age: 0, core: true });

    // debris burst: a handful of particles thrown outward
    const N = 16;
    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(N * 3);
    const vels = [];
    const normal = pos.clone().normalize();
    for (let i = 0; i < N; i++) {
      positions.set([pos.x, pos.y, pos.z], i * 3);
      const v = new THREE.Vector3().randomDirection();
      v.addScaledVector(normal, 1.2).normalize().multiplyScalar(0.08 + Math.random() * 0.12);
      vels.push(v);
    }
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({
      color: 0xffaa55, size: 0.008, transparent: true, opacity: 1.0,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    flashGroup.add(pts);
    particleBursts.push({ pts, vels, age: 0 });
  }
}

let particleBursts = [];

// ---------------------------------------------------------------------------
// Trade route arcs
// ---------------------------------------------------------------------------

const tradeGroup = new THREE.Group();
scene.add(tradeGroup);
let tradeKey = "";

function syncTrade(state, regionLatLon) {
  const key = JSON.stringify(state.trade_routes) + JSON.stringify(state.blocked_routes || [])
    + JSON.stringify(state.factions.map(f => f.capital));
  if (key === tradeKey) return;
  tradeKey = key;
  tradeGroup.clear();

  const drawArc = (a, b, material, dashed) => {
    const fa = state.factions[a], fb = state.factions[b];
    if (!fa.alive || !fb.alive || fa.capital < 0 || fb.capital < 0) return;
    const [la1, lo1] = regionLatLon(fa.capital);
    const [la2, lo2] = regionLatLon(fb.capital);
    const p1 = latLonToVec3(la1, lo1, GLOBE_R * 1.01);
    const p2 = latLonToVec3(la2, lo2, GLOBE_R * 1.01);
    const mid = p1.clone().add(p2).multiplyScalar(0.5).normalize()
      .multiplyScalar(GLOBE_R * (1.12 + p1.distanceTo(p2) * 0.22));
    const curve = new THREE.QuadraticBezierCurve3(p1, mid, p2);
    const geo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(40));
    const line = new THREE.Line(geo, material);
    if (dashed) line.computeLineDistances();
    tradeGroup.add(line);
  };

  const activeMat = new THREE.LineBasicMaterial({ color: 0x44dd88, transparent: true, opacity: 0.45 });
  const blockedMat = new THREE.LineDashedMaterial({
    color: 0xff5544, transparent: true, opacity: 0.55, dashSize: 0.035, gapSize: 0.03,
  });
  for (const [a, b] of state.trade_routes) drawArc(a, b, activeMat, false);
  for (const [a, b] of (state.blocked_routes || [])) drawArc(a, b, blockedMat, true);
}

// ---------------------------------------------------------------------------
// UI panels
// ---------------------------------------------------------------------------

const elTick = document.getElementById("tick");
const elFacList = document.getElementById("facList");
const elEvList = document.getElementById("evList");
const elDetail = document.getElementById("detail");
const elDetailTitle = document.getElementById("detailTitle");
const elDetailBody = document.getElementById("detailBody");

const everAlive = new Set();

function renderFactions(state) {
  const rows = [];
  for (const f of state.factions) {
    if (f.alive) everAlive.add(f.fid);
    // hide factions that never entered the stage (dormant rebels)
    if (!f.alive && !everAlive.has(f.fid)) continue;
    const wars = f.at_war_with.map(i => state.factions[i].name.split(" ")[0]).join(", ");
    const allies = (state.diplomacy.alliances || [])
      .filter(p => p.includes(f.fid))
      .map(p => state.factions[p[0] === f.fid ? p[1] : p[0]].name.split(" ")[0]).join(", ");
    const suzerain = f.suzerain >= 0 ? state.factions[f.suzerain].name.split(" ")[0] : "";
    const techStr = `M${f.tech.military} E${f.tech.economy} S${f.tech.science} I${f.tech.infrastructure}`;
    const leader = f.leader ? f.leader.name : "—";
    rows.push(`
      <div class="fac ${f.alive ? "" : "dead"}" style="border-left-color:${f.colour}">
        <div class="name" style="color:${f.colour}">${f.name}
          ${wars ? `<span class="war-tag">⚔ ${wars}</span>` : ""}
          ${allies ? `<span class="ally-tag">🤝 ${allies}</span>` : ""}
          ${suzerain ? `<span class="vassal-tag">⛓ ${suzerain}</span>` : ""}
        </div>
        <div class="row"><span>👑 <b>${leader}</b></span><span><b>${f.doctrine}</b></span></div>
        <div class="row"><span>regions <b>${f.regions}</b></span><span>power <b>${f.power}</b></span><span>₢ <b>${f.treasury}</b></span></div>
        <div class="row"><span>gdp <b>${f.gdp}</b></span><span>tech <b>${techStr}</b></span></div>
      </div>`);
  }
  elFacList.innerHTML = rows.join("");
}

let lastEventTick = -1;
function renderEvents(state) {
  const last = state.events[state.events.length - 1];
  if (!last || last.tick === lastEventTick && elEvList.childElementCount) { /* cheap skip */ }
  const html = [...state.events].reverse().map(ev =>
    `<div class="ev ${ev.type}"><span class="t">${ev.tick}</span><span class="txt">${ev.text}</span></div>`
  ).join("");
  elEvList.innerHTML = html;
  if (last) lastEventTick = last.tick;
}

// charts
function drawChart(canvasId, series, colours, ticks) {
  const cv = document.getElementById(canvasId);
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  let max = 1;
  for (const s of series) for (const v of s) if (v > max) max = v;
  ctx.lineWidth = 1.4;
  series.forEach((s, i) => {
    if (!s.length) return;
    ctx.strokeStyle = colours[i];
    ctx.beginPath();
    s.forEach((v, j) => {
      const x = (j / Math.max(s.length - 1, 1)) * (cv.width - 4) + 2;
      const y = cv.height - 3 - (v / max) * (cv.height - 8);
      j === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

// ---------------------------------------------------------------------------
// Region picking
// ---------------------------------------------------------------------------

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let pointerDownAt = null;

canvas.addEventListener("pointerdown", (e) => { pointerDownAt = [e.clientX, e.clientY]; });
canvas.addEventListener("pointerup", async (e) => {
  if (!pointerDownAt) return;
  const dx = e.clientX - pointerDownAt[0], dy = e.clientY - pointerDownAt[1];
  pointerDownAt = null;
  if (dx * dx + dy * dy > 25) return;          // it was a drag
  pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
  pointer.y = -(e.clientY / window.innerHeight) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObject(globe);
  if (!hits.length) { elDetail.style.display = "none"; return; }
  const uv = hits[0].uv;
  const col = Math.floor(uv.x * REGION_COLS) % REGION_COLS;
  const row = REGION_ROWS - 1 - Math.floor(uv.y * REGION_ROWS);
  const rid = THREE.MathUtils.clamp(row, 0, REGION_ROWS - 1) * REGION_COLS + col;
  try {
    const detail = await (await fetch(`/api/region?id=${rid}`)).json();
    showDetail(detail);
  } catch { /* server gone */ }
});

function showDetail(d) {
  elDetailTitle.textContent = `REGION ${d.rid} — ${d.owner_name.toUpperCase()}`;
  const buildings = Object.entries(d.buildings).map(([k, n]) => `${k}×${n}`).join(", ") || "—";
  const constr = d.construction.map(c => `${c.key} (${c.ticks_left}t)`).join(", ") || "—";
  const armies = d.armies.map(a => `F${a.fid}: ${Object.entries(a.comp).map(([k, n]) => `${n} ${k}`).join(", ")} [${a.stance}]`).join("<br>") || "—";
  elDetailBody.innerHTML = `<table>
    <tr><td>population</td><td>${d.population} M</td></tr>
    <tr><td>unrest / devastation</td><td>${d.unrest} / ${d.devastation}</td></tr>
    <tr><td>fertility / materials / energy</td><td>${d.fertility} / ${d.materials_richness} / ${d.energy_potential}</td></tr>
    <tr><td>stock</td><td>m ${d.stock.materials} · f ${d.stock.food} · e ${d.stock.energy}</td></tr>
    <tr><td>militia</td><td>${d.militia}</td></tr>
    <tr><td>buildings</td><td>${buildings}</td></tr>
    <tr><td>constructing</td><td>${constr}</td></tr>
    <tr><td>armies</td><td>${armies}</td></tr>
  </table>`;
  elDetail.style.display = "block";
}

// ---------------------------------------------------------------------------
// Controls: speed / save / reset
// ---------------------------------------------------------------------------

document.querySelectorAll("#topbar button[data-speed]").forEach(btn => {
  btn.addEventListener("click", async () => {
    document.querySelectorAll("#topbar button[data-speed]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    await fetch(`/api/speed?value=${btn.dataset.speed}`);
  });
});
document.getElementById("saveBtn").addEventListener("click", () => fetch("/api/save"));
document.getElementById("resetBtn").addEventListener("click", () => {
  if (confirm("Restart the simulation?")) fetch(`/api/reset?seed=${Math.floor(Math.random() * 10000)}`);
});

// ---------------------------------------------------------------------------
// Timeline scrubbing (history of ownership)
// ---------------------------------------------------------------------------

const tlSlider = document.getElementById("tlSlider");
const tlLabel = document.getElementById("tlLabel");
const tlLive = document.getElementById("tlLive");
let timelineData = null;
let scrubbing = false;

async function refreshTimeline() {
  try {
    timelineData = await (await fetch("/api/timeline")).json();
    if (!scrubbing && timelineData.keyframes.length) {
      tlSlider.max = String(timelineData.keyframes.length - 1);
      tlSlider.value = tlSlider.max;
    }
  } catch { /* server gone */ }
  setTimeout(refreshTimeline, 8000);
}
refreshTimeline();

function paintKeyframe(idx) {
  if (!timelineData) return;
  const kf = timelineData.keyframes[idx];
  if (!kf) return;
  const colours = {};
  for (const f of timelineData.factions) colours[f.fid] = f.colour;
  paintCityBase();
  for (let row = 0; row < REGION_ROWS; row++) {
    for (let col = 0; col < REGION_COLS; col++) {
      const rid = row * REGION_COLS + col;
      const ch = kf.owner[rid];                 // compact string keyframe
      const own = ch === "." ? -1 : parseInt(ch, 10);
      if (own < 0) continue;
      texCtx.globalAlpha = 0.55;
      texCtx.fillStyle = colours[own];
      texCtx.fillRect(col * PX, (REGION_ROWS - 1 - row) * PX, PX, PX);
    }
  }
  texCtx.globalAlpha = 1.0;
  mapTexture.needsUpdate = true;
  tlLabel.textContent = `tick ${kf.tick}`;
}

tlSlider.addEventListener("input", () => {
  scrubbing = true;
  tlLive.classList.remove("live");
  paintKeyframe(parseInt(tlSlider.value, 10));
});
tlLive.addEventListener("click", () => {
  scrubbing = false;
  tlLive.classList.add("live");
  tlLabel.textContent = "history";
  if (timelineData) tlSlider.value = String(timelineData.keyframes.length - 1);
  if (latestState) paintRegions(latestState);
});

// ---------------------------------------------------------------------------
// Poll loop
// ---------------------------------------------------------------------------

let latestState = null;

function regionLatLonFactory(state) {
  return (rid) => {
    const row = Math.floor(rid / REGION_COLS), col = rid % REGION_COLS;
    const lat = -89 + (178 * (row + 0.5)) / REGION_ROWS;
    const lon = (360 * (col + 0.5)) / REGION_COLS;
    return [lat, lon];
  };
}

async function poll() {
  try {
    const state = await (await fetch("/api/state")).json();
    latestState = state;
    const rll = regionLatLonFactory(state);
    elTick.textContent = `tick ${state.tick}`;
    if (!scrubbing) paintRegions(state);
    syncBuildings(state);
    syncArmies(state);
    spawnBattleFlashes(state, rll);
    syncTrade(state, rll);
    renderFactions(state);
    renderEvents(state);
    drawChart("chartRegions", state.charts.regions, state.factions.map(f => f.colour));
    drawChart("chartPower", state.charts.power, state.factions.map(f => f.colour));
  } catch { /* server not ready */ }
  setTimeout(poll, POLL_MS);
}
poll();

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------

const clock = new THREE.Clock();

// debug handle for diagnostics from the console
window.__rts = { scene, camera, controls, towerMesh, landmarkMeshes, beacons, armyMeshes };

let lodTimer = 0;
const lastCamPos = new THREE.Vector3();

function animate() {
  requestAnimationFrame(animate);
  const dt = clock.getDelta();

  // landmark LOD: refresh nearest-to-camera buildings on data change or after
  // the camera has moved, throttled so sorting stays cheap
  lodTimer += dt;
  if (lodTimer > 0.25) {
    lodTimer = 0;
    if (landmarkLODDirty || camera.position.distanceToSquared(lastCamPos) > 2e-4) {
      refreshLandmarkLOD();
      lastCamPos.copy(camera.position);
    }
  }

  // armies travel along great-circle arcs with a small altitude hop
  for (const [, entry] of armyMeshes) {
    const g = entry.group;
    if (entry.t < 1) {
      entry.t = Math.min(1, entry.t + dt * 1.6);
      const dir = slerpVec(entry.from, entry.target, entry.t);
      const hop = 0.06 * Math.sin(Math.PI * entry.t);
      g.position.copy(dir.multiplyScalar(GLOBE_R * 1.045 + hop));
    } else if (entry.kind === "aircraft" || entry.kind === "fleet") {
      // air and orbital assets hover with a gentle bob
      const bob = 0.005 * Math.sin(clock.elapsedTime * 2.0 + entry.phase);
      g.position.copy(entry.target).normalize()
        .multiplyScalar(GLOBE_R * 1.045 + bob);
    }
    g.lookAt(0, 0, 0);
    g.rotateZ(clock.elapsedTime * 0.35 + entry.phase);   // slow display rotation
    if (entry.battle) {
      g.rotation.z += Math.sin(clock.elapsedTime * 30) * 0.05;   // shake in combat
    }
  }

  // battle flash decay
  flashes = flashes.filter(f => {
    f.age += dt;
    if (f.core) {
      f.mesh.scale.setScalar(1 + f.age * 6.0);
      f.mesh.material.opacity = Math.max(0, 1.0 - f.age * 2.6);
      if (f.age > 0.4) { flashGroup.remove(f.mesh); f.mesh.geometry.dispose(); f.mesh.material.dispose(); return false; }
      return true;
    }
    const s = 1 + f.age * 3.0;
    f.mesh.scale.setScalar(s);
    f.mesh.material.opacity = Math.max(0, 0.95 - f.age * 1.1);
    if (f.age > 0.95) { flashGroup.remove(f.mesh); f.mesh.geometry.dispose(); f.mesh.material.dispose(); return false; }
    return true;
  });

  // debris particles fly outward and fade
  particleBursts = particleBursts.filter(b => {
    b.age += dt;
    const attr = b.pts.geometry.getAttribute("position");
    for (let i = 0; i < b.vels.length; i++) {
      attr.setXYZ(i,
        attr.getX(i) + b.vels[i].x * dt,
        attr.getY(i) + b.vels[i].y * dt,
        attr.getZ(i) + b.vels[i].z * dt);
    }
    attr.needsUpdate = true;
    b.pts.material.opacity = Math.max(0, 1.0 - b.age * 1.4);
    if (b.age > 0.8) {
      flashGroup.remove(b.pts); b.pts.geometry.dispose(); b.pts.material.dispose();
      return false;
    }
    return true;
  });

  // capital beacons breathe
  for (const [, b] of beacons) {
    const beam = b.group.children[0];
    beam.material.opacity = 0.4 + 0.2 * Math.sin(clock.elapsedTime * 2.4 + b.rid);
  }

  controls.update();
  composer.render();
}
animate();

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
});
