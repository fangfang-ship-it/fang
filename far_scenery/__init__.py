"""ComfyUI nodes for packaging distant scenery as PBR GLB assets."""

import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode

import numpy as np
from PIL import Image

from .glb import build_glb


COMFY_MASK = "ComfyUI mask (white = transparent)"
FOREGROUND_MASK = "Foreground alpha (white = opaque)"
ASSET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}")
RING_TEXTURE_SIZE = (2048, 640)
RING_RADIUS = 500.0
RING_ARC_DEGREES = 72.0
RING_SEGMENTS = 32
RING_FOOT_LINE = 600
RING_METERS_PER_PIXEL = RING_RADIUS * math.radians(RING_ARC_DEGREES) / RING_TEXTURE_SIZE[0]
RING_BASE_Y = (RING_FOOT_LINE - RING_TEXTURE_SIZE[1]) * RING_METERS_PER_PIXEL


def read_rgba(image, mask, mask_mode):
    rgb = image.detach().float().cpu().numpy()
    opacity = mask.detach().float().cpu().numpy()
    if rgb.ndim != 4 or rgb.shape[0] != 1 or rgb.shape[-1] != 3:
        raise ValueError("Connect one RGB image. / 此节点每次接一张 RGB 图。")
    if opacity.shape != rgb.shape[:3]:
        raise ValueError("Connect a same-size mask. For Load Image, pick a PNG with an alpha channel. / 请接入同尺寸遮罩。")
    if not np.isfinite(rgb).all() or not np.isfinite(opacity).all():
        raise ValueError("Image and mask must contain finite values.")
    if mask_mode not in (COMFY_MASK, FOREGROUND_MASK):
        raise ValueError("Choose a supported mask mode.")
    if mask_mode == COMFY_MASK:
        opacity = 1 - opacity
    alpha = np.rint(np.clip(opacity[0], 0, 1) * 255).astype(np.uint8)
    rgb8 = np.rint(np.clip(rgb[0], 0, 1) * 255).astype(np.uint8)
    return np.dstack((rgb8, alpha))


def visible_bounds(alpha):
    if not (alpha.min() < 13 and alpha.max() >= 128):
        raise ValueError("Alpha must contain both transparent background and visible terrain. / 请检查遮罩方向和 PNG 的透明通道。")
    rows, columns = np.nonzero(alpha >= 13)
    left, top = int(columns.min()), int(rows.min())
    right, bottom = int(columns.max()) + 1, int(rows.max()) + 1
    if min(right - left, bottom - top) < 2:
        raise ValueError("The visible region must be at least 2 by 2 pixels.")
    return left, top, right, bottom


def encode_png(rgba):
    buffer = BytesIO()
    Image.fromarray(rgba).save(buffer, format="PNG")
    return buffer.getvalue()


def write_atomic(path, payload):
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temp_path = Path(temporary.name)
        try:
            temporary.write(payload)
            temporary.close()
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)


