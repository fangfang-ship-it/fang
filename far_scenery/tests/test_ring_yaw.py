"""Check the fixed-template export and the join between all five rotations."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


plugin_dir = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("far_scenery_yaw_test", plugin_dir / "__init__.py",
                                             submodule_search_locations=[str(plugin_dir)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class TestRingYaw(unittest.TestCase):
    def test_five_exports_share_origin_and_close_ring(self):
        image = np.zeros((640, 2048, 4), dtype=np.uint8)
        image[400:600, 100:1948] = (158, 108, 80, 255)
        exporter = plugin.FarSceneryExportRingGLB()
        angles = (0, 72, 144, 216, 288)
        world_positions = []
        with tempfile.TemporaryDirectory() as output, \
                patch.dict(sys.modules, {"folder_paths": SimpleNamespace(get_output_directory=lambda: output)}), \
                patch.object(plugin, "read_rgba", return_value=image):
            for yaw in angles:
                with self.subTest(yaw=yaw):
                    args = {} if yaw == 0 else {"yaw_degrees": yaw}
                    result = exporter.export(None, None, "far-ring-01", **args)
                    filename, _, report = result["result"]
                    geometry = json.loads(report)["geometry"]
                    self.assertEqual(geometry["originMeters"], [0, 0, 0])
                    self.assertEqual(geometry["radiusMeters"], 500)
                    self.assertEqual(geometry["spanDegrees"], 72)
                    self.assertEqual(geometry["yawDegrees"], yaw)

                    glb = Path(filename).read_bytes()
                    json_size = struct.unpack_from("<I", glb, 12)[0]
                    gltf = json.loads(glb[20:20 + json_size])
                    node = gltf["nodes"][0]
                    self.assertEqual(node["translation"], [0, 0, 0])
                    self.assertAlmostEqual(np.linalg.norm(node["rotation"]), 1)
                    direction = np.array(node["rotation"][:3])
                    scalar = node["rotation"][3]
                    view = gltf["bufferViews"][0]
                    start = 28 + json_size + view["byteOffset"]
                    positions = np.frombuffer(glb, dtype="<f4", count=view["byteLength"] // 4,
                                              offset=start).reshape(-1, 3)
                    cross = np.cross(direction, positions)
                    world = positions + 2 * (scalar * cross + np.cross(direction, cross))
                    np.testing.assert_allclose(np.linalg.norm(world[:, [0, 2]], axis=1), 500, atol=.001)
                    world_positions.append(world)

            for current, following in zip(world_positions, world_positions[1:] + world_positions[:1]):
                np.testing.assert_allclose(current[:2], following[-2:], atol=.001)


if __name__ == "__main__":
    unittest.main()
