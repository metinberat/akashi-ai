// three.js renderer for Spatial Lab. It draws the scene document it is given;
// it never owns or mutates scene state. Each object is:
//   group (scene transform) → norm (server normalisation: ground pivot, scale) → GLB scene
// so the source asset is untouched and the transform matches the backend exactly.

import * as THREE from "three";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";
import { clone as cloneSkinned } from "three/addons/utils/SkeletonUtils.js";

import type { CameraRig } from "@/lib/spatial/projection";
import type { SceneObject, SceneState } from "@/lib/spatial/types";

const FORM_HUD_NODE = /^hud-ring-\d+-[0-9a-f]{16}$/u;

export type AssetLoadState = { state: "loading" | "ready" | "error"; detail?: string };

type Entry = {
  object: SceneObject;
  group: THREE.Group;
  norm: THREE.Group;
  model: THREE.Object3D | null;
  assetId: string;
  mixer: THREE.AnimationMixer | null;
  clips: THREE.AnimationClip[];
  action: THREE.AnimationAction | null;
  actionClip: string | null;
  skeleton: THREE.SkeletonHelper | null;
  bounds: THREE.Box3Helper | null;
  hudNodes: THREE.Object3D[];
  ring: THREE.Mesh;
  measured: THREE.Vector3 | null;
};

export type RendererStats = { frames: number; fps: number; frameMs: number; calls: number; triangles: number; objects: number; assets: number; continuous: boolean };

export class SpatialRenderer {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private entries = new Map<string, Entry>();
  private assets = new Map<string, Promise<GLTF>>();
  private assetUsers = new Map<string, number>();
  private frame = 0;
  private previous = performance.now();
  private dirty = true;
  private disposed = false;
  private resize: ResizeObserver;
  private view: SceneState | null = null;
  private hover: string | null = null;
  private interactive = false;
  private statsValue: RendererStats = { frames: 0, fps: 0, frameMs: 0, calls: 0, triangles: 0, objects: 0, assets: 0, continuous: false };
  private fpsWindow: number[] = [];

