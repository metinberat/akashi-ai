"""Blender-only fabricated articulated surface with deliberately damaged skin."""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
from workshop_characters import limb

fixture = limb(rings=65, segments=16)
bpy.ops.wm.read_factory_settings(use_empty=True)
armature = bpy.data.armatures.new("SYNTHETIC-RIG")
rig = bpy.data.objects.new("SYNTHETIC-RIG", armature)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
mapping = {}
for joint in fixture["joints"]:
    bone = armature.edit_bones.new(joint["name"])
    bone.head, bone.tail = joint["metadata"]["head"], joint["metadata"]["tail"]
    if joint.get("parent"):
        bone.parent = mapping[joint["parent"]]
    mapping[joint["id"]] = bone
bpy.ops.object.mode_set(mode="OBJECT")
data = bpy.data.meshes.new("SYNTHETIC-SURFACE")
data.from_pydata(fixture["meshes"][0]["positions"], [], fixture["meshes"][0]["faces"])
data.update()
obj = bpy.data.objects.new("SYNTHETIC-LIMB", data)
bpy.context.collection.objects.link(obj)
modifier = obj.modifiers.new("SYNTHETIC-SKIN", "ARMATURE")
modifier.object = rig
groups = {j["id"]: obj.vertex_groups.new(name=j["name"]) for j in fixture["joints"]}
for index, weights in enumerate(fixture["skins"][0]["weights"]):
    y = fixture["meshes"][0]["positions"][index][1]
    if 1 <= y <= 2:
        weights = {"upper": .95 if index % 2 else .05, "lower": .05 if index % 2 else .95}
    for key, value in weights.items():
        groups[key].add([index], value, "REPLACE")
material = bpy.data.materials.new("SYNTHETIC-TITANIUM")
material.diffuse_color = (.25, .4, .65, 1)
obj.data.materials.append(material)
for polygon in obj.data.polygons:
    polygon.use_smooth = True
bpy.ops.object.camera_add(location=(5, 1.5, 3))
camera = bpy.context.object
camera.rotation_euler = (Vector((0,1.5,0))-camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.type, camera.data.ortho_scale = "ORTHO", 4
bpy.context.scene.camera = camera
bpy.ops.object.light_add(type="AREA", location=(3,0,4))
bpy.context.object.data.energy = 500
bpy.context.object.data.shape, bpy.context.object.data.size = "DISK", 4
try:
    bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
except TypeError:
    bpy.context.scene.render.engine = "BLENDER_EEVEE"
bpy.context.scene.render.resolution_x = 640
bpy.context.scene.render.resolution_y = 480
bpy.context.scene.render.resolution_percentage = 100
bpy.context.scene.world = bpy.data.worlds.new("SYNTHETIC-WORLD")
bpy.context.scene.world.color = (.1,.1,.1)
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--")+1])
