"""Offline U²-Netp and ViTMatte inference for white-background scenery assets."""

from functools import lru_cache
from hashlib import sha256
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image


MODEL_FOLDER = "far_scenery_matting"
MANAGED_VIT_NAMES = ("far_scenery_vitmatte_small.safetensors", "far_scenery_vitmatte_small")
VIT_URL = "https://huggingface.co/hustvl/vitmatte-small-composition-1k/resolve/main/"
FILES = (
    ("u2netp.onnx", "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
     "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"),
    ("vitmatte/config.json", VIT_URL + "config.json",
     "ae1006f5a83227048b563b2e60709d4203e432b2276949ebef41a8cfeeeaf45f"),
    ("vitmatte/preprocessor_config.json", VIT_URL + "preprocessor_config.json",
     "0db558038b96a3f5c97e46d4ec8966fcc479e9aa58a391bca60b5094a5f7fee0"),
    ("vitmatte/model.safetensors", VIT_URL + "model.safetensors",
     "bda9289db1bb6762d978b42d1c62ae3f34daf7497171a347a1d09657efd788cb"),
)
_model_lock = Lock()


def model_directory():
    override = os.environ.get("FAR_SCENERY_MATTE_MODEL_DIR")
    if override:
        return Path(override).expanduser()
    import folder_paths
    return Path(folder_paths.models_dir) / MODEL_FOLDER


def file_digest(path):
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def managed_vit_candidates(directory):
    """Read the exact Manager-downloaded name from standard configured model folders."""
    model_root = directory.parent
    roots = [model_root / "checkpoints", model_root / "checkpoint"]
    found = []
    try:
        import folder_paths
    except ImportError:
        folder_paths = None
    if folder_paths is not None:
        model_root = Path(folder_paths.models_dir)
        roots.extend((model_root / "checkpoints", model_root / "checkpoint"))
        try:
            roots.extend(Path(p) for p in folder_paths.get_folder_paths("checkpoints"))
        except (AttributeError, KeyError):
            pass
        for name in MANAGED_VIT_NAMES:
            try:
                path = folder_paths.get_full_path("checkpoints", name)
            except (AttributeError, KeyError):
                path = None
            if path:
                found.append(Path(path))
    found.extend(root / name for root in roots for name in MANAGED_VIT_NAMES)
    if folder_paths is not None and not any(path.is_file() for path in found):
        # Some managers register a named file in a subfolder rather than the root.
        try:
            for entry in folder_paths.get_filename_list("checkpoints"):
                if Path(entry).name in MANAGED_VIT_NAMES:
                    path = folder_paths.get_full_path("checkpoints", entry)
                    if path:
                        found.append(Path(path))
        except (AttributeError, KeyError):
            pass
    return tuple(dict.fromkeys(path.resolve() for path in found if path.is_file()))