  constructor(private readonly container: HTMLElement, rig: CameraRig, private readonly loadAsset: (assetId: string) => Promise<ArrayBuffer>,
              private readonly onAsset: (assetId: string, state: AssetLoadState) => void, private readonly onResize: (aspect: number) => void) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.domElement.className = "spatial-canvas";
    container.append(this.renderer.domElement);
    this.camera = new THREE.PerspectiveCamera(rig.fov, 16 / 9, rig.near, rig.far);
    this.camera.position.set(...rig.position);
    this.camera.lookAt(new THREE.Vector3(...rig.target));
    this.scene.add(new THREE.HemisphereLight(0xe3ebf2, 0x1d2024, 2.1));
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(2.5, 4, 3);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0xff3148, 0.45);
    rim.position.set(-3, 2.5, -2.5);
    this.scene.add(rim);
    this.resize = new ResizeObserver(() => this.fit());
    this.resize.observe(container);
    this.fit();
    this.tick = this.tick.bind(this);
    this.frame = requestAnimationFrame(this.tick);
  }

  stats(): RendererStats {
    return { ...this.statsValue };
  }

  /** The renderer's own measured size of an object's model (normalised, unscaled), for debug comparison with the server's. */
  measuredSize(objectId: string): THREE.Vector3 | null {
    return this.entries.get(objectId)?.measured ?? null;
  }

  setInteractive(value: boolean): void {
    this.interactive = value;
    this.dirty = true;
  }

  sync(view: SceneState | null, hover: string | null): void {
    this.view = view;
    this.hover = hover;
    const wanted = new Set(view?.order ?? []);
    for (const [id, entry] of this.entries) if (!wanted.has(id)) this.remove(id, entry);
    for (const id of view?.order ?? []) {
      const object = view!.objects[id];
      let entry = this.entries.get(id);
      if (!entry || entry.assetId !== object.asset.asset_id) {
        if (entry) this.remove(id, entry);
        entry = this.create(object);
      }
      this.apply(entry, object, view!);
    }
    this.dirty = true;
  }

  private create(object: SceneObject): Entry {
    const group = new THREE.Group();
    group.name = object.id;
    const norm = new THREE.Group();
    group.add(norm);
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.42, 0.46, 64),
      new THREE.MeshBasicMaterial({ color: 0xff2a40, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.004;
    ring.visible = false;
    group.add(ring);
    this.scene.add(group);
    const entry: Entry = { object, group, norm, model: null, assetId: object.asset.asset_id, mixer: null, clips: [], action: null, actionClip: null,
      skeleton: null, bounds: null, hudNodes: [], ring, measured: null };
    this.entries.set(object.id, entry);
    this.attachAsset(entry);
    return entry;
  }

  private attachAsset(entry: Entry): void {
    const assetId = entry.assetId;
    this.assetUsers.set(assetId, (this.assetUsers.get(assetId) ?? 0) + 1);
    if (!this.assets.has(assetId)) {
      this.onAsset(assetId, { state: "loading" });
      const loading = this.loadAsset(assetId).then((buffer) => {
        const manager = new THREE.LoadingManager();
        manager.setURLModifier((url) => {
          if (url.startsWith("blob:") || url.startsWith("data:")) return url;
          throw new Error("External asset resources are refused");
        });
        return new GLTFLoader(manager).parseAsync(buffer, "").then(staticizeUnboundSkins);
      });
      this.assets.set(assetId, loading);
      loading.then(() => this.onAsset(assetId, { state: "ready" }), (error: unknown) => {
        this.assets.delete(assetId);
        this.onAsset(assetId, { state: "error", detail: error instanceof Error ? error.message : "GLB could not be decoded" });
      });
    }
    void this.assets.get(assetId)!.then((gltf) => {
      if (this.disposed || this.entries.get(entry.object.id) !== entry) return;
      const model = cloneSkinned(gltf.scene);
      entry.model = model;
      entry.norm.add(model);
      entry.clips = gltf.animations;
      entry.mixer = new THREE.AnimationMixer(model);
      model.traverse((node) => { if (FORM_HUD_NODE.test(node.name)) entry.hudNodes.push(node); });
      const box = new THREE.Box3().setFromObject(model);
      entry.measured = box.isEmpty() ? null : box.getSize(new THREE.Vector3());
      if (this.view?.objects[entry.object.id]) this.apply(entry, this.view.objects[entry.object.id], this.view);
      this.dirty = true;
    }).catch((error: unknown) => {
      // Decoding failures are reported by the loader above; anything thrown while
      // instancing the model must be visible too, never swallowed.
      if (!this.disposed) this.onAsset(assetId, { state: "error", detail: "Model instancing failed: " + (error instanceof Error ? error.message : String(error)) });
    });
  }

  private apply(entry: Entry, object: SceneObject, view: SceneState): void {
    entry.object = object;
    const { position, rotation, scale } = object.transform;
    entry.group.position.set(position[0], position[1], position[2]);
    entry.group.quaternion.set(rotation[0], rotation[1], rotation[2], rotation[3]).normalize();
    entry.group.scale.setScalar(scale);
    entry.group.visible = object.visible;
    const n = object.asset.normalization;
    entry.norm.scale.setScalar(n.scale);
    entry.norm.position.set(n.offset[0] * n.scale, n.offset[1] * n.scale, n.offset[2] * n.scale);
    const selected = view.selection.includes(object.id);
    const footprint = Math.max(n.size[0], n.size[2]) * 0.62 + 0.08;
    entry.ring.scale.setScalar(footprint / 0.44);
    entry.ring.visible = view.view.vfx_visible && (selected || this.hover === object.id);
    (entry.ring.material as THREE.MeshBasicMaterial).color.set(selected ? 0xff2a40 : 0xe8edf2);
    for (const node of entry.hudNodes) node.visible = object.display.form_hud;
    if (entry.model) {
      if (object.display.skeleton && !entry.skeleton) {
        entry.skeleton = new THREE.SkeletonHelper(entry.model);
        (entry.skeleton.material as THREE.LineBasicMaterial).depthTest = false;
        this.scene.add(entry.skeleton);
      }
      if (entry.skeleton) entry.skeleton.visible = object.display.skeleton && object.visible;
      if (object.display.bounds) {
        if (!entry.bounds) {
          entry.bounds = new THREE.Box3Helper(new THREE.Box3(), 0x9fb4c7);
          this.scene.add(entry.bounds);
        }
        entry.group.updateMatrixWorld(true);
        entry.bounds.box.setFromObject(entry.model);
        entry.bounds.visible = object.visible;
      } else if (entry.bounds) {
        entry.bounds.visible = false;
      }
      this.animate(entry, object);
    }
  }

  private animate(entry: Entry, object: SceneObject): void {
    const { clip, playing, speed } = object.animation;
    if (!entry.mixer) return;
    if (clip !== entry.actionClip) {
      entry.mixer.stopAllAction();
      entry.action = null;
      entry.actionClip = clip;
      const summary = object.asset.clips.find((c) => c.name === clip);
      const three = summary ? entry.clips[summary.index] : undefined;
      if (three) entry.action = entry.mixer.clipAction(three).play();
    }
    if (entry.action) {
      entry.action.paused = !playing;
      entry.action.timeScale = speed;
    }
  }

  private remove(id: string, entry: Entry): void {
    this.scene.remove(entry.group);
    if (entry.skeleton) { this.scene.remove(entry.skeleton); entry.skeleton.dispose(); }
    if (entry.bounds) { this.scene.remove(entry.bounds); entry.bounds.dispose(); }
    entry.mixer?.stopAllAction();
    entry.ring.geometry.dispose();
    (entry.ring.material as THREE.Material).dispose();
    this.entries.delete(id);
    const users = (this.assetUsers.get(entry.assetId) ?? 1) - 1;
    this.assetUsers.set(entry.assetId, users);
    if (users <= 0) {
      const cached = this.assets.get(entry.assetId);
      this.assets.delete(entry.assetId);
      this.assetUsers.delete(entry.assetId);
      void cached?.then((gltf) => disposeTree(gltf.scene)).catch(() => undefined);
    }
  }

  private fit(): void {
    const rect = this.container.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.camera.aspect = rect.width / rect.height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(rect.width, rect.height, false);
    this.onResize(this.camera.aspect);
    this.dirty = true;
  }

  private tick(time: number): void {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(this.tick);
    if (document.hidden) return;
    const delta = Math.min((time - this.previous) / 1000, 0.1);
    let animating = false;
    for (const entry of this.entries.values()) {
      if (entry.mixer && entry.action && !entry.action.paused && entry.object.visible) {
        entry.mixer.update(delta);
        animating = true;
      }
      if (entry.ring.visible) {
        const material = entry.ring.material as THREE.MeshBasicMaterial;
        material.opacity = 0.55 + Math.sin(time / 380) * 0.25;
        animating = true;
      }
    }
    const continuous = animating || this.interactive;
    if (!continuous && !this.dirty) {
      this.previous = time;
      return;
    }
    const started = performance.now();
    this.renderer.render(this.scene, this.camera);
    this.dirty = false;
    const frameMs = performance.now() - started;
    this.fpsWindow.push(time);
    while (this.fpsWindow.length && time - this.fpsWindow[0] > 1000) this.fpsWindow.shift();
    const info = this.renderer.info.render;
    this.statsValue = { frames: this.statsValue.frames + 1, fps: this.fpsWindow.length, frameMs, calls: info.calls, triangles: info.triangles,
      objects: this.entries.size, assets: this.assets.size, continuous };
    this.container.dataset.frames = String(this.statsValue.frames);
    this.container.dataset.objects = String(this.entries.size);
    this.container.dataset.models = String([...this.entries.values()].filter((e) => e.model).length);
    this.previous = time;
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.resize.disconnect();
    for (const [id, entry] of [...this.entries]) this.remove(id, entry);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

/**
 * glTF allows (with a validator warning) skinned geometry on a node without a
 * skin. three.js then creates a SkinnedMesh with no skeleton, which cannot be
 * cloned or animated. Render such nodes as static meshes instead of failing.
 */
export function staticizeUnboundSkins(gltf: GLTF): GLTF {
  const replacements: Array<[THREE.SkinnedMesh, THREE.Mesh]> = [];
  gltf.scene.traverse((node) => {
    const skinned = node as THREE.SkinnedMesh;
    if (skinned.isSkinnedMesh && !skinned.skeleton) {
      const mesh = new THREE.Mesh(skinned.geometry, skinned.material);
      mesh.name = skinned.name;
      mesh.position.copy(skinned.position);
      mesh.quaternion.copy(skinned.quaternion);
      mesh.scale.copy(skinned.scale);
      mesh.userData = skinned.userData;
      replacements.push([skinned, mesh]);
    }
  });
  for (const [skinned, mesh] of replacements) {
    const parent = skinned.parent;
    if (!parent) continue;
    for (const child of [...skinned.children]) mesh.add(child);
    parent.add(mesh);
    parent.remove(skinned);
  }
  return gltf;
}

function disposeTree(root: THREE.Object3D): void {
  root.traverse((node) => {
    const mesh = node as THREE.Mesh;
    mesh.geometry?.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
    for (const material of materials) {
      for (const value of Object.values(material)) if ((value as THREE.Texture)?.isTexture) (value as THREE.Texture).dispose();
      material.dispose();
    }
  });
}
