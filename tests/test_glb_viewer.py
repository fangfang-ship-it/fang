import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("glb_viewer_under_test", ROOT / "glb_viewer.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FangGLBViewerTests(unittest.TestCase):
    def test_resolves_output_relative_glb(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "douyin3d" / "model.glb"
            model.parent.mkdir()
            model.write_bytes(b"glTF")
            with mock.patch.object(module, "_output_root", return_value=root):
                resolved, relative = module.resolve_output_glb("douyin3d/model.glb")
        self.assertEqual(resolved, model)
        self.assertEqual(relative, "douyin3d/model.glb")

    def test_rejects_path_outside_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "output"
            root.mkdir()
            outside = Path(directory) / "secret.glb"
            outside.write_bytes(b"glTF")
            with mock.patch.object(module, "_output_root", return_value=root):
                with self.assertRaisesRegex(module.FangGLBViewerError, "inside"):
                    module.resolve_output_glb(str(outside))

    def test_rejects_missing_or_non_glb_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "model.txt"
            text.write_text("not a model")
            with mock.patch.object(module, "_output_root", return_value=root):
                with self.assertRaisesRegex(module.FangGLBViewerError, "Only .glb"):
                    module.resolve_output_glb("model.txt")
                with self.assertRaisesRegex(module.FangGLBViewerError, "does not exist"):
                    module.resolve_output_glb("missing.glb")

    def test_node_returns_viewer_route_and_relative_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "douyin3d" / "girl model.glb"
            model.parent.mkdir()
            model.write_bytes(b"glTF")
            with mock.patch.object(module, "_output_root", return_value=root):
                result = module.FangGLBWebViewer().open_viewer("douyin3d/girl model.glb")
        self.assertEqual(result["result"], (
            "/fang/glb-viewer?model=douyin3d%2Fgirl%20model.glb",
            "douyin3d/girl model.glb",
        ))
        self.assertEqual(result["ui"]["viewer_url"][0], result["result"][0])

    def test_html_contains_interactive_viewer_controls(self):
        page = module._viewer_html("douyin3d/model.glb")
        self.assertIn("camera-controls", page)
        self.assertIn("自动旋转", page)
        self.assertIn("复位视角", page)
        self.assertIn("/fang/glb-file?model=douyin3d%2Fmodel.glb", page)


if __name__ == "__main__":
    unittest.main()
