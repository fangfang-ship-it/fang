"""AI Studio 3D generation nodes for ComfyUI.

Credentials are read from environment variables and are never stored in workflow JSON.
The public node keeps its original class name so existing ByteArtist workflows continue to load.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_API_BASE = "https://3d.bytedance.net"
_TERMINAL_SUCCESS = {"success", "succeeded", "done", "completed"}
_TERMINAL_FAILURE = {"failed", "error", "canceled", "cancelled"}


class Douyin3DError(RuntimeError):
    """Raised when the AI Studio API rejects or fails a generation."""


def _ticket() -> str:
    """Generate the anti-replay ticket used by AI Studio write endpoints."""
    timestamp = int(time.time()) + 1_234_567_890
    return base64.b64encode(str(timestamp).encode("ascii")).decode("ascii")


def _auth_headers(cas_session: str = "") -> dict[str, str]:
    cas_session = cas_session.strip()
    if cas_session.startswith("AGW_CAS_SESSION="):
        cas_session = cas_session.removeprefix("AGW_CAS_SESSION=").strip()
    if not cas_session:
        cas_session = os.environ.get("DOUYIN3D_CAS_SESSION", "").strip()
    if cas_session:
        if any(character in cas_session for character in ("\r", "\n", ";")):
            raise Douyin3DError("CAS session contains invalid characters; paste only the AGW_CAS_SESSION value.")
        return {"Cookie": f"AGW_CAS_SESSION={cas_session}"}

    key = os.environ.get("DOUYIN3D_API_KEY", "").strip()
    if not key:
        raise Douyin3DError(
            "No CAS session or API key is configured. Paste the AGW_CAS_SESSION value "
            "into cas_session, or configure DOUYIN3D_CAS_SESSION/DOUYIN3D_API_KEY "
            "in the ByteArtist runtime."
        )
    header = os.environ.get("DOUYIN3D_AUTH_HEADER", "Authorization").strip()
    scheme = os.environ.get("DOUYIN3D_AUTH_SCHEME", "Bearer").strip()
    value = f"{scheme} {key}".strip() if scheme else key
    return {header: value}


def _post(
    path: str,
    payload: dict[str, Any],
    timeout: float = 60,
    cas_session: str = "",
    allowed_codes: tuple[int | str, ...] = (),
) -> dict[str, Any]:
    payload = dict(payload)
    if any(word in path for word in ("generate", "upload", "create", "update")):
        payload.setdefault("ticket", _ticket())
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update(_auth_headers(cas_session))
    request = Request(
        f"{_API_BASE}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise Douyin3DError(f"HTTP {exc.code} from {path}: {detail[:800]}") from exc
    except URLError as exc:
        raise Douyin3DError(f"Cannot reach {_API_BASE}: {exc.reason}") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise Douyin3DError(f"Invalid JSON from {path}: {body[:500]}") from exc
    base_resp = data.get("base_resp") or {}
    code = base_resp.get("code", 0)
    if code not in (0, "0", None, *allowed_codes):
        raise Douyin3DError(base_resp.get("message") or f"API error: {base_resp}")
    return data


def _uploaded_url(data: dict[str, Any]) -> str:
    """Return the public image URL from the current AI Studio upload response."""
    candidates: list[Any] = [data]
    while candidates:
        item = candidates.pop(0)
        if isinstance(item, dict):
            for key in ("url", "image_url", "download_url"):
                value = item.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
            candidates.extend(item.values())
        elif isinstance(item, list):
            candidates.extend(item)
    raise Douyin3DError(f"Upload response has no image URL: {json.dumps(data, ensure_ascii=False)[:800]}")


def _upload_comfy_image(image: Any, cas_session: str = "") -> str:
    """Encode the first ComfyUI IMAGE batch item as PNG and upload it to AI Studio."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise Douyin3DError("IMAGE upload requires NumPy and Pillow from the ComfyUI runtime.") from exc
    if image is None or not hasattr(image, "detach"):
        raise Douyin3DError("image must be a ComfyUI IMAGE tensor.")
    array = image.detach().to(device="cpu").float().numpy()
    if array.ndim != 4 or array.shape[0] < 1 or array.shape[-1] not in (3, 4):
        raise Douyin3DError(f"Expected IMAGE shape [B,H,W,3|4], got {array.shape}.")
    pixels = (np.clip(array[0], 0.0, 1.0) * 255.0).round().astype(np.uint8)
    mode = "RGBA" if pixels.shape[-1] == 4 else "RGB"
    from io import BytesIO
    buffer = BytesIO()
    Image.fromarray(pixels, mode=mode).save(buffer, format="PNG")
    file_name = f"byteartist_{int(time.time() * 1000)}.png"
    payload = {
        "file_data": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "file_name": file_name,
        # AI Studio treats custom_path as the final object key, not a folder.
        # A stable key makes image-to-3D vendors reuse a cached previous image.
        "custom_path": f"byteartist/douyin3d/{file_name}",
    }
    return _uploaded_url(_post(
        "/api/v1/files/upload", payload, timeout=120, cas_session=cas_session
    ))


