import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";

const canvas = document.getElementById("scene");
const statusEl = document.getElementById("status");
const progressFillEl = document.getElementById("progressFill");
const ASSET_VERSION = "20260421d";

function assetUrl(path) {
  return `${path}?v=${ASSET_VERSION}`;
}

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

function setProgress(p) {
  if (!progressFillEl) return;
  const clamped = Math.max(0, Math.min(1, p));
  progressFillEl.style.width = `${(clamped * 100).toFixed(1)}%`;
}

setStatus("Loading textures...");
setProgress(0.02);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.65;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000); // overridden by stars.jpg once loaded

const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.1, 200);
camera.position.set(0.0, 3.8, 2.5);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.minDistance = 2.2;
controls.maxDistance = 10.0;
controls.autoRotate = false;

const ambient = new THREE.AmbientLight(0x264066, 0.12);
scene.add(ambient);

const sun = new THREE.DirectionalLight(0xe8c870, 1.0);
sun.position.set(5, 2.5, 2.2);
sun.castShadow = true;
sun.shadow.mapSize.width = 1024;
sun.shadow.mapSize.height = 1024;
scene.add(sun);

// Sun disc mesh — visible bright point in scene (textured with real sun surface)
const sunGeo = new THREE.SphereGeometry(0.14, 32, 32);
const sunMat = new THREE.MeshBasicMaterial({ color: 0xfff8e0 }); // texture applied after load
const sunMesh = new THREE.Mesh(sunGeo, sunMat);
sunMesh.position.copy(sun.position);
scene.add(sunMesh);

// === ANIMATED SUN CORONA SHADER ===
// FrontSide sphere: rim=1 at edges (halo), rim=0 at centre (transparent) → ring glow
const coronaUniforms = {
  time:    { value: 0.0 },
  color:   { value: new THREE.Color(0xffe480) },
};
const makeCLayer = (radius, col, strength) => {
  const mat = new THREE.ShaderMaterial({
    uniforms: { time: { value: 0.0 }, color: { value: new THREE.Color(col) } },
    vertexShader: `
      varying float vRim;
      void main() {
        vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
        vec3 n = normalize(normalMatrix * normal);
        vec3 v = normalize(-mvPos.xyz);
        vRim = 1.0 - max(0.0, dot(n, v));
        gl_Position = projectionMatrix * mvPos;
      }
    `,
    fragmentShader: `
      uniform float time;
      uniform vec3  color;
      varying float vRim;
      void main() {
        float pulse = 0.80 + 0.12 * sin(time * 2.1) + 0.05 * sin(time * 8.4 + 1.2);
        float alpha = pow(vRim, ${strength.toFixed(1)}) * pulse;
        gl_FragColor = vec4(color * (0.6 + 0.4 * pulse), alpha);
      }
    `,
    side: THREE.FrontSide,
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
  });
  return new THREE.Mesh(new THREE.SphereGeometry(radius, 32, 32), mat);
};

// Three corona layers — tight rim halos, progressively dimmer
const coronaInner = makeCLayer(0.17, 0xffffff,  2.8);
const coronaMid   = makeCLayer(0.22, 0xffdd55,  3.5);
const coronaOuter = makeCLayer(0.34, 0xff8800,  5.0);
const coronaLayers = [coronaInner, coronaMid, coronaOuter];
for (const m of coronaLayers) scene.add(m);

const fill = new THREE.DirectionalLight(0x4c76b7, 0.15);
fill.position.set(-3.0, -1.6, -1.2);
scene.add(fill);

const manager = new THREE.LoadingManager();
manager.onProgress = (_url, itemsLoaded, itemsTotal) => {
  if (itemsTotal > 0) {
    setProgress(0.08 + 0.78 * (itemsLoaded / itemsTotal));
    setStatus(`Loading textures ${itemsLoaded}/${itemsTotal}...`);
  }
};
manager.onLoad = () => {
  setProgress(0.95);
  setStatus("Initializing scene...");
  // Apply stars as equirectangular scene background
  scene.background = starsMap;
  // Apply real sun surface texture
  sunMat.map = sunTexMap;
  sunMat.color.set(0xffffff);
  sunMat.needsUpdate = true;
  // Scene is ready
  setTimeout(() => { setStatus("Live"); setProgress(1.0); }, 400);
};
manager.onError = (url) => {
  setStatus(`Asset failed: ${url}`);
};

const loader = new THREE.TextureLoader(manager);
const dayMap   = loader.load(assetUrl("./data/coruscant_diffuse.jpg"));
const nightMap = loader.load(assetUrl("./data/coruscant_lights_metropolis.jpg"));
const cloudMap = loader.load(assetUrl("./data/coruscant_clouds.jpg"));
const specularMap = loader.load(assetUrl("./data/coruscant_specular.jpg"));
const bumpMap  = loader.load(assetUrl("./data/coruscant_bump.jpg"));
const cloudBumpMap = loader.load(assetUrl("./data/coruscant_clouds_bump.jpg"));

// Stars background + sun surface texture
const starsMap = loader.load(assetUrl("./data/stars.jpg"));
const sunTexMap = loader.load(assetUrl("./data/sun.jpg"));

