import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export class CharacterViewer {
  constructor(element) {
    this.element = element;
    this.generation = 0;
    this.playing = false;
    this.wire = false;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    element.append(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.01, 100);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.scene.add(new THREE.HemisphereLight(0xe9f5ef, 0x3c4650, 2.5));
    const key = new THREE.DirectionalLight(0xffffff, 3);
    key.position.set(3, 5, 4);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0xabc2e2, 2);
    rim.position.set(-3, 3, -3);
    this.scene.add(rim);
    const grid = new THREE.GridHelper(6, 30, 0x52605c, 0x303b3e);
    this.scene.add(grid);
    this.resize = new ResizeObserver(() => {
      const r = element.getBoundingClientRect();
      if (r.width && r.height) {
        this.camera.aspect = r.width / r.height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(r.width, r.height, false);
      }
    });
    this.resize.observe(element);
    this.previous = performance.now();
    this.tick = this.tick.bind(this);
    this.frame = requestAnimationFrame(this.tick);
  }
  tick(time) {
    const delta = Math.min((time - this.previous) / 1000, 0.05);
    this.previous = time;
    if (!document.hidden && !this.element.hidden) {
      if (this.mixer && this.playing) this.mixer.update(delta);
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    }
    this.frame = requestAnimationFrame(this.tick);
  }
  release(model) {
    if (!model) return;
    model.traverse((n) => {
      if (n.geometry) n.geometry.dispose();
      for (const material of Array.isArray(n.material)
        ? n.material
        : [n.material]) {
        if (!material) continue;
        for (const v of Object.values(material)) if (v?.isTexture) v.dispose();
        material.dispose();
      }
    });
  }
  async load(url) {
    const generation = ++this.generation;
    this.element.dataset.loaded = "false";
    const response = await fetch(url);
    if (!response.ok) throw new Error("3D artifact unavailable");
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > 128 * 1024 * 1024)
      throw new Error("3D preview exceeds budget");
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((source) => {
      if (source.startsWith("blob:") || source.startsWith("data:"))
        return source;
      throw new Error("External asset resources are forbidden");
    });
    const gltf = await new GLTFLoader(manager).parseAsync(buffer, "");
    if (generation !== this.generation) {
      this.release(gltf.scene);
      return [];
    }
    if (this.model) {
      this.scene.remove(this.model);
      this.mixer?.stopAllAction();
      this.mixer?.uncacheRoot(this.model);
      this.release(this.model);
    }
    if (this.helper) {
      this.scene.remove(this.helper);
      this.helper.geometry.dispose();
      this.helper.material.dispose();
      this.helper = null;
    }
    this.model = gltf.scene;
    const textures = new Set();
    let joints = 0;
    this.model.traverse((node) => {
      if (node.isBone) joints++;
      for (const material of Array.isArray(node.material)
        ? node.material
        : [node.material])
        if (material?.map) textures.add(material.map);
    });
    this.element.dataset.textures = String(textures.size);
    this.element.dataset.joints = String(joints);
    this.scene.add(this.model);
    this.model.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(this.model),
      center = bounds.getCenter(new THREE.Vector3()),
      size = bounds.getSize(new THREE.Vector3());
    this.model.position.sub(
      new THREE.Vector3(center.x, bounds.min.y, center.z),
    );
    this.controls.target.set(0, size.y * 0.5, 0);
    this.camera.position.set(size.y * 0.65, size.y * 0.65, size.y * 2.1);
    this.controls.update();
    this.clips = gltf.animations;
    this.mixer = new THREE.AnimationMixer(this.model);
    this.playing = false;
    this.setWire(this.wire);
    this.element.dataset.loaded = "true";
    this.element.dataset.meshes = String(this.model.children.length);
    return this.clips.map((c) => c.name);
  }
  setWire(value) {
    this.wire = value;
    this.model?.traverse((n) => {
      if (n.isMesh)
        for (const m of Array.isArray(n.material) ? n.material : [n.material])
          m.wireframe = value;
    });
  }
  setSkeleton(value) {
    if (!this.model) return;
    if (!this.helper) {
      this.helper = new THREE.SkeletonHelper(this.model);
      this.scene.add(this.helper);
    }
    this.helper.visible = value;
  }
  play(index) {
    if (!this.mixer || !this.clips.length) return;
    this.mixer.stopAllAction();
    if (this.playing)
      this.mixer.clipAction(this.clips[index] || this.clips[0]).play();
  }
  dispose() {
    ++this.generation;
    cancelAnimationFrame(this.frame);
    this.resize.disconnect();
    this.controls.dispose();
    this.release(this.model);
    this.renderer.dispose();
    this.element.replaceChildren();
  }
}
