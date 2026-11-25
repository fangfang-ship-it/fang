"""ComfyUI nodes for packaging distant scenery as PBR GLB assets."""

import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode, urlsplit

import numpy as np
from PIL import Image

from .glb import build_glb
from .matte import FarSceneryWhiteMatte
from .fine_matte import FarSceneryFineMatte


WEB_DIRECTORY = "./web"
COMFY_MASK = "ComfyUI mask (white = transparent)"
FOREGROUND_MASK = "Foreground alpha (white = opaque)"
ASSET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}")
RING_TEXTURE_SIZE = (2048, 512)
RING_RADIUS = 500.0
RING_ARC_DEGREES = 80.0
RING_SEGMENTS = 40
RING_WIDTH_PERCENT = 95.0
RING_FOOT_LINE = 488
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


def resolve_download_url(workbench_url, relative_url):
    address = workbench_url.strip()
    if not address:
        return relative_url
    parts = urlsplit(address)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None:
        raise ValueError("workbench_url 请填写工作台的完整 http:// 或 https:// 地址。")
    return f"{parts.scheme}://{parts.netloc}{relative_url}"


def _smooth_foot_profile(values, sigma):
    """Smooth a 1D contour, without wrapping or mixing separate mountain spans."""
    radius = max(1, math.ceil(3 * sigma))
    offsets = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-0.5 * (offsets / sigma) ** 2)
    kernel /= kernel.sum()
    values = np.asarray(values, dtype=np.float32)
    return np.convolve(np.pad(values, (radius, radius), mode="edge"), kernel, mode="valid")


def fade_foot(alpha, pixels):
    """Apply a continuous lower-edge fade to the existing alpha, without blurring RGB or the skyline."""
    if pixels <= 0:
        return
    threshold = 13 / 255
    visible = alpha >= threshold
    active = visible.any(axis=0)
    if not active.any():
        return
    height, width = alpha.shape
    cols = np.arange(width)
    first = visible.argmax(axis=0)
    last = height - 1 - visible[::-1].argmax(axis=0)

    # Estimate the 5%-opacity crossing at subpixel precision. Integer last/first
    # indices previously made adjacent columns choose different fade heights/bands.
    top_value = alpha[first, cols]
    prev_value = np.where(first > 0, alpha[np.maximum(first - 1, 0), cols], 0)
    bottom_value = alpha[last, cols]
    next_value = np.where(last < height - 1, alpha[np.minimum(last + 1, height - 1), cols], 0)
    top = first - np.clip((top_value - threshold) / np.maximum(top_value - prev_value, 1e-6), 0, 1)
    bottom = last + np.clip((bottom_value - threshold) / np.maximum(bottom_value - next_value, 1e-6), 0, 1)

    # Build two smooth curves (foot elevation, fade-band thickness), independently
    # for every contiguous visible span. Avoid discontinuities from integer division.
    transitions = np.flatnonzero(np.diff(np.pad(active.astype(np.int8), (1, 1))))
    sigma = min(18.0, max(4.0, float(pixels) * .35))
    smooth_bottom = np.zeros(width, dtype=np.float32)
    smooth_band = np.ones(width, dtype=np.float32)
    for start, end in transitions.reshape(-1, 2):
        span = slice(start, end)
        smooth_bottom[span] = _smooth_foot_profile(bottom[span], sigma)
        local_height = _smooth_foot_profile(np.maximum(bottom[span] - top[span], 1), sigma)
        # Thin foothills still get a proportional fade, but with a floating-point
        # width that changes continuously along the horizontal direction.
        smooth_band[span] = np.clip(local_height * .25, 1.0, float(pixels))

    rows = np.arange(height, dtype=np.float32)[:, None]
    ramp = np.clip((smooth_bottom - rows) / smooth_band, 0.0, 1.0)
    np.multiply(alpha, ramp * ramp * (3.0 - 2.0 * ramp), out=alpha, where=active)


