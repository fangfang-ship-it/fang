"""Repeat a half-size sky image across the top and fill the bottom with edge color."""


class SkyRepeatTopFillBottom:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "resize_method": (
                    ["bicubic", "bilinear", "area", "nearest-exact"],
                    {"default": "bicubic"},
                ),
                "sample_rows": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 64,
                        "step": 1,
                        "tooltip": "从原图底部向上取多少行像素求平均色；1表示只读取最底边。",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "compose"
    CATEGORY = "Sky Tools"
    DESCRIPTION = (
        "将2:1输入缩小为半宽半高，横向复制两份放在上半幅，"
        "下半幅使用原图底边平均色填充；输出尺寸保持不变。"
    )

    def compose(self, image, resize_method="bicubic", sample_rows=1):
        import torch
        import torch.nn.functional as functional

        if not isinstance(image, torch.Tensor) or not image.is_floating_point():
            raise ValueError("Expected a floating-point ComfyUI IMAGE tensor.")
        if image.ndim != 4 or any(size < 1 for size in image.shape):
            raise ValueError("Expected nonempty IMAGE [batch, height, width, channels].")

        batch, height, width, channels = image.shape
        if width != height * 2:
            raise ValueError(
                f"Input must be exactly 2:1, but received {width}x{height}."
            )
        if height % 2:
            raise ValueError("Input height must be even so the canvas can split at 50%.")

        sample_rows = min(int(sample_rows), height)
        top_height = height // 2
        tile_width = width // 2

        # ComfyUI IMAGE is BHWC; interpolate expects BCHW.
        source = image.movedim(-1, 1)
        if resize_method in ("bicubic", "bilinear"):
            tile = functional.interpolate(
                source,
                size=(top_height, tile_width),
                mode=resize_method,
                align_corners=False,
                antialias=True,
            )
        else:
            tile = functional.interpolate(
                source,
                size=(top_height, tile_width),
                mode=resize_method,
            )

        top = torch.cat((tile, tile), dim=3).movedim(1, -1)

        # One fill color per batch item: mean RGB/RGBA value of the selected
        # bottom rows across the full width. Values and dtype are not quantized.
        fill_color = image[:, -sample_rows:, :, :].mean(
            dim=(1, 2), keepdim=True
        )
        bottom = fill_color.expand(batch, height - top_height, width, channels)
        output = torch.cat((top, bottom), dim=1)
        return (output,)
