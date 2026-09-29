import json
import re
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

from . import core


def _tensor(image):
    import torch
    return torch.from_numpy(np.ascontiguousarray(image, dtype=np.float32))[None]


def _report(packet):
    return json.dumps(packet["report"], ensure_ascii=False, indent=2)


class SkyAutoDetectBand:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",),
                "sensitivity": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0, "step": 0.05})}}

    RETURN_TYPES = ("SKY_AUTO_PACKET", "IMAGE", "STRING")
    RETURN_NAMES = ("sky_data", "debug_only", "report")
    CATEGORY = "Sky Auto Layout"
    FUNCTION = "detect"

    def detect(self, image, sensitivity=1.0):
        if image.ndim != 4 or image.shape[0] != 1:
            raise ValueError("Sky Auto Layout v0.1 processes one image per request. Queue multiple requests for a batch.")
        arr = image[0, ..., :3].detach().cpu().numpy().astype(np.float32)
        packet = core.analyze(arr, float(sensitivity))
        return (packet, _tensor(core.debug_image(packet)), _report(packet))


class SkyAutoPlanLayout:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sky_data": ("SKY_AUTO_PACKET",),
            "layout_mode": (["strict_30_45", "horizon_only"], {"default": "strict_30_45"}),
            "coordinate_space": (["design_21_9", "final_2_1"], {"default": "design_21_9"})}}

    RETURN_TYPES = ("SKY_AUTO_PACKET", "STRING")
    RETURN_NAMES = ("sky_data", "report")
    CATEGORY = "Sky Auto Layout"
    FUNCTION = "plan"

    def plan(self, sky_data, layout_mode, coordinate_space):
        packet = core.plan(sky_data, layout_mode, coordinate_space)
        return (packet, _report(packet))


class SkyAutoComposeGradient:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sky_data": ("SKY_AUTO_PACKET",)}}

    RETURN_TYPES = ("SKY_AUTO_PACKET", "IMAGE", "STRING")
    RETURN_NAMES = ("sky_data", "debug_only", "report")
    CATEGORY = "Sky Auto Layout"
    FUNCTION = "compose"

    def compose(self, sky_data):
        packet = core.compose(sky_data)
        return (packet, _tensor(core.debug_image(packet)), _report(packet))


class SkyAutoValidateSave:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sky_data": ("SKY_AUTO_PACKET",),
                "filename_prefix": ("STRING", {"default": "sky_layout"}),
                "save_debug": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("BOOLEAN", "STRING")
    RETURN_NAMES = ("layout_pass", "report_json")
    CATEGORY = "Sky Auto Layout"
    FUNCTION = "save"
    OUTPUT_NODE = True

    def save(self, sky_data, filename_prefix="sky_layout", save_debug=False):
        import folder_paths
        root = Path(folder_paths.get_output_directory()) / "sky_auto_layout"
        root.mkdir(parents=True, exist_ok=True)
        prefix = re.sub(r"[^\w-]+", "_", filename_prefix)[:64].strip("_") or "sky_layout"
        stem = f"{prefix}_{time.time_ns()}_{uuid.uuid4().hex[:6]}"
        report = dict(sky_data["report"])
        images = []
        if report.get("layout_pass") and "result" in sky_data:
            name = stem + ".png"
            rgb = np.round(np.clip(sky_data["result"], 0, 1)*255).astype(np.uint8)
            Image.fromarray(rgb).save(root / name)
            images.append({"filename": name, "subfolder": "sky_auto_layout", "type": "output"})
            report["candidate_file"] = str(Path("sky_auto_layout") / name)
        else:
            # No fail-through image: an empty images[] means the orchestrator must retry/fallback.
            report["candidate_file"] = None
        if save_debug:
            name = stem + "_debug.png"
            rgb = np.round(core.debug_image(sky_data)*255).astype(np.uint8)
            Image.fromarray(rgb).save(root / name)
            report["debug_file"] = str(Path("sky_auto_layout") / name)
        text = json.dumps(report, ensure_ascii=False, indent=2)
        (root / (stem + ".json")).write_text(text, encoding="utf-8")
        return {"ui": {"images": images, "text": [text]},
                "result": (bool(report.get("layout_pass")), text)}


NODE_CLASS_MAPPINGS = {
    "SkyAutoDetectBand": SkyAutoDetectBand,
    "SkyAutoPlanLayout": SkyAutoPlanLayout,
    "SkyAutoComposeGradient": SkyAutoComposeGradient,
    "SkyAutoValidateSave": SkyAutoValidateSave,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "SkyAutoDetectBand": "② 自动检测天空内容范围",
    "SkyAutoPlanLayout": "③ 自动排布（保持云形）",
    "SkyAutoComposeGradient": "④ 自动渐变与合成",
    "SkyAutoValidateSave": "⑤ 检查并保存候选图",
}