class FarSceneryFitTexture:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "mask": ("MASK",),
            "width_percent": ("FLOAT", {"default": 90.0, "min": 1.0, "max": 100.0, "step": 0.5}),
            "center_percent": ("FLOAT", {"default": 50.0, "min": 0.0, "max": 100.0, "step": 0.5}),
            "foot_line_px": ("INT", {"default": RING_FOOT_LINE, "min": 2, "max": RING_TEXTURE_SIZE[1]}),
            "mask_mode": ([COMFY_MASK, FOREGROUND_MASK],),
        }}

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "fit"
    CATEGORY = "Far Scenery"
    DESCRIPTION = "等比缩放透明山体，对齐山脚并输出 2048 × 640 画布。"

    def fit(self, image, mask, width_percent, center_percent, foot_line_px, mask_mode):
        import torch

        width, height = RING_TEXTURE_SIZE
        if not (1 <= width_percent <= 100 and 0 <= center_percent <= 100 and 2 <= foot_line_px <= height):
            raise ValueError("请检查山体占宽、横向中心和山脚线的范围。")
        rgba = read_rgba(image, mask, mask_mode)
        bounds = visible_bounds(rgba[..., 3])
        mountain = Image.fromarray(rgba).crop(bounds)
        target_width = round(width * width_percent / 100)
        target_height = round(mountain.height * target_width / mountain.width)
        if target_height < 2:
            raise ValueError("缩放后山体过薄，请提高 width_percent。")
        left = round(width * center_percent / 100 - target_width / 2)
        top = foot_line_px - target_height
        if left < 0 or left + target_width > width:
            raise ValueError("山体超出画布左右边界，请减小 width_percent 或调整 center_percent。")
        if top < 0:
            raise ValueError("山峰超出画布上沿，请减小 width_percent 或把 foot_line_px 调大。")

        canvas = Image.new("RGBA", RING_TEXTURE_SIZE)
        canvas.paste(mountain.resize((target_width, target_height), Image.Resampling.LANCZOS), (left, top))
        fitted = np.asarray(canvas, dtype=np.float32) / 255.0
        return (
            torch.from_numpy(fitted[None, ..., :3].copy()),
            torch.from_numpy(1.0 - fitted[None, ..., 3]),
        )


class ArcExport:
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("glb_path", "download_url", "report")
    FUNCTION = "export"
    OUTPUT_NODE = True
    CATEGORY = "Far Scenery"

    def write_export(self, png, asset_id, radius, arc_degrees, segments, base_y, window, touches_edge):
        import folder_paths

        if not ASSET_ID.fullmatch(asset_id):
            raise ValueError("asset_id must be 1–48 ASCII letters, digits, underscores, or hyphens, starting with a letter or digit.")
        glb, geometry = build_glb(png, radius, arc_degrees, segments, base_y, window, asset_id)
        digest = hashlib.sha256(glb).hexdigest()
        subfolder = f"far-scenery/{asset_id}-{digest[:12]}"
        destination = Path(folder_paths.get_output_directory()) / subfolder
        destination.mkdir(parents=True, exist_ok=True)
        glb_name = asset_id + ".glb"
        png_name = asset_id + ".png"
        url = "/api/view?" + urlencode({"filename": glb_name, "subfolder": subfolder, "type": "output"})
        warnings = ["Visible alpha touches a texture edge. / 可见区域触边，请检查轮廓。"] if touches_edge else []
        report = {
            "asset_id": asset_id,
            "glb": glb_name,
            "png": png_name,
            "download_url": url,
            "sha256": digest,
            "triangles": segments * 2,
            "material": {"model": "PBR", "alphaMode": "BLEND", "doubleSided": True},
            "geometry": geometry,
            "warnings": warnings,
            "editor_verification": "pending",
        }
        report_text = json.dumps(report, ensure_ascii=False, indent=2)
        write_atomic(destination / glb_name, glb)
        write_atomic(destination / png_name, png)
        write_atomic(destination / "manifest.json", report_text.encode("utf-8"))
        return {
            "ui": {"images": [{"filename": png_name, "subfolder": subfolder, "type": "output"}],
                   "text": [url]},
            "result": (str(destination / glb_name), url, report_text),
        }


