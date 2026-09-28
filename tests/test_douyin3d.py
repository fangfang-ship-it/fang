import base64
import importlib.util
import json
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

    def test_credentials_are_required(self):
        with mock.patch.dict(module.os.environ, {}, clear=True):
            with self.assertRaisesRegex(module.Douyin3DError, "DOUYIN3D_API_KEY"):
                module._auth_headers()

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

        def fake_post(path, payload, timeout=60):
            calls.append((path, payload))
            if path.endswith("generate"):
                return {"asset_id": 42}
            return {"asset": asset}

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(module, "_post", side_effect=fake_post), \
                mock.patch.object(module, "download_glb", return_value=Path(directory) / "42.glb"):
            result = module.Douyin3DGenerate().generate("cup", timeout_minutes=1, poll_seconds=2)

        self.assertEqual(result[:3], (str(Path(directory) / "42.glb"), "https://x/model.glb", 42))
        self.assertEqual([call[0] for call in calls], [
            "/api/v1/assets/generate",
            "/api/v1/assets/status",
            "/api/v1/assets/detail",
        ])
        submit = calls[0][1]
        self.assertEqual(submit["vendor"], "douyin3d")
        self.assertEqual(submit["source_type"], "prompt")
        self.assertEqual(submit["douyin3d_params"]["OutputFormat"], "glb")
        self.assertEqual(json.loads(result[3])["status"], "success")


if __name__ == "__main__":
    unittest.main()
