"""Verify that copied workflows generate URLs using their current room."""

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "far_scenery_workbench_test", Path(__file__).resolve().parents[1] / "workbench.py"
)
workbench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workbench)


class TestWorkbenchOrigin(unittest.IsolatedAsyncioTestCase):
    async def test_current_room_replaces_copied_address_without_leaking_between_runs(self):
        middlewares = []
        hooks = []
        server = SimpleNamespace(
            app=SimpleNamespace(frozen=False, middlewares=middlewares),
            add_on_prompt_handler=hooks.append,
        )
        fake_modules = {
            "server": SimpleNamespace(PromptServer=SimpleNamespace(instance=server)),
            "aiohttp": SimpleNamespace(web=SimpleNamespace(middleware=lambda func: func)),
        }
        with patch.dict(sys.modules, fake_modules):
            workbench.install_workbench_url_detection()
            workbench.install_workbench_url_detection()
        middleware, = middlewares
        hook, = hooks
        first = "https://bench-647421636978423438.byteartist-workbench.bytedance.net"
        second = "https://bench-647713312905110088.byteartist-workbench.bytedance.net"

        async def handle(_request):
            await asyncio.sleep(0)
            payload = {"prompt": {
                "1": {"class_type": "FarSceneryExportRingGLB", "inputs": {"workbench_url": first}},
                "2": {"class_type": "FarSceneryMergeRingGLB", "inputs": {}},
                "3": {"class_type": "OtherNode", "inputs": {"workbench_url": "kept"}},
            }}
            return tuple(node["inputs"].get("workbench_url") for node in hook(payload)["prompt"].values())

        headless = SimpleNamespace(method="POST", path="/prompt", headers={"Host": "127.0.0.1:8188"})
        room_one = SimpleNamespace(method="POST", path="/api/prompt", headers={"Origin": first})
        room_two = SimpleNamespace(
            method="POST", path="/prompt",
            headers={"Host": "127.0.0.1:8188", "Referer": second + "/next", "Origin": "null"},
        )
        self.assertEqual(await asyncio.gather(
            middleware(room_one, handle),
            middleware(room_two, handle),
            middleware(headless, handle),
        ), [(first, first, "kept"), (second, second, "kept"), (first, None, "kept")])
        self.assertIsNone(workbench.request_origin.get())

    def test_forwarded_host_must_be_a_byteartist_workbench(self):
        expected = "bench-647713312905110088.byteartist-workbench.bytedance.net"
        self.assertEqual(workbench.workbench_origin({"X-Forwarded-Host": expected}), f"https://{expected}")
        self.assertIsNone(workbench.workbench_origin({"X-Forwarded-Host": expected + ".example.org"}))