const maxAniso = renderer.capabilities.getMaxAnisotropy();

for (const tex of [dayMap, nightMap, cloudMap]) {
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.anisotropy = Math.max(8, maxAniso);
}
for (const tex of [specularMap, bumpMap, cloudBumpMap]) {
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.anisotropy = Math.max(8, maxAniso);
}

// Stars background — equirectangular, applied as scene.background once loaded
starsMap.colorSpace = THREE.SRGBColorSpace;
starsMap.mapping = THREE.EquirectangularReflectionMapping;

// Sun surface texture — self-luminous, no lighting
sunTexMap.colorSpace = THREE.SRGBColorSpace;

const planetGeo = new THREE.IcosahedronGeometry(1, 64);
const planetMat = new THREE.MeshStandardMaterial({
  map: dayMap,
  color: new THREE.Color(1.0, 1.0, 1.0),
  roughnessMap: specularMap,
  roughness: 0.85,
  metalness: 0.0,
  bumpMap: bumpMap,
  bumpScale: 0.020,
});

const planet = new THREE.Mesh(planetGeo, planetMat);
planet.castShadow = true;
planet.receiveShadow = true;
// Coruscant axial obliquity
planet.rotation.z = THREE.MathUtils.degToRad(21);
scene.add(planet);

// City lights on the night side — AdditiveBlending means lights only
// appear where the surface is dark (no wash-out on the day side)
const lightsMat = new THREE.MeshBasicMaterial({
  map: nightMap,
  blending: THREE.AdditiveBlending,
  depthWrite: false,
});
const lightsMesh = new THREE.Mesh(planetGeo, lightsMat);
lightsMesh.rotation.z = THREE.MathUtils.degToRad(21);
scene.add(lightsMesh);

const cloudsGeo = new THREE.SphereGeometry(1.014, 192, 192);
const cloudsMat = new THREE.MeshStandardMaterial({
  map: cloudMap,
  alphaMap: cloudMap,
  bumpMap: cloudBumpMap,
  bumpScale: 0.012,
  transparent: true,
  opacity: 0.34,
  roughness: 0.98,
  metalness: 0.0,
  depthWrite: false,
  blending: THREE.NormalBlending,
  side: THREE.FrontSide,
});
const clouds = new THREE.Mesh(cloudsGeo, cloudsMat);
clouds.castShadow = false;
scene.add(clouds);

const cloudsHighGeo = new THREE.SphereGeometry(1.022, 160, 160);
const cloudsHighMat = new THREE.MeshStandardMaterial({
  map: cloudMap,
  alphaMap: cloudMap,
  transparent: true,
  opacity: 0.068,
  roughness: 0.95,
  metalness: 0.0,
  depthWrite: false,
  blending: THREE.NormalBlending,
  side: THREE.FrontSide,
});
const cloudsHigh = new THREE.Mesh(cloudsHighGeo, cloudsHighMat);
scene.add(cloudsHigh);

// Atmosphere: inner haze layer (forward-scatter on lit side)
const atmoGeo = new THREE.SphereGeometry(1.06, 128, 128);
const atmoMat = new THREE.ShaderMaterial({
  uniforms: {
    c: { value: 0.28 },
    p: { value: 5.5 },
    viewVector: { value: camera.position.clone() },
    sunDir: { value: sun.position.clone().normalize() },
  },
  vertexShader: `
    uniform vec3 viewVector;
    uniform float c;
    uniform float p;
    varying float intensity;
    varying vec3 vWorldNormal;
    void main() {
      // World-space normal so sunDir (world-space) dot products are correct
      vWorldNormal = normalize((modelMatrix * vec4(normal, 0.0)).xyz);
      vec3 vNormel = normalize(normalMatrix * viewVector);
      vec3 vNormal = normalize(normalMatrix * normal);
      intensity = pow(max(0.0, c - dot(vNormal, vNormel)), p);
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    uniform vec3 sunDir;
    varying float intensity;
    varying vec3 vWorldNormal;
    void main() {
      float sunDot = dot(vWorldNormal, normalize(sunDir));

      // Rayleigh-like scattering: blue on day limb, orange at terminator, dark on night limb
      float termFactor = smoothstep(-0.20, 0.20, sunDot);
      vec3 dayColor   = vec3(0.18, 0.52, 1.00);  // blue dayside limb
      vec3 duskColor  = vec3(1.00, 0.48, 0.12);  // orange terminator
      vec3 nightColor = vec3(0.04, 0.08, 0.22);  // dark night limb

      vec3 color;
      if (sunDot >= 0.0) {
        color = mix(duskColor, dayColor, termFactor);
      } else {
        color = mix(nightColor, duskColor, smoothstep(-0.40, 0.0, sunDot));
      }

      gl_FragColor = vec4(color * intensity, intensity * 0.55);
    }
  `,
  side: THREE.BackSide,
  blending: THREE.AdditiveBlending,
  transparent: true,
  depthWrite: false,
});
const atmosphere = new THREE.Mesh(atmoGeo, atmoMat);
scene.add(atmosphere);