class FarSceneryFitTexture:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "mask": ("MASK",),
            "width_percent": ("FLOAT", {"default": RING_WIDTH_PERCENT, "min": 1.0, "max": 100.0, "step": 0.5}),
            "center_percent": ("FLOAT", {"default": 50.0, "min": 0.0, "max": 100.0, "step": 0.5}),
            "foot_line_px": ("INT", {"default": RING_FOOT_LINE, "min": 2, "max": RING_TEXTURE_SIZE[1]}),
            "mask_mode": ([COMFY_MASK, FOREGROUND_MASK],),
        }, "optional": {
            "foot_fade_px": ("INT", {"default": 0, "min": 0, "max": 80, "step": 1,
                                    "tooltip": "沿连续平滑的山脚曲线向上渐隐（2048 × 512 贴图像素）。先试 24 px，0 保留原始遮罩。"}),
        }}

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "fit"
    CATEGORY = "Far Scenery"
    DESCRIPTION = "等比缩放透明山体，对齐山脚并输出 2048 × 512 的 4:1 画布。"

    def fit(self, image, mask, width_percent, center_percent, foot_line_px, mask_mode, foot_fade_px=0):
        import torch

        width, height = RING_TEXTURE_SIZE
        if not (1 <= width_percent <= 100 and 0 <= center_percent <= 100 and 2 <= foot_line_px <= height):
            raise ValueError("请检查山体占宽、横向中心和山脚线的范围。")
        if not 0 <= foot_fade_px <= 80:
            raise ValueError("山脚渐隐 foot_fade_px 的范围为 0–80 px。")
        rgba = read_rgba(image, mask, mask_mode)
        bounds = visible_bounds(rgba[..., 3])
        mountain = Image.fromarray(rgba).crop(bounds)
        target_width = min(round(width * width_percent / 100), foot_line_px * mountain.width // mountain.height)
        target_height = round(mountain.height * target_width / mountain.width)
        if min(target_width, target_height) < 2:
            raise ValueError("缩放后山体过薄，请检查山体宽高比、width_percent 和 foot_line_px。")
        left = round(width * center_percent / 100 - target_width / 2)
        top = foot_line_px - target_height
        if left < 0 or left + target_width > width:
            raise ValueError("山体超出画布左右边界，请减小 width_percent 或调整 center_percent。")

        canvas = Image.new("RGBA", RING_TEXTURE_SIZE)
        canvas.paste(mountain.resize((target_width, target_height), Image.Resampling.LANCZOS), (left, top))
        fitted = np.asarray(canvas, dtype=np.float32) / 255.0
        if foot_fade_px:
            fade_foot(fitted[..., 3], foot_fade_px)
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
    DOWNLOAD_INPUTS = {"workbench_url": ("STRING", {
        "default": "",
        "tooltip": "填工作台地址以输出完整 GLB 下载链接，例如 https://workbench.example.com。",
    })}

    def write_export(self, png, asset_id, radius, arc_degrees, segments, base_y, window, touches_edge, workbench_url,
                     *, yaw_degrees=None):
        import folder_paths

        if not ASSET_ID.fullmatch(asset_id):
            raise ValueError("asset_id must be 1–48 ASCII letters, digits, underscores, or hyphens, starting with a letter or digit.")
        glb, geometry = build_glb(png, radius, arc_degrees, segments, base_y, window, asset_id, yaw_degrees=yaw_degrees)
        digest = hashlib.sha256(glb).hexdigest()
        subfolder = f"far-scenery/{asset_id}-{digest[:12]}"
        destination = Path(folder_paths.get_output_directory()) / subfolder
        glb_name = asset_id + ".glb"
        png_name = asset_id + ".png"
        relative_url = "/api/view?" + urlencode({"filename": glb_name, "subfolder": subfolder, "type": "output"})
        url = resolve_download_url(workbench_url, relative_url)
        destination.mkdir(parents=True, exist_ok=True)
        warnings = ["Visible alpha touches a texture edge. / 可见区域触边，请检查轮廓。"] if touches_edge else []
        report = {
            "asset_id": asset_id,
            "glb": glb_name,
            "png": png_name,
            "download_url": relative_url,
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
            "ui": {
                "images": [{"filename": png_name, "subfolder": subfolder, "type": "output"}],
                "3d": [{"filename": glb_name, "subfolder": subfolder, "type": "output"}],
                "text": [url],
            },
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
        }, "optional": cls.DOWNLOAD_INPUTS}

    DESCRIPTION = "Export a transparent PBR arc GLB, the RGBA PNG, and a manifest."

    def export(self, image, mask, asset_id, radius, arc_degrees, segments, base_y, mask_mode, workbench_url=""):
        if not (1 <= radius <= 100000 and 1 <= arc_degrees <= 179 and 2 <= segments <= 512):
            raise ValueError("Check radius, arc angle, and segment count.")
        if not math.isfinite(base_y) or abs(base_y) > 100000:
            raise ValueError("base_y must be within ±100000.")
        rgba = read_rgba(image, mask, mask_mode)
        height, width = rgba.shape[:2]
        left, top, right, bottom = visible_bounds(rgba[..., 3])
        window = (max(0, left - 10), max(0, top - 10), min(width, right + 10), min(height, bottom + 10))
        touches_edge = left == 0 or top == 0 or right == width or bottom == height
        return self.write_export(
            encode_png(rgba), asset_id, radius, arc_degrees, segments, base_y, window, touches_edge, workbench_url
        )


