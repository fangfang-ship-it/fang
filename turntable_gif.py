"""Render a GLB as a real 360-degree turntable GIF inside ComfyUI."""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from .glb_viewer import resolve_output_glb


class TurntableRenderError(RuntimeError):
    pass


def _output_root() -> Path:
    try:
        import folder_paths
        return Path(folder_paths.get_output_directory()).resolve()
    except ImportError:
        return (Path.cwd() / "output").resolve()


def _background_rgba(name: str) -> tuple[int, int, int, int]:
    return {
        "透明": (0, 0, 0, 0),
        "白色": (255, 255, 255, 255),
        "黑色": (0, 0, 0, 255),
        "灰色": (128, 128, 128, 255),
    }[name]


def _look_at(camera: Any, target: Any, np: Any) -> Any:
    forward = target - camera
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.array([0.0, 0.0, 1.0]))
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1.0, 0.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    pose = np.eye(4)
    pose[:3, 0] = right
    pose[:3, 1] = up
    pose[:3, 2] = -forward
    pose[:3, 3] = camera
    return pose


def render_turntable_gif(model_file: str, size: int, frames: int, fps: int,
                         elevation: int, background: str, direction: str,
                         filename_prefix: str) -> tuple[Path, list[Any]]:
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    try:
        import numpy as np
        # pyrender 0.1.45 still references the NumPy 1.x alias removed in NumPy 2.
        if not hasattr(np, "infty"):
            np.infty = np.inf
        import pyrender
        import trimesh
        from PIL import Image
    except ImportError as exc:
        raise TurntableRenderError(
            "缺少360 GIF渲染依赖，请重新安装插件并重启房间，使 requirements.txt 生效。"
        ) from exc

    source, _ = resolve_output_glb(model_file)
    try:
        loaded = trimesh.load(source, force="scene", process=False)
        if isinstance(loaded, trimesh.Trimesh):
            loaded = trimesh.Scene(loaded)
        bounds = loaded.bounds
        if bounds is None:
            raise ValueError("模型没有有效几何体")
        center = bounds.mean(axis=0)
        extent = float(np.max(bounds[1] - bounds[0]))
        if not np.isfinite(extent) or extent <= 0:
            raise ValueError("模型尺寸无效")

        scene = pyrender.Scene(
            bg_color=np.array(_background_rgba(background), dtype=np.float32) / 255.0,
            ambient_light=np.array([0.45, 0.45, 0.45, 1.0]),
        )
        for node_name in loaded.graph.nodes_geometry:
            transform, geometry_name = loaded.graph.get(node_name)
            geometry = loaded.geometry[geometry_name]
            scene.add(pyrender.Mesh.from_trimesh(geometry, smooth=False), pose=transform)

        yfov = math.radians(35.0)
        camera = pyrender.PerspectiveCamera(yfov=yfov, znear=max(extent / 10000, 0.001), zfar=extent * 100)
        distance = extent / (2 * math.tan(yfov / 2)) * 1.35
        camera_node = scene.add(camera, pose=np.eye(4))
        key = pyrender.DirectionalLight(color=np.ones(3), intensity=3.2)
        fill = pyrender.DirectionalLight(color=np.ones(3), intensity=1.8)
        key_node = scene.add(key, pose=np.eye(4))
        fill_node = scene.add(fill, pose=np.eye(4))
        renderer = pyrender.OffscreenRenderer(viewport_width=size, viewport_height=size)

        images: list[Image.Image] = []
        elevation_radians = math.radians(elevation)
        sign = -1 if direction == "顺时针" else 1
        flags = pyrender.RenderFlags.RGBA | pyrender.RenderFlags.SHADOWS_DIRECTIONAL
        try:
            for index in range(frames):
                angle = sign * 2 * math.pi * index / frames
                horizontal = distance * math.sin(elevation_radians)
                position = center + np.array([
                    horizontal * math.cos(angle),
                    horizontal * math.sin(angle),
                    distance * math.cos(elevation_radians),
                ])
                pose = _look_at(position, center, np)
                scene.set_pose(camera_node, pose)
                scene.set_pose(key_node, pose)
                opposite = center + (center - position)
                scene.set_pose(fill_node, _look_at(opposite, center, np))
                color, _ = renderer.render(scene, flags=flags)
                image = Image.fromarray(color, mode="RGBA")
                if background != "透明":
                    canvas = Image.new("RGBA", image.size, _background_rgba(background))
                    canvas.alpha_composite(image)
                    image = canvas.convert("RGB")
                images.append(image)
        finally:
            renderer.delete()
    except TurntableRenderError:
        raise
    except Exception as exc:
        raise TurntableRenderError(f"GLB旋转GIF渲染失败：{exc}") from exc

    prefix = Path(filename_prefix.strip()).name or source.stem
    prefix = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in prefix).strip("_") or "turntable"
    output_dir = _output_root() / "douyin3d"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{prefix}_turntable.gif"
    duration = max(1, round(1000 / fps))
    images[0].save(
        target,
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=0,
        disposal=2,
        optimize=False,
        transparency=0 if background == "透明" else None,
    )
    return target, images


class GLBTurntableGIF:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model_path": ("STRING", {"default": "douyin3d/model.glb", "forceInput": True}),
            "size": ([256, 384, 512, 768], {"default": 512}),
            "frames": ("INT", {"default": 36, "min": 12, "max": 120, "step": 1}),
            "fps": ("INT", {"default": 12, "min": 1, "max": 30, "step": 1}),
            "camera_elevation": ("INT", {"default": 75, "min": 5, "max": 85, "step": 1}),
            "background": (["透明", "白色", "黑色", "灰色"], {"default": "透明"}),
            "direction": (["顺时针", "逆时针"], {"default": "顺时针"}),
            "filename_prefix": ("STRING", {"default": "douyin3d"}),
        }}

    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("gif_path", "frames")
    FUNCTION = "render"
    CATEGORY = "Fang/3D"
    OUTPUT_NODE = True
    DESCRIPTION = "直接渲染并保存360°旋转GIF，输出GIF路径和帧序列。"

    def render(self, model_path: str, size: int, frames: int, fps: int,
               camera_elevation: int, background: str, direction: str,
               filename_prefix: str):
        target, images = render_turntable_gif(
            model_path, int(size), int(frames), int(fps), int(camera_elevation),
            background, direction, filename_prefix,
        )
        try:
            import numpy as np
            import torch
            tensors = []
            for image in images:
                rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
                tensors.append(torch.from_numpy(rgb))
            batch = torch.stack(tensors)
        except ImportError as exc:
            raise TurntableRenderError("ComfyUI环境缺少NumPy或PyTorch。") from exc
        relative = target.relative_to(_output_root()).as_posix()
        return {
            "ui": {"images": [{"filename": target.name, "subfolder": "douyin3d", "type": "output"}]},
            "result": (relative, batch),
        }