// Fresnel atmosphere glow — world-space normals, physically correct limb
// Warm amber/orange for Coruscant city-planet character
const fresnelUniforms = {
  rimColor:    { value: new THREE.Color(0xff8833) },  // orange city-glow rim
  faceColor:   { value: new THREE.Color(0x000000) },
  fresnelBias:  { value: 0.08 },
  fresnelScale: { value: 1.20 },
  fresnelPower: { value: 4.2 },
};
const fresnelMat = new THREE.ShaderMaterial({
  uniforms: fresnelUniforms,
  vertexShader: `
    uniform float fresnelBias;
    uniform float fresnelScale;
    uniform float fresnelPower;
    varying float vReflectionFactor;
    void main() {
      vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
      vec4 worldPosition = modelMatrix * vec4(position, 1.0);
      vec3 worldNormal = normalize(mat3(
        modelMatrix[0].xyz, modelMatrix[1].xyz, modelMatrix[2].xyz
      ) * normal);
      vec3 I = worldPosition.xyz - cameraPosition;
      vReflectionFactor = fresnelBias + fresnelScale *
        pow(1.0 + dot(normalize(I), worldNormal), fresnelPower);
      gl_Position = projectionMatrix * mvPosition;
    }
  `,
  fragmentShader: `
    uniform vec3 rimColor;
    uniform vec3 faceColor;
    varying float vReflectionFactor;
    void main() {
      float f = clamp(vReflectionFactor, 0.0, 1.0);
      gl_FragColor = vec4(mix(faceColor, rimColor, vec3(f)), f * 0.70);
    }
  `,
  transparent: true,
  blending: THREE.AdditiveBlending,
  depthWrite: false,
  side: THREE.FrontSide,
});
const glowMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(1.02, 64), fresnelMat);
glowMesh.rotation.z = THREE.MathUtils.degToRad(21);
scene.add(glowMesh);

// === NEBULA BACKGROUND ===
// Large BackSide sphere with procedural colored gas cloud shader
const nebulaMat = new THREE.ShaderMaterial({
  side: THREE.BackSide,
  depthWrite: false,
  transparent: true,
  blending: THREE.AdditiveBlending,
  uniforms: { time: { value: 0.0 } },
  vertexShader: `
    varying vec3 vDir;
    void main() {
      vDir = position;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    varying vec3 vDir;
    float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
    float noise(vec2 p) {
      vec2 i = floor(p); vec2 f = fract(p);
      vec2 u = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash(i), hash(i + vec2(1,0)), u.x),
                 mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), u.x), u.y);
    }
    void main() {
      vec3 d = normalize(vDir);
      // Convert to spherical UV for noise sampling
      float u = atan(d.z, d.x) * 0.15915 + 0.5;
      float v = asin(clamp(d.y, -1.0, 1.0)) * 0.31831 + 0.5;
      float n1 = noise(vec2(u * 3.1, v * 2.8) + 0.5);
      float n2 = noise(vec2(u * 6.3 + 1.0, v * 5.7 + 2.0) + 0.3);
      float n  = n1 * 0.65 + n2 * 0.35;
      // Nebula color bands: purple / blue / teal
      vec3 col1 = vec3(0.28, 0.04, 0.55); // deep purple
      vec3 col2 = vec3(0.04, 0.12, 0.50); // dark blue
      vec3 col3 = vec3(0.02, 0.30, 0.40); // deep teal
      vec3 color = mix(col1, mix(col2, col3, smoothstep(0.4, 0.7, n)), smoothstep(0.3, 0.6, n));
      float alpha = pow(n, 2.8) * 0.18;
      gl_FragColor = vec4(color, alpha);
    }
  `,
});
const nebulaMesh = new THREE.Mesh(new THREE.SphereGeometry(90, 64, 64), nebulaMat);
scene.add(nebulaMesh);

// === PLANETARY RINGS — RingGeometry with correct UV remap ===
// Default Three.js RingGeometry UVs are billboard-style (wrong for ring textures).
// Fix from https://discourse.threejs.org/t/applying-a-texture-to-a-ringgeometry/9990
// UV.x must = 0 at inner edge, 1 at outer edge (radial direction).
const ringInnerR = 1.35, ringOuterR = 2.20;
const ringGeo = new THREE.RingGeometry(ringInnerR, ringOuterR, 320, 8);
{
  const pos = ringGeo.attributes.position;
  const uv  = ringGeo.attributes.uv;
  const v3  = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v3.fromBufferAttribute(pos, i);
    // U = normalized radial distance (0=inner, 1=outer)
    uv.setXY(i, (v3.length() - ringInnerR) / (ringOuterR - ringInnerR), 0.5);
  }
  uv.needsUpdate = true;
}

const ringTex = new THREE.TextureLoader().load(assetUrl('./data/saturn_ring_alpha.png'));

// alphaMap: white pixels = visible ring band, black = transparent gap
// NormalBlending with color tint — guaranteed visible unlike AdditiveBlending
const ringMat = new THREE.MeshBasicMaterial({
  color: 0xf0d090,
  alphaMap: ringTex,
  side: THREE.DoubleSide,
  transparent: true,
  opacity: 0.90,
  depthWrite: false,
});

