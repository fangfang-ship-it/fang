import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("douyin3d_under_test", ROOT / "douyin3d.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Douyin3DTests(unittest.TestCase):
    def test_ticket_contains_shifted_timestamp(self):
        with mock.patch.object(module.time, "time", return_value=100):
            self.assertEqual(base64.b64decode(module._ticket()).decode(), "1234567990")

    def test_cookie_accepts_full_cookie_and_bare_session(self):
        self.assertEqual(module._cookie_headers("a=1; AGW_CAS_SESSION=x"),
                         {"Cookie": "a=1; AGW_CAS_SESSION=x"})
        self.assertEqual(module._cookie_headers("session-value"),
                         {"Cookie": "AGW_CAS_SESSION=session-value"})
        self.assertEqual(module._cookie_headers("Cookie: a=1; b=2"),
                         {"Cookie": "a=1; b=2"})

    def test_cookie_rejects_header_injection(self):
        with self.assertRaisesRegex(module.Douyin3DError, "换行"):
            module._cookie_headers("a=1\r\nX-Evil: yes")

    def test_current_douyin_parameters_are_passed_directly(self):
        params = module._douyin_params(
            "V3.1", "超高", "中", 4096, 123456, False, True,
            "强", True, True, 7, 8,
        )
        self.assertEqual(params["model_version"], 0)
        self.assertEqual(params["gene_quality_geo"], 3)
        self.assertIsNone(params["gene_quality_tex"])
        self.assertEqual(params["faces_num"], 123456)
        self.assertFalse(params["enable_texture"])
        self.assertFalse(params["enable_pbr"])
        self.assertTrue(params["split_model"])
        self.assertTrue(params["quad_remesh"])
        self.assertEqual(params["seed_geo"], 7)
        self.assertIsNone(params["seed_tex"])

    def test_quality_is_not_overridden_by_a_preset(self):
        params = module._douyin_params(
            "V3.1-fast", "低", "超高", 1024, 5000, True, False,
            "弱", False, False, 11, 22,
        )
        self.assertEqual(params["model_version"], 1)
        self.assertEqual(params["gene_quality_geo"], 0)
        self.assertEqual(params["gene_quality_tex"], 3)
        self.assertEqual(params["uv_size"], 1024)
        self.assertEqual(params["faces_num"], 5000)
        self.assertEqual(params["seed_tex"], 22)

    def test_image_upload_uses_unique_path(self):
        image = mock.MagicMock()
        image.detach.return_value.to.return_value.float.return_value.numpy.return_value = np.zeros(
            (1, 2, 2, 3), dtype=np.float32
        )
        with mock.patch.object(module.time, "time", return_value=123.456), \
                mock.patch.object(module, "_request", return_value={"data": {"url": "https://x/i.png"}}) as request:
            url = module._upload_image(image, "a=1")
        self.assertEqual(url, "https://x/i.png")
        payload = request.call_args.args[1]
        self.assertEqual(payload["file_name"], "comfyui_123456.png")
        self.assertTrue(payload["custom_path"].endswith("comfyui_123456.png"))

    def test_project_id_auto_resolution(self):
        response = {"items": [[{"project_id": 99, "name": "demo"}]]}
        with mock.patch.object(module, "_request", return_value=response):
            self.assertEqual(module._resolve_project_id(0, "a=1"), 99)
        self.assertEqual(module._resolve_project_id(88, "a=1"), 88)

    def test_generate_uses_image_source_and_exact_params(self):
        asset = {"asset_id": 42, "status": "success", "progress": 100,
                 "artifacts": [{"format": "glb", "status": "success", "url": "https://x/m.glb"}]}
        calls = []

        def fake_request(path, payload=None, **kwargs):
            calls.append((path, payload))
            if path.endswith("generate"):
                return {"asset_id": 42}
            return {"asset": asset}

        with mock.patch.object(module, "_resolve_project_id", return_value=9), \
                mock.patch.object(module, "_upload_image", return_value="https://x/i.png"), \
                mock.patch.object(module, "_request", side_effect=fake_request), \
                mock.patch.object(module, "_wait_for_asset", return_value=asset):
            bundle, asset_id, status = module.Douyin3DGenerate().generate(
                object(), "a=1", 9, "测试模型", "V3.1-fast", "高", "中",
                2048, 654321, True, True, "强", False, True, 12, 34, 30, 10,
            )
        submit = calls[0][1]
        self.assertEqual(submit["project_id"], 9)
        self.assertEqual(submit["vendor"], "douyin3d")
        self.assertEqual(submit["source_type"], "image")
        self.assertEqual(submit["image_url"], "https://x/i.png")
        self.assertEqual(submit["description"], "测试模型")
        self.assertEqual(submit["douyin3d_params"]["faces_num"], 654321)
        self.assertEqual(submit["douyin3d_params"]["gene_quality_tex"], 1)
        self.assertEqual(asset_id, 42)
        self.assertEqual(bundle["cookies"], "a=1")
        self.assertNotIn("cookies", json.loads(status))

    def test_save_existing_glb_downloads_file(self):
        current = {"asset_id": 7, "artifacts": [
            {"format": "glb", "status": "success", "url": "https://x/model.glb"}
        ]}
        bundle = {"asset_id": 7, "project_id": 9, "cookies": "a=1", "asset": current}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(module, "_request", return_value={"asset": current}) as request, \
                mock.patch.object(module, "_output_directory", return_value=Path(directory)), \
                mock.patch.object(module, "_download", side_effect=lambda url, target, **kwargs: target) as download:
            result = module.Douyin3DSaveModel().save(bundle, "GLB", "my model", 10, 3)
        self.assertEqual(result, ("douyin3d/my_model_7.glb", "https://x/model.glb", 7))
        request.assert_called_once()
        self.assertEqual(download.call_args.args[1].name, "my_model_7.glb")

    def test_save_requests_conversion_when_format_missing(self):
        glb = {"asset_id": 7, "artifacts": [
            {"format": "glb", "status": "success", "url": "https://x/model.glb"}
        ]}
        obj = {"asset_id": 7, "artifacts": [
            {"format": "obj", "status": "success", "url": "https://x/model.obj"}
        ]}
        responses = [{"asset": glb}, {"accepted": True}, {"asset": obj}]
        bundle = {"asset_id": 7, "cookies": "a=1", "asset": glb}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(module, "_request", side_effect=responses) as request, \
                mock.patch.object(module, "_output_directory", return_value=Path(directory)), \
                mock.patch.object(module, "_download", side_effect=lambda url, target, **kwargs: target):
            result = module.Douyin3DSaveModel().save(bundle, "OBJ", "result", 1, 1)
        self.assertEqual(result[0], "douyin3d/result_7.obj")
        self.assertEqual(request.call_args_list[1].args[0], "/api/v1/assets/convert")
        self.assertEqual(request.call_args_list[1].args[1]["target_format"], 3)

    def test_download_glb_rejects_html(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(module, "_output_directory", return_value=Path(directory)), \
                mock.patch.object(module, "urlopen", return_value=io.BytesIO(b"<html>bad</html>")):
            with self.assertRaisesRegex(module.Douyin3DError, "有效 GLB"):
                module.download_glb("https://x/model.glb", 1)


if __name__ == "__main__":
    unittest.main()