def install_verified_stream(source, target, expected):
    """Stage a verified model atomically; leave existing models untouched."""
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256()
        with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                stream.write(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError("模型文件 SHA-256 与预期不一致。")
        if target.exists():
            if not target.is_file() or file_digest(target) != expected:
                raise RuntimeError(f"模型目标已存在且校验失败：{target}；不会自动覆盖。")
        else:
            temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ensure_weights(directory):
    """Reuse verified Manager weights before attempting a fixed public download."""
    for relative, url, expected in FILES:
        target = directory / relative
        if target.is_file():
            if file_digest(target) != expected:
                raise RuntimeError(f"精细抠图模型校验不通过：{target}。请核对官方文件；不会自动覆盖现有模型。")
            continue
        if relative == "vitmatte/model.safetensors":
            candidates = managed_vit_candidates(directory)
            if candidates:
                valid = next((path for path in candidates if file_digest(path) == expected), None)
                if valid is None:
                    raise RuntimeError("Manager 下载的 far_scenery_vitmatte_small 校验失败：" +
                                       ", ".join(str(p) for p in candidates) + "。请确认是官方 ViTMatte-Small 权重。")
                with valid.open("rb") as source:
                    install_verified_stream(source, target, expected)
                print(f"[Far Scenery] 已使用 Manager 模型：{valid}", flush=True)
                continue
        try:
            print(f"[Far Scenery] 下载精细抠图模型：{relative}", flush=True)
            request = Request(url, headers={"User-Agent": "FarSceneryMatting/1.0"})
            with urlopen(request, timeout=120) as response:
                install_verified_stream(response, target, expected)
        except Exception as exc:
            manager_help = (" 或使用 Manager 的 checkpoint 类别下载，名称填 far_scenery_vitmatte_small（不含后缀）。"
                            if relative == "vitmatte/model.safetensors" else "")
            raise RuntimeError(
                f"精细抠图缺少模型：{relative}。自动下载失败。请从 {url} 下载到 {target}，"
                "保持目录结构后重试（平台若限制外网，需要管理员配置模型）。" + manager_help
            ) from exc


@lru_cache(maxsize=1)
def _load_models(directory):
    # Keep imports lazy so the old CPU-only nodes still load without ML dependencies.
    try:
        import onnxruntime as ort
        from scipy import ndimage
        from transformers import VitMatteForImageMatting, VitMatteImageProcessor
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError("远景精细抠图依赖未安装或不兼容。请安装插件 requirements.txt 并重启运行环境。") from exc
    ensure_weights(directory)
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    saliency = ort.InferenceSession(str(directory / "u2netp.onnx"), sess_options=options,
                                    providers=["CPUExecutionProvider"])
    processor = VitMatteImageProcessor.from_pretrained(directory / "vitmatte", local_files_only=True)
    model = VitMatteForImageMatting.from_pretrained(directory / "vitmatte", local_files_only=True,
                                                   use_safetensors=True).eval().cpu()
    return saliency, processor, model, ndimage


def get_models(directory):
    # Prevent five simultaneously queued branches from initializing/downloading five copies.
    with _model_lock:
        return _load_models(directory.resolve())


def largest(mask, ndi):
    labels, count = ndi.label(mask)
    if not count:
        raise ValueError("未找到可用的山体前景。请使用完整山体、白色或近白色背景的横向图片。")
    counts = np.bincount(labels.ravel())
    counts[0] = 0
    return labels == counts.argmax()


def image8(values):
    return np.rint(np.clip(values, 0, 1) * 255).astype(np.uint8)


def infer_rgba(source, models):
    """Return straight-alpha RGB + opacity, using the validated 2048px processing scale."""
    import torch
    saliency, processor, model, ndi = models
    source = source.convert("RGB")
    # Preserve horizontal composition and bound Transformer memory on nonstandard inputs.
    scale = min(2048 / source.width, 1024 / source.height)
    source = source.resize((max(2, round(source.width * scale)), max(2, round(source.height * scale))),
                           Image.Resampling.LANCZOS)
    width, height = source.size
    rgb = np.asarray(source, dtype=np.float32) / 255
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]))
    bg = np.median(border, axis=0)
    if np.min(bg) < .85 or np.ptp(bg) > .10:
        raise ValueError("精细抠图针对白底远景素材，请保留白色或近白色背景。")
    delta = ndi.gaussian_filter(np.maximum(0, bg - rgb).max(-1), 1.2) * 255

    low = np.asarray(source.resize((320, 320), Image.Resampling.LANCZOS), dtype=np.float32) / 255
    low = ((low - np.array([.485, .456, .406], dtype=np.float32)) /
           np.array([.229, .224, .225], dtype=np.float32)).transpose(2, 0, 1)[None]
    pred = saliency.run(None, {saliency.get_inputs()[0].name: low})[0].squeeze()
    pred = (pred - pred.min()) / max(pred.max() - pred.min(), 1e-5)
    ai = np.asarray(Image.fromarray(image8(pred)).resize((width, height), Image.Resampling.BILINEAR),
                    dtype=np.float32) / 255
    ai_region = ndi.binary_fill_holes(largest(ai > .35, ndi))
    ai_gate = ndi.distance_transform_edt(~ai_region) < 45

    # AI localization gates image evidence, not a color-to-alpha mapping.
    body = ndi.binary_fill_holes(largest(ndi.binary_closing((delta > 22) & ai_gate, iterations=2), ndi))
    body_y, _ = np.where(body)
    dist_in = ndi.distance_transform_edt(body)
    dist_out = ndi.distance_transform_edt(~body)
    yy = np.arange(height)[:, None]
    column_base = np.max(np.where(body, yy, -1), axis=0)
    present = column_base >= 0
    column_base = ndi.median_filter(np.interp(np.arange(width), np.where(present)[0], column_base[present]), size=19)
    foot_band = max(20, round((body_y.max() - body_y.min()) * .16))
    core = (dist_in >= 7) & (yy < column_base[None, :] - foot_band)
    if not core.any():
        # A very thin distant ridge still needs definite foreground seeds.
        core = dist_in >= max(1, dist_in.max() * .5)
    outer = (dist_out < 13) | ((dist_out < 35) & (yy > column_base[None, :] - foot_band) & (delta > 5))
    trimap = np.zeros((height, width), dtype=np.uint8)
    trimap[outer] = 128
    trimap[core] = 255

    y0 = max(0, int(body_y.min()) - 80)
    y1 = min(height, int(body_y.max()) + 80)
    inputs = processor(images=source.crop((0, y0, width, y1)),
                       trimaps=Image.fromarray(trimap[y0:y1]), return_tensors="pt")
    with torch.inference_mode():
        prediction = model(**inputs).alphas[0, 0, :y1-y0, :width].float().cpu().numpy()
    alpha = np.zeros((height, width), dtype=np.float32)
    alpha[y0:y1] = np.clip(prediction, 0, 1)
    alpha[trimap == 0] = 0
    alpha[trimap == 255] = 1
    if not np.isfinite(alpha).all() or not (alpha.min() < .05 and alpha.max() >= .5):
        raise ValueError("精细抠图未得到有效透明度，请检查原图。")

    # Remove the original near-white background from soft edges; constrain faint pixels
    # using the nearest opaque foreground colors instead of amplifying JPEG artifacts.
    indices = ndi.distance_transform_edt(~core, return_distances=False, return_indices=True)
    smooth_rgb = np.stack([ndi.gaussian_filter(rgb[..., c], 1.3) for c in range(3)], axis=-1)
    near = smooth_rgb[indices[0], indices[1]]
    unmix = np.clip(bg + (rgb - bg) / np.maximum(alpha[..., None], .10), 0, 1)
    weight = np.clip((alpha - .06) / .55, 0, 1)[..., None]
    fg = unmix * weight + near * (1 - weight)
    fg[alpha >= .995] = rgb[alpha >= .995]
    fg[alpha == 0] = 0
    return image8(np.concatenate((fg, alpha[..., None]), axis=2))