const ringMesh = new THREE.Mesh(ringGeo, ringMat);
ringMesh.rotation.x = Math.PI / 2;
scene.add(ringMesh);


// === MOON (Jedha-class) ===
const moonOrbit = new THREE.Object3D();
moonOrbit.rotation.x = THREE.MathUtils.degToRad(14);
moonOrbit.rotation.z = THREE.MathUtils.degToRad(-8);
scene.add(moonOrbit);

const moonGeo = new THREE.SphereGeometry(0.14, 32, 32);
const moonMat = new THREE.MeshStandardMaterial({
  color: 0x888880,
  roughness: 0.88,
  metalness: 0.04,
  bumpScale: 0.015,
});
const moonMesh = new THREE.Mesh(moonGeo, moonMat);
moonMesh.position.set(2.6, 0, 0);
moonOrbit.add(moonMesh);

// Moon subtle glow (reflected city light)
const moonGlowMat = new THREE.MeshBasicMaterial({
  color: 0xffaa44,
  transparent: true,
  opacity: 0.06,
  blending: THREE.AdditiveBlending,
  depthWrite: false,
  side: THREE.BackSide,
});
const moonGlow = new THREE.Mesh(new THREE.SphereGeometry(0.19, 16, 16), moonGlowMat);
moonMesh.add(moonGlow);

// Moon orbit line (thin, dimmer than sat lines)
const moonOrbitPts = [];
for (let i = 0; i <= 256; i++) {
  const a = (i / 256) * Math.PI * 2;
  moonOrbitPts.push(new THREE.Vector3(2.6 * Math.cos(a), 0, 2.6 * Math.sin(a)));
}
const moonOrbitLine = new THREE.LineLoop(
  new THREE.BufferGeometry().setFromPoints(moonOrbitPts),
  new THREE.LineBasicMaterial({ color: 0x8899bb, transparent: true, opacity: 0.22 })
);
moonOrbit.add(moonOrbitLine);

const orbitGroup = new THREE.Group();
scene.add(orbitGroup);
const labelsGroup = new THREE.Group();
scene.add(labelsGroup);

function makeOrbitLine(radius, inc, raan, color = 0xf5f7ff) {
  const points = [];
  const n = 360;
  for (let i = 0; i <= n; i += 1) {
    const t = (i / n) * Math.PI * 2;
    const x = radius * Math.cos(t);
    const y = radius * Math.sin(t);
    points.push(new THREE.Vector3(x, y, 0));
  }
  const geo = new THREE.BufferGeometry().setFromPoints(points);
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.36 });
  const line = new THREE.LineLoop(geo, mat);
  line.rotation.x = inc;
  line.rotation.z = raan;
  return line;
}

for (let i = 0; i < 18; i += 1) {
  const radius = 1.12 + Math.random() * 0.28;
  const inc = Math.random() * Math.PI;
  const raan = Math.random() * Math.PI * 2;
  const line = makeOrbitLine(radius, inc, raan);
  orbitGroup.add(line);

  if (i < 8) {
    const div = document.createElement("div");
    div.textContent = `SAT-${i + 1}`;
    div.style.color = "#dce8ff";
    div.style.fontSize = "11px";
    div.style.textShadow = "0 0 8px rgba(0,0,0,0.8)";
    div.style.pointerEvents = "none";
    const label = new THREE.Sprite(new THREE.SpriteMaterial({ color: 0xffffff, opacity: 0.0, transparent: true }));
    label.userData.dom = div;
    labelsGroup.add(label);
    document.body.appendChild(div);
    label.position.set(radius, 0, 0);
    label.rotation.x = inc;
    label.rotation.z = raan;
  }
}

let showOrbits = true;
let showLabels = true;
window.addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() === "o") {
    showOrbits = !showOrbits;
    orbitGroup.visible = showOrbits;
  }
  if (e.key.toLowerCase() === "l") {
    showLabels = !showLabels;
    labelsGroup.visible = showLabels;
    for (const child of labelsGroup.children) {
      if (child.userData.dom) {
        child.userData.dom.style.display = showLabels ? "block" : "none";
      }
    }
  }
});

