"""Extend a 2:1 image to a square by continuing its last row downward."""


class SkyExtendBottomColorSquare:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "extend"
    CATEGORY = "Sky Tools"
    DESCRIPTION = (
        "保持2:1原图不变并放在正方形画布上半幅，"
        "保留最底一行每个横向位置的颜色并逐行向下延伸。"
    )

    def extend(self, image):
        import torch

        if not isinstance(image, torch.Tensor) or not image.is_floating_point():
            raise ValueError("Expected a floating-point ComfyUI IMAGE tensor.")
        if image.ndim != 4 or any(size < 1 for size in image.shape):
            raise ValueError("Expected nonempty IMAGE [batch, height, width, channels].")

        batch, height, width, channels = image.shape
        if width != height * 2:
            raise ValueError(
                f"Input must be exactly 2:1, but received {width}x{height}."
            )

        # Preserve every pixel across the last row. Repeating the row downward
        # keeps left-to-right color variation instead of collapsing it to one
        # average color. Values and dtype remain unchanged.
        edge_row = image[:, -1:, :, :]
        added_height = width - height
        bottom = edge_row.expand(batch, added_height, width, channels)
        output = torch.cat((image, bottom), dim=1)
        return (output,)
