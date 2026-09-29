"""Browser turntable GIF maker for GLB files saved in ComfyUI output."""
from __future__ import annotations

import html
from urllib.parse import parse_qs, quote, urlencode

from .glb_viewer import FangGLBViewerError, resolve_output_glb


def turntable_route(model_file: str, size: int, frames: int, fps: int,
                    elevation: int, background: str, direction: str) -> str:
    _, relative = resolve_output_glb(model_file)
    query = urlencode({
        "model": relative,
        "size": max(128, min(1024, int(size))),
        "frames": max(12, min(120, int(frames))),
        "fps": max(1, min(30, int(fps))),
        "elevation": max(0, min(90, int(elevation))),
        "background": background,
        "direction": direction,
    })
    return f"/fang/turntable-gif?{query}"


class GLBTurntableGIF:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model_path": ("STRING", {"default": "douyin3d/model.glb", "forceInput": True}),
            "size": ([256, 384, 512, 768], {"default": 512}),
            "frames": ("INT", {"default": 36, "min": 12, "max": 120, "step": 1}),
            "fps": ("INT", {"default": 12, "min": 1, "max": 30, "step": 1}),
            "camera_elevation": ("INT", {"default": 75, "min": 0, "max": 90, "step": 1}),
            "background": (["透明", "白色", "黑色", "灰色"], {"default": "透明"}),
            "direction": (["顺时针", "逆时针"], {"default": "顺时针"}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("gif_maker_url", "model_path")
    FUNCTION = "make"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = "在浏览器中把 GLB 渲染为360°旋转 GIF；不会重新生成3D模型。"

    def make(self, model_path: str, size: int, frames: int, fps: int,
             camera_elevation: int, background: str, direction: str):
        route = turntable_route(model_path, size, frames, fps, camera_elevation,
                                background, direction)
        _, relative = resolve_output_glb(model_path)
        return {"ui": {"gif_maker_url": [route]}, "result": (route, relative)}


def _maker_html(params: dict[str, str]) -> str:
    relative = params["model"]
    size = int(params["size"])
    frames = int(params["frames"])
    fps = int(params["fps"])
    elevation = int(params["elevation"])
    background = params["background"]
    direction = params["direction"]
    model_url = f"/fang/glb-file?model={quote(relative, safe='')}"
    title = html.escape(relative.rsplit("/", 1)[-1])
    color = {"透明": "transparent", "白色": "#ffffff", "黑色": "#000000", "灰色": "#808080"}.get(background, "transparent")
    transparent = "true" if background == "透明" else "false"
    sign = -1 if direction == "顺时针" else 1
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 360 GIF</title>
<script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#111318;color:#f5f7ff;font-family:Inter,-apple-system,sans-serif;display:grid;place-items:center;min-height:100vh}}
.card{{width:min(92vw,760px);padding:20px;border:1px solid #ffffff20;border-radius:16px;background:#1b1e25;box-shadow:0 18px 60px #0008}}
model-viewer{{display:block;width:min(80vw,{size}px);height:min(80vw,{size}px);margin:auto;background:{color};border-radius:12px}}
.row{{display:flex;align-items:center;gap:12px;margin-top:16px}} button{{padding:10px 16px;border:0;border-radius:9px;background:#5577ff;color:white;font-weight:600;cursor:pointer}} button:disabled{{opacity:.45}} progress{{flex:1}} .meta{{font-size:13px;color:#aeb4c2;margin:8px 0 14px}}
</style></head><body><div class="card"><strong>{title}</strong><div class="meta">{frames}帧 · {fps} FPS · {size}×{size} · {html.escape(background)} · {html.escape(direction)}</div>
<model-viewer id="viewer" src="{html.escape(model_url, quote=True)}" camera-controls interaction-prompt="none" shadow-intensity="1" exposure="1" environment-image="neutral" camera-orbit="0deg {elevation}deg auto"></model-viewer>
<div class="row"><button id="make" disabled>生成并下载 GIF</button><progress id="progress" value="0" max="{frames}"></progress><span id="status">加载模型…</span></div></div>
<script type="module">
import {{ GIFEncoder, quantize, applyPalette }} from 'https://esm.sh/gifenc@1.0.3';
const viewer=document.getElementById('viewer'), button=document.getElementById('make'), progress=document.getElementById('progress'), status=document.getElementById('status');
viewer.addEventListener('load',()=>{{button.disabled=false;status.textContent='准备就绪';}});
viewer.addEventListener('error',()=>{{status.textContent='GLB 加载失败';}});
const waitFrame=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
button.onclick=async()=>{{
 button.disabled=true; const gif=GIFEncoder(); const delay=Math.round(1000/{fps});
 try{{
  for(let i=0;i<{frames};i++){{
   viewer.cameraOrbit=`${{{sign}*i*360/{frames}}}deg {elevation}deg auto`; await waitFrame();
   const blob=await viewer.toBlob({{idealAspect:true}}); const bitmap=await createImageBitmap(blob);
   const canvas=document.createElement('canvas'); canvas.width={size}; canvas.height={size}; const ctx=canvas.getContext('2d',{{willReadFrequently:true}});
   {'ctx.clearRect(0,0,canvas.width,canvas.height);' if transparent == 'true' else f"ctx.fillStyle='{color}';ctx.fillRect(0,0,canvas.width,canvas.height);"}
   ctx.drawImage(bitmap,0,0,{size},{size}); bitmap.close(); const rgba=ctx.getImageData(0,0,{size},{size}).data;
   const palette=quantize(rgba,256); const index=applyPalette(rgba,palette);
   gif.writeFrame(index,{size},{size},{{palette,delay,repeat:0}}); progress.value=i+1; status.textContent=`${{i+1}}/{frames}`;
  }}
  gif.finish(); const output=new Blob([gif.bytesView()],{{type:'image/gif'}}); const url=URL.createObjectURL(output); const a=document.createElement('a');
  a.href=url;a.download='{html.escape(title.rsplit('.',1)[0])}_turntable.gif';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);status.textContent='GIF 已下载';
 }}catch(error){{console.error(error);status.textContent='生成失败：'+(error?.message||error);}} finally{{button.disabled=false;}}
}};
</script></body></html>"""


def register_routes() -> bool:
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return False

    @PromptServer.instance.routes.get("/fang/turntable-gif")
    async def turntable_gif(request):
        try:
            params = {
                "model": request.query.get("model", ""),
                "size": str(max(128, min(1024, int(request.query.get("size", 512))))),
                "frames": str(max(12, min(120, int(request.query.get("frames", 36))))),
                "fps": str(max(1, min(30, int(request.query.get("fps", 12))))),
                "elevation": str(max(0, min(90, int(request.query.get("elevation", 75))))),
                "background": request.query.get("background", "透明"),
                "direction": request.query.get("direction", "顺时针"),
            }
            resolve_output_glb(params["model"])
        except (FangGLBViewerError, ValueError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.Response(text=_maker_html(params), content_type="text/html", charset="utf-8")
    return True


register_routes()