// === CORUSCANT DISTRICTS (lore-accurate) ===
const DISTRICTS = [
  { name: "Senate District",      level: "Upper City",  lat:  2,  lon:   5, color: "#ffcc44",
    desc: "Grand Convocation Chamber of the Republic. Center of galactic governance for 25,000 years. Towers rise 5 km above ground level." },
  { name: "Jedi Temple",          level: "Upper City",  lat: 14,  lon:  42, color: "#88ccff",
    desc: "Jedi Order HQ built atop an ancient Force nexus. Five distinctive spires visible from low orbit. Home to 10,000 Jedi." },
  { name: "500 Republica",        level: "Upper City",  lat:  7,  lon:  18, color: "#ffaa66",
    desc: "The most exclusive address in the galaxy. Supreme Chancellors and Senators reside here above the smog line." },
  { name: "CoCo Town",            level: "Mid-Level",   lat: 24,  lon:  62, color: "#ff8844",
    desc: "Collective Commerce District. Dex's Diner, cantinas, alien merchants. Never truly dark. Level 3204 above surface." },
  { name: "Level 1313",           level: "Underworld",  lat: -20, lon: 115, color: "#cc4444",
    desc: "Criminal underworld 1,313 levels beneath the surface. Black Sun, Pyke Syndicate, bounty hunters. Never sees sunlight." },
  { name: "Industrial Sector",    level: "Lower City",  lat: -38, lon: -75, color: "#cc9944",
    desc: "Massive power reactors, droid factories, fuel refineries. Workers never see daylight. Endless machine noise." },
  { name: "Alien Quarters",       level: "Mid-Level",   lat: 48,  lon:-118, color: "#66aa88",
    desc: "Uscru District, Corellian Quarter, Refugee Sector. Dozens of species coexist. Cheapest rents above Level 1000." },
  { name: "Galactic City Center", level: "Apex",        lat: -5,  lon: -30, color: "#ffffff",
    desc: "Pinnacle of civilization. Millions of starships land here daily. The face of the Republic to the galaxy." },
];

function latLonToLocal(lat, lon) {
  const phi   = THREE.MathUtils.degToRad(90 - lat);
  const theta = THREE.MathUtils.degToRad(lon + 90);
  return new THREE.Vector3(
    Math.sin(phi) * Math.cos(theta),
    Math.cos(phi),
    Math.sin(phi) * Math.sin(theta)
  ).normalize();
}

// Create marker meshes as children of planet (auto-rotate with it)
const markerGeo = new THREE.SphereGeometry(0.012, 8, 8);
DISTRICTS.forEach((d) => {
  d._localVec = latLonToLocal(d.lat, d.lon);
  const col = new THREE.Color(d.color);
  const dot = new THREE.Mesh(markerGeo, new THREE.MeshBasicMaterial({ color: col }));
  dot.position.copy(d._localVec).multiplyScalar(1.003);
  planet.add(dot);
  d._marker = dot;

  // Glow halo around marker
  const halo = new THREE.Mesh(
    new THREE.SphereGeometry(0.030, 8, 8),
    new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.22,
      blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.BackSide })
  );
  dot.add(halo);

  // HTML label
  const div = document.createElement("div");
  div.className = "district-label";
  div.textContent = d.name;
  div.style.color = d.color;
  document.body.appendChild(div);
  d._labelDiv = div;
});

// Info panel
const districtPanel = document.createElement("div");
districtPanel.id = "districtPanel";
districtPanel.innerHTML =
  "<div id='dpName'></div><div id='dpLevel'></div><div id='dpDesc'></div>" +
  "<div style='display:flex;gap:8px;margin-top:8px'>" +
  "<button id='dpBack'>↑ Orbital View</button>" +
  "<button id='dpCity' onclick=\"window.location.href='./city.html?district='+encodeURIComponent(document.getElementById('dpName').textContent)\">🏙 City Simulation</button>" +
  "</div>";
document.body.appendChild(districtPanel);

function showDistrictPanel(d) {
  document.getElementById("dpName").textContent = d.name;
  document.getElementById("dpLevel").textContent = d.level;
  document.getElementById("dpDesc").textContent = d.desc;
  districtPanel.classList.add("visible");
}
function hideDistrictPanel() {
  districtPanel.classList.remove("visible");
}

// === CITY SIMULATION LAYER ===
const TIER_PALETTE = {
  "Apex":        { tower: 0xd8e4f2, glass: 0x99ccff, emit: 0x1a3366, speeder: 0xffffff, fog: 0x224488 },
  "Upper City":  { tower: 0x8eaac8, glass: 0x66aaff, emit: 0x1a2f55, speeder: 0xffdd66, fog: 0x1a2b4a },
  "Mid-Level":   { tower: 0x6a7a60, glass: 0x55aa77, emit: 0x112218, speeder: 0xffaa33, fog: 0x0f1f10 },
  "Lower City":  { tower: 0x4e4030, glass: 0x996633, emit: 0x1a0e00, speeder: 0xff8800, fog: 0x130a00 },
  "Underworld":  { tower: 0x281e18, glass: 0xcc3322, emit: 0x3a0000, speeder: 0xff3300, fog: 0x200000 },
};

let cityGroup = null;
const citySpeeders = [];
let _fogPrev = null;

function disposeCityView() {
  if (cityGroup) {
    planet.remove(cityGroup);
    cityGroup.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose();
    });
    cityGroup = null;
  }
  for (const sp of citySpeeders) {
    planet.remove(sp.mesh);
    sp.mesh.geometry.dispose();
    sp.mesh.material.dispose();
  }
  citySpeeders.length = 0;
  if (_fogPrev !== null) { scene.fog = _fogPrev; _fogPrev = null; }
}

