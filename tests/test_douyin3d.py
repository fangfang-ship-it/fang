import base64
import importlib.util
import json
import numpy as np
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("douyin3d_under_test", ROOT / "douyin3d.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Douyin3DTests(unittest.TestCase):
    def test_ticket_contains_shifted_unix_timestamp(self):
        with mock.patch.object(module.time, "time", return_value=100):
            decoded = base64.b64decode(module._ticket()).decode("ascii")
        self.assertEqual(decoded, str(1_234_567_990))

    def test_auth_headers_are_configurable(self):
        env = {
            "DOUYIN3D_API_KEY": "secret",
            "DOUYIN3D_AUTH_HEADER": "X-API-Key",
            "DOUYIN3D_AUTH_SCHEME": "",
        }
        with mock.patch.dict(module.os.environ, env, clear=True):
            self.assertEqual(module._auth_headers(), {"X-API-Key": "secret"})

    def test_cas_session_auth_takes_priority(self):
        env = {
            "DOUYIN3D_CAS_SESSION": "temporary-session",
            "DOUYIN3D_API_KEY": "api-secret",
        }
        with mock.patch.dict(module.os.environ, env, clear=True):
            self.assertEqual(
                module._auth_headers(),
                {"Cookie": "AGW_CAS_SESSION=temporary-session"},
            )

    def test_node_cas_session_overrides_environment_and_accepts_cookie_pair(self):
        with mock.patch.dict(
            module.os.environ,
            {"DOUYIN3D_CAS_SESSION": "environment-session"},
            clear=True,
        ):
            self.assertEqual(
                module._auth_headers("AGW_CAS_SESSION=node-session"),
                {"Cookie": "AGW_CAS_SESSION=node-session"},
            )

    def test_cas_session_rejects_header_injection(self):
        with mock.patch.dict(
            module.os.environ,
            {"DOUYIN3D_CAS_SESSION": "session\r\nX-Evil: yes"},
            clear=True,
        ):
            with self.assertRaisesRegex(module.Douyin3DError, "invalid characters"):
                module._auth_headers()

    def test_credentials_are_required(self):
        with mock.patch.dict(module.os.environ, {}, clear=True):
            with self.assertRaisesRegex(module.Douyin3DError, "DOUYIN3D_CAS_SESSION"):
                module._auth_headers()

    def test_image_upload_uses_ai_studio_file_data_field(self):
        image = mock.MagicMock()
        image.detach.return_value.to.return_value.float.return_value.numpy.return_value = np.zeros(
            (1, 2, 2, 3), dtype=np.float32
        )
        with mock.patch.object(
            module, "_post", return_value={"url": "https://x/upload.png"}
        ) as mocked_post:
            url = module._upload_comfy_image(image, cas_session="node-session")
        self.assertEqual(url, "https://x/upload.png")
        payload = mocked_post.call_args.args[1]
        self.assertIn("file_data", payload)
        self.assertNotIn("base64", payload)
        self.assertEqual(payload["custom_path"], f"byteartist/douyin3d/{payload['file_name']}")
        self.assertTrue(payload["custom_path"].endswith(".png"))
        self.assertEqual(mocked_post.call_args.kwargs["cas_session"], "node-session")

    def test_extract_nested_asset_and_url(self):
        asset = {
            "asset_id": 42,
            "status": "success",
            "artifacts": [{"primary": True, "format": "glb", "url": "https://x/model.glb"}],
        }
        data = {"items": [[asset]]}
        self.assertEqual(module._extract_asset(data), asset)
        self.assertEqual(module._artifact_url(asset), "https://x/model.glb")

    def test_generate_submits_polls_and_downloads(self):
        asset = {
            "asset_id": 42,
            "status": "success",
            "progress": 100,
            "artifacts": [{"primary": True, "url": "https://x/model.glb"}],
        }
        calls = []

        def fake_post(path, payload, timeout=60, cas_session=""):
            calls.append((path, payload, cas_session))
            if path.endswith("generate"):
                return {"asset_id": 42}
            return {"asset": asset}

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(module, "_post", side_effect=fake_post), \
                mock.patch.object(module, "download_glb", return_value=Path(directory) / "42.glb"):
            result = module.Douyin3DGenerate().generate(
                "Douyin3D", "推荐（随供应商）", "标准", "cup",
                cas_session="node-session", timeout_minutes=1, poll_seconds=2,
            )

        self.assertEqual(result[:3], ("douyin3d/42.glb", "https://x/model.glb", 42))
        self.assertEqual([call[0] for call in calls], [
            "/api/v1/assets/generate",
            "/api/v1/assets/status",
            "/api/v1/assets/detail",
        ])
        self.assertTrue(all(call[2] == "node-session" for call in calls))
        submit = calls[0][1]
        self.assertEqual(submit["vendor"], "douyin3d")
        self.assertEqual(submit["source_type"], "prompt")
        self.assertEqual(submit["douyin3d_params"]["output_format"], "glb")
        self.assertEqual(json.loads(result[3])["status"], "success")

    def test_upload_response_url_is_extracted_from_nested_data(self):
        self.assertEqual(
            module._uploaded_url({"data": {"url": "https://x/image.png"}}),
            "https://x/image.png",
        )

    def test_comfy_image_upload_url_is_used_for_image_generation(self):
        calls = []

        def fake_post(path, payload, timeout=60, cas_session=""):
            calls.append((path, payload))
            if path.endswith("generate"):
                return {"data": {"asset_id": 77}}
            if path.endswith("status"):
                return {"assets": [{"asset_id": 77, "status": "success", "progress": 100}]}
            return {"asset": {"asset_id": 77, "status": "success", "artifacts": [
                {"primary": True, "url": "https://x/model.glb"}
            ]}}

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(module, "_post", side_effect=fake_post), \
                mock.patch.object(module, "_upload_comfy_image", return_value="https://x/upload.png"), \
                mock.patch.object(module, "download_glb", return_value=Path(directory) / "77.glb"):
            module.Douyin3DGenerate().generate(
                "Tripo3D", "推荐（随供应商）", "标准", "", image=object(),
                timeout_minutes=1, poll_seconds=2,
            )

        submit = calls[0][1]
        self.assertEqual(submit["source_type"], "image")
        self.assertEqual(submit["image_url"], "https://x/upload.png")
        self.assertIn("tripo_params", submit)

    def test_vendor_payloads_use_ai_studio_field_names(self):
        common = ("推荐（随供应商）", "高质量", "high", "high", 300000, 2048, True, 7, "不选风格")
        cases = {
            "douyin3d": ("douyin3d_params", "model_version", 1),
            "hunyuan3d": ("hunyuan3d_params", "model", 0),
            "rodin": ("rodin_params", "tier", 8),
            "seed3d": ("seed3d_params", "fileformat", 0),
            "tripo3d": ("tripo_params", "model_version", 2),
        }
        for vendor, (field, key, expected) in cases.items():
            with self.subTest(vendor=vendor):
                payload, meta = module._build_vendor_fields(vendor, *common)
                self.assertEqual(payload[field][key], expected)
                self.assertEqual(meta, {})

    def test_poly3d_style_is_stored_in_meta(self):
        payload, meta = module._build_vendor_fields(
            "module", "推荐（随供应商）", "标准", "high", "high",
            300000, 2048, True, 0, "黏土手办",
        )
        self.assertEqual(payload, {})
        self.assertEqual(meta["moduleStyleProfile"], "worldplay-clay-figurine-v1")

    def test_poly3d_image_input_is_rejected_until_upload_flow_is_supported(self):
        with self.assertRaisesRegex(module.Douyin3DError, "text-to-3D only"):
            module.Douyin3DGenerate().generate(
                "Poly3D", "推荐（随供应商）", "标准", "toy", image_url="https://x/image.png"
            )

    def test_download_glb_rejects_html_disguised_as_model(self):
        import io
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(module, "_output_directory", return_value=Path(directory)), \
                mock.patch.object(module, "urlopen", return_value=io.BytesIO(b"<html>not a model</html>")):
            with self.assertRaisesRegex(module.Douyin3DError, "not a valid binary glTF"):
                module.download_glb("https://x/model.glb", 42)
            self.assertFalse((Path(directory) / "douyin3d_42.glb").exists())

    def test_download_existing_glb_skips_api_authentication(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(
                    module,
                    "download_glb",
                    return_value=Path(directory) / "douyin3d_42.glb",
                ) as mocked_download:
            result = module.Douyin3DDownloadGLB().download(
                "https://x/model.glb", 42
            )

        self.assertEqual(result, (
            "douyin3d/douyin3d_42.glb",
            "https://x/model.glb",
            42,
        ))
        mocked_download.assert_called_once_with("https://x/model.glb", 42)

    def test_download_existing_glb_rejects_non_http_url(self):
        with self.assertRaisesRegex(module.Douyin3DError, "HTTP or HTTPS"):
            module.Douyin3DDownloadGLB().download("file:///tmp/model.glb", 42)

    def test_generate_prompt_widget_is_compact_and_prompt_input_is_connectable(self):
        inputs = module.Douyin3DGenerate.INPUT_TYPES()
        prompt_options = inputs["required"]["prompt"][1]
        prompt_input_options = inputs["optional"]["prompt_input"][1]
        self.assertFalse(prompt_options["multiline"])
        self.assertEqual(prompt_options["default"], "")
        self.assertTrue(prompt_input_options["forceInput"])

    def test_faces_below_old_10000_floor_are_preserved(self):
        payload, _ = module._build_vendor_fields(
            "tripo3d", "Tripo v3.1", "标准", "middle", "middle",
            5000, 2048, True, 0, "不选风格",
        )
        self.assertEqual(payload["tripo_params"]["face_limit"], 5000)
        self.assertEqual(module.Douyin3DGenerate.INPUT_TYPES()["required"]["faces"][1]["min"], 100)

    def test_download_asset_returns_existing_glb(self):
        asset = {
            "asset_id": 7,
            "artifacts": [
                {"format": "glb", "status": "success", "url": "https://x/model.glb"}
            ],
        }
        with mock.patch.object(module, "_post", return_value={"asset": asset}) as mocked_post:
            result = module.Douyin3DDownloadAsset().get_download(7, "GLB", "session")
        self.assertEqual(result[:3], ("https://x/model.glb", "glb", 7))
        mocked_post.assert_called_once()

    def test_download_asset_converts_fbx_and_polls_detail(self):
        glb_asset = {
            "asset_id": 7,
            "artifacts": [
                {"format": "glb", "status": "success", "url": "https://x/model.glb"}
            ],
        }
        fbx_asset = {
            "asset_id": 7,
            "artifacts": [
                {"format": "fbx", "status": "success", "url": "https://x/model.fbx"}
            ],
        }
        responses = [
            {"asset": glb_asset},
            {"base_resp": {"code": 0}, "accepted": True},
            {"asset": fbx_asset},
        ]
        with mock.patch.object(module, "_post", side_effect=responses) as mocked_post:
            result = module.Douyin3DDownloadAsset().get_download(7, "FBX", "session")
        self.assertEqual(result[:3], ("https://x/model.fbx", "fbx", 7))
        convert_call = mocked_post.call_args_list[1]
        self.assertEqual(convert_call.args[0], "/api/v1/assets/convert")
        self.assertEqual(convert_call.args[1]["target_format"], 2)
        self.assertEqual(convert_call.args[1]["content_type"], 0)


if __name__ == "__main__":
    unittest.main()
