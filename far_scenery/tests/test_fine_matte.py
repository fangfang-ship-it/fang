"""Offline registration/weight checks, plus optional real-image inference regression.

Run from the plugin directory: python tests/test_fine_matte.py
Set FAR_SCENERY_TEST_IMAGE and FAR_SCENERY_MATTE_MODEL_DIR for the real model test.
The test never downloads model artifacts: it skips if the four files are absent.
"""
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from hashlib import sha256
from unittest.mock import patch

import numpy as np
from PIL import Image

plugin_dir = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("far_scenery_test", plugin_dir / "__init__.py",
                                             submodule_search_locations=[str(plugin_dir)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
matting = sys.modules[spec.name + ".fine_matte"]


class TestFineMatte(unittest.TestCase):
    def test_registration(self):
        cls = plugin.NODE_CLASS_MAPPINGS["FarSceneryFineMatte"]
        self.assertEqual(cls.INPUT_TYPES(), {"required": {"image": ("IMAGE",)}})
        self.assertEqual(cls.RETURN_TYPES, ("IMAGE", "MASK", "IMAGE"))
        self.assertEqual(cls.RETURN_NAMES, ("image", "mask", "preview"))
        self.assertIn("FarSceneryWhiteMatte", plugin.NODE_CLASS_MAPPINGS)

    def test_wrong_weight_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u2netp.onnx"
            path.write_bytes(b"not a model")
            with self.assertRaisesRegex(RuntimeError, "校验不通过"):
                matting.ensure_weights(Path(tmp))
            self.assertEqual(path.read_bytes(), b"not a model")

    def test_manager_model_filename_with_or_without_extension(self):
        payload = b"test-verified-weight"
        expected = sha256(payload).hexdigest()
        files = (("vitmatte/model.safetensors", "https://example.invalid/model.safetensors", expected),)
        for name in matting.MANAGED_VIT_NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                directory = root / matting.MODEL_FOLDER
                original = root / "checkpoints" / name
                original.parent.mkdir()
                original.write_bytes(payload)
                with patch.object(matting, "FILES", files), patch.object(matting, "urlopen", side_effect=AssertionError("network not allowed")):
                    matting.ensure_weights(directory)
                self.assertEqual((directory / "vitmatte/model.safetensors").read_bytes(), payload)
                self.assertEqual(original.read_bytes(), payload)

    def test_manager_wrong_file_not_loaded(self):
        expected = sha256(b"valid weight").hexdigest()
        files = (("vitmatte/model.safetensors", "https://example.invalid/model.safetensors", expected),)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = root / "checkpoints" / matting.MANAGED_VIT_NAMES[0]
            checkpoint.parent.mkdir()
            checkpoint.write_bytes(b"bad weight")
            with patch.object(matting, "FILES", files), patch.object(matting, "urlopen", side_effect=AssertionError("network not allowed")):
                with self.assertRaisesRegex(RuntimeError, "Manager 下载的.*校验失败"):
                    matting.ensure_weights(root / matting.MODEL_FOLDER)
            self.assertFalse((root / matting.MODEL_FOLDER / "vitmatte/model.safetensors").exists())

    def test_workflow_ports(self):
        workflow = json.loads((plugin_dir / "workflows" / "fine_matte_to_glb.json").read_text())
        nodes = {node["id"]: node for node in workflow["nodes"]}
        for lid, src, sport, dst, dport, dtype in workflow["links"]:
            self.assertEqual(nodes[src]["outputs"][sport]["type"], dtype)
            self.assertIn(lid, nodes[src]["outputs"][sport]["links"])
            self.assertEqual(nodes[dst]["inputs"][dport]["type"], dtype)
            self.assertEqual(nodes[dst]["inputs"][dport]["link"], lid)

    def test_real_models_to_glb(self):
        image_path = os.environ.get("FAR_SCENERY_TEST_IMAGE")
        directory = os.environ.get("FAR_SCENERY_MATTE_MODEL_DIR")
        if not image_path or not directory or not all((Path(directory) / p).is_file() for p, _, _ in matting.FILES):
            self.skipTest("Set the offline test image and installed model directory to run inference.")
        import torch
        # Limit test-process CPU threads only; the actual shared ComfyUI node does not change them.
        torch.set_num_threads(4)
        original = Image.open(image_path).convert("RGB")
        x = torch.from_numpy(np.asarray(original, dtype=np.float32)[None] / 255)
        # Simulate ByteArtist after Manager download: the ViTMatte weight is in checkpoints only.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        cached = root / matting.MODEL_FOLDER
        for relative, _, _ in matting.FILES:
            target = root / "checkpoints" / matting.MANAGED_VIT_NAMES[0] if relative == "vitmatte/model.safetensors" else cached / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(directory) / relative, target)
        with patch.dict(os.environ, {"FAR_SCENERY_MATTE_MODEL_DIR": str(cached)}), patch.object(matting, "urlopen", side_effect=AssertionError("network not allowed")):
            image, mask, preview = plugin.FarSceneryFineMatte().matte(x)
        self.assertTrue((cached / "vitmatte/model.safetensors").is_file())
        self.assertEqual(tuple(image.shape[:3]), tuple(mask.shape))
        self.assertEqual(image.shape[-1], 3)
        self.assertTrue(bool((mask == 0).any() and (mask == 1).any() and ((mask > 0) & (mask < 1)).any()))
        self.assertEqual(preview.shape[-1], 3)
        self.assertIs(matting.get_models(cached), matting.get_models(cached))
        fitted, fitted_mask = plugin.FarSceneryFitTexture().fit(image, mask, 95, 50, 488, plugin.COMFY_MASK, 0)
        rgba = plugin.read_rgba(fitted, fitted_mask, plugin.COMFY_MASK)
        self.assertEqual(rgba.shape, (512, 2048, 4))

        reference = os.environ.get("FAR_SCENERY_TEST_REFERENCE")
        if reference:
            expected = np.asarray(Image.open(reference).convert("RGBA"), dtype=np.int16)
            diff = np.abs(rgba.astype(np.int16) - expected)
            self.assertLess(float(diff.mean()), .1, "Unexpected deviation from accepted trial texture")
            self.assertLess(float((diff > 3).mean()), .001)

        png = plugin.encode_png(rgba)
        glb, meta = plugin.build_glb(png, plugin.RING_RADIUS, plugin.RING_ARC_DEGREES,
                                     plugin.RING_SEGMENTS, plugin.RING_BASE_Y, None, "fine-matte-test")
        json_size = struct.unpack_from("<I", glb, 12)[0]
        gltf = json.loads(glb[20:20 + json_size])
        view = gltf["bufferViews"][gltf["images"][0]["bufferView"]]
        offset = 28 + json_size + view["byteOffset"]
        self.assertEqual(glb[offset:offset + view["byteLength"]], png)
        self.assertEqual(gltf["materials"][0]["alphaMode"], "BLEND")
        self.assertEqual(meta["radiusMeters"], 500)
        self.assertEqual(meta["spanDegrees"], 80)
        self.assertEqual(Image.open(BytesIO(png)).mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
