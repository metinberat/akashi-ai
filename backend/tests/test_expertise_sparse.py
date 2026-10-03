import copy
import struct
import unittest
from app.expertise.parsers import Accessors


class SparseTests(unittest.TestCase):
    def fixture(self):
        binary = bytes([0, 2, 0, 0]) + struct.pack("<6f", 1, 2, 3, 4, 5, 6)
        data = {
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": [
                {"buffer": 0, "byteLength": 2},
                {"buffer": 0, "byteOffset": 4, "byteLength": 24},
            ],
            "accessors": [
                {
                    "count": 3,
                    "type": "VEC3",
                    "componentType": 5126,
                    "sparse": {
                        "count": 2,
                        "indices": {"bufferView": 0, "componentType": 5121},
                        "values": {"bufferView": 1},
                    },
                }
            ],
        }
        return data, binary

    def test_sparse_morph_values_are_actual_overlays_not_zero_approximations(self):
        data, binary = self.fixture()
        reader = Accessors(data, [binary])
        self.assertEqual(reader.values(0), [[1, 2, 3], [0, 0, 0], [4, 5, 6]])
        self.assertIs(reader.values(0), reader.values(0))
        self.assertEqual(reader._decoded_scalars, 9)

    def test_malformed_sparse_indices_counts_bounds_and_nonfinite_rejected(self):
        data, binary = self.fixture()
        for raw in (
            bytes([2, 0]) + binary[2:],
            bytes([0, 0]) + binary[2:],
            bytes([0, 5]) + binary[2:],
            binary[:4] + struct.pack("<f", float("nan")) + binary[8:],
        ):
            with self.assertRaises(ValueError):
                Accessors(data, [raw]).values(0)
        for mutate in (
            lambda d: d["accessors"][0]["sparse"].update(count=4),
            lambda d: d["accessors"][0]["sparse"]["values"].update(byteOffset=100),
            lambda d: d["accessors"][0].update(count=True),
        ):
            bad = copy.deepcopy(data)
            mutate(bad)
            with self.assertRaises(ValueError):
                Accessors(bad, [binary]).values(0)

    def test_missing_external_sparse_buffer_remains_unavailable(self):
        data, _ = self.fixture()
        data["buffers"][0]["uri"] = "https://example.invalid/asset.bin"
        reader = Accessors(data, [])
        self.assertEqual(reader.values(0), [])
        self.assertTrue(reader.unavailable)
