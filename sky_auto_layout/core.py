"""Conservative sky-band layout prototype. No diffusion, learned segmentation, or network calls."""
from __future__ import annotations

import copy
import math
import numpy as np
from PIL import Image, ImageDraw

VERSION = "0.1.0"


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def resize_float(image, width, height):
    if image.shape[:2] == (height, width):
        return image.copy()
    channels = [np.asarray(Image.fromarray(image[..., c].astype(np.float32)).resize(
        (width, height), Image.Resampling.BILINEAR), dtype=np.float32)
        for c in range(3)]
    return np.stack(channels, axis=-1)


def _copy(packet):
    out = dict(packet)
    out["report"] = copy.deepcopy(packet["report"])
    return out


def _horizontal_detail(arr):
    # Remove slow horizontal color drift before looking for cloud structure.
    # Three box passes approximate a broad Gaussian, without scipy/opencv.
    radius = max(3, round(arr.shape[1] * 0.025))
    size = 2 * radius + 1
    smooth = arr.astype(np.float64)
    for _ in range(3):
        padded = np.pad(smooth, ((0, 0), (radius, radius), (0, 0)), mode="edge")
        cumulative = np.concatenate([np.zeros((arr.shape[0], 1, 3)),
                                     np.cumsum(padded, axis=1)], axis=1)
        smooth = (cumulative[:, size:] - cumulative[:, :-size]) / size
    return np.max(np.abs(arr - smooth), axis=2)


def _reject(packet, code, message):
    packet["report"].update(status="retry_required", code=code, message=message,
                            layout_pass=False, publishable=False,
                            next_action="upstream_retry_or_fallback")
    return packet


def analyze(image, sensitivity=1.0):
    """Estimate ALL textured rows, never just the largest connected cloud.

    This is a heuristic for structured clouds against near row-uniform sky.
    It is not a calibrated confidence score or a semantic cloud detector.
    """
    arr = np.asarray(image, dtype=np.float32)
    report = {"version": VERSION, "status": "pending", "layout_pass": False,
              "publishable": False, "detector": "horizontal_deviation_v1",
              "semantic_detection_verified": False,
              "limitations": ["Clouds over smooth sky only; faint or uniform features may be missed.",
                              "No automatic repair/verification of a 360-degree seam.",
                              "Output is SDR PNG, not radiometric HDR."]}
    packet = {"source": arr, "report": report}
    if arr.ndim != 3 or arr.shape[-1] != 3:
        raise ValueError("Expected one RGB image [height, width, 3].")
    h, w = arr.shape[:2]
    report["input_size"] = [w, h]
    if not np.isfinite(arr).all() or arr.min() < 0 or arr.max() > 1:
        return _reject(packet, "INVALID_RGB", "Requires finite RGB data in [0, 1].")
    if w < 128 or h < 64 or not 1.8 <= w / h <= 2.7:
        return _reject(packet, "INPUT_GEOMETRY", "Load the sky image itself (2:1 or 21:9), not a UI screenshot.")
    if not 0.5 <= float(sensitivity) <= 2.0:
        raise ValueError("sensitivity must be between 0.5 and 2.0")

    aw = min(1024, w)
    ah = max(32, round(h * aw / w))
    small = resize_float(arr, aw, ah)
    median = np.median(small, axis=1)
    deviation = _horizontal_detail(small)
    strong_t, weak_t = 0.034 / sensitivity, 0.016 / sensitivity
    strong_hits = np.sum(deviation > strong_t, axis=1)
    weak_hits = np.sum(deviation > weak_t, axis=1)
    strong_rows = strong_hits >= max(2, math.ceil(aw * 0.003))
    weak_rows = weak_hits >= max(2, math.ceil(aw * 0.004))
    report["detection"] = {"analysis_size": [aw, ah], "sensitivity": sensitivity,
        "strong_threshold": strong_t, "weak_threshold": weak_t,
        "strong_row_count": int(strong_rows.sum())}
    if not strong_rows.any():
        # Deliberately refuse to turn 'no detection' into 'certainly cloud-free'.
        return _reject(packet, "NO_RELIABLE_CONTENT", "No reliable cloud band detected; do not discard faint content.")
    indices = np.flatnonzero(strong_rows)
    lo, hi = int(indices[0]), int(indices[-1]) + 1
    # Include weaker neighboring fringes; all strong detached rows already count.
    max_gap = max(1, round(ah * 0.01))
    while lo > 0:
        nearby = np.flatnonzero(weak_rows[max(0, lo - max_gap):lo])
        if not nearby.size:
            break
        lo = max(0, lo - max_gap) + int(nearby[0])
    while hi < ah:
        nearby = np.flatnonzero(weak_rows[hi:min(ah, hi + max_gap)])
        if not nearby.size:
            break
        hi += int(nearby[-1]) + 1

    # Re-evaluate at source resolution to avoid losing edges after downsampling.
    row_median = np.median(arr, axis=1)
    dev = _horizontal_detail(arr)
    source_strong = np.sum(dev > strong_t, axis=1) >= max(2, math.ceil(w * 0.003))
    source_weak = np.sum(dev > weak_t, axis=1) >= max(2, math.ceil(w * 0.004))
    src_ids = np.flatnonzero(source_strong)
    y0 = math.floor(lo * h / ah)
    y1 = math.ceil(hi * h / ah)
    if src_ids.size:
        y0, y1 = min(y0, int(src_ids[0])), max(y1, int(src_ids[-1]) + 1)
    # Keep a small fixed safety margin for soft fringes.
    margin = max(2, math.ceil(h * 0.012))
    core_top = max(0, y0 - margin)
    core_bottom = min(h, y1 + margin)
    feather = max(2, math.ceil(h * 0.012))
    band_top, band_bottom = core_top - feather, core_bottom + feather
    if band_top < 0 or band_bottom > h:
        return _reject(packet, "CONTENT_TOUCHES_EDGE", "Cloud band lacks clean top/bottom margins; cannot preserve it safely.")
    if np.any(source_strong[:band_top]) or np.any(source_strong[band_bottom:]):
        return _reject(packet, "DETACHED_CONTENT", "Detected content lies outside the retained band.")
    # Very broad row changes are not trusted as an isolated cloud band.
    if (band_bottom - band_top) / h > 0.65:
        return _reject(packet, "CONTENT_TOO_BROAD", "Not a compact cloud band; overcast/rain/aurora needs separate validation.")
    clean_top = max(0, band_top - max(2, margin))
    clean_bottom = min(h, band_bottom + max(2, margin))
    if np.any(source_weak[clean_top:band_top]) or np.any(source_weak[band_bottom:clean_bottom]):
        return _reject(packet, "UNCLEAN_MARGIN", "A clean blending margin could not be established.")

    packet["bounds"] = (band_top, band_bottom, core_top, core_bottom)
    packet["row_median"] = row_median
    report["detection"].update(band_px=[band_top, band_bottom],
        core_px=[core_top, core_bottom],
        band_percent=[100.0 * band_top / h, 100.0 * band_bottom / h],
        note="Automatic heuristic estimate, not a guarantee that every low-contrast wisp is detected.")
    report.update(status="detected", code="DETECTED", message="A candidate band was detected.")
    return packet


