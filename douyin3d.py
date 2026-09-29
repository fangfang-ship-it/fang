"""ComfyUI nodes for AI Studio image-to-3D generation and model saving."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_API_BASE = "https://3d.bytedance.net"
_SUCCESS = {"success", "succeeded", "done", "completed"}
_FAILURE = {"failed", "error", "canceled", "cancelled"}
_FORMAT_IDS = {"GLB": 1, "FBX": 2, "OBJ": 3}
_SUPPLIERS = {
    "Douyin3D": "douyin3d", "混元3D": "hunyuan3d", "Poly3D": "module",
    "Rodin": "rodin", "Seed3D": "seed3d", "Tripo3D": "tripo3d",
}
_MODEL_PROFILES = [
    "推荐（随供应商）", "Douyin V3.1-fast", "Douyin V3.1",
    "混元 3.0", "混元 3.1", "混元 Express", "Rodin Gen-1", "Rodin Gen-2",
    "Rodin Gen-2.5", "Seed3D 2.0", "Tripo v3.1", "Tripo v3.0", "Tripo v2.5",
    "Tripo P1", "Tripo P2 Preview",
]
_GENERATION_CACHE: dict[str, tuple[dict[str, Any], int, str]] = {}


class Douyin3DError(RuntimeError):
    pass


def _ticket() -> str:
    value = int(time.time()) + 1_234_567_890
    return base64.b64encode(str(value).encode("ascii")).decode("ascii")


def _cookie_headers(cookies: str = "") -> dict[str, str]:
    """Accept either a full Cookie string or a bare AGW_CAS_SESSION value."""
    value = cookies.strip() or os.environ.get("DOUYIN3D_COOKIES", "").strip()
    if not value:
        value = os.environ.get("DOUYIN3D_CAS_SESSION", "").strip()
    if value:
        if "\r" in value or "\n" in value:
            raise Douyin3DError("Cookie 中不能包含换行符。")
        if value.lower().startswith("cookie:"):
            value = value.split(":", 1)[1].strip()
        if "=" not in value:
            value = f"AGW_CAS_SESSION={value}"
        return {"Cookie": value}

    key = os.environ.get("DOUYIN3D_API_KEY", "").strip()
    if key:
        header = os.environ.get("DOUYIN3D_AUTH_HEADER", "Authorization").strip()
        scheme = os.environ.get("DOUYIN3D_AUTH_SCHEME", "Bearer").strip()
        return {header: f"{scheme} {key}".strip()}
    raise Douyin3DError(
        "请在 cookies 中粘贴 3d.bytedance.net 的 Cookie，或设置 DOUYIN3D_COOKIES。"
    )


# Backward compatibility for previous tests/workflows.
def _auth_headers(cas_session: str = "") -> dict[str, str]:
    return _cookie_headers(cas_session)


def _request(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    cookies: str = "",
    timeout: float = 60,
    method: str = "POST",
    allowed_codes: tuple[int | str, ...] = (),
) -> dict[str, Any]:
    headers = {"Accept": "application/json", **_cookie_headers(cookies)}
    data = None
    if payload is not None:
        payload = dict(payload)
        if method == "POST" and any(x in path for x in ("generate", "upload", "convert")):
            payload.setdefault("ticket", _ticket())
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(f"{_API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in (401, 403):
            raise Douyin3DError("鉴权失败：Cookie 已过期或无 AI Studio 权限。") from exc
        raise Douyin3DError(f"AI Studio HTTP {exc.code}: {detail[:800]}") from exc
    except URLError as exc:
        raise Douyin3DError(f"无法连接 AI Studio：{exc.reason}") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise Douyin3DError(f"AI Studio 返回了非 JSON 内容：{body[:300]}") from exc
    base = result.get("base_resp") or {}
    code = base.get("code", 0)
    if code not in (0, "0", None, *allowed_codes):
        raise Douyin3DError(base.get("message") or f"AI Studio 接口错误：{code}")
    return result


def _post(path: str, payload: dict[str, Any], timeout: float = 60,
          cas_session: str = "", allowed_codes: tuple[int | str, ...] = ()) -> dict[str, Any]:
    return _request(path, payload, cookies=cas_session, timeout=timeout, allowed_codes=allowed_codes)


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _uploaded_url(data: dict[str, Any]) -> str:
    for item in _walk(data):
        if isinstance(item, dict):
            for key in ("url", "image_url", "download_url"):
                value = item.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
    raise Douyin3DError("图片上传成功，但响应中没有图片 URL。")


def _extract_asset(data: dict[str, Any]) -> dict[str, Any] | None:
    for item in _walk(data):
        if isinstance(item, dict) and "asset_id" in item:
            return item
    return None


def _asset_id(data: dict[str, Any]) -> int:
    asset = _extract_asset(data)
    if asset is not None:
        return int(asset["asset_id"])
    raise Douyin3DError(f"生成响应中没有 asset_id：{json.dumps(data, ensure_ascii=False)[:500]}")


def _artifact_url(asset: dict[str, Any], target_format: str = "") -> str:
    wanted = target_format.lower()
    for artifact in asset.get("artifacts") or []:
        fmt = str(artifact.get("format", "")).lower()
        status = str(artifact.get("status", "success")).lower()
        if artifact.get("url") and status == "success" and (not wanted or fmt == wanted):
            return str(artifact["url"])
    info = asset.get("info")
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except json.JSONDecodeError:
            info = {}
    if isinstance(info, dict) and wanted in ("", "glb"):
        return str(info.get("modelUrl") or info.get("model_url") or "")
    return ""


def _resolve_project_id(project_id: int, cookies: str) -> int:
    if int(project_id) > 0:
        return int(project_id)
    data = _request("/api/v1/projects/list", {"page_num": 1, "page_size": 100}, cookies=cookies)
    for item in _walk(data):
        if isinstance(item, dict) and item.get("project_id"):
            return int(item["project_id"])
    raise Douyin3DError("无法自动获取项目 ID，请在 project_id 中填写 AI Studio 项目 ID。")


def _upload_image(image: Any, cookies: str) -> str:
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise Douyin3DError("图片上传需要 ComfyUI 环境中的 NumPy 和 Pillow。") from exc
    if image is None or not hasattr(image, "detach"):
        raise Douyin3DError("image 必须连接 ComfyUI IMAGE 输出。")
    array = image.detach().to(device="cpu").float().numpy()
    if array.ndim != 4 or array.shape[0] < 1 or array.shape[-1] not in (3, 4):
        raise Douyin3DError(f"图片形状应为 [B,H,W,3|4]，实际为 {array.shape}。")
    pixels = (np.clip(array[0], 0, 1) * 255).round().astype(np.uint8)
    buffer = BytesIO()
    Image.fromarray(pixels, mode="RGBA" if pixels.shape[-1] == 4 else "RGB").save(buffer, "PNG")
    name = f"comfyui_{int(time.time() * 1000)}.png"
    return _uploaded_url(_request("/api/v1/files/upload", {
        "file_data": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "file_name": name,
        "custom_path": f"comfyui/douyin3d/{name}",
    }, cookies=cookies, timeout=120))


# Compatibility alias used by older code/tests.
def _upload_comfy_image(image: Any, cas_session: str = "") -> str:
    return _upload_image(image, cas_session)


def _douyin_params(model_version: str, geometry_quality: str, texture_quality: str,
                   texture_size: int, faces: int, generate_texture: bool,
                   enable_pbr: bool, delight_strength: str, split_model: bool,
                   quad_remesh: bool, geometry_seed: int, texture_seed: int) -> dict[str, Any]:
    quality = {"低": 0, "中": 1, "高": 2, "超高": 3}
    return {
        "style": 0,
        "model_version": {"V3.1": 0, "V3.1-fast": 1}[model_version],
        "gene_quality_geo": quality[geometry_quality],
        "gene_quality_tex": quality[texture_quality] if generate_texture else None,
        "uv_size": int(texture_size) if generate_texture else None,
        "faces_num": max(100, min(1_000_000, int(faces))),
        "enable_texture": bool(generate_texture),
        "enable_pbr": bool(enable_pbr) if generate_texture else False,
        "delight_strength": {"弱": 0, "强": 1}[delight_strength] if generate_texture else None,
        "output_format": "glb",
        "split_model": bool(split_model),
        "quad_remesh": bool(quad_remesh),
        "seed_geo": max(0, min(65535, int(geometry_seed))),
        "seed_tex": max(0, min(65535, int(texture_seed))) if generate_texture else None,
    }


def _vendor_params(supplier: str, model_profile: str, **values) -> tuple[str, dict[str, Any]]:
    vendor = _SUPPLIERS[supplier]
    if vendor == "douyin3d":
        version = "V3.1" if model_profile == "Douyin V3.1" else "V3.1-fast"
        return vendor, {"douyin3d_params": _douyin_params(model_version=version, **values)}
    quality = {"低": 0, "中": 1, "高": 2, "超高": 3}
    geo = quality[values["geometry_quality"]]
    tex = quality[values["texture_quality"]]
    faces = max(100, min(1_000_000, int(values["faces"])))
    seed_geo = max(0, min(65535, int(values["geometry_seed"])))
    seed_tex = max(0, min(65535, int(values["texture_seed"])))
    pbr = bool(values["enable_pbr"] and values["generate_texture"])
    if vendor == "tripo3d":
        models = {"Tripo P1": 0, "Tripo v3.1": 2, "Tripo v3.0": 3,
                  "Tripo v2.5": 4, "Tripo P2 Preview": 5}
        params = {"model_version": models.get(model_profile, 2),
                  "geometry_quality": 1 if geo >= 2 else 0,
                  "texture_quality": 2 if tex >= 3 else (1 if tex >= 2 else 0),
                  "face_limit": faces, "orientation": 0, "texture_alignment": 0,
                  "texture": bool(values["generate_texture"]), "pbr": pbr,
                  "quad": bool(values["quad_remesh"]), "smart_low_poly": geo == 0,
                  "generate_parts": bool(values["split_model"]), "export_uv": True,
                  "auto_size": False, "model_seed": seed_geo, "texture_seed": seed_tex}
        return vendor, {"tripo_params": params}
    if vendor == "hunyuan3d":
        model = {"混元 3.0": 0, "混元 3.1": 1, "混元 Express": 2}.get(model_profile, 0)
        params = {"model": model, "enable_pbr": pbr}
        params.update({"result_format": 1, "enable_geometry": True} if model == 2
                      else {"face_count": faces, "generate_type": 0})
        return vendor, {"hunyuan3d_params": params}
    if vendor == "rodin":
        tier = {"Rodin Gen-1": 0, "Rodin Gen-2": 4, "Rodin Gen-2.5": 7}.get(model_profile, 7)
        return vendor, {"rodin_params": {"tier": tier, "geometry_file_format": 0,
                                          "seed": seed_geo, "material": 0, "mesh_mode": 1}}
    if vendor == "seed3d":
        return vendor, {"seed3d_params": {"fileformat": 0, "subdivisionlevel": min(2, geo)}}
    if vendor == "module":
        return vendor, {"meta": "{}"}
    raise Douyin3DError(f"不支持的供应商：{supplier}")


def _generation_key(image: Any, values: tuple[Any, ...]) -> str:
    """Create a stable key so downstream format changes never regenerate the model."""
    try:
        array = image.detach().to(device="cpu").numpy()
        image_digest = hashlib.sha256(array.tobytes()).hexdigest()
    except Exception:
        image_digest = str(id(image))
    encoded = json.dumps([image_digest, *values], ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _wait_for_asset(asset_id: int, project_id: int, cookies: str,
                    timeout_minutes: int, poll_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, int(timeout_minutes)) * 60
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        data = _request("/api/v1/assets/status", {
            "project_id": project_id,
            "asset_ids": [asset_id],
            "include_deleted": False,
        }, cookies=cookies)
        latest = _extract_asset(data) or latest
        status = str(latest.get("status", "")).lower()
        if status in _FAILURE:
            raise Douyin3DError(f"资产 {asset_id} 生成失败：{json.dumps(latest, ensure_ascii=False)[:1000]}")
        if status in _SUCCESS and int(latest.get("progress", 100)) >= 100:
            return latest
        time.sleep(max(2, int(poll_seconds)))
    raise Douyin3DError(f"等待资产 {asset_id} 超时。")


def _output_directory(subfolder: str = "douyin3d") -> Path:
    try:
        import folder_paths
        root = Path(folder_paths.get_output_directory())
    except ImportError:
        root = Path.cwd() / "output"
    target = root / subfolder
    target.mkdir(parents=True, exist_ok=True)
    return target


def _safe_prefix(value: str) -> str:
    value = Path(value.strip()).name
    value = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", value, flags=re.UNICODE).strip("._")
    return value or "douyin3d"


def _download(url: str, target: Path, cookies: str = "", timeout: float = 180) -> Path:
    headers = {"Accept": "*/*"}
    if url.startswith(_API_BASE):
        headers.update(_cookie_headers(cookies))
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response, target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except (HTTPError, URLError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise Douyin3DError(f"下载模型失败：{exc}") from exc
    if not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise Douyin3DError("下载结果为空。")
    return target


def download_glb(url: str, asset_id: int, timeout: float = 120) -> Path:
    target = _output_directory() / f"douyin3d_{asset_id}.glb"
    _download(url, target, timeout=timeout)
    with target.open("rb") as stream:
        if stream.read(4) != b"glTF":
            target.unlink(missing_ok=True)
            raise Douyin3DError("下载结果不是有效 GLB。")
    return target


class Douyin3DGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "cookies": ("STRING", {"default": "", "multiline": True, "password": True,
                "tooltip": "粘贴 3d.bytedance.net 的完整 Cookie；不要分享含 Cookie 的工作流。"}),
            "asset_name": ("STRING", {"default": "ComfyUI image-to-3D"}),
            "supplier": (list(_SUPPLIERS), {"default": "Douyin3D"}),
            "model_profile": (_MODEL_PROFILES, {"default": "推荐（随供应商）"}),
            "geometry_quality": (["低", "中", "高", "超高"], {"default": "高"}),
            "texture_quality": (["低", "中", "高", "超高"], {"default": "高"}),
            "texture_size": ([1024, 2048, 4096], {"default": 2048}),
            "faces": ("INT", {"default": 500000, "min": 100, "max": 1000000, "step": 100}),
            "generate_texture": ("BOOLEAN", {"default": True}),
            "enable_pbr": ("BOOLEAN", {"default": True}),
            "delight_strength": (["弱", "强"], {"default": "弱"}),
            "split_model": ("BOOLEAN", {"default": False}),
            "quad_remesh": ("BOOLEAN", {"default": False}),
            "geometry_seed": ("INT", {"default": 0, "min": 0, "max": 65535}),
            "texture_seed": ("INT", {"default": 0, "min": 0, "max": 65535}),
            "force_regenerate": ("BOOLEAN", {"default": False,
                "tooltip": "关闭时复用同图同参数的上次资产；需要重新生成时开启。"}),
            "timeout_minutes": ("INT", {"default": 30, "min": 1, "max": 90}),
            "poll_seconds": ("INT", {"default": 10, "min": 2, "max": 60}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("saved_glb_path", "download_glb_url")
    FUNCTION = "generate"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = "使用 AI Studio 将输入图片生成 3D，并直接保存 GLB、提供本机下载按钮。"

    def generate(self, image: Any, cookies: str, asset_name: str,
                 supplier: str, model_profile: str, geometry_quality: str, texture_quality: str,
                 texture_size: int, faces: int, generate_texture: bool, enable_pbr: bool,
                 delight_strength: str, split_model: bool, quad_remesh: bool,
                 geometry_seed: int, texture_seed: int, force_regenerate: bool,
                 timeout_minutes: int, poll_seconds: int):
        cache_key = _generation_key(image, (
            asset_name, supplier, model_profile, geometry_quality,
            texture_quality, texture_size, faces, generate_texture, enable_pbr,
            delight_strength, split_model, quad_remesh, geometry_seed, texture_seed,
        ))
        if not force_regenerate and cache_key in _GENERATION_CACHE:
            return _GENERATION_CACHE[cache_key]
        project_id = _resolve_project_id(0, cookies)
        image_url = _upload_image(image, cookies)
        vendor, vendor_fields = _vendor_params(
            supplier, model_profile,
            geometry_quality=geometry_quality, texture_quality=texture_quality,
            texture_size=texture_size, faces=faces, generate_texture=generate_texture,
            enable_pbr=enable_pbr, delight_strength=delight_strength,
            split_model=split_model, quad_remesh=quad_remesh,
            geometry_seed=geometry_seed, texture_seed=texture_seed,
        )
        response = _request("/api/v1/assets/generate", {
            "project_id": project_id,
            "vendor": vendor,
            "source_type": "image",
            "prompt": "",
            "image_url": image_url,
            "description": asset_name.strip() or "ComfyUI image-to-3D",
            "meta": vendor_fields.pop("meta", "{}"),
            **vendor_fields,
        }, cookies=cookies)
        asset_id = _asset_id(response)
        asset = _wait_for_asset(asset_id, project_id, cookies, timeout_minutes, poll_seconds)
        detail = _request("/api/v1/assets/detail", {"asset_id": asset_id}, cookies=cookies)
        asset = _extract_asset(detail) or asset
        glb_url = _artifact_url(asset, "glb")
        if not glb_url:
            raise Douyin3DError(f"资产 {asset_id} 已完成，但没有可下载的 GLB。")
        output = _output_directory() / f"{_safe_prefix(asset_name)}_{asset_id}.glb"
        _download(glb_url, output, cookies=cookies)
        relative = f"douyin3d/{output.name}"
        local_download_url = f"/fang/download-model?model={quote(relative, safe='')}"
        result = {
            "ui": {
                "saved_glb_path": [relative],
                "download_glb_url": [glb_url],
                "local_download_url": [local_download_url],
            },
            "result": (relative, glb_url),
        }
        _GENERATION_CACHE[cache_key] = result
        return result


class Douyin3DSaveModel:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "asset": ("DOUYIN3D_ASSET",),
            "format": (list(_FORMAT_IDS), {"default": "GLB"}),
            "filename_prefix": ("STRING", {"default": "douyin3d"}),
            "timeout_minutes": ("INT", {"default": 10, "min": 1, "max": 30}),
            "poll_seconds": ("INT", {"default": 3, "min": 1, "max": 10}),
        }}

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("saved_path", "download_url", "asset_id")
    FUNCTION = "save"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = "保存上游生成结果；可选择 GLB、FBX 或 OBJ，缺少格式时自动请求转换。"

    def save(self, asset: dict[str, Any], format: str, filename_prefix: str,
             timeout_minutes: int, poll_seconds: int):
        target_format = format.upper()
        asset_id = int(asset["asset_id"])
        cookies = str(asset.get("cookies", ""))
        detail = _request("/api/v1/assets/detail", {"asset_id": asset_id}, cookies=cookies)
        current = _extract_asset(detail) or asset.get("asset") or {}
        url = _artifact_url(current, target_format)
        if not url:
            _request("/api/v1/assets/convert", {
                "asset_id": asset_id,
                "target_format": _FORMAT_IDS[target_format],
                "content_type": 0,
            }, cookies=cookies, allowed_codes=(10005, "10005"))
            deadline = time.monotonic() + max(1, int(timeout_minutes)) * 60
            while time.monotonic() < deadline:
                detail = _request("/api/v1/assets/detail", {"asset_id": asset_id}, cookies=cookies)
                current = _extract_asset(detail) or current
                url = _artifact_url(current, target_format)
                if url:
                    break
                time.sleep(max(1, int(poll_seconds)))
            else:
                raise Douyin3DError(f"等待 {target_format} 转换超时。")
        prefix = _safe_prefix(filename_prefix)
        output = _output_directory() / f"{prefix}_{asset_id}.{target_format.lower()}"
        _download(url, output, cookies=cookies)
        relative = f"douyin3d/{output.name}"
        local_download_url = f"/fang/download-model?model={quote(relative, safe='')}"
        return {
            "ui": {"local_download_url": [local_download_url], "saved_path": [relative]},
            "result": (relative, url, asset_id),
        }


# Legacy aliases retained so old workflows at least load; new workflows should use the two nodes above.
Douyin3DDownloadAsset = Douyin3DSaveModel


class Douyin3DDownloadGLB:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"glb_url": ("STRING", {"default": ""}), "asset_id": ("INT", {"default": 1, "min": 1})}}
    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("glb_path", "glb_url", "asset_id")
    FUNCTION = "download"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True

    def download(self, glb_url: str, asset_id: int):
        if not glb_url.strip().startswith(("http://", "https://")):
            raise Douyin3DError("glb_url 必须是 HTTP(S) URL。")
        path = download_glb(glb_url.strip(), int(asset_id))
        return f"douyin3d/{path.name}", glb_url.strip(), int(asset_id)
