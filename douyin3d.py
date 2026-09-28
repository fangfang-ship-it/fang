"""Douyin3D generation nodes for ComfyUI.

Credentials are read from environment variables and are never stored in workflow JSON.
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


def _auth_headers() -> dict[str, str]:
    key = os.environ.get("DOUYIN3D_API_KEY", "").strip()
    if not key:
        raise Douyin3DError(
            "DOUYIN3D_API_KEY is not configured. Inject it into the ByteArtist "
            "runtime; do not put credentials in the workflow or Git repository."
        )
    header = os.environ.get("DOUYIN3D_AUTH_HEADER", "Authorization").strip()
    scheme = os.environ.get("DOUYIN3D_AUTH_SCHEME", "Bearer").strip()
    value = f"{scheme} {key}".strip() if scheme else key
    return {header: value}


def _post(path: str, payload: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
    payload = dict(payload)
    if any(word in path for word in ("generate", "upload", "create", "update")):
        payload.setdefault("ticket", _ticket())
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update(_auth_headers())
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
    if base_resp.get("code", 0) not in (0, "0", None):
        raise Douyin3DError(base_resp.get("message") or f"API error: {base_resp}")
    return data


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


def _artifact_url(asset: dict[str, Any]) -> str:
    for artifact in asset.get("artifacts") or []:
        if artifact.get("primary") and artifact.get("url"):
            return artifact["url"]
    for artifact in asset.get("artifacts") or []:
        if artifact.get("url"):
            return artifact["url"]
    info = asset.get("info")
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except json.JSONDecodeError:
            info = {}
    if isinstance(info, dict):
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
    return target


class Douyin3DGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"default": "一个白色陶瓷马克杯，完整单体，纯色背景，无文字", "multiline": True}),
                "model_version": (["V3.1-fast", "V3.1"], {"default": "V3.1-fast"}),
                "geometry_quality": (["low", "middle", "high", "ultra"], {"default": "high"}),
                "texture_quality": (["low", "middle", "high", "ultra"], {"default": "high"}),
                "faces": ("INT", {"default": 500000, "min": 10000, "max": 1000000, "step": 10000}),
                "texture_size": ([1024, 2048, 4096], {"default": 2048}),
                "enable_pbr": ("BOOLEAN", {"default": True}),
                "timeout_minutes": ("INT", {"default": 20, "min": 1, "max": 60}),
                "poll_seconds": ("INT", {"default": 10, "min": 2, "max": 60}),
            },
            "optional": {
                "image_url": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("glb_path", "glb_url", "asset_id", "status_json")
    FUNCTION = "generate"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = "调用 Douyin3D，轮询至完成并将 GLB 下载到 ComfyUI output/douyin3d。"

    def generate(
        self,
        prompt: str,
        model_version: str = "V3.1-fast",
        geometry_quality: str = "high",
        texture_quality: str = "high",
        faces: int = 500000,
        texture_size: int = 2048,
        enable_pbr: bool = True,
        timeout_minutes: int = 20,
        poll_seconds: int = 10,
        image_url: str = "",
    ):
        prompt = prompt.strip()
        image_url = image_url.strip()
        if not prompt and not image_url:
            raise Douyin3DError("Provide prompt or image_url.")
        source_type = "image" if image_url else "prompt"
        params = {
            "Style": "gagas",
            "ModelVersion": model_version,
            "GeneQualityGeo": geometry_quality,
            "GeneQualityTex": texture_quality,
            "FacesNum": int(faces),
            "UVSize": int(texture_size),
            "EnableTexture": True,
            "DelightStrength": "weak",
            "EnablePbr": bool(enable_pbr),
            "SeedGeo": 0,
            "SeedTex": 0,
            "OutputFormat": "glb",
            "SplitModel": False,
            "QuadRemesh": False,
        }
        response = _post("/api/v1/assets/generate", {
            "project_id": 0,
            "vendor": "douyin3d",
            "source_type": source_type,
            "prompt": prompt,
            "image_url": image_url,
            "description": prompt or "ByteArtist image-to-3D",
            "douyin3d_params": params,
        })
        asset_id = _asset_id(response)
        deadline = time.monotonic() + max(1, int(timeout_minutes)) * 60
        asset: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            status_data = _post("/api/v1/assets/status", {
                "project_id": 0,
                "asset_ids": [asset_id],
                "include_deleted": False,
            })
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
        detail = _post("/api/v1/assets/detail", {"asset_id": asset_id})
        asset = _extract_asset(detail) or asset or {}
        url = _artifact_url(asset)
        if not url:
            raise Douyin3DError(f"Asset {asset_id} completed without a GLB URL.")
        path = download_glb(url, asset_id)
        return str(path), url, asset_id, json.dumps(asset, ensure_ascii=False)
