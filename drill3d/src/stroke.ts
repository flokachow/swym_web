/**
 * Freestyle kinematics for the drill viewer.
 *
 * Everything here works in the swimmer's body frame (metres, origin at the pelvis):
 *   +Y forward: towards the head, the direction of travel
 *   +Z down: towards the pool floor (the face points this way)
 *   +X the swimmer's left, -X the swimmer's right
 *
 * Arms are driven by the wrist: a keyframed hand path through one stroke, solved to
 * shoulder/elbow/wrist with two-bone IK. Keys are authored for the right arm and mirrored
 * for the left. The body rolls about Y; the head stays still unless it turns to breathe.
 */
import {Vector3} from 'three';

export type Side = 'R' | 'L';
export const SIDES: readonly Side[] = ['R', 'L'];

export const BODY = {
  shoulder: new Vector3(-0.18, 0.54, 0), // right side; x is mirrored for the left
  upperArm: 0.3,
  forearm: 0.27,
  hip: new Vector3(-0.095, -0.03, 0),
  thigh: 0.44,
  shin: 0.42,
  neckBase: new Vector3(0, 0.56, 0),
  head: new Vector3(0, 0.745, 0),
} as const;

// ---------- the arm stroke ----------

type Vec = readonly [number, number, number];

interface ArmKey {
  /** Fraction of one arm stroke; 0 = the hand enters the water. */
  t: number;
  /** Wrist position relative to the (rolled) shoulder. */
  wrist: Vec;
  /** Which way the elbow points — a high elbow is a pole that points out and up (-Z). */
  pole: Vec;
  /** Which way the palm faces. */
  palm: Vec;
}

/** Right arm. The underwater phase runs 0 → 0.64, recovery 0.64 → 1. */
const ARM_KEYS: readonly ArmKey[] = [
  // entry: fingertips first, arm locked straight, tucked in close to the head (no crossover).
  // The wrist target overshoots the arm's reach on purpose — solveTwoBone clamps it to the
  // arm's full length, which is the only way to pin the elbow dead straight instead of just close.
  {t: 0.0, wrist: [0.03, 0.619, 0], pole: [-0.3, 0, -1], palm: [-0.3, 0, 1]},
  // extension: reach forward, arm still locked straight, hand a little below the shoulder
  {t: 0.12, wrist: [0.018, 0.598, 0.156], pole: [-0.2, 0, -1], palm: [-0.15, -0.2, 1]},
  // catch: the forearm tips down while the elbow stays up near the surface
  {t: 0.24, wrist: [-0.06, 0.42, 0.3], pole: [-0.5, 0.3, -1], palm: [0, -1, 0.6]},
  // early vertical forearm: hand and forearm face backwards, elbow high and wide
  {t: 0.33, wrist: [-0.08, 0.26, 0.36], pole: [-0.6, 0.4, -1], palm: [0, -1, 0.15]},
  // pull: hand passes under the chest, elbow bent ~100°
  {t: 0.45, wrist: [0.04, 0, 0.42], pole: [-1, 0, -0.3], palm: [0, -1, 0]},
  // push: elbow out to the side, forearm angled back as the hand drives past the hip
  {t: 0.56, wrist: [-0.06, -0.4, 0.26], pole: [-0.8, 0.1, -0.6], palm: [0, -1, -0.3]},
  // finish: beside the thigh, palm turning in, pinky leads out
  {t: 0.64, wrist: [-0.08, -0.54, 0.08], pole: [-0.3, 0, -1], palm: [1, -0.3, 0]},
  // early recovery: elbow lifts first, hand still trailing near the hip, outside the elbow
  {t: 0.7, wrist: [-0.1, -0.42, -0.06], pole: [-0.3, 0, -1], palm: [0.6, -0.6, -0.4]},
  // mid recovery: high elbow leads in close, relaxed hand hangs outside it, not crossing over it
  {t: 0.82, wrist: [-0.1, -0.02, -0.1], pole: [-0.4, -0.3, -1], palm: [0.4, -1, 0]},
  // late recovery: hand swings forward close to the head, palm turning down for the entry
  {t: 0.92, wrist: [0.04, 0.26, -0.1], pole: [-0.3, 0.2, -1], palm: [-0.3, 0, 1]},
];

/** Arm phase where the stroke waits with the arm extended (catch-up, the single-arm lead arm). */
const EXTENDED = 0.12;

const hermite = (p0: number, p1: number, p2: number, p3: number, t0: number, t1: number, t2: number, t3: number, s: number) => {
  const h = t2 - t1;
  const m1 = ((p2 - p0) / (t2 - t0)) * h;
  const m2 = ((p3 - p1) / (t3 - t1)) * h;
  const s2 = s * s;
  const s3 = s2 * s;
  return (2 * s3 - 3 * s2 + 1) * p1 + (s3 - 2 * s2 + s) * m1 + (-2 * s3 + 3 * s2) * p2 + (s3 - s2) * m2;
};