def plan(packet, layout_mode="strict_30_45", coordinate_space="design_21_9"):
    out = _copy(packet)
    if out["report"]["status"] == "retry_required":
        return out
    if layout_mode not in ("strict_30_45", "horizon_only"):
        raise ValueError("Unknown layout_mode")
    if coordinate_space not in ("design_21_9", "final_2_1"):
        raise ValueError("Unknown coordinate_space")
    arr = out["source"]
    h, w = arr.shape[:2]
    # Preserve all original pixels. Odd-width images get one interpolated wrap column.
    ow = w + w % 2
    oh = ow // 2
    ref_h = w * 9.0 / 21.0 if coordinate_space == "design_21_9" else float(oh)
    lower_fraction = 0.45
    top_fraction = 0.30 if layout_mode == "strict_30_45" else 0.03
    target_top = math.ceil(ref_h * top_fraction)
    target_bottom = math.floor(ref_h * lower_fraction)
    b0, b1, c0, c1 = out["bounds"]
    span = b1 - b0
    layout = {"mode": layout_mode, "coordinate_space": coordinate_space,
        "reference_height_px": ref_h, "output_size": [ow, oh],
        "allowed_px": [target_top, target_bottom],
        "allowed_percent_of_final": [100 * target_top / oh, 100 * target_bottom / oh],
        "band_height_px": span, "deformation": "none", "horizontal_scale": 1.0,
        "vertical_scale": 1.0, "odd_width_extra_wrap_column": bool(w % 2)}
    out["report"]["layout"] = layout
    if span > target_bottom - target_top:
        return _reject(out, "BAND_DOES_NOT_FIT", "Complete band does not fit without distortion. Retry upstream; nothing is cropped.")
    desired = round(ref_h * 0.375 - span / 2)
    dst_top = int(np.clip(desired, target_top, target_bottom - span))
    dst_bottom = dst_top + span
    layout.update(destination_px=[dst_top, dst_bottom], translation_y_px=dst_top - b0,
                  destination_core_px=[dst_top + c0 - b0, dst_top + c1 - b0])
    out["destination"] = (dst_top, dst_bottom)
    out["output_size"] = (ow, oh)
    out["report"].update(status="planned", code="PLANNED", message="Pixel-preserving translation planned.")
    return out


def _profile(positions, colors, height):
    result = np.empty((height, 3), dtype=np.float32)
    positions = list(positions)
    for k in range(len(positions) - 1):
        a, b = positions[k:k+2]
        if b <= a:
            raise ValueError("Gradient anchors must be increasing")
        ys = np.arange(a, b + 1)
        t = _smoothstep((ys - a) / (b - a))[:, None]
        result[ys] = colors[k] * (1-t) + colors[k+1] * t
    return result


