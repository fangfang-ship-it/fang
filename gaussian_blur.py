"""Fractional-radius Pillow Gaussian blur, compatible with Art Venture's scale."""
import math

import numpy as np
from PIL import Image, ImageFilter


def gaussian_blur_array(images, radius=1.5):
    """Blur BHWC images using the same 8-bit Pillow path as ImageGaussianBlur.

    Radius is passed directly as a float, never rounded to an integer.
    Zero bypasses quantization. Positive values use Pillow's edge handling.
    """
    radius = float(radius)
    if not math.isfinite(radius) or not 0.0 <= radius <= 100.0:
        raise ValueError("radius must be a finite number between 0 and 100.")
    if images.ndim != 4 or any(s < 1 for s in images.shape):
        raise ValueError("Expected a nonempty IMAGE [batch, height, width, channels].")
    if not np.issubdtype(images.dtype, np.floating):
        raise ValueError("IMAGE must contain floating-point pixels.")
    if images.shape[-1] not in (1, 3, 4):
        raise ValueError("Expected 1, 3 or 4 image channels.")
    if radius == 0.0:
        return images.copy()
    result = np.empty(images.shape, dtype=np.float32)
    for index, frame in enumerate(images):
        pixels = np.clip(255.0 * frame, 0, 255).astype(np.uint8)
        if pixels.shape[-1] == 1:
            pixels = pixels[..., 0]
        blurred = Image.fromarray(pixels).filter(ImageFilter.GaussianBlur(radius=radius))
        pixels = np.asarray(blurred, dtype=np.float32) / 255.0
        if pixels.ndim == 2:
            pixels = pixels[..., None]
        result[index] = pixels
    return result


class SkyGaussianBlurFloat:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "radius": ("FLOAT", {
                "default": 1.5, "min": 0.0, "max": 100.0,
                "step": 0.1, "round": 0.01,
                "tooltip": "模糊半径，支持1.5、1.25等小数。0不模糊；数值越大越模糊。",
            }),
        }}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "blur"
    CATEGORY = "Sky Tools"
    DESCRIPTION = "沿用Pillow高斯模糊，支持小数半径，默认1.5。"

    def blur(self, images, radius=1.5):
        import torch
        if not isinstance(images, torch.Tensor) or not images.is_floating_point():
            raise ValueError("Expected a floating-point ComfyUI IMAGE tensor.")
        cpu = images.detach().to(device="cpu")
        if cpu.dtype not in (torch.float32, torch.float64):
            cpu = cpu.float()
        result = gaussian_blur_array(cpu.numpy(), radius)
        if float(radius) == 0.0:
            return (images,)
        output = torch.from_numpy(result).to(device=images.device, dtype=images.dtype)
        return (output,)