/** Periodic cubic Hermite through the keys with time-aware tangents, so speed is smooth. */
function sampleArm(phase: number, wrist: Vector3, pole: Vector3, palm: Vector3) {
  const t = ((phase % 1) + 1) % 1;
  const n = ARM_KEYS.length;
  let i = 0;
  for (let k = 0; k < n; k++) {
    if (ARM_KEYS[k].t <= t) {
      i = k;
    }
  }
  const k0 = ARM_KEYS[(i - 1 + n) % n];
  const k1 = ARM_KEYS[i];
  const k2 = ARM_KEYS[(i + 1) % n];
  const k3 = ARM_KEYS[(i + 2) % n];
  const t1 = k1.t;
  const t0 = k0.t < t1 ? k0.t : k0.t - 1;
  const t2 = k2.t > t1 ? k2.t : k2.t + 1;
  const t3 = k3.t > t2 ? k3.t : k3.t + 1;
  const s = (t - t1) / (t2 - t1);
  const channel = (out: Vector3, key: 'wrist' | 'pole' | 'palm') =>
    out.set(
      hermite(k0[key][0], k1[key][0], k2[key][0], k3[key][0], t0, t1, t2, t3, s),
      hermite(k0[key][1], k1[key][1], k2[key][1], k3[key][1], t0, t1, t2, t3, s),
      hermite(k0[key][2], k1[key][2], k2[key][2], k3[key][2], t0, t1, t2, t3, s),
    );
  channel(wrist, 'wrist');
  channel(pole, 'pole');
  channel(palm, 'palm');
}

const _dir = new Vector3();
const _bend = new Vector3();

/** Places mid (elbow/knee) and end (wrist/ankle) so the bones keep their length. */
function solveTwoBone(root: Vector3, target: Vector3, pole: Vector3, a: number, b: number, mid: Vector3, end: Vector3) {
  _dir.subVectors(target, root);
  const reach = _dir.length();
  _dir.divideScalar(reach || 1);
  const d = Math.min(Math.max(reach, Math.abs(a - b) + 1e-4), a + b - 1e-4);
  const cos = (a * a + d * d - b * b) / (2 * a * d);
  const sin = Math.sqrt(Math.max(0, 1 - cos * cos));
  _bend.copy(pole).addScaledVector(_dir, -pole.dot(_dir));
  if (_bend.lengthSq() < 1e-8) {
    _bend.set(0, 0, -1).addScaledVector(_dir, _dir.z);
  }
  _bend.normalize();
  mid.copy(root).addScaledVector(_dir, a * cos).addScaledVector(_bend, a * sin);
  end.copy(root).addScaledVector(_dir, d);
}

// ---------- the drills ----------

export type DrillId = 'single_arm' | 'catch_up';

interface DrillSpec {
  /** Seconds for one loop of the drill at 1x. */
  cycleSeconds: number;
  /** Downbeats (both legs together) per loop. */
  kicksPerCycle: number;
  /** Arm phase (0 = entry) of each arm at loop fraction u. */
  arms(u: number): Record<Side, number>;
  /** How far the head is turned to breathe towards each side, 0..1. */
  breath(u: number, arms: Record<Side, number>): Record<Side, number>;
  /** Arms drawn in the accent colour at loop fraction u: the one doing the work. */
  highlight(u: number): readonly Side[];
}

/** Slow into and out of the waiting position rather than snapping. */
const RIGHT: readonly Side[] = ['R'];
const LEFT: readonly Side[] = ['L'];

const easeStroke = (u: number) => u - (0.6 * Math.sin(2 * Math.PI * u)) / (2 * Math.PI);

const smoothstep = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/** Head turns during the pull/push, is fully round at the exit, and is back before the entry. */
const breathCurve = (armPhase: number) => {
  const t = ((armPhase % 1) + 1) % 1;
  return smoothstep(0.4, 0.6, t) * (1 - smoothstep(0.74, 0.92, t));
};

export const DRILLS: Record<DrillId, DrillSpec> = {
  // Single arm: right arm strokes, left arm stays up front, breathe towards the stroking arm every
  // stroke, 3 kicks per stroke.
  single_arm: {
    cycleSeconds: 2,
    kicksPerCycle: 3,
    arms: u => ({R: u, L: EXTENDED}),
    breath: (_u, arms) => ({R: breathCurve(arms.R), L: 0}),
    highlight: () => RIGHT,
  },
  // Catch-up: the lead arm waits extended until the recovering hand catches up with it, then
  // strokes itself. Breathe on the right-arm stroke; the kick never stops.
  catch_up: {
    cycleSeconds: 3.4,
    kicksPerCycle: 6,
    arms: u =>
      u < 0.5
        ? {R: EXTENDED + easeStroke(u * 2), L: EXTENDED}
        : {R: EXTENDED, L: EXTENDED + easeStroke(u * 2 - 1)},
    breath: (u, arms) => ({R: u < 0.5 ? breathCurve(arms.R) : 0, L: 0}),
    highlight: u => (u < 0.5 ? RIGHT : LEFT),
  },
};

export const isDrillId = (id: unknown): id is DrillId => typeof id === 'string' && id in DRILLS;

// ---------- the pose ----------