def _extract_asset(data: dict[str, Any]) -> dict[str, Any] | None:
    """Accept the list/detail/status response shapes observed in AI Studio."""
    candidates: list[Any] = []
    for key in ("asset", "data", "item", "items", "assets"):
        if key in data:
            candidates.append(data[key])
    while candidates:
        item = candidates.pop(0)
        if isinstance(item, dict):
            if "asset_id" in item:
                return item
            candidates.extend(item.values())
        elif isinstance(item, list):
            candidates.extend(item)
    return None


def _asset_id(data: dict[str, Any]) -> int:
    asset = _extract_asset(data)
    value = (asset or {}).get("asset_id")
    if value is None:
        value = data.get("asset_id") or (data.get("data") or {}).get("asset_id")
    if value is None:
        raise Douyin3DError(f"Generate response has no asset_id: {json.dumps(data)[:800]}")
    return int(value)


def _artifact_url(asset: dict[str, Any], target_format: str = "") -> str:
    artifacts = asset.get("artifacts") or []
    wanted = target_format.strip().lower()
    if wanted:
        for artifact in artifacts:
            if str(artifact.get("format", "")).lower() == wanted and artifact.get("url"):
                if str(artifact.get("status", "success")).lower() == "success":
                    return artifact["url"]
        if wanted != "glb":
            return ""
    else:
        for artifact in artifacts:
            if artifact.get("primary") and artifact.get("url"):
                return artifact["url"]
        for artifact in artifacts:
            if artifact.get("url"):
                return artifact["url"]
    info = asset.get("info")
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except json.JSONDecodeError:
            info = {}
    if isinstance(info, dict) and (not wanted or wanted == "glb"):
        return info.get("modelUrl") or info.get("model_url") or ""
    return ""


def _output_directory() -> Path:
    try:
        import folder_paths
        root = Path(folder_paths.get_output_directory())
    except ImportError:
        root = Path.cwd() / "output"
    target = root / "douyin3d"
    target.mkdir(parents=True, exist_ok=True)
    return target


