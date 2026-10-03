"""Add clearly synthetic rich pipeline features to an owned practice test scene."""
import sys
from pathlib import Path
import bpy

output = Path(sys.argv[sys.argv.index("--")+1])
if output.exists():
    raise ValueError("Fixture output must be new.")
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh = next(o for o in bpy.data.objects if o.type == "MESH")
mesh.shape_key_add(name="Basis")
key = mesh.shape_key_add(name="SYNTHETIC surface correction")
for vertex in key.data:
    vertex.co.z += .025
driver = mesh.data.shape_keys.driver_add('key_blocks["SYNTHETIC surface correction"].value')
driver.driver.expression = "0.25"
root = next(b for b in rig.pose.bones if b.parent is None)
root.rotation_mode = "XYZ"
for frame, angle in ((1, 0.), (10, .4), (20, 0.)):
    root.rotation_euler.x = angle
    root.keyframe_insert("rotation_euler", frame=frame)
if len(rig.pose.bones) > 1:
    helper = rig.pose.bones[1].constraints.new("COPY_ROTATION")
    helper.target, helper.subtarget, helper.influence = rig, root.name, .2
modifier = mesh.modifiers.new("SYNTHETIC surface refinement", "SUBSURF")
modifier.levels = 1
material = mesh.data.materials[0]
image = bpy.data.images.new("SYNTHETIC checker evidence", width=8, height=8)
image.pixels[:] = [.5,.5,.5,1.] * 64
image.pack()
node = material.node_tree.nodes.new("ShaderNodeTexImage")
node.image = image
material.node_tree.links.new(node.outputs["Color"], material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])
bpy.context.scene["akashi_synthetic"] = True
bpy.context.scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
