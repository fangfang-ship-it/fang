"""Recover a soft matte from terrain rendered over a near-white background."""

import numpy as np
from PIL import Image, ImageDraw


class FarSceneryWhiteMatte:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "background_tolerance": ("INT", {"default": 8, "min": 0, "max": 64,
                                              "tooltip": "与实际底色相差多少个色阶仍视为全透明。"}),
            "opaque_distance": ("INT", {"default": 56, "min": 1, "max": 255,
                                         "tooltip": "与底色相差达到此值时保留为实色。两项之间输出渐变透明度。"}),
        }}

    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE")
    RETURN_NAMES = ("image", "mask", "preview")
    FUNCTION = "key"
    CATEGORY = "Far Scenery"
    DESCRIPTION = "从近白背景提取软遮罩，同时去除边缘混入的底色。MASK 白色表示透明。"

    def key(self, image, background_tolerance, opaque_distance):
        import torch

        batch = image.detach().float().cpu().numpy()
        if batch.ndim != 4 or batch.shape[0] != 1 or batch.shape[-1] != 3 or min(batch.shape[1:3]) < 2:
            raise ValueError("白底转透明需要一张 RGB 图。")
        if not np.isfinite(batch).all():
            raise ValueError("输入图像含无效像素。")
        if not 0 <= background_tolerance < opaque_distance <= 255:
            raise ValueError("opaque_distance 必须大于 background_tolerance。")

        rgb = np.clip(batch[0], 0.0, 1.0)
        border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]))
        background = np.median(border, axis=0)
        if np.min(background) < 0.9 or np.ptp(background) > 0.07:
            raise ValueError("图像外边缘没有足够的近白背景，请检查输入图或留白。")

        distance = np.abs(rgb - background).max(axis=-1) * 255.0
        candidate = Image.fromarray(np.where(distance < opaque_distance, 255, 0).astype(np.uint8))
        # The padded border is one starting region for all background-connected areas.
        # Near-white highlights surrounded by solid rock keep their original opacity.
        outside = Image.new("L", (candidate.width + 2, candidate.height + 2), 255)
        outside.paste(candidate, (1, 1))
        ImageDraw.floodfill(outside, (0, 0), 128)
        connected = np.asarray(outside)[1:-1, 1:-1] == 128

        soft_alpha = np.clip((distance - background_tolerance) / (opaque_distance - background_tolerance), 0.0, 1.0)
        alpha = np.where(connected, soft_alpha, 1.0)
        if alpha.min() >= 0.05 or alpha.max() < 0.5:
            raise ValueError("遮罩需要同时包含透明背景和可见山体，请检查底色或调整两个色差值。")

        # Limit color recovery in faint pixels so JPEG noise is not amplified.
        opacity = alpha[..., None]
        clean_rgb = background + (rgb - background) / np.maximum(opacity, 0.20)
        np.clip(clean_rgb, 0.0, 1.0, out=clean_rgb)
        clean_rgb[alpha == 0.0] = background

        # Composite the RGB and Alpha for workbenches that display image outputs as JPEG.
        preview_background = np.array([35, 42, 52], dtype=np.float32) / 255.0
        preview_rgb = clean_rgb * opacity + preview_background * (1.0 - opacity)
        preview = Image.fromarray(np.rint(preview_rgb * 255).astype(np.uint8))
        preview.thumbnail((960, 960), Image.Resampling.LANCZOS)
        return (
            torch.from_numpy(clean_rgb[None]),
            torch.from_numpy(1.0 - alpha[None]),
            torch.from_numpy(np.asarray(preview, dtype=np.float32)[None] / 255.0),
        )
