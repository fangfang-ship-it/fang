"""Center a 2048x2048 ComfyUI image on a white 4096x2048 canvas."""


class SkySquareTo2To1WhitePad:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "pad"
    CATEGORY = "Sky Tools"
    DESCRIPTION = "将 2048×2048 原图居中放在 4096×2048 画布上，左右各补 1024 像素纯白。"

    def pad(self, image):
        if image.ndim != 4 or not image.is_floating_point():
            raise ValueError("Expected a floating-point ComfyUI IMAGE [batch, height, width, channels].")

        batch, height, width, channels = image.shape
        if (width, height) != (2048, 2048) or batch < 1 or channels < 1:
            raise ValueError(
                "Expected a nonempty 2048x2048 IMAGE (width x height), "
                f"received shape {tuple(image.shape)}."
            )

        left = width // 2
        output = image.new_ones((batch, height, width * 2, channels))
        output[:, :, left:left + width, :] = image
        return (output,)
