"""Fixed DCC authoring/evaluation, never model-generated Python or source execution."""

import json
import math
from pathlib import Path


def configure_stage(bpy, center, height, transparent=False):
    from mathutils import Vector

    scene = bpy.context.scene
    for obj in list(scene.objects):
        if obj.get("akashi_production_stage"):
            bpy.data.objects.remove(obj, do_unlink=True)
    (
        scene.render.resolution_x,
        scene.render.resolution_y,
        scene.render.resolution_percentage,
    ) = 960, 1080, 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = transparent
    engines = scene.render.bl_rna.properties["engine"].enum_items.keys()
    scene.render.engine = (
        "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    )
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get("Background").inputs["Color"].default_value = (
        0.018,
        0.022,
        0.03,
        1,
    )
    scene.world.node_tree.nodes.get("Background").inputs[
        "Strength"
    ].default_value = 0.35
    target = Vector(center)
    for name, offset in (
        ("Front", (0, -2.8, 0.18)),
        ("ThreeQuarter", (1.8, -2.6, 0.2)),
        ("Back", (0, 2.8, 0.18)),
    ):
        data = bpy.data.cameras.new("Production " + name)
        obj = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(obj)
        obj["akashi_production_stage"] = True
        obj.location = target + Vector(offset) * height
        obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
        data.type = "ORTHO"
        data.ortho_scale = height * 1.4
        if name == "ThreeQuarter":
            scene.camera = obj
    for name, offset, power, color in (
        ("Key", (-1.4, -1.8, 1.8), 1100, (1, 0.86, 0.74)),
        ("Fill", (1.5, -0.6, 0.7), 750, (0.55, 0.68, 1)),
        ("Rim", (0.1, 1.2, 1.5), 1300, (1, 0.16, 0.12)),
    ):
        data = bpy.data.lights.new("Production " + name, "AREA")
        data.energy = power
        data.color = color
        data.size = height
        obj = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(obj)
        obj["akashi_production_stage"] = True
        obj.location = target + Vector(offset) * height
        obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
    scene.view_settings.view_transform = "AgX"


def polish(bpy, document):
    design = document["metadata"]["production_design"]
    h = design["height"]
    # Only factory-generated practice furniture. Never remove a supplied scene's lights.
    for name in ("Practice Camera", "Practice Key"):
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
    meshes = {
        obj.get("akashi_source_id"): obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
    }
    source = {m["id"]: m for m in document["meshes"]}
    for key, obj in meshes.items():
        if key not in source:
            continue
        obj["akashi_family"] = source[key]["metadata"]["family"]
        for p in obj.data.polygons:
            p.use_smooth = True
        # Keep evaluated vertex correspondence for actual pose tests. No hidden subdivision.
        if design["facial"] and key == "body-head":
            obj.shape_key_add(name="Basis")
            for name in ("JawOpen", "Smile"):
                shape = obj.shape_key_add(name=name)
                for v in shape.data:
                    p = v.co
                    face_t = (p.z / h - (1 - design["head_ratio"])) / design[
                        "head_ratio"
                    ]
                    if p.y < -0.015 * h and 0 < face_t < 0.6:
                        falloff = max(0, 1 - abs(face_t - 0.32) / 0.25)
                        if name == "JawOpen":
                            p.z -= 0.014 * h * falloff
                        else:
                            p.z += 0.007 * h * falloff * min(1, abs(p.x) / (h * 0.04))
                shape.value = 0
        if obj["akashi_family"] == "hud":
            obj["akashi_character_attached"] = True
            obj.shape_key_add(name="Basis")
            shape = obj.shape_key_add(name="FlowEnergy")
            for v in shape.data:
                v.co.x *= 1.03
                v.co.z = h * 0.84 + (v.co.z - h * 0.84) * 1.03
            for frame, value in ((1, 0), (48, 0.25), (120, 1), (192, 0)):
                shape.value = value
                shape.keyframe_insert(data_path="value", frame=frame)
            shape.value = 0
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        node = material.node_tree.nodes.get("Principled BSDF")
        if not node:
            continue
        atelier = design.get("appearance") == "atelier"
        node.inputs["Roughness"].default_value = (
            (0.72 if material.name in {"cloth", "lining", "hair"} else 0.48)
            if atelier
            else (0.55 if material.name in {"cloth", "hair"} else 0.32)
        )
        node.inputs["Metallic"].default_value = 0.8 if material.name == "metal" else 0
        if material.name in {"cloth", "lining", "hair", "skin"}:
            node.inputs["Specular IOR Level"].default_value = 0.2
        if atelier and material.name == "skin":
            node.inputs["Subsurface Weight"].default_value = 0.065
            node.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.2)
        if material.name in {"cloth", "skin"}:
            image = bpy.data.images.new(
                "Generated " + material.name + " Tile", width=128, height=128
            )
            color = list(material.diffuse_color)
            pixels = []
            for y in range(128):
                for x in range(128):
                    noise_value = 0.96 + 0.04 * math.sin(x * 12.9898 + y * 78.233)
                    pixels.extend([color[i] * noise_value for i in range(3)] + [1])
            image.pixels.foreach_set(pixels)
            image.pack()
            texture = material.node_tree.nodes.new("ShaderNodeTexImage")
            texture.image = image
            material.node_tree.links.new(
                texture.outputs["Color"], node.inputs["Base Color"]
            )
            noise = material.node_tree.nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = 85
            bump = material.node_tree.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.12
            bump.inputs["Distance"].default_value = 0.001
            material.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            material.node_tree.links.new(bump.outputs["Normal"], node.inputs["Normal"])
        if material.name == "energy":
            node.inputs["Emission Color"].default_value = design["accent_color"] + [1]
            for frame, value in ((1, 0.15), (48, 2), (120, 12), (192, 0.15)):
                node.inputs["Emission Strength"].default_value = value
                node.inputs["Emission Strength"].keyframe_insert(
                    data_path="default_value", frame=frame
                )
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    rig.show_in_front = True
    # Actual FK demonstration clip, not a claim of production IK/FK controls.
    for bone in rig.pose.bones:
        key = bone.bone.get("akashi_source_id", "")
        if key not in {"head", "chest", "forearm_L", "forearm_R", "index0_L"}:
            continue
        bone.rotation_mode = "XYZ"
        for frame, angle in ((1, 0), (48, 0.08), (96, -0.08), (144, 0)):
            bone.rotation_euler[1] = angle
            bone.keyframe_insert(data_path="rotation_euler", frame=frame)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 192
    scene.render.fps = 24
    scene.frame_set(1)
    scene["akashi_production_version"] = "character-production-1.0"
    scene["akashi_production_scope"] = (
        "local procedural stylized humanoid; not reference-certified professional character"
    )
    configure_stage(bpy, [0, 0, h * 0.52], h, design.get("appearance") == "atelier")