function buildCityView(district) {
  disposeCityView();
  cityGroup = new THREE.Group();
  planet.add(cityGroup);

  const pal = TIER_PALETTE[district.level] || TIER_PALETTE["Mid-Level"];

  const up = district._localVec.clone().normalize();
  const tmp = Math.abs(up.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
  const right   = new THREE.Vector3().crossVectors(up, tmp).normalize();
  const forward = new THREE.Vector3().crossVectors(right, up).normalize();

  const GRID    = 16;
  const SPACING = 0.018;
  const BASE_R  = 1.002;

  // Procedural buildings
  for (let i = 0; i < GRID; i++) {
    for (let j = 0; j < GRID; j++) {
      const ox = (i - GRID / 2 + 0.5) * SPACING;
      const oz = (j - GRID / 2 + 0.5) * SPACING;

      const h = 0.018 + Math.pow(Math.random(), 1.4) * 0.14 *
        (district.level === "Apex" ? 1.8 : district.level === "Upper City" ? 1.4 : 1.0);
      const w = 0.003 + Math.random() * 0.006;
      const d = 0.003 + Math.random() * 0.006;

      // Centre of base on sphere surface, then offset upward along normal
      const basePos = up.clone().multiplyScalar(BASE_R)
        .addScaledVector(right, ox)
        .addScaledVector(forward, oz);

      const geo = new THREE.BoxGeometry(w, h, d);
      const mat = new THREE.MeshStandardMaterial({
        color: pal.tower,
        emissive: new THREE.Color(pal.emit),
        emissiveIntensity: 0.7,
        metalness: 0.45,
        roughness: 0.55,
      });

      // Windows: random emissive on some faces
      if (Math.random() > 0.45) {
        mat.emissive.set(pal.glass);
        mat.emissiveIntensity = 0.3 + Math.random() * 0.5;
      }

      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.copy(basePos).addScaledVector(up, h / 2);
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), up);
      cityGroup.add(mesh);
    }
  }

  // Local point light to illuminate buildings
  const cityLight = new THREE.PointLight(0xffd8a0, 2.5, 0.8);
  cityLight.position.copy(up).multiplyScalar(1.22);
  cityGroup.add(cityLight);
  cityGroup.userData.light = cityLight;

  // Rooftop glow pads
  const padGeo = new THREE.CylinderGeometry(0.002, 0.002, 0.0003, 8);
  const padMat = new THREE.MeshBasicMaterial({ color: pal.glass });
  for (let k = 0; k < 18; k++) {
    const ox = (Math.random() - 0.5) * SPACING * GRID * 0.85;
    const oz = (Math.random() - 0.5) * SPACING * GRID * 0.85;
    const pos = up.clone().multiplyScalar(BASE_R + 0.10)
      .addScaledVector(right, ox).addScaledVector(forward, oz);
    const pad = new THREE.Mesh(padGeo, padMat);
    pad.position.copy(pos);
    pad.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), up);
    cityGroup.add(pad);
  }

  // Speeder light particles
  const speederGeo = new THREE.SphereGeometry(0.0012, 5, 5);
  for (let s = 0; s < 40; s++) {
    const mat = new THREE.MeshBasicMaterial({ color: pal.speeder });
    const mesh = new THREE.Mesh(speederGeo, mat);
    planet.add(mesh);
    const angle  = Math.random() * Math.PI * 2;
    const radius = 0.018 + Math.random() * 0.075;
    const h2     = BASE_R + 0.025 + Math.random() * 0.065;
    const speed  = (0.5 + Math.random() * 0.9) * (Math.random() < 0.5 ? 1 : -1);
    citySpeeders.push({ mesh, up, right, forward, angle, radius, h: h2, speed });
  }
}

// Camera zoom animation state
const camAnim = {
  active: false,
  startPos: new THREE.Vector3(),
  endPos: new THREE.Vector3(),
  startTime: 0,
  duration: 2.2,
};

document.getElementById("dpBack").addEventListener("click", () => {
  hideDistrictPanel();
  disposeCityView();
  camAnim.startPos.copy(camera.position);
  camAnim.endPos.set(0.0, 3.8, 2.5);
  camAnim.startTime = performance.now();
  camAnim.active = true;
  controls.minDistance = 2.2;
  controls.target.set(0, 0, 0);
});

// Distinguish click from drag
let _mouseDownX = 0, _mouseDownY = 0;
const raycaster = new THREE.Raycaster();
const mouse2 = new THREE.Vector2();

canvas.addEventListener("mousedown", (e) => { _mouseDownX = e.clientX; _mouseDownY = e.clientY; });
canvas.addEventListener("mouseup", (e) => {
  const dx = e.clientX - _mouseDownX, dy = e.clientY - _mouseDownY;
  if (Math.sqrt(dx * dx + dy * dy) > 5) return; // drag — ignore

  mouse2.x =  (e.clientX / window.innerWidth)  * 2 - 1;
  mouse2.y = -(e.clientY / window.innerHeight) * 2 + 1;
  raycaster.setFromCamera(mouse2, camera);
  const hits = raycaster.intersectObject(planet);
  if (!hits.length) { hideDistrictPanel(); return; }

  const hitPoint = hits[0].point;

  // Find nearest district in planet-local space
  const hitLocal = planet.worldToLocal(hitPoint.clone()).normalize();
  let nearestAngle = Infinity, nearestDistrict = DISTRICTS[0];
  DISTRICTS.forEach((d) => {
    const angle = hitLocal.angleTo(d._localVec);
    if (angle < nearestAngle) { nearestAngle = angle; nearestDistrict = d; }
  });
  showDistrictPanel(nearestDistrict);

  // Build city view at this district
  buildCityView(nearestDistrict);

  // Zoom camera along the hit-point surface normal
  const dir = hitPoint.clone().normalize();
  camAnim.startPos.copy(camera.position);
  camAnim.endPos.copy(dir.multiplyScalar(1.22));
  camAnim.startTime = performance.now();
  camAnim.active = true;
  controls.minDistance = 1.08;
});

