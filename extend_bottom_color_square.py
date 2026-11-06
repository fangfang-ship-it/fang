"""Extend a 2:1 image to a square by continuing its last row downward."""


class SkyExtendBottomColorSquare:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "blur_radius": (
                    "FLOAT",
                    {
                        "default": 6.0,
                        "min": 0.0,
                        "max": 64.0,
                        "step": 0.5,
                        "round": 0.1,
                        "tooltip": "只模糊新增下半幅的横向延伸线；0为不模糊。",
                    },
                ),
                "blend_height": (
                    "INT",
                    {
                        "default": 64,
                        "min": 1,
                        "max": 1024,
                        "step": 1,
                        "tooltip": "从连接处向下逐渐增强模糊的过渡高度，单位为像素。",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "extend"
    CATEGORY = "Sky Tools"
    DESCRIPTION = (
        "保持2:1原图不变并放在正方形画布上半幅，"
        "保留最底一行的横向颜色变化并向下延伸，只对新增区域做横向轻度模糊。"
    )

    def extend(self, image, blur_radius=6.0, blend_height=64):
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

        blur_radius = float(blur_radius)
        if not 0.0 <= blur_radius <= 64.0:
            raise ValueError("blur_radius must be between 0 and 64.")

        # Preserve every pixel across the last row. The original image tensor is
        # never filtered or resampled; all processing below applies only to the
        # newly created lower half.
        edge_row = image[:, -1:, :, :]
        added_height = width - height

        if blur_radius == 0.0:
            bottom = edge_row.expand(batch, added_height, width, channels)
        else:
            # A horizontal-only Gaussian removes vertical streaks while keeping
            # the intended left-to-right color variation. Circular padding is
            # used so the left and right skybox boundaries remain continuous.
            calculation = edge_row.movedim(-1, 1).float()
            kernel_radius = min(width - 1, max(1, int(blur_radius * 3.0 + 0.5)))
            positions = torch.arange(
                -kernel_radius,
                kernel_radius + 1,
                device=image.device,
                dtype=torch.float32,
            )
            kernel_1d = torch.exp(-0.5 * (positions / blur_radius) ** 2)
            kernel_1d = kernel_1d / kernel_1d.sum()
            kernel = kernel_1d.view(1, 1, 1, -1).repeat(channels, 1, 1, 1)
            padded = functional.pad(
                calculation,
                (kernel_radius, kernel_radius, 0, 0),
                mode="circular",
            )
            blurred_row = functional.conv2d(
                padded, kernel, groups=channels
            ).movedim(1, -1).to(dtype=image.dtype)

            raw_bottom = edge_row.expand(batch, added_height, width, channels)
            blurred_bottom = blurred_row.expand(
                batch, added_height, width, channels
            )

            # Keep the very first added row identical to the source edge, then
            # ease into the blurred result. This avoids creating a new seam.
            transition = min(max(1, int(blend_height)), added_height)
            alpha = torch.ones(
                (1, added_height, 1, 1),
                device=image.device,
                dtype=image.dtype,
            )
            if transition == 1:
                alpha[:, 0] = 0
            else:
                alpha[:, :transition] = torch.linspace(
                    0.0,
                    1.0,
                    transition,
                    device=image.device,
                    dtype=image.dtype,
                ).view(1, transition, 1, 1)
            bottom = raw_bottom + (blurred_bottom - raw_bottom) * alpha

        output = torch.cat((image, bottom), dim=1)
        return (output,)