def build(bpy, character_path, output, build_character):
    document = json.loads(Path(character_path).read_text(encoding="utf-8"))
    # Agent and staging validate the exact typed document before this fixed script.
    result = build_character(bpy, character_path, output)
    polish(bpy, document)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    return {
        **result,
        "production": True,
        "facial_controls": sum(
            len(o.data.shape_keys.key_blocks) - 1
            for o in bpy.data.objects
            if o.type == "MESH" and o.data.shape_keys
        ),
        "hud_objects": sum(
            bool(o.get("akashi_character_attached")) for o in bpy.data.objects
        ),
        "verified": output.is_file(),
    }


def present(bpy, patch, output):
    from mathutils import Vector

    if output.exists():
        raise ValueError("Presentation needs a new output.")
    from production_contract import validate_production

    validate_production(json.loads(Path(patch).read_text(encoding="utf-8")))
    source = Path(bpy.data.filepath)
    before = source.read_bytes()
    objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objects:
        raise ValueError("No supplied character geometry.")
    points = [
        o.matrix_world @ Vector(corner) for o in objects for corner in o.bound_box
    ]
    lower = Vector([min(p[k] for p in points) for k in range(3)])
    upper = Vector([max(p[k] for p in points) for k in range(3)])
    configure_stage(bpy, list((lower + upper) / 2), max((upper - lower).z, 0.5))
    # Existing assets keep geometry/rig/materials: no unsupported reconstruction is silently applied.
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    return {
        "verified": output.is_file() and source.read_bytes() == before,
        "source_preserved": True,
        "scope": "non-destructive presentation only; requested reconstruction/HUD needs explicit adapter",
    }