// --- Post-processing: Bloom ---
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));

const bloomPass = new UnrealBloomPass(
  new THREE.Vector2(window.innerWidth, window.innerHeight),
  0.28,
  0.20,
  0.82
);
composer.addPass(bloomPass);
composer.addPass(new OutputPass());

async function loadMetrics() {
  const metricsEl = document.getElementById("metrics");
  try {
    const res = await fetch(assetUrl("./data/metrics.json"));
    const m = await res.json();
    const tempC = (m.temperature_k.mean - 273.15).toFixed(1);
    const tempK = m.temperature_k.mean.toFixed(1);
    const pressHpa = (m.pressure_pa.mean / 100.0).toFixed(0);
    const cloudPct = (m.cloud_fraction.mean * 100).toFixed(1);
    const precipMm = m.precipitation_mm_day.mean.toFixed(1);
    metricsEl.innerHTML = [
      `<span style="color:#ffcc66">🌡 ${tempC}°C</span> <span style="opacity:.6">(${tempK} K)</span>`,
      `<span style="color:#88ccff">🌀 ${pressHpa} hPa</span>`,
      `<span style="color:#aaddff">☁ Clouds ${cloudPct}%</span>`,
      `<span style="color:#66bbff">💧 Precip ${precipMm} mm/day</span>`,
      `<span style="opacity:.5;font-size:10px">Grid ${m.resolution.lat}×${m.resolution.lon}</span>`,
    ].join("<br>");
  } catch (_err) {
    metricsEl.textContent = "Metrics unavailable.";
  }
}
loadMetrics();

// ============================================================
// LIVE SIM STATE — polls /api/state every 1.5 s when server
// is running (sim_server.py).  Falls back silently if offline.
// ============================================================

const FACTION_HEX = ["#3372d9", "#d93333", "#33bf4d", "#cc9919", "#8c1abf"];
const FACTION_NAMES = ["Senate District", "Industrial Sector", "Commerce Ring", "Underworld", "Military Zone"];
const SPEC_HEX  = ["#4caf50", "#e53935", "#ffa726", "#7b1fa2", "#90a4ae"];
const SPEC_NAMES_SHORT = ["Agri", "Indus", "Comm", "Mil", "Res"];
const ACTION_HEX = { survive: "#ff4444", expand: "#ff9900", trade: "#44ff88", consolidate: "#4488ff", idle: "#555" };

// Sim overlay panel (injected into DOM once)
const simPanel = document.createElement("div");
simPanel.id = "simPanel";
simPanel.style.cssText = `
  position:fixed; bottom:14px; left:14px; max-width:310px;
  background:rgba(5,8,20,0.88); border:1px solid #1a2a4a;
  border-radius:8px; padding:10px 14px; color:#ccc;
  font-family:'Courier New',monospace; font-size:11px;
  pointer-events:none; z-index:200; line-height:1.55;
  backdrop-filter:blur(4px);
`;
document.body.appendChild(simPanel);

let _lastStep = -1;

function _factionRow(f, e) {
  const col   = FACTION_HEX[f.id] ?? "#aaa";
  const act   = f.last_action ?? "?";
  const actC  = ACTION_HEX[act] ?? "#aaa";
  const gdp   = e ? e.gdp_index.toFixed(2) : "–";
  return `<span style="color:${col};font-weight:bold">${f.name.padEnd(18,' ').slice(0,17)}</span>` +
         ` ${String(f.cells).padStart(5)} cells` +
         ` str=<span style="color:#ffd">${f.strength.toFixed(2)}</span>` +
         ` <span style="color:${actC}">${act.slice(0,4)}</span>` +
         ` GDP=<span style="color:#8df">${gdp}</span>`;
}

