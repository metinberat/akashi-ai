"""Fabricated structures for tests only. No professional character data."""
import copy


def character(variant="A"):
    names = ["root", "hips", "spine", "neck", "head", "upper_arm_L", "forearm_L", "hand_L", "upper_arm_R", "forearm_R", "hand_R", "thigh_L", "shin_L", "foot_L", "thigh_R", "shin_R", "foot_R"]
    parents = [None, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 1, 11, 12, 1, 14, 15]
    if variant in {"B", "C"}:
        for side, hand in (("L", 7), ("R", 10)):
            for finger in ("thumb", "index", "middle", "ring", "pinky"):
                parent = hand
                for digit in range(1, 4):
                    names.append(f"{finger}_{digit}_{side}")
                    parents.append(parent)
                    parent = len(names) - 1
    if variant == "C":
        for side, foot, arm in (("L", 13, 6), ("R", 16, 9)):
            names.extend([f"toe_{side}", f"forearm_twist_{side}"])
            parents.extend([foot, arm])
    if variant == "D":
        names = [name.replace("upper_arm_L", "mixamorig:LeftArm").replace("upper_arm_R", "RightArm").replace("forearm_L", "LeftForeArm").replace("forearm_R", "RightForeArm").replace("hand_L", "LeftHand").replace("hand_R", "RightHand") for name in names]
    if variant == "F":
        parents[5] = 0
        parents[8] = 0
    joints = [{"id": str(index), "name": name, "parent": str(parents[index]) if parents[index] is not None else None, "translation": [0, index * 0.1, 0]} for index, name in enumerate(names)]
    result = {"schema_version": 1, "name": "SYNTHETIC-" + variant, "joints": joints,
              "meshes": [{"id": "body", "name": "synthetic_quad", "vertex_count": 4, "positions": [[0,0,0], [1,0,0], [1,1,0], [0,1,0]], "faces": [[0,1,2,3]], "face_count": 1, "uv_maps": ["uv0"], "materials": ["mat"], "skin_id": "skin"}],
              "skins": [{"id": "skin", "mesh_id": "body", "joints": ["0", "1"], "weights": [{"0": 1}, {"0": 0.5, "1": 0.5}, {"1": 1}, {"0": 0.25, "1": 0.75}]}],
              "materials": [{"id": "mat", "name": "fabricated_material", "base_color": [0.5, 0.5, 0.5, 1]}],
              "animations": [{"id": "test", "name": "synthetic-motion", "duration": 1, "frame_rate": 30, "channels": [{"target": "0", "path": "translation", "times": [0,1], "values": [[0,0,0],[0,0.1,0]], "keyframe_count": 2}]}],
              "metadata": {"synthetic": True, "purpose": "test_fixture"}}
    if variant == "E":
        result["animations"] = []
        result["unavailable"] = ["No facial setup in this fabricated source."]
    if variant == "G":
        result["joints"][0]["parent"] = "4"
    return copy.deepcopy(result)
