/**
 * Drill viewer page. Meant to run in a sandboxed <iframe> on the swimform page, which drives it
 * with postMessage; it can also be opened on its own, where a small HUD replaces the page's
 * controls. It never touches the network and has no access to the page around it.
 */
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {DRILLS, createPose, isDrillId, poseAt, type DrillId} from './stroke';
import {DEFAULT_PALETTE, Swimmer} from './swimmer';

interface InitConfig {
  drill?: DrillId;
  speed?: number;
  playing?: boolean;
  view?: ViewName;
  hud?: boolean;
}

type ViewName = 'default' | 'side' | 'front' | 'above' | 'below';
const VIEW_NAMES: ViewName[] = ['default', 'side', 'front', 'above', 'below'];

interface Drill3dApi {
  setDrill(id: DrillId): void;
  setSpeed(speed: number): void;
  setPlaying(playing: boolean): void;
  resetView(): void;
  setView(name: ViewName): void;
  /** Jump to a fraction of the drill loop and pause there. */
  seek(u: number): void;
}

declare global {
  interface Window {
    drill3d: Drill3dApi;
  }
}

/** True when this page is inside a frame on the swimform page. */
const embedded = window.parent !== window;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const init: InitConfig = readHash();

function readHash(): InitConfig {
  const params = new URLSearchParams(location.hash.slice(1));
  const drill = params.get('drill');
  const view = params.get('view') as ViewName | null;
  const speed = Number(params.get('speed'));
  const play = params.get('play');
  return {
    drill: isDrillId(drill) ? drill : undefined,
    speed: speed > 0 && speed <= 4 ? speed : undefined,
    view: view && VIEW_NAMES.includes(view) ? view : undefined,
    // Moving pictures are not essential: respect the system setting unless asked to play.
    playing: play === '1' ? true : play === '0' ? false : !reducedMotion,
    hud: params.get('hud') === '1' || (!embedded && params.get('hud') !== '0'),
  };
}

/** Tell the page around us what happened. Only the page that framed us can hear it. */
const post = (message: Record<string, unknown>) => {
  if (embedded) {
    window.parent.postMessage({swimform: 'drill3d', ...message}, '*');
  }
};

// ---------- scene ----------

const canvas = document.getElementById('scene') as HTMLCanvasElement;
let renderer: THREE.WebGLRenderer;
try {
  renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true, powerPreference: 'high-performance'});
} catch (error) {
  post({event: 'error', message: String(error)});
  throw error;
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);
renderer.toneMapping = THREE.NeutralToneMapping;

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.75;
pmrem.dispose();

const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(1.5, 4, 2.5);
const rim = new THREE.DirectionalLight(0xd8eef8, 0.7);
rim.position.set(-2, -2.5, -3);
scene.add(key, rim);

const swimmer = new Swimmer(DEFAULT_PALETTE);
scene.add(swimmer.root);

const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 50);
const TARGET = new THREE.Vector3(0, -0.08, 0.06);

const controls = new OrbitControls(camera, canvas);
controls.target.copy(TARGET);
controls.enablePan = false;
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.rotateSpeed = 0.9;
controls.minDistance = 1.6;
controls.maxDistance = 7;

// ---------- camera views ----------

/** theta: around the vertical, 0 = looking at the swimmer's face; phi: from straight above. */
const VIEWS: Record<ViewName, {theta: number; phi: number; scale: number}> = {
  default: {theta: -Math.PI / 2 + 0.6, phi: Math.PI / 2 - 0.2, scale: 1},
  side: {theta: -Math.PI / 2, phi: Math.PI / 2, scale: 1},
  front: {theta: 0, phi: Math.PI / 2 + 0.08, scale: 0.8},
  above: {theta: -Math.PI / 2, phi: 0.35, scale: 1},
  below: {theta: -Math.PI / 2, phi: Math.PI - 0.35, scale: 1},
};

/** Distance at which the whole swimmer (~2.4 m, fingertips to toes) fits across the view. */
function fitRadius() {
  const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
  const across = Math.tan(halfFov) * Math.min(camera.aspect, 1.6);
  return Math.max(2.6, 1.3 / across);
}

let flight: {from: THREE.Spherical; to: THREE.Spherical; start: number} | null = null;

function viewSpherical(name: ViewName) {
  const v = VIEWS[name];
  return new THREE.Spherical(fitRadius() * v.scale, v.phi, v.theta);
}

function jumpTo(name: ViewName) {
  camera.position.setFromSpherical(viewSpherical(name)).add(TARGET);
  controls.update();
  dirty = true;
}

function flyTo(name: ViewName) {
  const from = new THREE.Spherical().setFromVector3(camera.position.clone().sub(TARGET));
  const to = viewSpherical(name);
  // go the short way round
  while (to.theta - from.theta > Math.PI) {
    to.theta -= 2 * Math.PI;
  }
  while (from.theta - to.theta > Math.PI) {
    to.theta += 2 * Math.PI;
  }
  flight = {from, to, start: performance.now()};
}

