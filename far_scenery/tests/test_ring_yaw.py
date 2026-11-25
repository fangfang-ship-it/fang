"""Check the fixed-template export and the overlap between the five rotations."""
import importlib.util
import json
import math
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
    def test_five_exports_share_origin_and_overlap_by_eight_degrees(self):
        image = np.zeros((512, 2048, 4), dtype=np.uint8)
        image[300:488, 51:1997] = (158, 108, 80, 255)
        exporter = plugin.FarSceneryExportRingGLB()
        angles = (0, 72, 144, 216, 288)
        sector_positions = []
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
                    self.assertEqual(geometry["spanDegrees"], 80)
                    self.assertEqual(geometry["textureSize"], [2048, 512])
                    self.assertAlmostEqual(geometry["heightMeters"], 500 * math.radians(80) / 4)
                    self.assertAlmostEqual(
                        geometry["baseMeters"] + geometry["heightMeters"] * 24 / 512, 0
                    )
                    self.assertEqual(geometry["yawDegrees"], yaw)
                    self.assertTrue(geometry["yawBakedIntoMesh"])

                    glb = Path(filename).read_bytes()
                    json_size = struct.unpack_from("<I", glb, 12)[0]
                    gltf = json.loads(glb[20:20 + json_size])
                    node = gltf["nodes"][0]
                    self.assertEqual(node["translation"], [0, 0, 0])
                    self.assertEqual(node["rotation"], [0, 0, 0, 1])
                    view = gltf["bufferViews"][0]
                    start = 28 + json_size + view["byteOffset"]
                    positions = np.frombuffer(glb, dtype="<f4", count=view["byteLength"] // 4,
                                              offset=start).reshape(-1, 3)
                    np.testing.assert_allclose(np.linalg.norm(positions[:, [0, 2]], axis=1), 500, atol=.001)
                    middle = positions[len(positions) // 2]
                    angle = math.radians(yaw)
                    np.testing.assert_allclose(
                        middle[[0, 2]], [-500 * math.sin(angle), -500 * math.cos(angle)], atol=.001
                    )
                    sector_positions.append(positions)

            for current, following in zip(sector_positions, sector_positions[1:] + sector_positions[:1]):
                # Five vertex pairs span the shared 8 degrees at 2 degrees per segment.
                np.testing.assert_allclose(current[:10], following[-10:], atol=.001)

    def test_merge_five_exports_preserves_meshes_and_textures(self):
        exporter = plugin.FarSceneryExportRingGLB()
        merger = plugin.NODE_CLASS_MAPPINGS["FarSceneryMergeRingGLB"]()
        paths = []
        angles = [0, 72, 144, 216, 288]

        def buffer_view(document, binary, index):
            view = document["bufferViews"][index]
            start = view["byteOffset"]
            return binary[start:start + view["byteLength"]]

        with tempfile.TemporaryDirectory() as output, patch.dict(sys.modules, {
            "folder_paths": SimpleNamespace(get_output_directory=lambda: output),
        }):
            for index, angle in enumerate(angles):
                image = np.zeros((512, 2048, 4), dtype=np.uint8)
                image[300:488, 51:1997] = (158 + index, 108, 80, 255)
                with patch.object(plugin, "read_rgba", return_value=image):
                    entry = exporter.export(None, None, f"far-ring-{index + 1}", yaw_degrees=angle)
                paths.append(entry["result"][0])

            result = merger.export(*paths, "far-ring-full", workbench_url="https://workbench.example.com")
            path, url, report = result["result"]
            self.assertEqual(result["ui"]["3d"][0]["filename"], "far-ring-full.glb")
            self.assertTrue(url.startswith("https://workbench.example.com/api/view?"))
            self.assertEqual(json.loads(report)["geometry"]["yawAnglesDegrees"], angles)
            self.assertEqual(json.loads(report)["triangles"], 400)
            with self.assertRaisesRegex(ValueError, "第 5 路 GLB.*方向重复"):
                merger.export(*paths[:4], paths[0], "duplicate")
            with self.assertRaisesRegex(ValueError, "第 5 路.*请重新运行"):
                merger.export(*paths[:4], str(Path(paths[4]).with_name("missing.glb")), "missing")

            blob = Path(path).read_bytes()
            json_size = struct.unpack_from("<I", blob, 12)[0]
            document = json.loads(blob[20:20 + json_size])
            binary = blob[28 + json_size:]
            node, = document["nodes"]
            self.assertEqual(node["translation"], [0, 0, 0])
            self.assertEqual(node["rotation"], [0, 0, 0, 1])
            mesh, = document["meshes"]
            self.assertEqual(len(mesh["primitives"]), 5)
            for source_path, primitive in zip(paths, mesh["primitives"]):
                source, source_binary, _ = plugin.glb.read_ring_glb(Path(source_path).read_bytes())
                original = source["meshes"][0]["primitives"][0]
                for key, source_accessor in original["attributes"].items():
                    source_view = source["accessors"][source_accessor]["bufferView"]
                    view = document["accessors"][primitive["attributes"][key]]["bufferView"]
                    self.assertEqual(buffer_view(document, binary, view),
                                     buffer_view(source, source_binary, source_view))
                material = document["materials"][primitive["material"]]
                self.assertEqual(material["alphaMode"], "BLEND")
                texture = material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
                image_index = document["textures"][texture]["source"]
                self.assertEqual(buffer_view(document, binary, document["images"][image_index]["bufferView"]),
                                 buffer_view(source, source_binary, source["images"][0]["bufferView"]))


if __name__ == "__main__":
    unittest.main()
