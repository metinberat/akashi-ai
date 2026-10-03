"""Run only inside Blender. Generates fabricated local test data."""
import sys
from pathlib import Path
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
armature = bpy.data.armatures.new("SYNTHETIC_RIG")
rig = bpy.data.objects.new("SYNTHETIC_RIG", armature)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
root = armature.edit_bones.new("upper_arm_L")
root.head, root.tail = (0, 0, 0), (0, 0, 1)
twist = armature.edit_bones.new("forearm_twist_L")
twist.head, twist.tail, twist.parent = (0, 0, 1), (0, 0, 2), root
bpy.ops.object.mode_set(mode="OBJECT")
mesh = bpy.data.meshes.new("SYNTHETIC_TRIANGLE")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 0, 1)], [], [(0, 1, 2)])
obj = bpy.data.objects.new("SYNTHETIC_MESH", mesh)
bpy.context.collection.objects.link(obj)
modifier = obj.modifiers.new("SYNTHETIC_SKIN", "ARMATURE")
modifier.object = rig
for bone in ("upper_arm_L", "forearm_twist_L"):
    obj.vertex_groups.new(name=bone).add([0, 1, 2], .5, "REPLACE")
material = bpy.data.materials.new("SYNTHETIC_MATERIAL")
mesh.materials.append(material)
rig.pose.bones["forearm_twist_L"].rotation_mode = "XYZ"
rig.pose.bones["forearm_twist_L"].rotation_euler = (0, 0, 0)
rig.pose.bones["forearm_twist_L"].keyframe_insert("rotation_euler", frame=1)
rig.pose.bones["forearm_twist_L"].rotation_euler = (0, .2, 0)
rig.pose.bones["forearm_twist_L"].keyframe_insert("rotation_euler", frame=30)
bpy.context.scene.name = "SYNTHETIC_CHARACTER_TEST"
bpy.context.scene.frame_end = 30
bpy.ops.wm.save_as_mainfile(filepath=str(Path(sys.argv[sys.argv.index("--") + 1])))