class FarSceneryExportGLB(ArcExport):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "mask": ("MASK",),
            "asset_id": ("STRING", {"default": "far-ridge"}),
            "radius": ("FLOAT", {"default": 1600.0, "min": 1.0, "max": 100000.0, "step": 1.0}),
            "arc_degrees": ("FLOAT", {"default": 74.0, "min": 1.0, "max": 179.0, "step": 1.0}),
            "segments": ("INT", {"default": 32, "min": 2, "max": 512}),
            "base_y": ("FLOAT", {"default": -26.0, "min": -100000.0, "max": 100000.0, "step": 1.0}),
            "mask_mode": ([COMFY_MASK, FOREGROUND_MASK],),
        }}

    DESCRIPTION = "Export a transparent PBR arc GLB, the RGBA PNG, and a manifest."

    def export(self, image, mask, asset_id, radius, arc_degrees, segments, base_y, mask_mode):
        if not (1 <= radius <= 100000 and 1 <= arc_degrees <= 179 and 2 <= segments <= 512):
            raise ValueError("Check radius, arc angle, and segment count.")
        if not math.isfinite(base_y) or abs(base_y) > 100000:
            raise ValueError("base_y must be within ±100000.")
        rgba = read_rgba(image, mask, mask_mode)
        height, width = rgba.shape[:2]
        left, top, right, bottom = visible_bounds(rgba[..., 3])
        window = (max(0, left - 10), max(0, top - 10), min(width, right + 10), min(height, bottom + 10))
        touches_edge = left == 0 or top == 0 or right == width or bottom == height
        return self.write_export(encode_png(rgba), asset_id, radius, arc_degrees, segments, base_y, window, touches_edge)


class FarSceneryExportRingGLB(ArcExport):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "mask": ("MASK",),
            "asset_id": ("STRING", {"default": "far-ring-01"}),
        }}

    DESCRIPTION = "以 500 m 半径、72° 弧段和固定 UV 导出完整透明画布。"

    def export(self, image, mask, asset_id):
        rgba = read_rgba(image, mask, COMFY_MASK)
        width, height = RING_TEXTURE_SIZE
        if rgba.shape[:2] != (height, width):
            raise ValueError("固定模板需要 2048 × 640 贴图，请先接入「远景贴图适配」。")
        left, top, right, bottom = visible_bounds(rgba[..., 3])
        touches_edge = left == 0 or top == 0 or right == width or bottom == height
        return self.write_export(
            encode_png(rgba), asset_id, RING_RADIUS, RING_ARC_DEGREES, RING_SEGMENTS, RING_BASE_Y, None, touches_edge
        )


class FarSceneryPlanItem:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "plan": ("STRING", {"forceInput": True}),
            "index": ("INT", {"default": 1, "min": 1, "max": 10}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "asset_id")
    FUNCTION = "select"
    CATEGORY = "Far Scenery"
    DESCRIPTION = "Select one image prompt and its matching export ID from a far scenery plan."

    def select(self, plan, index):
        text = plan.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.split("\n", 1)[-1][:-3].strip()
        try:
            document = json.loads(text)
            assets = document.get("assets") if isinstance(document, dict) else None
        except json.JSONDecodeError as error:
            raise ValueError("规划节点须返回有效 JSON，根字段为 assets。") from error
        if not isinstance(assets, list) or not 1 <= len(assets) <= 10:
            raise ValueError("assets 必须包含 1–10 件远景。")
        if not 1 <= index <= len(assets):
            raise ValueError(f"当前清单只有 {len(assets)} 项，无法读取第 {index} 项。")
        seen = set()
        for item in assets:
            if not isinstance(item, dict):
                raise ValueError("每个资产必须是 JSON 对象。")
            asset_id, prompt = item.get("asset_id"), item.get("prompt")
            if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id) or asset_id in seen:
                raise ValueError("每个 asset_id 必须是唯一的安全英文文件名。")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f"{asset_id} 缺少生图提示词。")
            seen.add(asset_id)
        item = assets[index - 1]
        return item["prompt"].strip(), item["asset_id"]


NODE_CLASS_MAPPINGS = {
    "FarSceneryFitTexture": FarSceneryFitTexture,
    "FarSceneryExportRingGLB": FarSceneryExportRingGLB,
    "FarSceneryExportGLB": FarSceneryExportGLB,
    "FarSceneryPlanItem": FarSceneryPlanItem,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "FarSceneryFitTexture": "Far Scenery Fit Texture / 远景贴图适配",
    "FarSceneryExportRingGLB": "Far Scenery Export Ring GLB / 远景固定模板 GLB",
    "FarSceneryExportGLB": "Far Scenery Export GLB / 远景透明圆弧 GLB",
    "FarSceneryPlanItem": "Far Scenery Plan Item / 读取远景方案",
}
