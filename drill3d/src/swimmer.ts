/**
 * A smooth mannequin swimmer built from lathed segments — no model file to load. Each limb
 * mesh has its origin at the proximal joint and extends along -Y, so posing is just "aim
 * this segment from joint A to joint B"; only hands and feet need a full orientation.
 */
import * as THREE from 'three';
import {BODY, SIDES, type Pose, type Side} from './stroke';

/** Colours come from the app's theme; these defaults are for the standalone preview. */
export interface Palette {
  body: string;
  /** The arm the drill is about. */
  accent: string;
  cap: string;
  lens: string;
}

export const DEFAULT_PALETTE: Palette = {
  body: '#B4B4B4',
  accent: '#F5C518',
  cap: '#1A1A1A',
  lens: '#1A1A1A',
};

/** A closed, tapered limb from y=0 down to y=-length, with round ends. */
function limbGeometry(length: number, r0: number, r1: number, bulge = 0) {
  const pts: THREE.Vector2[] = [];
  const cap = 6;
  const shaft = 10;
  for (let i = 0; i <= cap; i++) {
    const a = (i / cap) * (Math.PI / 2);
    pts.push(new THREE.Vector2(Math.sin(a) * r1, -length - Math.cos(a) * r1));
  }
  for (let i = 1; i < shaft; i++) {
    const s = i / shaft;
    const r = r1 + (r0 - r1) * s + bulge * Math.sin(Math.PI * s);
    pts.push(new THREE.Vector2(r, -length + s * length));
  }
  for (let i = 0; i <= cap; i++) {
    const a = (i / cap) * (Math.PI / 2);
    pts.push(new THREE.Vector2(Math.cos(a) * r0, Math.sin(a) * r0));
  }
  return new THREE.LatheGeometry(pts, 24);
}

/** A torso piece: lathe of (radius, y) pairs, flattened front-to-back. */
function torsoGeometry(profile: ReadonlyArray<readonly [number, number]>, depth: number) {
  const g = new THREE.LatheGeometry(
    profile.map(([r, y]) => new THREE.Vector2(r, y)),
    40,
  );
  g.scale(1, 1, depth);
  return g;
}

// Stays broad through the shoulder line (y≈0.5) so the deltoid sphere sinks into the torso
// instead of perching on top of it, then tapers hard into the neck right at the top.
const CHEST: ReadonlyArray<readonly [number, number]> = [
  [0.001, 0.12], [0.13, 0.13], [0.145, 0.2], [0.165, 0.3], [0.185, 0.38],
  [0.2, 0.44], [0.205, 0.5], [0.19, 0.54], [0.1, 0.575], [0.001, 0.6],
];
const PELVIS: ReadonlyArray<readonly [number, number]> = [
  [0.001, -0.16], [0.09, -0.15], [0.14, -0.1], [0.155, -0.02], [0.145, 0.06],
  [0.13, 0.14], [0.125, 0.22], [0.001, 0.26],
];

const DOWN = new THREE.Vector3(0, -1, 0);
const _v = new THREE.Vector3();
const _x = new THREE.Vector3();
const _y = new THREE.Vector3();
const _z = new THREE.Vector3();
const _m = new THREE.Matrix4();

/** Points a limb mesh from joint `from` to joint `to`. */
function aim(mesh: THREE.Object3D, from: THREE.Vector3, to: THREE.Vector3) {
  mesh.position.copy(from);
  mesh.quaternion.setFromUnitVectors(DOWN, _v.subVectors(to, from).normalize());
}

/** Places a hand/foot at `origin`, pointing along `dir`, with its flat side facing `normal`. */
function orient(mesh: THREE.Object3D, origin: THREE.Vector3, dir: THREE.Vector3, normal: THREE.Vector3) {
  _y.copy(dir).normalize().negate();
  _z.copy(normal).addScaledVector(_y, -normal.dot(_y));
  if (_z.lengthSq() < 1e-8) {
    _z.set(0, 0, 1).addScaledVector(_y, -_y.z);
  }
  _z.normalize();
  _x.crossVectors(_y, _z);
  mesh.quaternion.setFromRotationMatrix(_m.makeBasis(_x, _y, _z));
  mesh.position.copy(origin);
}

interface ArmMeshes {
  deltoid: THREE.Mesh;
  upper: THREE.Mesh;
  fore: THREE.Mesh;
  hand: THREE.Mesh;
}

interface LegMeshes {
  thigh: THREE.Mesh;
  shin: THREE.Mesh;
  foot: THREE.Mesh;
}