def compose(packet):
    out = _copy(packet)
    if out["report"]["status"] == "retry_required":
        return out
    arr = out["source"]
    h, w = arr.shape[:2]
    ow, oh = out["output_size"]
    b0, b1, c0, c1 = out["bounds"]
    d0, d1 = out["destination"]
    rows = out["row_median"]
    n = max(2, math.ceil(h * 0.01))
    top_color = np.median(arr[:n].reshape(-1, 3), axis=0)
    bottom_color = np.median(arr[-n:].reshape(-1, 3), axis=0)
    band_top_color, band_bottom_color = rows[b0], rows[b1 - 1]
    profile = _profile([0, d0, d1 - 1, oh - 1],
        [top_color, band_top_color, band_bottom_color, bottom_color], oh)
    background = np.broadcast_to(profile[:, None, :], (oh, ow, 3)).copy()
    result = background.copy()
    band = arr[b0:b1].copy()
    if ow > w:
        # Does not fix an existing seam: only add a cyclic interpolation column.
        wrap = (band[:, :1] + band[:, -1:]) * 0.5
        band = np.concatenate([band, wrap], axis=1)
    ys = np.arange(b1-b0)
    a = _smoothstep(ys / max(1, c0-b0))
    b = _smoothstep((b1-b0-1-ys) / max(1, b1-c1-1))
    alpha = np.minimum(a, b).astype(np.float32)
    alpha[c0-b0:c1-b0] = 1.0
    result[d0:d1] = result[d0:d1] * (1-alpha[:, None, None]) + band * alpha[:, None, None]
    result = np.clip(result, 0, 1).astype(np.float32)
    # Enforce the background after feathering as well, so it cannot leak out.
    t0, t1 = out["report"]["layout"]["allowed_px"]
    result[:t0] = background[:t0]
    result[t1:] = background[t1:]
    out["result"] = result
    dc0, dc1 = out["report"]["layout"]["destination_core_px"]
    core_error = float(np.max(np.abs(result[dc0:dc1, :w] - arr[c0:c1])))
    lower_uniformity = float(np.max(np.abs(result[t1:] - result[t1:, :1])))
    top_uniformity = float(np.max(np.abs(result[:t0] - result[:t0, :1])))
    seam_before = float(np.mean(np.abs(arr[b0:b1, 0] - arr[b0:b1, -1])))
    seam_after = float(np.mean(np.abs(result[d0:d1, 0] - result[d0:d1, -1])))
    out["report"]["checks"] = {
        "ratio_2_1": ow == 2*oh,
        "retained_core_max_error": core_error,
        "top_uniformity_max_error": top_uniformity,
        "bottom_uniformity_max_error": lower_uniformity,
        "outside_allowed_band_is_background": bool(np.array_equal(result[:t0], background[:t0]) and
                                                    np.array_equal(result[t1:], background[t1:])),
        "seam_mean_abs_difference_before": seam_before,
        "seam_mean_abs_difference_after": seam_after,
        "seam_validated": False,
        "spherical_projection_validated": False,
        "hdr_radiance": False,
    }
    passed = (ow == 2*oh and core_error < 1e-6 and top_uniformity < 1e-6 and
              lower_uniformity < 1e-6 and d0 >= t0 and d1 <= t1)
    if not passed:
        return _reject(out, "COMPOSITE_CHECK_FAILED", "Geometry/pixel-preservation checks failed.")
    out["report"].update(status="layout_pass", code="LAYOUT_PASS", layout_pass=True,
        publishable=False, next_action="downstream_visual_and_seam_validation",
        message="Layout passed. Cloud detection, blending appearance and spherical seam still need validation.")
    return out


def debug_image(packet):
    use_result = packet["report"].get("layout_pass", False)
    arr = packet["result"] if use_result else packet["source"]
    canvas = Image.fromarray(np.round(np.clip(arr, 0, 1)*255).astype(np.uint8))
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    if "bounds" in packet and not use_result:
        b0, b1, c0, c1 = packet["bounds"]
        for y in (b0, b1-1):
            draw.line([(0, y), (w-1, y)], fill=(255, 160, 0), width=2)
        for y in (c0, c1-1):
            draw.line([(0, y), (w-1, y)], fill=(0, 220, 230))
    if use_result:
        for y in packet["report"]["layout"]["allowed_px"]:
            draw.line([(0, min(y, h-1)), (w-1, min(y, h-1))], fill=(0, 220, 230))
    draw.line([(0, h//2), (w-1, h//2)], fill=(255, 70, 70), width=1)
    label = "DEBUG ONLY | " + packet["report"]["code"]
    draw.rectangle((0, 0, min(w, len(label)*7+12), 20), fill=(15, 15, 15))
    draw.text((5, 4), label, fill=(235, 235, 235))
    return np.asarray(canvas, dtype=np.float32) / 255.0


def process(image, layout_mode="strict_30_45", coordinate_space="design_21_9", sensitivity=1.0):
    return compose(plan(analyze(image, sensitivity), layout_mode, coordinate_space))
