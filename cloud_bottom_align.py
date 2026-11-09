"""Parse a vision-model percentage and vertically align a sky image to a target line."""

import math
import re


class SkyParseCloudBottomPercent:
    """Extract a cloud-bottom percentage from strict JSON or plain model text."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "default": '{"cloud_bottom_percent": 46.5}',
                        "multiline": True,
                        "dynamicPrompts": False,
                        "tooltip": "连接识图模型输出。推荐只输出JSON：{\"cloud_bottom_percent\":46.5}",
                    },
                )
            }
        }

    RETURN_TYPES = ("FLOAT", "STRING")
    RETURN_NAMES = ("cloud_bottom_percent", "info")
    FUNCTION = "parse"
    CATEGORY = "Sky Tools/Alignment"
    DESCRIPTION = "从识图模型文本中提取最低云端百分比，供天空垂直对齐节点使用。"

    _KEYED_PATTERNS = (
        r'["\']?cloud_bottom_percent["\']?\s*[:=]\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))',
        r'(?:最低云端|云底|云层底端)(?:位置|高度|百分比)?\s*[:：=]?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*%?',
    )

    def parse(self, text):
        text = str(text).strip()
        if not text:
            raise ValueError("Vision-model text is empty.")

        value = None
        source = ""
        for pattern in self._KEYED_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = float(match.group(1))
                source = "keyed field"
                break

        if value is None:
            percent_matches = re.findall(
                r'([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*%', text
            )
            if len(percent_matches) == 1:
                value = float(percent_matches[0])
                source = "single percent"

        if value is None:
            plain = re.fullmatch(
                r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*', text
            )
            if plain:
                value = float(plain.group(1))
                source = "plain number"

        if value is None:
            raise ValueError(
                "Could not safely identify one cloud-bottom percentage. "
                "Use JSON such as {\"cloud_bottom_percent\": 46.5}."
            )
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise ValueError("cloud_bottom_percent must be between 0 and 100.")

        info = f"Parsed cloud bottom: {value:.3f}% ({source})"
        return float(value), info


class SkyAlignCloudBottom:
    """Move an image vertically so a detected cloud bottom reaches a target line."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "cloud_bottom_percent": (
                    "FLOAT",
                    {
                        "default": 46.5,
                        "min": 0.0,
                        "max": 100.0,
                        "step": 0.1,
                        "round": 0.001,
                        "tooltip": "连接解析节点输出，或手动输入最低云端位置。按画面顶边向下计算。",
                    },
                ),
                "target_percent": (
                    "FLOAT",
                    {
                        "default": 49.7,
                        "min": 0.0,
                        "max": 100.0,
                        "step": 0.1,
                        "round": 0.001,
                        "tooltip": "希望最低云端对齐到的水平线位置。按画面顶边向下计算。",
                    },
                ),
                "max_shift_percent": (
                    "FLOAT",
                    {
                        "default": 15.0,
                        "min": 0.1,
                        "max": 100.0,
                        "step": 0.5,
                        "tooltip": "安全限制：所需位移超过该比例时停止并报错。",
                    },
                ),
                "fill_sample_rows": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 64,
                        "step": 1,
                        "tooltip": "从露空一侧的原图边缘取多少行，计算填充用的平均纯色。",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "INT", "STRING")
    RETURN_NAMES = (
        "image",
        "shift_pixels",
        "detected_y",
        "target_y",
        "info",
    )
    FUNCTION = "align"
    CATEGORY = "Sky Tools/Alignment"
    DESCRIPTION = "按识别出的最低云端百分比垂直平移图片，并用边缘平均纯色填充空区。"

    def align(
        self,
        image,
        cloud_bottom_percent=46.5,
        target_percent=49.7,
        max_shift_percent=15.0,
        fill_sample_rows=1,
    ):
        import torch

        if not isinstance(image, torch.Tensor) or not image.is_floating_point():
            raise ValueError("Expected a floating-point ComfyUI IMAGE tensor.")
        if image.ndim != 4 or any(size < 1 for size in image.shape):
            raise ValueError("Expected nonempty IMAGE [batch, height, width, channels].")

        cloud_bottom_percent = float(cloud_bottom_percent)
        target_percent = float(target_percent)
        max_shift_percent = float(max_shift_percent)
        for name, value in (
            ("cloud_bottom_percent", cloud_bottom_percent),
            ("target_percent", target_percent),
            ("max_shift_percent", max_shift_percent),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite.")
        if not 0.0 <= cloud_bottom_percent <= 100.0:
            raise ValueError("cloud_bottom_percent must be between 0 and 100.")
        if not 0.0 <= target_percent <= 100.0:
            raise ValueError("target_percent must be between 0 and 100.")
        if not 0.0 < max_shift_percent <= 100.0:
            raise ValueError("max_shift_percent must be in (0, 100].")

        batch, height, width, channels = image.shape
        detected_y = int(round(cloud_bottom_percent * height / 100.0))
        target_y = int(round(target_percent * height / 100.0))
        detected_y = min(height, max(0, detected_y))
        target_y = min(height, max(0, target_y))
        shift_pixels = target_y - detected_y

        max_shift_pixels = max(1, int(round(max_shift_percent * height / 100.0)))
        if abs(shift_pixels) > max_shift_pixels:
            raise ValueError(
                f"Required shift is {shift_pixels}px ({abs(shift_pixels) * 100.0 / height:.2f}%), "
                f"which exceeds the safety limit of {max_shift_pixels}px "
                f"({max_shift_percent:.2f}%). Check the vision-model value."
            )
        if abs(shift_pixels) >= height:
            raise ValueError("Shift would remove the complete source image.")

        if shift_pixels == 0:
            output = image.clone()
            fill_side = "none"
        elif shift_pixels > 0:
            sample_rows = min(int(fill_sample_rows), height)
            fill_color = image[:, :sample_rows, :, :].mean(
                dim=(1, 2), keepdim=True
            )
            fill = fill_color.expand(batch, shift_pixels, width, channels)
            output = torch.cat((fill, image[:, : height - shift_pixels]), dim=1)
            fill_side = "top"
        else:
            amount = -shift_pixels
            sample_rows = min(int(fill_sample_rows), height)
            fill_color = image[:, -sample_rows:, :, :].mean(
                dim=(1, 2), keepdim=True
            )
            fill = fill_color.expand(batch, amount, width, channels)
            output = torch.cat((image[:, amount:], fill), dim=1)
            fill_side = "bottom"

        info = (
            f"cloud bottom {cloud_bottom_percent:.3f}% -> target {target_percent:.3f}%; "
            f"detected_y={detected_y}px, target_y={target_y}px, "
            f"shift={shift_pixels:+d}px; pure-color fill={fill_side}"
        )
        return output, shift_pixels, detected_y, target_y, info