function stepFlight(now: number) {
  if (!flight) {
    return false;
  }
  const t = Math.min(1, (now - flight.start) / 600);
  const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
  const s = new THREE.Spherical(
    THREE.MathUtils.lerp(flight.from.radius, flight.to.radius, e),
    THREE.MathUtils.lerp(flight.from.phi, flight.to.phi, e),
    THREE.MathUtils.lerp(flight.from.theta, flight.to.theta, e),
  );
  camera.position.setFromSpherical(s).add(TARGET);
  camera.lookAt(TARGET);
  if (t === 1) {
    flight = null;
    controls.update();
  }
  return true;
}

// cancel a reset flight as soon as the user grabs the model
controls.addEventListener('start', () => {
  flight = null;
});

// double-tap resets the view
let lastTap = {time: 0, x: 0, y: 0};
let down = {time: 0, x: 0, y: 0};
canvas.addEventListener('pointerdown', e => {
  down = {time: e.timeStamp, x: e.clientX, y: e.clientY};
});
canvas.addEventListener('pointerup', e => {
  const isTap = e.timeStamp - down.time < 300 && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 10;
  if (!isTap) {
    return;
  }
  const isDouble = e.timeStamp - lastTap.time < 320 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 40;
  if (isDouble) {
    flyTo('default');
    lastTap = {time: 0, x: 0, y: 0};
  } else {
    lastTap = {time: e.timeStamp, x: e.clientX, y: e.clientY};
  }
});

// ---------- playback ----------

let drill: DrillId = init.drill ?? 'single_arm';
let speed = init.speed ?? 1;
let playing = init.playing ?? true;
let time = 0;
let dirty = true;
const pose = createPose();


function resize() {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
  dirty = true;
}
window.addEventListener('resize', resize);
resize();
jumpTo('default');

let frames = 0;
let fpsWindowStart = performance.now();
let last = performance.now();
let announced = false;

renderer.setAnimationLoop(now => {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  if (playing) {
    time += dt * speed;
  }
  const flying = stepFlight(now);
  const orbiting = flying ? false : controls.update();
  if (!(playing || flying || orbiting || dirty)) {
    fpsWindowStart = now;
    frames = 0;
    return;
  }
  dirty = false;
  swimmer.apply(poseAt(drill, time, pose));
  renderer.render(scene, camera);

  if (!announced) {
    announced = true;
    post({event: 'ready'});
  }
  frames++;
  if (now - fpsWindowStart >= 1000) {
    const fps = Math.round((frames * 1000) / (now - fpsWindowStart));
    frames = 0;
    fpsWindowStart = now;
    hud?.update(fps);
  }
});

// ---------- API ----------

window.drill3d = {
  setDrill(id) {
    if (!isDrillId(id)) {
      return;
    }
    drill = id;
    dirty = true;
    hud?.update();
  },
  setSpeed(value) {
    if (typeof value === 'number' && value > 0 && value <= 4) {
      speed = value;
      hud?.update();
    }
  },
  setPlaying(value) {
    playing = Boolean(value);
    dirty = true;
    hud?.update();
  },
  resetView() {
    flyTo('default');
  },
  setView(name) {
    if (VIEW_NAMES.includes(name)) {
      flyTo(name);
    }
  },
  seek(u) {
    if (typeof u !== 'number' || !Number.isFinite(u)) {
      return;
    }
    playing = false;
    time = u * DRILLS[drill].cycleSeconds;
    dirty = true;
    hud?.update();
  },
};

// ---------- messages from the page that framed us ----------

const CALLS = new Set(['setDrill', 'setSpeed', 'setPlaying', 'resetView', 'setView', 'seek']);

window.addEventListener('message', e => {
  const data = e.data;
  if (e.source !== window.parent || !data || data.swimform !== 'drill3d' || !CALLS.has(data.call)) {
    return;
  }
  const args = Array.isArray(data.args) ? data.args.slice(0, 1) : [];
  (window.drill3d as unknown as Record<string, (...a: unknown[]) => void>)[data.call](...args);
});

// ---------- the on-screen controls, for when this page is opened on its own ----------

const hud = init.hud ? createHud() : null;
if (init.view) {
  jumpTo(init.view);
}

function createHud() {
  const el = document.createElement('div');
  el.id = 'hud';
  document.body.appendChild(el);
  const fpsLabel = document.createElement('span');
  const button = (label: string, action: () => void) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.onclick = action;
    return b;
  };
  const render = () => {
    el.replaceChildren(
      button(drill === 'single_arm' ? 'Single arm ✓' : 'Single arm', () => window.drill3d.setDrill('single_arm')),
      button(drill === 'catch_up' ? 'Catch-up ✓' : 'Catch-up', () => window.drill3d.setDrill('catch_up')),
      button(playing ? 'Pause' : 'Play', () => {
        window.drill3d.setPlaying(!playing);
      }),
      ...[0.25, 0.5, 1].map(s => button(speed === s ? `${s}× ✓` : `${s}×`, () => window.drill3d.setSpeed(s))),
      button('Reset view', () => window.drill3d.resetView()),
      fpsLabel,
    );
  };
  render();
  return {
    update(fps?: number) {
      if (fps === undefined) {
        render();
      } else {
        fpsLabel.textContent = `${fps} fps`;
      }
    },
  };
}