def download_glb(url: str, asset_id: int, timeout: float = 120) -> Path:
    target = _output_directory() / f"douyin3d_{asset_id}.glb"
    request = Request(url, headers={"Accept": "model/gltf-binary,*/*"})
    try:
        with urlopen(request, timeout=timeout) as response, target.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
    except (HTTPError, URLError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise Douyin3DError(f"Failed to download GLB: {exc}") from exc
    if target.stat().st_size < 12:
        target.unlink(missing_ok=True)
        raise Douyin3DError("Downloaded GLB is empty or invalid.")
    with target.open("rb") as model_file:
        if model_file.read(4) != b"glTF":
            target.unlink(missing_ok=True)
            raise Douyin3DError("Downloaded file is not a valid binary glTF (GLB).")
    return target


def _preview_path(path: Path) -> str:
    """Return the output-relative path expected by ComfyUI Preview3D."""
    return f"douyin3d/{path.name}"


class Douyin3DDownloadGLB:
    """Download an existing GLB URL for downstream Preview 3D validation."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_url": ("STRING", {
                    "default": "https://lf3-creative.dailygn.com/obj/ai-studio/asset/models/1790582042_6372692172.glb",
                    "multiline": False,
                }),
                "asset_id": ("INT", {"default": 6372692172, "min": 1}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("glb_path", "glb_url", "asset_id")
    FUNCTION = "download"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = "下载已有 GLB 到 ComfyUI output/douyin3d，用于无 Key 验证 Preview 3D 下游链路。"

    def download(self, glb_url: str, asset_id: int):
        glb_url = glb_url.strip()
        if not glb_url.lower().startswith(("https://", "http://")):
            raise Douyin3DError("glb_url must be an HTTP or HTTPS URL.")
        path = download_glb(glb_url, int(asset_id))
        return _preview_path(path), glb_url, int(asset_id)


_SUPPLIER_IDS = {
    "Douyin3D": "douyin3d",
    "混元3D": "hunyuan3d",
    "Poly3D": "module",
    "Rodin": "rodin",
    "Seed3D": "seed3d",
    "Tripo3D": "tripo3d",
}
_MODEL_PROFILES = [
    "推荐（随供应商）",
    "Douyin V3.1-fast", "Douyin V3.1",
    "混元 3.0", "混元 3.1", "混元 Express",
    "Rodin Gen-1", "Rodin Gen-2", "Rodin Gen-2.5",
    "Seed3D 2.0",
    "Tripo v3.1", "Tripo v3.0", "Tripo v2.5", "Tripo P1", "Tripo P2 Preview",
]
_QUALITY_LEVELS = {"快速预览": 0, "标准": 1, "高质量": 2, "超高质量": 3}


def _vendor_model(vendor: str, profile: str) -> int | None:
    mappings = {
        "douyin3d": {"Douyin V3.1": 0, "Douyin V3.1-fast": 1},
        "hunyuan3d": {"混元 3.0": 0, "混元 3.1": 1, "混元 Express": 2},
        "rodin": {"Rodin Gen-1": 0, "Rodin Gen-2": 4, "Rodin Gen-2.5": 7},
        "seed3d": {"Seed3D 2.0": 0},
        "tripo3d": {
            "Tripo P1": 0, "Tripo v3.1": 2, "Tripo v3.0": 3,
            "Tripo v2.5": 4, "Tripo P2 Preview": 5,
        },
    }
    defaults = {"douyin3d": 1, "hunyuan3d": 0, "rodin": 7, "seed3d": 0, "tripo3d": 2}
    return mappings.get(vendor, {}).get(profile, defaults.get(vendor))


def _build_vendor_fields(
    vendor: str,
    model_profile: str,
    quality_preset: str,
    geometry_quality: str,
    texture_quality: str,
    faces: int,
    texture_size: int,
    enable_pbr: bool,
    seed: int,
    poly_style: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the vendor-specific fields used by the current AI Studio web client."""
    level = _QUALITY_LEVELS.get(quality_preset, 2)
    custom_quality = {"low": 0, "middle": 1, "high": 2, "ultra": 3}
    geo_level = custom_quality[geometry_quality] if quality_preset == "自定义" else level
    tex_level = custom_quality[texture_quality] if quality_preset == "自定义" else level
    faces = max(100, min(1_000_000, int(faces)))
    seed = max(0, min(65_535, int(seed)))
    model = _vendor_model(vendor, model_profile)

    if vendor == "douyin3d":
        return {"douyin3d_params": {
            "style": 0,
            "model_version": model,
            "gene_quality_geo": geo_level,
            "gene_quality_tex": tex_level,
            "faces_num": faces,
            "uv_size": int(texture_size),
            "enable_texture": True,
            "enable_pbr": bool(enable_pbr),
            "delight_strength": 0,
            "seed_geo": seed,
            "seed_tex": seed,
            "output_format": "glb",
            "split_model": False,
            "quad_remesh": False,
        }}, {}
    if vendor == "hunyuan3d":
        params = {"model": model, "enable_pbr": bool(enable_pbr)}
        if model != 2:
            params.update({"face_count": faces, "generate_type": 0})
        else:
            params.update({"result_format": 1, "enable_geometry": True})
        return {"hunyuan3d_params": params}, {}
    if vendor == "module":
        style_map = {
            "不选风格": "", "低模玩具": "worldplay-lowpoly-toy-v1",
            "黏土手办": "worldplay-clay-figurine-v1",
            "机械积木": "worldplay-mech-brick-v1",
        }
        style = style_map[poly_style]
        return {}, ({"moduleStyleProfile": style} if style else {})
    if vendor == "rodin":
        tier = model
        if model == 7 and quality_preset != "自定义":
            tier = {0: 5, 1: 7, 2: 8, 3: 9}[level]
        return {"rodin_params": {
            "tier": tier, "geometry_file_format": 0, "seed": seed,
            "material": 0, "mesh_mode": 1,
        }}, {}
    if vendor == "seed3d":
        subdivision = min(2, level if quality_preset != "自定义" else geo_level)
        return {"seed3d_params": {"fileformat": 0, "subdivisionlevel": subdivision}}, {}
    if vendor == "tripo3d":
        tripo_geo = 1 if geo_level >= 2 else 0
        tripo_tex = 2 if tex_level >= 3 else (1 if tex_level >= 2 else 0)
        return {"tripo_params": {
            "model_version": model,
            "geometry_quality": tripo_geo,
            "texture_quality": tripo_tex,
            "face_limit": faces,
            "orientation": 0,
            "texture_alignment": 0,
            "texture": True,
            "pbr": bool(enable_pbr),
            "quad": False,
            "smart_low_poly": quality_preset == "快速预览",
            "generate_parts": False,
            "export_uv": True,
            "auto_size": False,
            "model_seed": seed,
            "texture_seed": seed,
        }}, {}
    raise Douyin3DError(f"Unsupported AI Studio vendor: {vendor}")


class Douyin3DDownloadAsset:
    """Return a downloadable GLB/FBX/OBJ URL, converting the asset when needed."""

    _FORMATS = {"GLB": 1, "FBX": 2, "OBJ": 3}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "asset_id": ("INT", {"default": 1, "min": 1, "forceInput": True}),
                "format": (list(cls._FORMATS), {"default": "GLB"}),
                "cas_session": ("STRING", {
                    "default": "", "password": True,
                    "tooltip": "与生成节点相同的 AGW_CAS_SESSION；会随工作流保存。",
                }),
                "timeout_minutes": ("INT", {"default": 10, "min": 1, "max": 30}),
                "poll_seconds": ("INT", {"default": 3, "min": 1, "max": 10}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("download_url", "format", "asset_id", "status_json")
    FUNCTION = "get_download"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = "获取 GLB/FBX/OBJ 下载链接；需要时调用 AI Studio 官方转换接口。"

    def get_download(
        self,
        asset_id: int,
        format: str,
        cas_session: str = "",
        timeout_minutes: int = 10,
        poll_seconds: int = 3,
    ):
        target = format.strip().upper()
        if target not in self._FORMATS:
            raise Douyin3DError(f"Unsupported download format: {format}")
        asset_id = int(asset_id)
        detail = _post(
            "/api/v1/assets/detail", {"asset_id": asset_id}, cas_session=cas_session
        )
        asset = _extract_asset(detail) or {}
        url = _artifact_url(asset, target.lower())
        if not url:
            conversion = _post(
                "/api/v1/assets/convert",
                {
                    "asset_id": asset_id,
                    "target_format": self._FORMATS[target],
                    "content_type": 0,
                },
                cas_session=cas_session,
                allowed_codes=(10005, "10005"),
            )
            accepted = conversion.get("accepted")
            code = (conversion.get("base_resp") or {}).get("code", 0)
            if accepted is False and code not in (10005, "10005"):
                raise Douyin3DError(f"AI Studio rejected {target} conversion.")
            deadline = time.monotonic() + max(1, int(timeout_minutes)) * 60
            while time.monotonic() < deadline:
                detail = _post(
                    "/api/v1/assets/detail", {"asset_id": asset_id}, cas_session=cas_session
                )
                asset = _extract_asset(detail) or asset
                url = _artifact_url(asset, target.lower())
                if url:
                    break
                time.sleep(max(1, int(poll_seconds)))
            else:
                raise Douyin3DError(f"Timed out converting asset {asset_id} to {target}.")
        return url, target.lower(), asset_id, json.dumps(asset, ensure_ascii=False)


class Douyin3DGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "supplier": (list(_SUPPLIER_IDS), {"default": "Douyin3D"}),
                "model_profile": (_MODEL_PROFILES, {"default": "推荐（随供应商）"}),
                "quality_preset": (["快速预览", "标准", "高质量", "超高质量", "自定义"], {"default": "标准"}),
                "prompt": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "可选兜底提示词；连接 prompt_input 后优先使用连线内容。",
                }),
                "cas_session": ("STRING", {
                    "default": "", "password": True,
                    "tooltip": "AGW_CAS_SESSION 的值；会随工作流保存，请勿分享或发布。",
                }),
                "geometry_quality": (["low", "middle", "high", "ultra"], {"default": "high"}),
                "texture_quality": (["low", "middle", "high", "ultra"], {"default": "high"}),
                "faces": ("INT", {
                    "default": 300000, "min": 100, "max": 1000000, "step": 100,
                    "tooltip": "面数上限；Tripo v3.1 官方支持从 100 起，5000 会原样传递。",
                }),
                "texture_size": ([1024, 2048, 4096], {"default": 2048}),
                "enable_pbr": ("BOOLEAN", {"default": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 65535}),
                "poly_style": (["不选风格", "低模玩具", "黏土手办", "机械积木"], {"default": "不选风格"}),
                "timeout_minutes": ("INT", {"default": 20, "min": 1, "max": 60}),
                "poll_seconds": ("INT", {"default": 10, "min": 2, "max": 60}),
            },
            "optional": {
                "prompt_input": ("STRING", {"forceInput": True}),
                "image": ("IMAGE",),
                "image_url": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("glb_path", "glb_url", "asset_id", "status_json")
    FUNCTION = "generate"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = (
        "选择 AI Studio 供应商与质量参数，生成 3D 并将 GLB 下载到 ComfyUI output/douyin3d。"
        "cas_session 会随工作流保存，请勿分享或发布含凭证的工作流。"
    )

    def generate(
        self,
        supplier: str,
        model_profile: str,
        quality_preset: str,
        prompt: str,
        cas_session: str = "",
        geometry_quality: str = "high",
        texture_quality: str = "high",
        faces: int = 300000,
        texture_size: int = 2048,
        enable_pbr: bool = True,
        seed: int = 0,
        poly_style: str = "不选风格",
        timeout_minutes: int = 20,
        poll_seconds: int = 10,
        image: Any = None,
        image_url: str = "",
        prompt_input: str = "",
    ):
        prompt = (prompt_input or prompt).strip()
        image_url = image_url.strip()
        vendor = _SUPPLIER_IDS.get(supplier)
        if not vendor:
            raise Douyin3DError(f"Unknown supplier: {supplier}")
        if vendor == "module" and (image is not None or image_url):
            raise Douyin3DError("Poly3D currently supports text-to-3D only in this node.")
        if image is not None:
            image_url = _upload_comfy_image(image, cas_session=cas_session)
        if not prompt and not image_url:
            raise Douyin3DError("Provide prompt or image.")
        source_type = "image" if image_url else "prompt"
        vendor_fields, meta = _build_vendor_fields(
            vendor, model_profile, quality_preset, geometry_quality, texture_quality,
            faces, texture_size, enable_pbr, seed, poly_style,
        )
        response = _post("/api/v1/assets/generate", {
            "project_id": 0,
            "vendor": vendor,
            "source_type": source_type,
            "prompt": prompt,
            "image_url": image_url,
            "description": prompt or "ByteArtist image-to-3D",
            "meta": json.dumps(meta, ensure_ascii=False),
            **vendor_fields,
        }, cas_session=cas_session)
        asset_id = _asset_id(response)
        deadline = time.monotonic() + max(1, int(timeout_minutes)) * 60
        asset: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            status_data = _post("/api/v1/assets/status", {
                "project_id": 0,
                "asset_ids": [asset_id],
                "include_deleted": False,
            }, cas_session=cas_session)
            asset = _extract_asset(status_data)
            if asset:
                status = str(asset.get("status", "")).lower()
                if status in _TERMINAL_SUCCESS and int(asset.get("progress", 100)) >= 100:
                    break
                if status in _TERMINAL_FAILURE:
                    raise Douyin3DError(f"Asset {asset_id} failed: {json.dumps(asset, ensure_ascii=False)[:1200]}")
            time.sleep(max(2, int(poll_seconds)))
        else:
            raise Douyin3DError(f"Timed out waiting for asset {asset_id}.")
        detail = _post(
            "/api/v1/assets/detail", {"asset_id": asset_id}, cas_session=cas_session
        )
        asset = _extract_asset(detail) or asset or {}
        url = _artifact_url(asset)
        if not url:
            raise Douyin3DError(f"Asset {asset_id} completed without a GLB URL.")
        path = download_glb(url, asset_id)
        return _preview_path(path), url, asset_id, json.dumps(asset, ensure_ascii=False)