function applySimState(s) {
  if (!s || s.step === _lastStep) return;
  _lastStep = s.step;

  // Update district marker colours from faction ownership
  // Map each district lat/lon → faction cell index
  const gridLat = s.grid_lat;
  const gridLon = s.grid_lon;
  DISTRICTS.forEach((d) => {
    const latIdx = Math.round((d.lat + 90) / 180 * (gridLat - 1));
    const lonIdx = Math.round(((d.lon % 360 + 360) % 360) / 360 * (gridLon - 1));
    const row = s.faction_id[Math.max(0, Math.min(gridLat - 1, latIdx))];
    if (!row) return;
    const fid = row[Math.max(0, Math.min(gridLon - 1, lonIdx))];
    const col = new THREE.Color(FACTION_HEX[fid] ?? "#ffffff");
    d._marker.material.color.copy(col);
    d._marker.children[0]?.material.color.copy(col);  // halo
    d._labelDiv.style.color = FACTION_HEX[fid] ?? d.color;
  });

  // Build overlay HTML
  const sum = s.summary;
  const hapPct = (sum.mean_happiness * 100).toFixed(1);
  const unrPct = (sum.mean_unrest * 100).toFixed(1);
  const lines = [
    `<span style="color:#ffd060;font-size:12px;font-weight:bold">◈ CORUSCANT SIM</span>` +
    `<span style="color:#556;float:right">step ${String(s.step).padStart(5,'0')}</span>`,
    `<span style="color:#888">───────────────────────────────────</span>`,
    `😊 Happiness <b style="color:#6f6">${hapPct}%</b>` +
    `  ⚡ Unrest <b style="color:#f64">${unrPct}%</b>`,
    `🍞 Food <b>${sum.mean_food_days.toFixed(1)}d</b>` +
    `  💧 Water <b>${sum.mean_water_l.toFixed(1)}L</b>` +
    `  ⚡ Energy <b>${sum.mean_energy_kwh.toFixed(1)} kWh</b>`,
    `<span style="color:#888">───────────────────────────────────</span>`,
    `<span style="color:#aaa;font-size:10px">FACTION          CELLS  STR   ACT  GDP</span>`,
    ...s.factions.map((f, i) => _factionRow(f, s.economy?.[i])),
  ];
  simPanel.innerHTML = lines.join("<br>");
}

async function pollSimState() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    if (res.ok) {
      const s = await res.json();
      applySimState(s);
    }
  } catch (_) {
    // Server not running — overlay stays empty
  }
  setTimeout(pollSimState, 1500);
}
pollSimState();

function updateLabels() {
  for (const sprite of labelsGroup.children) {
    const dom = sprite.userData.dom;
    if (!dom) continue;
    const vec = sprite.position.clone().project(camera);
    const x = (vec.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-vec.y * 0.5 + 0.5) * window.innerHeight;
    dom.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px)`;
    dom.style.opacity = vec.z < 1 ? "0.88" : "0";
  }

  // Project district markers to screen
  const _wp = new THREE.Vector3();
  DISTRICTS.forEach((d) => {
    d._marker.getWorldPosition(_wp);
    // Only show if facing camera (dot < 0 means normal points toward camera)
    const facing = _wp.clone().normalize().dot(camera.position.clone().normalize()) > 0.05;
    const proj = _wp.clone().project(camera);
    const x = (proj.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-proj.y * 0.5 + 0.5) * window.innerHeight;
    d._labelDiv.style.transform = `translate(-50%, -50%) translate(${x}px, ${y + 18}px)`;
    d._labelDiv.style.opacity = (facing && proj.z < 1) ? "1" : "0";
    d._labelDiv.style.pointerEvents = (facing && proj.z < 1) ? "auto" : "none";
  });
}

function animate(t) {
  const dt = 0.001 * t;
  planet.rotation.y = dt * 0.06;
  lightsMesh.rotation.y = dt * 0.06;
  glowMesh.rotation.y = dt * 0.06;
  clouds.rotation.y = dt * 0.09;
  cloudsHigh.rotation.y = dt * 0.13;
  atmosphere.rotation.y = dt * 0.03;

  // Move sun slowly for live day/night dynamics.
  const sunX = 5 * Math.cos(dt * 0.08);
  const sunZ = 5 * Math.sin(dt * 0.08);
  sun.position.set(sunX, 2.5, sunZ);
  sunMesh.position.set(sunX, 2.5, sunZ);

  // Animate corona layers: follow sun, pulse time
  const coronaTime = t * 0.001;
  for (const layer of coronaLayers) {
    layer.position.set(sunX, 2.5, sunZ);
    layer.material.uniforms.time.value = coronaTime;
  }

  // Moon orbit (slower than planet)
  moonOrbit.rotation.y = dt * 0.022;

  // Update atmosphere uniforms — sunDir stays world-space (matches world-space vWorldNormal)
  atmoMat.uniforms.viewVector.value.copy(camera.position);
  atmoMat.uniforms.sunDir.value.copy(sun.position).normalize();

  controls.update();

  // Smooth camera zoom animation (ease-in-out quad)
  if (camAnim.active) {
    const p = Math.min((performance.now() - camAnim.startTime) / (camAnim.duration * 1000), 1.0);
    const ease = p < 0.5 ? 2 * p * p : -1 + (4 - 2 * p) * p;
    camera.position.lerpVectors(camAnim.startPos, camAnim.endPos, ease);
    if (p >= 1.0) camAnim.active = false;
  }

  // Animate speeder lights around city districts
  for (const sp of citySpeeders) {
    sp.angle += sp.speed * 0.010;
    const pos = sp.up.clone().multiplyScalar(sp.h)
      .addScaledVector(sp.right, Math.cos(sp.angle) * sp.radius)
      .addScaledVector(sp.forward, Math.sin(sp.angle) * sp.radius);
    sp.mesh.position.copy(pos);
  }

  composer.render();
  updateLabels();
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
});