def report(bpy):
    from mathutils import Matrix

    meshes = [
        o for o in bpy.data.objects if o.type == "MESH" and o.get("akashi_source_id")
    ]
    rig = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if not meshes or not rig:
        raise ValueError("Production rig/readback missing.")
    schema = {
        "verified": True,
        "method": "saved_blend_actual_pose_and_feature_readback",
        "vertices": sum(len(o.data.vertices) for o in meshes),
        "meshes": len(meshes),
        "joints": len(rig.data.bones),
        "facial_keys": {},
        "hud_controls": {},
        "hud": [],
        "deformation": [],
        "animation_actions": len(bpy.data.actions),
    }
    scene = bpy.context.scene
    oldframe = scene.frame_current
    action = rig.animation_data.action if rig.animation_data else None
    if rig.animation_data:
        rig.animation_data.action = None
    bases = {p.name: p.matrix_basis.copy() for p in rig.pose.bones}
    for p in rig.pose.bones:
        p.matrix_basis = Matrix.Identity(4)

    def points(obj):
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            return [tuple(evaluated.matrix_world @ v.co) for v in mesh.vertices]
        finally:
            evaluated.to_mesh_clear()

    for obj in meshes:
        if obj.data.shape_keys:
            keys = obj.data.shape_keys
            animation = keys.animation_data.action if keys.animation_data else None
            if keys.animation_data:
                keys.animation_data.action = None
            for key in list(keys.key_blocks)[1:]:
                key.value = 0
                bpy.context.view_layer.update()
                before = points(obj)
                key.value = 1
                bpy.context.view_layer.update()
                after = points(obj)
                displacement = max(
                    (math.dist(a, b) for a, b in zip(before, after)), default=0
                )
                controls = (
                    schema["hud_controls"]
                    if obj.get("akashi_character_attached")
                    else schema["facial_keys"]
                )
                controls[obj.name + ":" + key.name] = {
                    "maximum_displacement": displacement,
                    "tested": displacement > 1e-7,
                }
                key.value = 0
            if keys.animation_data:
                keys.animation_data.action = animation
    for source_id in ("forearm_L", "index0_L", "thigh_R", "jaw", "chest"):
        bone = next(
            (b for b in rig.pose.bones if b.bone.get("akashi_source_id") == source_id),
            None,
        )
        if not bone:
            continue
        for degrees in (25, 65, -35):
            bone.matrix_basis = Matrix.Identity(4)
            bpy.context.view_layer.update()
            baseline = {o.name: points(o) for o in meshes}
            bone.rotation_mode = "XYZ"
            bone.rotation_euler[0] = math.radians(degrees)
            bpy.context.view_layer.update()
            for obj in meshes:
                before, after = baseline[obj.name], points(obj)
                maxdelta = max(
                    (math.dist(a, b) for a, b in zip(before, after)), default=0
                )
                if not all(math.isfinite(v) for p in after for v in p):
                    raise ValueError("Non-finite deformation.")
                strain = []
                for edge in list(obj.data.edges)[:: max(1, len(obj.data.edges) // 256)]:
                    a, b = edge.vertices
                    rest = math.dist(before[a], before[b])
                    posed = math.dist(after[a], after[b])
                    if rest > 1e-8:
                        strain.append(abs(math.log(max(1e-8, posed / rest))))
                schema["deformation"].append(
                    {
                        "joint": source_id,
                        "mesh": obj.name,
                        "degrees": degrees,
                        "max_displacement": maxdelta,
                        "mean_log_strain": sum(strain) / max(1, len(strain)),
                        "collapsed_edges": sum(v > 3 for v in strain),
                    }
                )
                if obj.get("akashi_character_attached") and source_id == "chest":
                    schema["hud"].append(
                        {
                            "object": obj.name,
                            "anchor": "chest",
                            "actual_motion": maxdelta,
                            "verified": maxdelta > 1e-5,
                        }
                    )
            bone.matrix_basis = Matrix.Identity(4)
    for p in rig.pose.bones:
        p.matrix_basis = bases[p.name]
    if rig.animation_data:
        rig.animation_data.action = action
    scene.frame_set(oldframe)
    schema["verified"] = (
        bool(schema["deformation"])
        and all(v["tested"] for v in schema["facial_keys"].values())
        and all(v["tested"] for v in schema["hud_controls"].values())
        and all(v["verified"] for v in schema["hud"])
    )
    schema["quality_gates"] = {
        "no_collapsed_sampled_edges": not any(
            v["collapsed_edges"] for v in schema["deformation"]
        ),
        "bounded_pose_strain": max(
            (v["mean_log_strain"] for v in schema["deformation"]), default=0
        )
        < 0.5,
    }
    schema["verified"] = schema["verified"] and all(schema["quality_gates"].values())
    from bpy_extras.object_utils import world_to_camera_view

    frame_evidence = {}
    for camera in [
        o
        for o in scene.objects
        if o.type == "CAMERA" and o.get("akashi_production_stage")
    ]:
        coords = [
            world_to_camera_view(scene, camera, obj.matrix_world @ v.co)
            for obj in meshes
            for v in list(obj.data.vertices)[:: max(1, len(obj.data.vertices) // 100)]
        ]
        clipped = sum(
            not 0 <= p.x <= 1 or not 0 <= p.y <= 1 or p.z <= 0 for p in coords
        )
        frame_evidence[camera.name] = {
            "sampled_vertices": len(coords),
            "clipped": clipped,
            "verified": clipped == 0,
        }
    schema["render_framing"] = frame_evidence
    schema["verified"] = (
        schema["verified"]
        and bool(frame_evidence)
        and all(v["verified"] for v in frame_evidence.values())
    )
    schema["scope"] = (
        "finite poses, active facial keys and character-attached spatial effects; artist-quality/fidelity remain unverified"
    )
    return schema
