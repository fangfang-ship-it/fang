"""BA-compatible, browser-based GLB viewer for ComfyUI output models."""
from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import quote


class FangGLBViewerError(ValueError):
    """Raised when a requested model is outside ComfyUI output or invalid."""


def _output_root() -> Path:
    try:
        import folder_paths
        return Path(folder_paths.get_output_directory()).resolve()
    except ImportError:
        return (Path.cwd() / "output").resolve()


def resolve_output_glb(model_file: str) -> tuple[Path, str]:
    """Resolve a GLB while preventing traversal outside ComfyUI/output."""
    raw = (model_file or "").strip()
    if not raw:
        raise FangGLBViewerError("model_file is required.")
    root = _output_root()
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise FangGLBViewerError("model_file must be inside the ComfyUI output directory.") from exc
    if resolved.suffix.lower() != ".glb":
        raise FangGLBViewerError("Only .glb files are supported by this viewer.")
    if not resolved.is_file():
        raise FangGLBViewerError(f"GLB file does not exist: {relative.as_posix()}")
    return resolved, relative.as_posix()


def viewer_route(model_file: str) -> str:
    _, relative = resolve_output_glb(model_file)
    return f"/fang/glb-viewer?model={quote(relative, safe='')}"


class FangGLBWebViewer:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model_file": ("STRING", {
                "default": "douyin3d/douyin3d_5000565429.glb",
                "multiline": False,
                "tooltip": "连接 AI Studio 3D 节点的 glb_path，或填写 output 下的相对 GLB 路径。",
            }),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("viewer_url", "model_file")
    FUNCTION = "open_viewer"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = "在独立 WebGL 页面打开 GLB，支持旋转、缩放、平移、自动旋转和全屏。"

    def open_viewer(self, model_file: str):
        route = viewer_route(model_file)
        _, relative = resolve_output_glb(model_file)
        return {"ui": {"viewer_url": [route]}, "result": (route, relative)}


def _viewer_html(relative: str) -> str:
    title = html.escape(Path(relative).name)
    model_url = f"/fang/glb-file?model={quote(relative, safe='')}"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} · Fang GLB Viewer</title>
  <script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; overflow: hidden; background: #111318; color: #f6f7fb; }}
    model-viewer {{ width: 100vw; height: 100vh; background: radial-gradient(circle at 50% 35%, #3a3f4b 0, #1d2028 44%, #0d0f13 100%); }}
    .bar {{ position: fixed; z-index: 10; left: 18px; right: 18px; top: 18px; display: flex; align-items: center; gap: 8px; padding: 10px 12px; border: 1px solid #ffffff20; border-radius: 12px; background: #12151dcc; backdrop-filter: blur(12px); box-shadow: 0 8px 30px #0006; }}
    .name {{ min-width: 0; margin-right: auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: #d8dbe5; }}
    button, a {{ border: 1px solid #ffffff26; border-radius: 8px; padding: 7px 10px; color: #f5f7ff; background: #292e39; text-decoration: none; cursor: pointer; font-size: 12px; }}
    button:hover, a:hover {{ background: #3a4150; }}
    .help {{ position: fixed; z-index: 10; left: 18px; bottom: 18px; padding: 8px 11px; border-radius: 9px; background: #12151dcc; color: #c7cbd5; font-size: 12px; }}
    .error {{ position: fixed; inset: 0; z-index: 20; display: none; place-items: center; padding: 30px; background: #111318; color: #ffb4b4; text-align: center; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <model-viewer id="viewer" src="{html.escape(model_url, quote=True)}" camera-controls touch-action="pan-y" shadow-intensity="1" exposure="1" environment-image="neutral" interaction-prompt="auto" alt="{title}"></model-viewer>
  <div class="bar">
    <div class="name">{title}</div>
    <button id="rotate">自动旋转</button>
    <button id="reset">复位视角</button>
    <button id="bg">切换背景</button>
    <button id="full">全屏</button>
    <a href="{html.escape(model_url)}" download>下载 GLB</a>
  </div>
  <div class="help">左键旋转 · 滚轮缩放 · 右键/双指平移</div>
  <div id="error" class="error"></div>
  <script>
    const viewer = document.getElementById('viewer');
    const error = document.getElementById('error');
    document.getElementById('rotate').onclick = (event) => {{
      viewer.autoRotate = !viewer.autoRotate;
      event.currentTarget.textContent = viewer.autoRotate ? '停止旋转' : '自动旋转';
    }};
    document.getElementById('reset').onclick = () => {{ viewer.cameraOrbit = '0deg 75deg auto'; viewer.cameraTarget = 'auto auto auto'; viewer.fieldOfView = 'auto'; }};
    const backgrounds = [
      'radial-gradient(circle at 50% 35%, #3a3f4b 0, #1d2028 44%, #0d0f13 100%)',
      'linear-gradient(145deg, #f5f5f2, #cfd4dc)',
      'linear-gradient(145deg, #242424, #080808)'
    ];
    let backgroundIndex = 0;
    document.getElementById('bg').onclick = () => {{ backgroundIndex = (backgroundIndex + 1) % backgrounds.length; viewer.style.background = backgrounds[backgroundIndex]; }};
    document.getElementById('full').onclick = () => document.documentElement.requestFullscreen?.();
    viewer.addEventListener('error', (event) => {{ error.style.display = 'grid'; error.textContent = '模型加载失败。请确认 GLB 文件仍在 ComfyUI/output 中，并检查浏览器是否允许加载 model-viewer。\n' + (event.detail?.message || ''); }});
  </script>
</body>
</html>"""


def register_routes() -> bool:
    """Register viewer/model routes when running inside ComfyUI."""
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return False

    routes = PromptServer.instance.routes

    @routes.get("/fang/glb-file")
    async def glb_file(request):
        try:
            path, _ = resolve_output_glb(request.query.get("model", ""))
        except FangGLBViewerError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.FileResponse(path, headers={
            "Content-Type": "model/gltf-binary",
            "Content-Disposition": f'inline; filename="{path.name}"',
            "Cache-Control": "no-store",
        })

    @routes.get("/fang/glb-viewer")
    async def glb_viewer(request):
        try:
            _, relative = resolve_output_glb(request.query.get("model", ""))
        except FangGLBViewerError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.Response(text=_viewer_html(relative), content_type="text/html")

    return True


register_routes()
