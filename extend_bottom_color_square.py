"""Extend a 2:1 image to a square by filling below it with its bottom-edge color."""


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
        "读取原图最底一整行的平均色，纯色填充新增的下半幅。"
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

        # Average the complete last row for each batch image. Keep floating-point
        # values and dtype so the node does not introduce 8-bit quantization.
        fill_color = image[:, -1:, :, :].mean(dim=2, keepdim=True)
        added_height = width - height
        bottom = fill_color.expand(batch, added_height, width, channels)
        output = torch.cat((image, bottom), dim=1)
        return (output,)