class FarSceneryFineMatte:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE")
    RETURN_NAMES = ("image", "mask", "preview")
    FUNCTION = "matte"
    CATEGORY = "Far Scenery"
    DESCRIPTION = "U²-Netp 主体分割 + ViTMatte 精细透明度，保留山脚渐隐、去白边。CPU 推理，首次下载模型。MASK 白色表示透明。"

    def matte(self, image):
        import torch
        rgb = image.detach().float().cpu().numpy()
        if rgb.ndim != 4 or rgb.shape[0] != 1 or rgb.shape[-1] != 3 or min(rgb.shape[1:3]) < 2:
            raise ValueError("远景精细抠图每次接收一张 RGB 图片。")
        if not np.isfinite(rgb).all():
            raise ValueError("输入图像含无效像素。")
        rgba = infer_rgba(Image.fromarray(image8(rgb[0])), get_models(model_directory()))
        foreground = Image.fromarray(rgba)
        preview = Image.new("RGB", foreground.size, (35, 42, 52))
        preview.paste(foreground.convert("RGB"), mask=foreground.getchannel("A"))
        preview.thumbnail((960, 960), Image.Resampling.LANCZOS)
        values = rgba.astype(np.float32) / 255
        return (torch.from_numpy(values[None, ..., :3].copy()),
                torch.from_numpy(1 - values[None, ..., 3]),
                torch.from_numpy(np.asarray(preview, dtype=np.float32)[None] / 255))
