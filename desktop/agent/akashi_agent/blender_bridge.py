"""Fixed Blender-side operations invoked only by the typed Windows Agent adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


def geometry_digest(obj):
    value = {"positions": [list(v.co) for v in obj.data.vertices], "faces": [list(p.vertices) for p in obj.data.polygons]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            value.update(chunk)
    return value.hexdigest()


def build_character(bpy, character_path, output):
    """Create a NEW practice artifact using fixed API calls; no asset script execution."""
    from mathutils import Vector
    sys.path.insert(0, str(Path(__file__).parent))
    from character_document import validate_document
    document = validate_document(json.loads(Path(character_path).read_text(encoding="utf-8")), construction=True)
    if output.exists():
        raise ValueError("Construction cannot overwrite an artifact.")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    armature = bpy.data.armatures.new("SYNTHETIC Practice Rig")
    rig = bpy.data.objects.new("AKASHI Practice Rig", armature)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bones = {}
    for joint in document["joints"]:
        name = joint["id"][:36]+"-"+hashlib.sha256(joint["id"].encode()).hexdigest()[:16]
        bone = armature.edit_bones.new(name)
        bone.head, bone.tail = joint["metadata"]["head"], joint["metadata"]["tail"]
        bones[joint["id"]] = bone
    for joint in document["joints"]:
        if joint.get("parent"):
            bones[joint["id"]].parent = bones[joint["parent"]]
    names = {key: bone.name for key, bone in bones.items()}
    bpy.ops.object.mode_set(mode="OBJECT")
    for joint in document["joints"]:
        armature.bones[names[joint["id"]]]["akashi_source_id"] = joint["id"]
    materials = {}
    for item in document.get("materials", []):
        material = bpy.data.materials.new(item["id"][:50])
        color = item.get("diffuse_color", [.35,.4,.45,1.])
        if not isinstance(color, list) or len(color) != 4 or any(type(x) not in (int,float) or not 0 <= x <= 1 for x in color):
            raise ValueError("Invalid synthetic surface color.")
        material.diffuse_color = color
        material.use_nodes = True
        material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = color
        materials[item["id"]] = material
    skins = {s["mesh_id"]: s for s in document["skins"]}
    created = []
    for mesh in document["meshes"]:
        data = bpy.data.meshes.new("Practice Surface")
        data.from_pydata(mesh["positions"], [], mesh["faces"])
        data.update()
        name = mesh["id"][:36]+"-"+hashlib.sha256(mesh["id"].encode()).hexdigest()[:16]
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj["akashi_source_id"] = mesh["id"]
        created.append(obj)
        for key in mesh.get("materials", []):
            if key not in materials:
                raise ValueError("Unknown synthetic material.")
            data.materials.append(materials[key])
        for key in mesh.get("uv_maps", []):
            coordinates = mesh.get("metadata", {}).get("uv_coordinates", {}).get(key)
            if not isinstance(coordinates, list) or len(coordinates) != len(data.loops) or any(not isinstance(v, list) or len(v) != 2 or any(type(x) not in (int,float) for x in v) for v in coordinates):
                raise ValueError("Construction requires actual declared UV coordinates.")
            uv = data.uv_layers.new(name=key)
            for loop, value in zip(uv.data, coordinates):
                loop.uv = value
        skin = skins[mesh["id"]]
        groups = {key: obj.vertex_groups.new(name=names[key]) for key in skin["joints"]}
        for index, weights in enumerate(skin["weights"]):
            for key, weight in weights.items():
                if weight > 0:
                    groups[key].add([index], weight, "REPLACE")
        modifier = obj.modifiers.new("Observed Practice Binding", "ARMATURE")
        modifier.object = rig
    points = [Vector(p) for mesh in document["meshes"] for p in mesh["positions"]]
    lower = Vector([min(p[k] for p in points) for k in range(3)])
    upper = Vector([max(p[k] for p in points) for k in range(3)])
    center, extent = (lower+upper)/2, max((upper-lower).length, .5)
    camera_data = bpy.data.cameras.new("Practice Camera")
    camera = bpy.data.objects.new("Practice Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = center + Vector((extent*.25, extent*.1, extent*1.1))
    camera.rotation_euler = (center-camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type, camera_data.ortho_scale = "ORTHO", extent*1.1
    light_data = bpy.data.lights.new("Practice Key", "AREA")
    light_data.energy, light_data.size = 1500, extent
    light = bpy.data.objects.new("Practice Key", light_data)
    bpy.context.collection.objects.link(light)
    light.location = center+Vector((0, 0, extent))
    scene = bpy.context.scene
    scene["akashi_synthetic"] = True
    scene.camera = camera
    engines = scene.render.bl_rna.properties["engine"].enum_items.keys()
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 768, 768, 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (.06,.06,.06)
    if output.exists():
        raise ValueError("Output was created concurrently; refusing overwrite.")
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    return {"verified": output.is_file(), "synthetic": True, "joints": len(names), "meshes": len(created),
            "canonical_joint_names": names, "scope": "fixed synthetic construction; no professional rig recreation claimed"}


def rna_parameters(item):
    """Bounded numeric/string settings; references remain names, never code or file loads."""
    result = {}
    def primitive(value, depth=0):
        if isinstance(value, (bool, int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Non-finite RNA setting.")
            return value
        if isinstance(value, str):
            return value[:1000]
        if depth < 3 and hasattr(value, "__len__") and len(value) <= 16:
            return [primitive(v, depth+1) for v in value]
        raise TypeError("Unsupported RNA setting type.")
    for prop in item.bl_rna.properties:
        key = prop.identifier
        if key == "rna_type" or prop.type == "COLLECTION":
            continue
        try:
            value = getattr(item, key)
            if prop.type == "POINTER":
                if value is not None and hasattr(value, "name"):
                    result[key] = {"reference_name": value.name}
            elif isinstance(value, (bool, int, float)):
                if not isinstance(value, float) or math.isfinite(value):
                    result[key] = value
            elif isinstance(value, str):
                result[key] = value[:1000]
            elif prop.is_array and len(value) <= 16:
                result[key] = primitive(value)
        except (AttributeError, TypeError, ValueError):
            continue
        if len(result) >= 100:
            break
    return result


def validate_patch(bpy, patch_path):
    """Fixed numeric patch only. Validate every target before changing any group."""
    patch = json.loads(Path(patch_path).read_text(encoding="utf-8"))
    if (not isinstance(patch, dict) or patch.get("schema_version") != 1
        or not isinstance(patch.get("version_id"), str) or not 1 <= len(patch["version_id"]) <= 128
        or set(patch) - {"schema_version", "version_id", "synthetic", "patches", "quality_scope", "source_digest"}):
        raise ValueError("Unsupported weight patch schema.")
    patches = patch.get("patches")
    if not isinstance(patches, list) or not patches or len(patches) > 1000:
        raise ValueError("Invalid patch budget.")
    targets, seen, count = [], set(), 0
    for item in patches:
        if not isinstance(item, dict) or set(item) != {"mesh", "geometry_digest", "bones", "weights"} or item["mesh"] in seen:
            raise ValueError("Invalid or duplicate patch target.")
        seen.add(item["mesh"])
        obj = bpy.data.objects.get(item["mesh"])
        if not obj or obj.type != "MESH" or geometry_digest(obj) != item["geometry_digest"]:
            raise ValueError("Patch geometry does not match the actual source mesh.")
        armature = obj.find_armature()
        if not armature or not isinstance(item["bones"], dict) or set(item["bones"].values()) != {bone.name for bone in armature.data.bones} or any(key != armature.name+":"+name for key, name in item["bones"].items()):
            raise ValueError("Patch bone palette does not match the actual source armature.")
        weights = item["weights"]
        if not isinstance(weights, list) or len(weights) != len(obj.data.vertices):
            raise ValueError("Patch vertex count mismatch.")
        count += len(weights)
        if count > 200000:
            raise ValueError("Patch exceeds the vertex budget.")
        for value in weights:
            if not isinstance(value, dict) or not value or set(value)-set(item["bones"]) or any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 or w > 1 for w in value.values()) or abs(sum(value.values())-1) > 1e-5:
                raise ValueError("Patch contains invalid/unbound vertex weights.")
        targets.append((obj, item))
    return patch, targets, count


def verify_weights(bpy, patch_path):
    patch, targets, count = validate_patch(bpy, patch_path)
    maximum_error = 0.
    for obj, item in targets:
        group_ids = {group.index: key for key, name in item["bones"].items() for group in obj.vertex_groups if group.name == name}
        for vertex, expected in zip(obj.data.vertices, item["weights"]):
            actual = {group_ids[g.group]: g.weight for g in vertex.groups if g.group in group_ids}
            maximum_error = max(maximum_error, max((abs(actual.get(k,0)-expected.get(k,0)) for k in set(actual)|set(expected)), default=0))
    return {"verified": maximum_error <= 1e-6, "max_weight_error": maximum_error, "vertices": count, "version_id": patch["version_id"], "geometry_matched": True}


def apply_weights(bpy, patch_path, output):
    patch, targets, count = validate_patch(bpy, patch_path)
    if output.exists():
        raise ValueError("Character output must be a new artifact, never an overwrite.")
    source = Path(bpy.data.filepath).resolve()
    before_digest = file_digest(source)
    for obj, item in targets:
        groups = {key: obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name) for key, name in item["bones"].items()}
        indices = list(range(len(obj.data.vertices)))
        for group in groups.values():
            group.remove(indices)
        for index, weights in enumerate(item["weights"]):
            for key, value in weights.items():
                groups[key].add([index], value, "REPLACE")
        for index, expected in enumerate(item["weights"]):
            observed = {key: obj.vertex_groups[name].weight(index) for key, name in item["bones"].items() if key in expected}
            if any(abs(observed[key]-value) > 1e-6 for key, value in expected.items()):
                raise ValueError("Application weight readback failed.")
    if output.exists():
        raise ValueError("Another process created the requested output; refusing overwrite.")
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    unchanged = before_digest == file_digest(source)
    return {"verified": output.is_file() and unchanged, "vertices_applied": count, "version_id": patch["version_id"], "source_preserved": unchanged,
            "source_sha256": before_digest}


def test_deformation(bpy):
    """Read actual evaluated Blender meshes, including the real modifier stack."""
    from mathutils import Matrix, Quaternion
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH" and obj.find_armature()]
    if not meshes or sum(len(obj.data.vertices) for obj in meshes) > 200000:
        raise ValueError("No bounded skinned mesh to evaluate.")
    for obj in armatures:
        if obj.animation_data:
            obj.animation_data.action = None
        for bone in obj.pose.bones:
            bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()

    def positions(obj):
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        data = evaluated.to_mesh()
        try:
            if len(data.vertices) != len(obj.data.vertices):
                raise ValueError("Topology-changing modifiers need a different evaluation correspondence.")
            return [tuple(evaluated.matrix_world @ vertex.co) for vertex in data.vertices]
        finally:
            evaluated.to_mesh_clear()

    baseline = {obj.name: positions(obj) for obj in meshes}
    records = []
    joints = [(obj, bone) for obj in armatures for bone in obj.pose.bones if bone.bone.use_deform][:8]
    for armature, bone in joints:
        for degrees, axis, split in ((20, (1,0,0), "train"), (45, (1,0,0), "train"), (-30, (1,0,0), "held_out"), (70, (1,0,0), "held_out"), (60, (0,1,0), "held_out")):
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = Quaternion(axis, math.radians(degrees))
            bpy.context.view_layer.update()
            for obj in meshes:
                before, after = baseline[obj.name], positions(obj)
                sample = list(obj.data.edges)[::max(1, math.ceil(len(obj.data.edges)/1024))]
                strain, collapsed = [], 0
                for edge in sample:
                    a, b = edge.vertices
                    rest, posed = math.dist(before[a], before[b]), math.dist(after[a], after[b])
                    if rest > 1e-10:
                        strain.append(abs(math.log(max(1e-8, posed/rest))))
                        collapsed += int(posed < rest*.05)
                records.append({"joint": armature.name+":"+bone.name, "mesh": obj.name, "degrees": degrees, "split": split,
                                "axis": axis, "mean_log_strain": sum(strain)/max(1, len(strain)), "collapsed_edges": collapsed, "sampled_edges": len(strain)})
            bone.matrix_basis = Matrix.Identity(4)
    return {"method": "actual_blender_evaluated_modifier_mesh", "application_version": bpy.app.version_string,
            "poses": records, "scope": "numeric_stress_tests_not_artistic_certification", "verified": bool(records)}


def inspect_character(bpy):
    """Extract source structures without executing asset scripts or changing the scene."""
    joints, meshes, skins, materials, objects, animations, unavailable = [], [], [], [], [], [], []
    armatures = {obj.name: obj for obj in bpy.data.objects if obj.type == "ARMATURE"}
    for obj in bpy.data.objects:
        animation = obj.animation_data
        objects.append({"id": obj.name, "type": obj.type, "parent": obj.parent.name if obj.parent else None,
                        "matrix_world": [value for row in obj.matrix_world for value in row],
                        "active_action": animation.action.name if animation and animation.action else None,
                        "nla_tracks": [{"name": track.name, "mute": track.mute,
                            "strips": [{"name": strip.name, "action": strip.action.name if strip.action else None,
                                "frame_start": strip.frame_start, "frame_end": strip.frame_end, "repeat": strip.repeat,
                                "scale": strip.scale, "influence": strip.influence, "blend_type": strip.blend_type} for strip in list(track.strips)[:100]]}
                            for track in list(animation.nla_tracks)[:100]] if animation else []})
    detailed_vertices, sample_values = 0, 0
    for name, obj in armatures.items():
        for bone in obj.data.bones:
            pose = obj.pose.bones.get(bone.name)
            joints.append({"id": name + ":" + bone.name, "name": bone.name,
                           "parent": name + ":" + bone.parent.name if bone.parent else None,
                           "matrix": [value for row in bone.matrix_local for value in row],
                           "constraints": [{"type": constraint.type, "name": constraint.name, "parameters": rna_parameters(constraint)} for constraint in (pose.constraints if pose else [])][:100],
                           "metadata": {"head": list(bone.head_local), "tail": list(bone.tail_local), "deform": bone.use_deform,
                                        "transform_space": "armature_rest", "armature": name, "canonical_source_id": bone.get("akashi_source_id"),
                                        "inherit_scale": bone.inherit_scale, "connected": bone.use_connect,
                                        "bone_collections": [c.name for c in getattr(bone, "collections", [])],
                                        "pose_settings": rna_parameters(pose) if pose else {}}})
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        detailed = detailed_vertices+len(mesh.vertices) <= 200000 and len(mesh.polygons) <= 200000
        if detailed:
            detailed_vertices += len(mesh.vertices)
        else:
            unavailable.append("Mesh "+obj.name+": detailed geometry/weights exceed budget; counts and relations retained")
        armature = obj.find_armature()
        skin_id = "skin:" + obj.name if armature else None
        meshes.append({"id": obj.name, "name": obj.name, "vertex_count": len(mesh.vertices), "edge_count": len(mesh.edges),
                       "face_count": len(mesh.polygons), "positions": [list(vertex.co) for vertex in mesh.vertices] if detailed else None,
                       "faces": [list(face.vertices) for face in mesh.polygons] if detailed else None, "uv_maps": [layer.name for layer in mesh.uv_layers],
                       "materials": [slot.material.name for slot in obj.material_slots if slot.material],
                       "skin_id": skin_id, "normals": True,
                       "morph_targets": [key.name for key in mesh.shape_keys.key_blocks] if mesh.shape_keys else [],
                       "modifiers": [{"name": modifier.name, "type": modifier.type, "parameters": rna_parameters(modifier)} for modifier in obj.modifiers][:100],
                       "metadata": {"geometry_space": "object_local", "evaluated_modifiers": False,
                                    "canonical_source_id": obj.get("akashi_source_id"),
                                    "uv_coordinates": {}, "shape_key_data": {}}})
        if detailed:
            for layer in mesh.uv_layers:
                if sample_values+len(layer.data)*2 <= 400000:
                    meshes[-1]["metadata"]["uv_coordinates"][layer.name] = [list(loop.uv) for loop in layer.data]
                    sample_values += len(layer.data)*2
                else:
                    unavailable.append("UV coordinate budget exceeded for "+obj.name)
            if mesh.shape_keys:
                basis = mesh.shape_keys.key_blocks[0]
                for key in list(mesh.shape_keys.key_blocks)[1:]:
                    if sample_values+len(key.data)*3 <= 400000:
                        meshes[-1]["metadata"]["shape_key_data"][key.name] = {"value": key.value,
                            "relative_key": key.relative_key.name if key.relative_key else None,
                            "deltas": [[v.co[i]-b.co[i] for i in range(3)] for v,b in zip(key.data,basis.data)]}
                        sample_values += len(key.data)*3
                    else:
                        unavailable.append("Shape-key sample budget exceeded for "+obj.name)
        if armature:
            palette = {group.index: armature.name + ":" + group.name for group in obj.vertex_groups if group.name in armature.data.bones}
            skins.append({"id": skin_id, "mesh_id": obj.name, "joints": [armature.name + ":" + bone.name for bone in armature.data.bones],
                          "weights": [{palette[group.group]: group.weight for group in vertex.groups if group.group in palette} for vertex in mesh.vertices] if detailed else None})
    for material in bpy.data.materials:
        nodes = material.node_tree.nodes if material.use_nodes and material.node_tree else []
        materials.append({"id": material.name, "name": material.name, "diffuse_color": list(material.diffuse_color),
                          "shader_nodes": [{"type": node.bl_idname, "name": node.name,
                              "inputs": [{"name": socket.name, "linked": socket.is_linked, "default": rna_parameters(socket).get("default_value")} for socket in node.inputs][:64],
                              "image_reference": node.image.filepath if node.type == "TEX_IMAGE" and node.image else None,
                              "image_packed": bool(node.image.packed_file) if node.type == "TEX_IMAGE" and node.image else None} for node in list(nodes)[:256]],
                          "shader_links": [{"from_node": link.from_node.name, "from_socket": link.from_socket.name,
                              "to_node": link.to_node.name, "to_socket": link.to_socket.name} for link in list(material.node_tree.links)[:1024]] if material.node_tree else []})
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    for action in bpy.data.actions:
        curves = list(getattr(action, "fcurves", []))
        if not curves:
            for layer in getattr(action, "layers", []):
                for strip in layer.strips:
                    for bag in getattr(strip, "channelbags", []):
                        curves.extend(bag.fcurves)
        if not curves:
            unavailable.append("Action " + action.name + ": curve extraction unavailable in this Blender version")
        channels = [{"target": curve.data_path, "array_index": curve.array_index,
                     "times": [point.co.x / fps for point in curve.keyframe_points],
                     "values": [point.co.y for point in curve.keyframe_points],
                     "interpolation": [point.interpolation for point in curve.keyframe_points],
                     "handles_left": [list(point.handle_left) for point in curve.keyframe_points],
                     "handles_right": [list(point.handle_right) for point in curve.keyframe_points],
                     "extrapolation": curve.extrapolation, "modifiers": [rna_parameters(m) for m in curve.modifiers],
                     "keyframe_count": len(curve.keyframe_points)} for curve in curves]
        animations.append({"id": action.name, "name": action.name, "duration": (action.frame_range[1] - action.frame_range[0]) / fps,
                           "frame_rate": fps, "channels": channels,
                           "metadata": {"slots": [{"identifier": s.identifier, "target_id_type": s.target_id_type} for s in getattr(action, "slots", [])]}})
    driver_owners = list(bpy.data.objects)+list(bpy.data.shape_keys)+list(bpy.data.materials)+list(bpy.data.node_groups)+list(bpy.data.armatures)+list(bpy.data.scenes)
    return {"schema_version": 1, "name": bpy.context.scene.name, "coordinate_system": {"up_axis": "Z", "unit_scale": bpy.context.scene.unit_settings.scale_length},
            "joints": joints, "meshes": meshes, "skins": skins, "materials": materials, "objects": objects, "animations": animations,
            "unavailable": unavailable + ["Deformation quality, IK/FK function and facial behavior require evaluation, not metadata inference."],
            "metadata": {"application": "Blender", "version": bpy.app.version_string, "synthetic": bpy.context.scene.get("akashi_synthetic", False),
                         "drivers": [{"owner": obj.name, "data_path": driver.data_path, "array_index": driver.array_index,
                             "expression_source_data_only": driver.driver.expression,
                             "variables": [{"name": v.name, "type": v.type, "targets": [{"id": t.id.name if t.id else None,
                                 "data_path": t.data_path, "bone_target": t.bone_target} for t in v.targets]} for v in driver.driver.variables]}
                             for obj in driver_owners if obj.animation_data for driver in obj.animation_data.drivers][:1000]}}


def main() -> int:
    import bpy  # Available only inside Blender's Python runtime.

    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--operation", required=True, choices=("inspect_scene", "inspect_character", "render_current", "render_production", "export_gltf", "apply_weights", "verify_weights", "test_deformation", "build_character", "build_production", "present_production", "verify_production"))
    parser.add_argument("--character", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--patch", default="")
    parser.add_argument("--view", choices=("Front", "ThreeQuarter", "Back"), default="ThreeQuarter")
    parser.add_argument("--frame", type=int, default=1)
    options = parser.parse_args(arguments)
    scene = bpy.context.scene
    result = {
        "operation": options.operation,
        "scene": scene.name,
        "objects": len(scene.objects),
        "object_types": {},
        "frame": scene.frame_current,
        "render_engine": scene.render.engine,
    }
    for item in scene.objects:
        result["object_types"][item.type] = result["object_types"].get(item.type, 0) + 1
    if options.operation in {"build_production","present_production","verify_production"}:
        sys.path.insert(0,str(Path(__file__).parent))
        import blender_production
        output=Path(options.output)
        if options.operation=="build_production":
            from production_contract import validate_production
            validate_production(json.loads(Path(options.character).read_text(encoding="utf-8")))
            result.update(blender_production.build(bpy,options.character,output,build_character),output=str(output))
        elif options.operation=="present_production":
            from production_contract import validate_production
            validate_production(json.loads(Path(options.patch).read_text(encoding="utf-8")))
            result.update(blender_production.present(bpy,options.patch,output),output=str(output))
        else:
            value=blender_production.report(bpy)
            with output.open("x",encoding="utf-8") as stream: stream.write(json.dumps(value,allow_nan=False))
            compact={k:v for k,v in value.items() if k!="deformation"}
            compact["pose_measurements"]=len(value["deformation"])
            compact["maximum_mean_log_strain"]=max((r["mean_log_strain"] for r in value["deformation"]),default=0)
            result.update(compact,output=str(output))
    elif options.operation == "build_character":
        output = Path(options.output)
        result.update(build_character(bpy, options.character, output), output=str(output))
    elif options.operation == "apply_weights":
        output = Path(options.output)
        result.update(apply_weights(bpy, options.patch, output), output=str(output))
    elif options.operation == "verify_weights":
        output = Path(options.output)
        value = verify_weights(bpy, options.patch)
        output.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
        result.update(output=str(output), verified=value["verified"], vertices=value["vertices"])
    elif options.operation == "test_deformation":
        output = Path(options.output)
        value = test_deformation(bpy)
        output.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
        result.update(output=str(output), verified=value["verified"], poses=len(value["poses"]))
    elif options.operation == "inspect_character":
        output = Path(options.output)
        value = inspect_character(bpy)
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(payload) > 32*1024*1024:
            # Preserve relations/counts instead of silently truncating per-vertex correspondence.
            for mesh in value["meshes"]:
                mesh["positions"], mesh["faces"] = None, None
                mesh["metadata"]["uv_coordinates"], mesh["metadata"]["shape_key_data"] = {}, {}
            for skin in value["skins"]:
                skin["weights"] = None
            value["unavailable"].append("Detailed per-vertex data omitted to keep extraction under 32 MiB; source binary retained.")
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(payload) > 32*1024*1024:
            raise ValueError("Metadata/animation extraction exceeds the bounded transport budget.")
        with output.open("xb") as stream:
            stream.write(payload)
        result["output"] = str(output)
        result["verified"] = output.is_file() and output.stat().st_size > 0
        result["joint_count"] = len(value["joints"])
        result["mesh_count"] = len(value["meshes"])
        result["source_sha256"] = file_digest(Path(bpy.data.filepath))
    elif options.operation in {"render_current", "render_production"}:
        if options.operation == "render_production":
            camera = next((o for o in scene.objects if o.type == "CAMERA" and o.get("akashi_production_stage") and o.name == "Production " + options.view), None)
            if not camera or not 1 <= options.frame <= 192:
                raise ValueError("Production camera/frame unavailable.")
            scene.camera = camera
            scene.frame_set(options.frame)
            result.update(view=options.view, frame=options.frame)
        output = Path(options.output)
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        result["output"] = str(output)
        result["verified"] = output.is_file() and output.stat().st_size > 0
    elif options.operation == "export_gltf":
        output = Path(options.output)
        bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB" if output.suffix.casefold() == ".glb" else "GLTF_SEPARATE")
        result["output"] = str(output)
        result["verified"] = output.is_file() and output.stat().st_size > 0
    else:
        result["verified"] = True
        if bpy.data.filepath:
            result["source_sha256"] = file_digest(Path(bpy.data.filepath))
    print("AKASHI_BLENDER_RESULT=" + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
