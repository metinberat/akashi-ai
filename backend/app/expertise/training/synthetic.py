"""Seeded varied practice worlds. Analytic labels are synthetic, not professional truth."""
import copy
import math
import random

from .contracts import GENERATOR_VERSION


def recipe_finger_segments(recipe=None):
    semantics = (recipe or {}).get("patterns", {}).get("semantic_counts", {})
    return 3 if any(k in str(semantics).lower() for k in ("finger", "thumb", "index")) else 2


def practice_context(level, recipe=None):
    return GENERATOR_VERSION+":level:"+str(level)+":fingers:"+str(recipe_finger_segments(recipe))


def generate(seed, level, recipe=None):
    rng = random.Random(seed)
    height, width = rng.uniform(.8, 1.6), rng.uniform(.8, 1.5)
    # Source relations influence the practice distribution, not exact source geometry.
    finger_segments = recipe_finger_segments(recipe)
    observed_fingers = finger_segments == 3
    bones = []
    def bone(identifier, parent, head, tail, region):
        naming = rng.choice((identifier, "mixamorig:"+identifier.replace("_L", "Left").replace("_R", "Right"), "DEF-"+identifier))
        head, tail = [[p[0]*width, p[1]*height, p[2]*width] for p in (head, tail)]
        bones.append({"id": identifier, "name": naming, "parent": parent,
                      "metadata": {"head": head, "tail": tail, "deform": True, "synthetic_region": region}})
    # Each level has materially different geometry, hierarchy and failure patterns.
    bone("upper_arm_L", None, [0,0,0], [0,1.4,0], "arm")
    bone("forearm_L", "upper_arm_L", [0,1.4,0], [rng.uniform(-.2,.2),2.8,.05], "arm")
    if level >= 2:
        bone("hand_L", "forearm_L", [0,2.8,.05], [0,3.3,.05], "hand")
        for i, finger in enumerate(("thumb", "index", "middle", "ring", "little")):
            x = (i-2)*.13
            for segment in range(finger_segments):
                bone(finger+"_%02d_L" % (segment+1), "hand_L" if not segment else finger+"_%02d_L" % segment,
                     [x,3.3+segment*.7/finger_segments,.05], [x,3.3+(segment+1)*.7/finger_segments,.05], "hand")
    if level >= 3:
        bone("forearm_twist_L", "forearm_L", [0,1.8,.05], [0,2.35,.05], "twist")
        bone("thigh_R", None, [1.3,1,0], [1.3,-.3,0], "leg")
        bone("shin_R", "thigh_R", [1.3,-.3,0], [1.3,-1.5,0], "leg")
        bone("foot_R", "shin_R", [1.3,-1.5,0], [1.3,-1.5,.4], "foot")
        bone("toe_R", "foot_R", [1.3,-1.5,.4], [1.3,-1.5,.7], "foot")
    if level >= 4:
        bone("spine", None, [-1.2,0,0], [-1.2,1.5,0], "torso")
        bone("neck", "spine", [-1.2,1.5,0], [-1.2,1.9,0], "neck")
        bone("head", "neck", [-1.2,1.9,0], [-1.2,2.5,0], "head")
    meshes, skins, regions = [], [], []
    points_by_bone = {j["id"]: j for j in bones}
    rings, segments = rng.choice((7,9,11)), rng.choice((6,8,10))
    teacher_power = rng.choice((1., 2., 3.))
    for joint in bones:
        head, tail = joint["metadata"]["head"], joint["metadata"]["tail"]
        delta = [tail[i]-head[i] for i in range(3)]
        length = math.sqrt(sum(v*v for v in delta))
        axis = [v/length for v in delta]
        reference = [1.,0.,0.] if abs(axis[0]) < .9 else [0.,1.,0.]
        cross = [axis[1]*reference[2]-axis[2]*reference[1], axis[2]*reference[0]-axis[0]*reference[2], axis[0]*reference[1]-axis[1]*reference[0]]
        cross_length = math.sqrt(sum(v*v for v in cross))
        u = [v/cross_length for v in cross]
        v = [axis[1]*u[2]-axis[2]*u[1], axis[2]*u[0]-axis[0]*u[2], axis[0]*u[1]-axis[1]*u[0]]
        radius = length*rng.uniform(.045,.075)
        layers = 2 if level == 5 and joint["metadata"]["synthetic_region"] in {"arm", "torso"} else 1
        for layer in range(layers):
            mesh_id = "surface:"+joint["id"]+":"+str(layer)
            positions = [[head[k]+delta[k]*r/(rings-1)+radius*(1+.2*layer)*(u[k]*math.cos(2*math.pi*s/segments)+v[k]*math.sin(2*math.pi*s/segments)) for k in range(3)] for r in range(rings) for s in range(segments)]
            faces = [[r*segments+s,r*segments+(s+1)%segments,(r+1)*segments+(s+1)%segments,(r+1)*segments+s] for r in range(rings-1) for s in range(segments)]
            palette = [joint["id"]]+([joint["parent"]] if joint["parent"] else [])
            weights = []
            for p in positions:
                from app.expertise.workshop.geometry import segment_distance
                distances = {key: max(1e-8, segment_distance(p, (points_by_bone[key]["metadata"]["head"], points_by_bone[key]["metadata"]["tail"]))) for key in palette}
                raw = {key: (min(distances.values())/d)**teacher_power for key, d in distances.items()}
                weights.append({key: weight/sum(raw.values()) for key, weight in raw.items()})
            skin_id = "skin:"+mesh_id
            meshes.append({"id": mesh_id, "name": mesh_id, "vertex_count": len(positions), "positions": positions, "faces": faces,
                "skin_id": skin_id, "uv_maps": ["UVMap"], "materials": ["synthetic-surface"],
                "metadata": {"practice_joint": joint["id"], "orientation_hint": axis, "synthetic_layer": layer,
                             "uv_coordinates": {"UVMap": [[(index%segments)/segments, (index//segments)/(rings-1)] for face in faces for index in face]}}})
            skins.append({"id": skin_id, "mesh_id": mesh_id, "joints": palette, "weights": weights})
            regions.append({"mesh": mesh_id, "joint": joint["id"], "parent": joint["parent"], "name": joint["name"]})
    teacher = {"schema_version": 1, "name": "SYNTHETIC-PRACTICE-%s-L%s" % (seed,level), "joints": bones, "meshes": meshes, "skins": skins,
        "materials": [{"id": "synthetic-surface", "name": "SYNTHETIC graphite", "diffuse_color": [.35,.4,.45,1]}], "animations": [],
        "metadata": {"synthetic": True, "deformation_space": "shared_bind", "generator_version": GENERATOR_VERSION}}
    student = copy.deepcopy(teacher)
    if level in (2, 4):
        student["joints"], student["skins"] = [], []
        for mesh in student["meshes"]: mesh.pop("skin_id")
    else:
        for skin in student["skins"]:
            for i, weights in enumerate(skin["weights"]):
                if level == 0:
                    if i % rng.choice((3,5,7)) == 0: skin["weights"][i] = {k: w*rng.uniform(.2,.6) for k,w in weights.items()}
                elif i % 3 != 0:
                    skin["weights"][i] = {rng.choice(skin["joints"]): 1.}
    student["metadata"]["practice_descriptor"] = {"regions": regions, "synthetic_anatomy_labels": True,
        "note": "Region/parent labels are public synthetic task inputs; exact reference landmarks/weights are withheld."}
    return student, teacher, {"seed": seed, "level": level, "generator": GENERATOR_VERSION,
        "teacher_power": teacher_power, "recipe_id": recipe.get("id") if recipe else None, "synthetic": True,
        "capabilities": ["weights", "hierarchy", "joint_geometry"] if level in (2,4) else ["weights", "deformation"],
        "recipe_adaptation": {"finger_segments": finger_segments, "basis": "source semantic relations" if observed_fingers else "procedural baseline"},
        "scope": "procedural_distribution_not_professional_character_mastery"}
