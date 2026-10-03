"""Local fabricated limb surfaces, never professional/source training assets."""
import math


def limb(bad=True, naming="conventional", rings=13, segments=8):
    names = ["upper_arm_L", "forearm_L"] if naming == "conventional" else ["mixamorig:LeftArm", "LeftForeArm"]
    positions = [[.15*math.cos(2*math.pi*j/segments), i*3/(rings-1), .15*math.sin(2*math.pi*j/segments)] for i in range(rings) for j in range(segments)]
    faces = [[i*segments+j, i*segments+(j+1)%segments, (i+1)*segments+(j+1)%segments, (i+1)*segments+j] for i in range(rings-1) for j in range(segments)]
    weights = []
    for index, position in enumerate(positions):
        ratio = max(0., min(1., (position[1]-1.1)/.8))
        weights.append({key: value for key, value in (("upper", 1-ratio), ("lower", ratio)) if value > 0})
        if bad and index % 17 == 0:
            weights[-1] = {key: value*.3 for key, value in weights[-1].items()}
    return {"name": "SYNTHETIC-ARTICULATED-LIMB", "metadata": {"synthetic": True, "deformation_space": "shared_bind", "purpose": "fabricated_numeric_tests"},
        "joints": [{"id": "upper", "name": names[0], "metadata": {"head": [0,0,0], "tail": [0,1.5,0]}},
                   {"id": "lower", "name": names[1], "parent": "upper", "metadata": {"head": [0,1.5,0], "tail": [0,3,0]}}],
        "meshes": [{"id": "body", "name": "fabricated_limb", "vertex_count": len(positions), "positions": positions, "faces": faces, "skin_id": "skin"}],
        "skins": [{"id": "skin", "mesh_id": "body", "joints": ["upper", "lower"], "weights": weights}], "materials": [], "animations": []}
