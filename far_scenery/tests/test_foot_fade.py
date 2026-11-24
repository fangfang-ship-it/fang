"""Regression tests for continuous foothill fading; no model weights required."""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


plugin_dir = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("far_scenery_fade_test", plugin_dir / "__init__.py",
                                             submodule_search_locations=[str(plugin_dir)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


def old_fade(alpha, pixels):
    visible = alpha >= 13 / 255
    first = visible.argmax(axis=0)
    last = alpha.shape[0] - 1 - visible[::-1].argmax(axis=0)
    band = np.minimum(pixels, (last - first + 1) // 4)
    active = visible.any(axis=0) & (band > 0)
    rows = np.arange(alpha.shape[0], dtype=np.float32)[:, None]
    ramp = np.clip((last - rows) / np.maximum(1, band), 0, 1)
    np.multiply(alpha, ramp * ramp * (3 - 2 * ramp), out=alpha, where=active)


class TestFootFade(unittest.TestCase):
    def test_zero_and_empty(self):
        alpha = np.random.default_rng(9).random((64, 128), dtype=np.float32)
        before = alpha.copy()
        plugin.fade_foot(alpha, 0)
        np.testing.assert_array_equal(before, alpha)
        empty = np.zeros((64, 128), dtype=np.float32)
        plugin.fade_foot(empty, 40)
        self.assertFalse(empty.any())

    def test_flat_foot_keeps_upper_mountain(self):
        alpha = np.zeros((320, 200), dtype=np.float32)
        alpha[30:300, 10:190] = 1
        before = alpha.copy()
        plugin.fade_foot(alpha, 40)
        np.testing.assert_array_equal(alpha[:250], before[:250])
        np.testing.assert_array_equal(alpha[:, :10], 0)
        self.assertTrue(.45 < alpha[280, 100] < .55)
        self.assertLess(alpha[299, 100], .005)
        self.assertTrue(np.all(np.diff(alpha[258:300, 100]) <= 1e-6))
        self.assertTrue(np.all(alpha <= before))

    def test_stepped_contour_no_vertical_seams(self):
        # A 1–2 px staircase recreates the horizontal quantization in old masks.
        h, w = 320, 600
        row = np.arange(h)[:, None]
        column = np.arange(w)
        bottom = 260 + (column // 24) % 4
        top = 100 + (column // 30) % 5
        original = ((row >= top) & (row <= bottom)).astype(np.float32)
        before, after = original.copy(), original.copy()
        old_fade(before, 40)
        plugin.fade_foot(after, 40)
        # Compare only the smooth fade interior, excluding the actual silhouette.
        old_jump = np.max(np.abs(np.diff(before[232:249, 60:-60], axis=1)))
        new_jump = np.max(np.abs(np.diff(after[232:249, 60:-60], axis=1)))
        self.assertLess(new_jump, old_jump * .35)
        np.testing.assert_array_equal(original[:210], after[:210])
        self.assertTrue(np.isfinite(after).all() and np.all(after <= original))

    def test_separate_spans_do_not_cross_blend(self):
        alpha = np.zeros((220, 240), dtype=np.float32)
        alpha[50:175, 20:100] = 1
        alpha[120:210, 130:220] = 1
        before = alpha.copy()
        plugin.fade_foot(alpha, 80)
        np.testing.assert_array_equal(alpha[:, 100:130], 0)
        self.assertTrue(np.all(alpha <= before))
        self.assertLess(alpha[174, 60], .005)
        self.assertLess(alpha[209, 180], .01)
        self.assertEqual(alpha[100, 60], 1)
        self.assertEqual(alpha[140, 180], 1)

    def test_thin_foothill_and_canvas_border(self):
        alpha = np.zeros((64, 80), dtype=np.float32)
        alpha[50:64, 10:55] = 1
        alpha[62:64, 55:70] = 1
        original = alpha.copy()
        plugin.fade_foot(alpha, 80)
        self.assertTrue(np.all(alpha <= original) and np.isfinite(alpha).all())
        self.assertEqual(alpha[50, 20], 1)
        self.assertLess(alpha[-1, 20], .25)


if __name__ == "__main__":
    unittest.main()
