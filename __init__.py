"""ComfyUI Sky Bottom Stretch 1.0.0. Uses ComfyUI's existing torch/numpy."""
from .core import stretch_bottom_array


class SkyBottomStretchTo2To1:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "bottom_percent": ("FLOAT", {
                "default": 30.0, "min": 0.1, "max": 100.0, "step": 0.1,
                "tooltip": "拉伸原图底部的比例。30=保留上方70%，只拉伸底部30%。",
            }),
        }}

    RETURN_TYPES = ("IMAGE", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "width", "height", "info")
    FUNCTION = "stretch"
    CATEGORY = "Sky Tools"
    DESCRIPTION = "保持宽度和上部像素不变，只拉伸底部区域，增加高度至严格2:1。"

    def stretch(self, image, bottom_percent=30.0):
        import torch
        if not isinstance(image, torch.Tensor) or not image.is_floating_point():
            raise ValueError("Expected a floating-point ComfyUI IMAGE tensor.")
        # CPU processing works without CUDA; float conversion supports bfloat16.
        cpu = image.detach().to(device="cpu")
        if cpu.dtype not in (torch.float32, torch.float64):
            cpu = cpu.float()
        result, meta = stretch_bottom_array(cpu.numpy(), float(bottom_percent))
        output = torch.from_numpy(result).to(device=image.device, dtype=image.dtype)
        info = (f"{meta['width']}x{meta['input_height']} -> "
                f"{meta['width']}x{meta['output_height']}; "
                f"top {meta['preserved_rows']} rows unchanged; "
                f"bottom {meta['input_bottom_rows']} -> {meta['output_bottom_rows']} rows; "
                "vertical linear stretch only, not automatic horizon centering or HDR conversion")
        return output, meta["width"], meta["output_height"], info


NODE_CLASS_MAPPINGS = {"SkyBottomStretchTo2To1": SkyBottomStretchTo2To1}
NODE_DISPLAY_NAME_MAPPINGS = {
    "SkyBottomStretchTo2To1": "Sky Bottom Stretch 2:1 / 天空底部拉伸"
}
