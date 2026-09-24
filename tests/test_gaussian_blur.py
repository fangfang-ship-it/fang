"""Run: python -m unittest discover -s tests -v (requires ComfyUI dependencies)."""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image, ImageFilter
import torch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sky_tools_under_test", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
Node = plugin.NODE_CLASS_MAPPINGS["SkyGaussianBlurFloat"]


class GaussianBlurTests(unittest.TestCase):
    def setUp(self):
        self.pixels = np.random.default_rng(42).integers(0, 256, (2, 33, 65, 3), dtype=np.uint8)
        self.images = torch.from_numpy(self.pixels.astype(np.float32) / 255.0)

    def test_fractional_radius_and_integer_compatibility(self):
        results = []
        for radius in (1.0, 1.25, 1.5, 1.75, 2.0):
            actual, = Node().blur(self.images, radius)
            # Independent reference: original Art Venture tensor -> PIL -> tensor path.
            reference = []
            for image in self.images:
                p = np.clip(255.0 * image.numpy().squeeze(), 0, 255).astype(np.uint8)
                p = Image.fromarray(p).filter(ImageFilter.GaussianBlur(radius=radius))
                reference.append(np.asarray(p).astype(np.float32) / 255.0)
            np.testing.assert_array_equal(actual.numpy(), np.stack(reference))
            self.assertEqual(actual.shape, self.images.shape)
            results.append(actual.numpy())
        energies = [float(np.abs(np.diff(x, axis=2)).mean()) for x in results]
        self.assertTrue(all(a > b for a, b in zip(energies, energies[1:])), energies)

    def test_zero_bypasses_quantization(self):
        values = self.images * 3 - 1
        result, = Node().blur(values, 0)
        self.assertIs(result, values)

    def test_small_images_and_dtypes(self):
        for channels in (1, 3, 4):
            for dtype in (torch.float16, torch.bfloat16, torch.float32, torch.float64):
                x = torch.full((2, 1, 1, channels), 1.0, dtype=dtype)
                y, = Node().blur(x, 1.5)
                self.assertEqual(y.dtype, dtype)
                self.assertEqual(y.device, x.device)
                self.assertTrue(torch.equal(x, y))

    def test_invalid_values(self):
        for radius in (-1, 101, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                Node().blur(self.images, radius)

    def test_registration_and_existing_stretch(self):
        kind, options = Node.INPUT_TYPES()['required']['radius']
        self.assertEqual(kind, 'FLOAT')
        self.assertEqual(options['default'], 1.5)
        self.assertEqual(options['step'], 0.1)
        x = torch.rand(1, 90, 210, 3)
        y, width, height, _ = plugin.NODE_CLASS_MAPPINGS['SkyBottomStretchTo2To1']().stretch(x)
        self.assertEqual((width, height), (210, 105))
        self.assertTrue(torch.equal(x[:, :63], y[:, :63]))


if __name__ == '__main__':
    unittest.main()