export class Swimmer {
  /** Body frame → world: head towards +Z, face towards -Y (down), left towards +X. */
  readonly root = new THREE.Group();
  private readonly chest: THREE.Mesh;
  private readonly hips = new THREE.Group();
  private readonly head = new THREE.Group();
  private readonly arms: Record<Side, ArmMeshes>;
  private readonly legs: Record<Side, LegMeshes>;
  private readonly body: THREE.MeshStandardMaterial;
  private readonly accent: THREE.MeshStandardMaterial;
  private highlighted: readonly Side[] = [];

  constructor(palette: Palette = DEFAULT_PALETTE) {
    this.root.rotation.x = Math.PI / 2;

    const material = (color: string, roughness = 0.55) =>
      new THREE.MeshStandardMaterial({color, roughness, metalness: 0});
    this.body = material(palette.body);
    this.accent = material(palette.accent, 0.45);
    const capMaterial = material(palette.cap, 0.4);
    const lensMaterial = material(palette.lens, 0.15);

    const add = (parent: THREE.Object3D, geometry: THREE.BufferGeometry, mat = this.body) => {
      const mesh = new THREE.Mesh(geometry, mat);
      parent.add(mesh);
      return mesh;
    };

    this.chest = add(this.root, torsoGeometry(CHEST, 0.62));
    this.root.add(this.hips);
    add(this.hips, torsoGeometry(PELVIS, 0.68));

    const neck = add(this.root, limbGeometry(0.17, 0.05, 0.05));
    aim(neck, BODY.neckBase, BODY.head);

    // head: body-coloured, with a swim cap over the crown and goggles on the face (+Z)
    this.head.position.copy(BODY.head);
    this.root.add(this.head);
    const skull = new THREE.SphereGeometry(1, 32, 24);
    skull.scale(0.088, 0.118, 0.102);
    add(this.head, skull);
    const capShell = new THREE.SphereGeometry(1, 32, 16, 0, Math.PI * 2, 0, Math.PI * 0.62);
    capShell.rotateX(-0.45);
    capShell.scale(0.092, 0.123, 0.107);
    add(this.head, capShell, capMaterial);
    for (const x of [-0.034, 0.034]) {
      const lens = new THREE.SphereGeometry(1, 16, 12);
      lens.scale(0.027, 0.019, 0.013);
      add(this.head, lens, lensMaterial).position.set(x, 0.012, 0.091);
    }

    const handGeometry = limbGeometry(0.12, 0.04, 0.034);
    handGeometry.scale(1, 1, 0.42);
    const footGeometry = limbGeometry(0.15, 0.042, 0.03);
    footGeometry.scale(1, 1, 0.55);

    const arm = (): ArmMeshes => ({
      deltoid: add(this.root, new THREE.SphereGeometry(0.062, 20, 16)),
      upper: add(this.root, limbGeometry(BODY.upperArm, 0.052, 0.04, 0.006)),
      fore: add(this.root, limbGeometry(BODY.forearm, 0.041, 0.03, 0.004)),
      hand: add(this.root, handGeometry),
    });
    const leg = (): LegMeshes => ({
      thigh: add(this.hips, limbGeometry(BODY.thigh, 0.086, 0.052, 0.008)),
      shin: add(this.hips, limbGeometry(BODY.shin, 0.052, 0.033, 0.012)),
      foot: add(this.hips, footGeometry),
    });
    this.arms = {R: arm(), L: arm()};
    this.legs = {R: leg(), L: leg()};
  }

  /** Draws the given arms in the accent colour. */
  private setHighlight(sides: readonly Side[]) {
    if (sides === this.highlighted) {
      return;
    }
    this.highlighted = sides;
    for (const side of SIDES) {
      const mat = sides.includes(side) ? this.accent : this.body;
      const {upper, fore, hand} = this.arms[side];
      upper.material = mat;
      fore.material = mat;
      hand.material = mat;
    }
  }

  apply(pose: Pose) {
    this.setHighlight(pose.highlight);
    this.chest.rotation.y = pose.roll;
    this.hips.rotation.y = pose.hipRoll;
    this.head.rotation.y = pose.headYaw;
    for (const side of SIDES) {
      const a = pose.arms[side];
      const arm = this.arms[side];
      arm.deltoid.position.copy(a.shoulder);
      aim(arm.upper, a.shoulder, a.elbow);
      aim(arm.fore, a.elbow, a.wrist);
      orient(arm.hand, a.wrist, _v.subVectors(a.wrist, a.elbow), a.palm);

      const l = pose.legs[side];
      const leg = this.legs[side];
      aim(leg.thigh, l.hip, l.knee);
      aim(leg.shin, l.knee, l.ankle);
      orient(leg.foot, l.ankle, l.toe, l.sole);
    }
  }
}
