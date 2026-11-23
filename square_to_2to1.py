"""Resize a square ComfyUI image to a fixed 4096x2048 2:1 canvas."""


class SkySquareTo2To1Fixed:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "resize_method": (
                    ["bicubic", "bilinear", "area", "nearest-exact"],
                    {"default": "bicubic"},
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "width", "height", "info")
    FUNCTION = "resize"
    CATEGORY = "Sky Tools"
    DESCRIPTION = (
        "将严格1:1输入完整缩放为固定4096x2048（宽x高）的2:1图像；"
        "不裁切、不复制、不补边。"
    )

    def resize(self, image, resize_method="bicubic"):
        import torch
        import torch.nn.functional as functional

        if not isinstance(image, torch.Tensor) or not image.is_floating_point():
            raise ValueError("Expected a floating-point ComfyUI IMAGE tensor.")
        if image.ndim != 4 or any(size < 1 for size in image.shape):
            raise ValueError("Expected nonempty IMAGE [batch, height, width, channels].")

        _, input_height, input_width, _ = image.shape
        if input_width != input_height:
            raise ValueError(
                f"Input must be exactly 1:1, but received {input_width}x{input_height}."
            )

        output_width = 4096
        output_height = 2048

        # ComfyUI IMAGE uses BHWC; torch interpolation uses BCHW.
        source = image.movedim(-1, 1)
        if resize_method in ("bicubic", "bilinear"):
            resized = functional.interpolate(
                source,
                size=(output_height, output_width),
                mode=resize_method,
                align_corners=False,
                antialias=True,
            )
        else:
            resized = functional.interpolate(
                source,
                size=(output_height, output_width),
                mode=resize_method,
            )

        output = resized.movedim(1, -1)
        info = (
            f"{input_width}x{input_height} (1:1) -> "
            f"{output_width}x{output_height} (2:1); method={resize_method}; "
            "full-frame resize, no crop, repeat, or padding"
        )
        return output, output_width, output_height, info
