"""CPU vertical resampling; no quantization, color conversion, or x resampling."""
import math
import numpy as np


def stretch_bottom_array(image, bottom_percent=30.0):
    """BHWC floating array -> (array, metadata). Upper rows copied exactly.

    Even input width is required so width can remain unchanged at exact 2:1.
    Endpoint-aligned linear interpolation preserves the first/last bottom rows.
    """
    if image.ndim != 4 or any(s < 1 for s in image.shape):
        raise ValueError("Expected nonempty IMAGE [batch, height, width, channels].")
    if not np.issubdtype(image.dtype, np.floating):
        raise ValueError("IMAGE must contain floating-point pixels.")
    if not math.isfinite(bottom_percent) or not 0 < bottom_percent <= 100:
        raise ValueError("bottom_percent must be in (0, 100].")
    batch, height, width, channels = image.shape
    if width % 2:
        raise ValueError("Input width must be even for exact 2:1 without changing width.")
    target_height = width // 2
    if target_height < height:
        raise ValueError("Input is narrower than 2:1. This node expands height only.")
    bottom_rows = min(height, max(1, int(height * bottom_percent / 100 + 0.5)))
    split = height - bottom_rows
    output_bottom_rows = target_height - split
    meta = dict(width=width, input_height=height, output_height=target_height,
                preserved_rows=split, input_bottom_rows=bottom_rows,
                output_bottom_rows=output_bottom_rows)
    if target_height == height:
        return image.copy(), meta
    output = np.empty((batch, target_height, width, channels), dtype=image.dtype)
    output[:, :split] = image[:, :split]
    calc_dtype = np.float64 if image.dtype == np.float64 else np.float32
    # Chunk the resampling so temporary memory does not scale with image height.
    for start in range(0, output_bottom_rows, 32):
        stop = min(start + 32, output_bottom_rows)
        if output_bottom_rows == 1:
            pos = np.zeros(stop - start, dtype=np.float64)
        else:
            pos = np.arange(start, stop, dtype=np.float64) * ((bottom_rows - 1) / (output_bottom_rows - 1))
        lower = np.floor(pos).astype(np.int64)
        upper = np.minimum(lower + 1, bottom_rows - 1)
        weight = (pos - lower).astype(calc_dtype)[None, :, None, None]
        a = image[:, split + lower].astype(calc_dtype, copy=False)
        b = image[:, split + upper].astype(calc_dtype, copy=False)
        output[:, split + start:split + stop] = a + (b - a) * weight
    # Exact endpoint copies also avoid numerical drift for float64 pixel values.
    output[:, split] = image[:, split]
    output[:, -1] = image[:, -1]
    return output, meta