class FarSceneryExportRingGLB(ArcExport):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "mask": ("MASK",),
            "asset_id": ("STRING", {"default": "far-ring-01"}),
        }, "optional": {
            **cls.DOWNLOAD_INPUTS,
            "yaw_degrees": ("FLOAT", {
                "default": 0.0, "min": -360.0, "max": 360.0, "step": 0.1,
                "tooltip": "写入网格的方位角（度）。五片填 0、72、144、216、288，相邻弧面重叠 8°。",
            }),
        }}

    DESCRIPTION = "以 500 m 半径和 80° 弧段导出，并将绕原点 Y 轴的方位角写入网格。"

    def export(self, image, mask, asset_id, workbench_url="", yaw_degrees=0.0):
        rgba = read_rgba(image, mask, COMFY_MASK)
        width, height = RING_TEXTURE_SIZE
        if rgba.shape[:2] != (height, width):
            raise ValueError(f"固定模板需要 {width} × {height} 贴图，请先接入「远景贴图适配」。")
        left, top, right, bottom = visible_bounds(rgba[..., 3])
        touches_edge = left == 0 or top == 0 or right == width or bottom == height
        return self.write_export(
            encode_png(rgba), asset_id, RING_RADIUS, RING_ARC_DEGREES, RING_SEGMENTS, RING_BASE_Y, None,
            touches_edge, workbench_url, yaw_degrees=yaw_degrees
        )


def decode_plan_object(pairs):
    fields = dict(pairs)
    if len(fields) == len(pairs):
        return fields

    # Some text models repeat five complete pairs inside a single asset object.
    if [key for key, _ in pairs] == ["asset_id", "prompt"] * 5:
        return tuple(dict(pairs[i:i + 2]) for i in range(0, len(pairs), 2))
    raise ValueError("规划 JSON 含重复字段，请让每个 asset_id 和 prompt 位于独立对象中。")


def read_plan(plan):
    text = plan.strip().removeprefix("\ufeff").strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1][:-3].strip()
    try:
        document = json.loads(text, object_pairs_hook=decode_plan_object)
    except json.JSONDecodeError as error:
        raise ValueError("规划节点须返回有效 JSON，根字段为 assets。") from error

    assets = document.get("assets") if isinstance(document, dict) else None
    if not isinstance(assets, list) or not 1 <= len(assets) <= 10:
        raise ValueError("assets 必须包含 1–10 件远景。")
    if len(assets) == 1 and isinstance(assets[0], tuple):
        assets = list(assets[0])

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
    return assets


class FarScenerySplitPlan:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"plan": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",) * 5
    RETURN_NAMES = ("prompt_1", "prompt_2", "prompt_3", "prompt_4", "prompt_5")
    FUNCTION = "split"
    CATEGORY = "Far Scenery"
    DESCRIPTION = "按 assets 数组顺序，一次拆出五条远景生图提示词。"

    def split(self, plan):
        assets = read_plan(plan)
        if len(assets) != 5:
            raise ValueError(f"五路拆分需要恰好五项，当前收到 {len(assets)} 项。")
        return tuple(item["prompt"].strip() for item in assets)


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
        assets = read_plan(plan)
        if not 1 <= index <= len(assets):
            raise ValueError(f"当前清单只有 {len(assets)} 项，无法读取第 {index} 项。")
        item = assets[index - 1]
        return item["prompt"].strip(), item["asset_id"]


NODE_CLASS_MAPPINGS = {
    "FarSceneryFineMatte": FarSceneryFineMatte,
    "FarSceneryWhiteMatte": FarSceneryWhiteMatte,
    "FarSceneryFitTexture": FarSceneryFitTexture,
    "FarSceneryExportRingGLB": FarSceneryExportRingGLB,
    "FarSceneryExportGLB": FarSceneryExportGLB,
    "FarScenerySplitPlan": FarScenerySplitPlan,
    "FarSceneryPlanItem": FarSceneryPlanItem,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "FarSceneryFineMatte": "Far Scenery Fine Matte / 远景精细抠图",
    "FarSceneryWhiteMatte": "Far Scenery White Matte / 远景白底转透明",
    "FarSceneryFitTexture": "Far Scenery Fit Texture / 远景贴图适配",
    "FarSceneryExportRingGLB": "Far Scenery Export Ring GLB / 远景固定模板 GLB",
    "FarSceneryExportGLB": "Far Scenery Export GLB / 远景透明圆弧 GLB",
    "FarScenerySplitPlan": "Far Scenery Split Plan / 拆分五条远景提示词",
    "FarSceneryPlanItem": "Far Scenery Plan Item / 读取远景方案",
}
