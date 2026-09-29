import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import core


def sky(width=560, height=240, large=False):
    top = np.array([0.48, 0.42, 0.53], dtype=np.float32)
    bottom = np.array([1.0, 0.61, 0.36], dtype=np.float32)
    t = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    a = np.broadcast_to(top * (1-t) + bottom*t, (height, width, 3)).copy()
    y, x = np.mgrid[:height, :width]
    ry = 22 if large else 5
    mask = (((x-width*.3)/24)**2 + ((y-height*.58)/ry)**2 < 1)
    mask |= (((x-width*.62)/34)**2 + ((y-height*.59)/ry)**2 < 1)
    a[mask] = [0.28, 0.20, 0.34]
    return a, mask


class LayoutTests(unittest.TestCase):
    def test_strict_moves_all_known_content_without_pixel_change(self):
        a, mask = sky()
        p = core.process(a)
        self.assertTrue(p['report']['layout_pass'], p['report'])
        self.assertEqual(p['result'].shape, (280, 560, 3))
        shift = p['report']['layout']['translation_y_px']
        ys, xs = np.where(mask)
        self.assertTrue(np.array_equal(a[ys, xs], p['result'][ys+shift, xs]))
        low, high = p['report']['layout']['allowed_px']
        self.assertGreaterEqual(int((ys+shift).min()), low)
        self.assertLess(int((ys+shift).max()), high)
        for region in [p['result'][:low], p['result'][high:]]:
            self.assertTrue(np.array_equal(region, np.broadcast_to(region[:, :1], region.shape)))

    def test_large_cloud_rejected_strict_but_not_horizon(self):
        a, _ = sky(large=True)
        strict = core.process(a)
        safe = core.process(a, 'horizon_only')
        self.assertEqual(strict['report']['code'], 'BAND_DOES_NOT_FIT')
        self.assertNotIn('result', strict)
        self.assertTrue(safe['report']['layout_pass'])
        self.assertEqual(safe['report']['checks']['retained_core_max_error'], 0)

    def test_background_only_does_not_get_false_pass(self):
        a, _ = sky()
        a[:] = a[:, :1]
        p = core.process(a)
        self.assertEqual(p['report']['code'], 'NO_RELIABLE_CONTENT')
        self.assertNotIn('result', p)

    def test_detached_lower_cloud_is_not_silently_dropped(self):
        a, _ = sky()
        a[210:215, 110:125] = [0.12, 0.15, 0.24]
        p = core.process(a)
        self.assertFalse(p['report']['layout_pass'])
        if 'bounds' in p:
            self.assertGreater(p['bounds'][1], 214)

    def test_top_edge_content_is_rejected(self):
        a, _ = sky()
        a[0:12, 80:135] = [0.15, 0.2, 0.3]
        p = core.process(a)
        self.assertEqual(p['report']['code'], 'CONTENT_TOUCHES_EDGE')

    def test_odd_width_no_horizontal_scale(self):
        a, _ = sky(width=561)
        p = core.process(a)
        self.assertTrue(p['report']['layout_pass'])
        self.assertEqual(p['result'].shape[:2], (281, 562))
        self.assertEqual(p['report']['checks']['retained_core_max_error'], 0)

    def test_final_coordinate_option_is_explicit(self):
        a, _ = sky()
        p = core.process(a, coordinate_space='final_2_1')
        self.assertEqual(p['report']['layout']['allowed_px'], [84, 126])

    def test_invalid_input_is_not_exportable(self):
        a, _ = sky()
        a[0, 0, 0] = np.nan
        self.assertEqual(core.process(a)['report']['code'], 'INVALID_RGB')

    def test_known_transparent_fringe_moves_with_core(self):
        a, mask = sky()
        # Deliberately add a clear low-opacity wisp and ensure it remains included.
        a[152:154, 330:345] -= .07
        p = core.process(a, 'horizon_only')
        self.assertTrue(p['report']['layout_pass'])
        self.assertGreaterEqual(p['bounds'][3], 154)
        shift = p['report']['layout']['translation_y_px']
        self.assertTrue(np.array_equal(a[152:154, 330:345], p['result'][152+shift:154+shift, 330:345]))

    def test_backend_saves_no_image_for_rejected_request(self):
        # Test the real exporter with only Comfy's output-directory interface stubbed.
        spec = importlib.util.spec_from_file_location('sky_plugin', ROOT/'__init__.py',
                                                     submodule_search_locations=[str(ROOT)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules['sky_plugin'] = mod
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            old = sys.modules.get('folder_paths')
            sys.modules['folder_paths'] = types.SimpleNamespace(get_output_directory=lambda: tmp)
            try:
                a, _ = sky(large=True)
                packet = core.process(a)
                out = mod.NODE_CLASS_MAPPINGS['SkyAutoValidateSave']().save(packet, '../../bad path')
                self.assertFalse(out['result'][0])
                self.assertEqual(out['ui']['images'], [])
                self.assertFalse(list(Path(tmp).rglob('*.png')))
                self.assertEqual(len(list(Path(tmp).rglob('*.json'))), 1)
                report = json.loads(out['result'][1])
                self.assertIsNone(report['candidate_file'])
            finally:
                if old is None:
                    del sys.modules['folder_paths']
                else:
                    sys.modules['folder_paths'] = old

    def test_workflow_graphs_and_api_links(self):
        for path in (ROOT/'workflows').glob('*.json'):
            graph = json.loads(path.read_text())
            if 'nodes' not in graph:
                self.assertEqual(graph['5']['class_type'], 'SkyAutoValidateSave')
                for nid, item in graph.items():
                    for value in item['inputs'].values():
                        if isinstance(value, list):
                            self.assertIn(value[0], graph)
                continue
            nodes = {n['id']: n for n in graph['nodes']}
            for lid, src, src_slot, dst, dst_slot, typ in graph['links']:
                self.assertEqual(nodes[dst]['inputs'][dst_slot]['link'], lid)
                self.assertIn(lid, nodes[src]['outputs'][src_slot]['links'])
                self.assertEqual(nodes[src]['outputs'][src_slot]['type'], typ)
                self.assertEqual(nodes[dst]['inputs'][dst_slot]['type'], typ)


if __name__ == '__main__':
    unittest.main(verbosity=2)