export interface ArmPose {
  shoulder: Vector3;
  elbow: Vector3;
  wrist: Vector3;
  /** Palm normal hint; orthogonalised against the hand direction when drawn. */
  palm: Vector3;
}

export interface LegPose {
  hip: Vector3;
  knee: Vector3;
  ankle: Vector3;
  toe: Vector3;
  sole: Vector3;
}

export interface Pose {
  /** Shoulder roll about the spine, radians; positive = right side down. */
  roll: number;
  hipRoll: number;
  /** Head turn about the spine, radians; positive = face turns to the swimmer's left. */
  headYaw: number;
  /** Arms to draw in the accent colour. */
  highlight: readonly Side[];
  arms: Record<Side, ArmPose>;
  legs: Record<Side, LegPose>;
}

const armPose = (): ArmPose => ({shoulder: new Vector3(), elbow: new Vector3(), wrist: new Vector3(), palm: new Vector3()});
const legPose = (): LegPose => ({hip: new Vector3(), knee: new Vector3(), ankle: new Vector3(), toe: new Vector3(), sole: new Vector3()});

export const createPose = (): Pose => ({
  roll: 0,
  hipRoll: 0,
  headYaw: 0,
  highlight: [],
  arms: {R: armPose(), L: armPose()},
  legs: {R: legPose(), L: legPose()},
});

const ROLL = 0.9; // at most ~42° per side once the waiting arm is factored in
const HIP_ROLL = 0.7; // hips follow the shoulders, a little less
const HEAD_FOLLOW = 0.12; // the head barely moves with the body unless breathing
const BREATH_YAW = 1.62; // ~93°: one goggle stays in the water

// flutter kick: driven from the hip, knee bends at the top of the kick, toes pointed
const THIGH_BASE = 0.07;
const THIGH_SWING = 0.15;
const KNEE_BEND = 0.55;
const KNEE_PEAK = -Math.PI / 2 + 0.3;
const FOOT_TILT = 0.3;
const FOOT_FLEX = 0.15;

/** Peaks when that arm is extended and the other is recovering. */
const rollCurve = (armPhase: number) => Math.cos(2 * Math.PI * (armPhase - 0.26));

const _wrist = new Vector3();
const _pole = new Vector3();
const _target = new Vector3();

function solveArm(side: Side, phase: number, roll: number, out: ArmPose) {
  const m = side === 'R' ? 1 : -1;
  sampleArm(phase, _wrist, _pole, out.palm);
  _wrist.x *= m;
  _pole.x *= m;
  out.palm.x *= m;
  out.palm.normalize();

  const sx = BODY.shoulder.x * m;
  const sz = BODY.shoulder.z;
  out.shoulder.set(sx * Math.cos(roll) + sz * Math.sin(roll), BODY.shoulder.y, -sx * Math.sin(roll) + sz * Math.cos(roll));
  _target.copy(out.shoulder).add(_wrist);
  solveTwoBone(out.shoulder, _target, _pole, BODY.upperArm, BODY.forearm, out.elbow, out.wrist);
}

function solveLeg(side: Side, phase: number, out: LegPose) {
  const m = side === 'R' ? 1 : -1;
  const theta = THIGH_BASE + THIGH_SWING * Math.sin(phase);
  const w = Math.atan2(Math.sin(phase - KNEE_PEAK), Math.cos(phase - KNEE_PEAK));
  const knee = KNEE_BEND * Math.cos(w / 2) ** 4;
  const shinAngle = theta - knee;
  const footAngle = shinAngle + FOOT_TILT - FOOT_FLEX * Math.cos(phase);

  out.hip.set(BODY.hip.x * m, BODY.hip.y, BODY.hip.z);
  out.knee.set(0.04 * m, -Math.cos(theta), Math.sin(theta)).normalize().multiplyScalar(BODY.thigh).add(out.hip);
  out.ankle.set(0.02 * m, -Math.cos(shinAngle), Math.sin(shinAngle)).normalize().multiplyScalar(BODY.shin).add(out.knee);
  out.toe.set(0.1 * m, -Math.cos(footAngle), Math.sin(footAngle)).normalize();
  out.sole.set(0, -Math.sin(footAngle), -Math.cos(footAngle));
}

/** Pose of the drill `time` seconds in (at 1x). */
export function poseAt(drillId: DrillId, time: number, out: Pose): Pose {
  const drill = DRILLS[drillId];
  const loops = time / drill.cycleSeconds;
  const u = loops - Math.floor(loops);
  const arms = drill.arms(u);
  const breath = drill.breath(u, arms);

  out.roll = ROLL * 0.5 * (rollCurve(arms.R) - rollCurve(arms.L));
  out.hipRoll = out.roll * HIP_ROLL;
  out.headYaw = out.roll * HEAD_FOLLOW - BREATH_YAW * breath.R + BREATH_YAW * breath.L;
  out.highlight = drill.highlight(u);

  const kickPhase = 2 * Math.PI * loops * (drill.kicksPerCycle / 2);
  for (const side of SIDES) {
    solveArm(side, arms[side], out.roll, out.arms[side]);
    solveLeg(side, kickPhase + (side === 'L' ? Math.PI : 0), out.legs[side]);
  }
  return out;
}
