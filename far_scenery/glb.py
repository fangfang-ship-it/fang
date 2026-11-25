"""Pack a transparent mountain texture and a terrain-centered mesh into GLB."""

import json
import math
import struct


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def texture_size(png):
    if (
        len(png) < 33
        or png[:8] != PNG_SIGNATURE
        or png[12:16] != b"IHDR"
        or png[25] not in (4, 6)
    ):
        raise ValueError("Use a PNG with an explicit alpha channel (RGBA or gray + alpha).")
    width, height = struct.unpack_from(">II", png, 16)
    if not width or not height:
        raise ValueError("The PNG dimensions must be positive.")
    return width, height


def build_glb(png, radius, angle, segments, base_y, window, name, *, yaw_degrees=None):
    texture_width, texture_height = texture_size(png)
    left, top, right, bottom = window or (0, 0, texture_width, texture_height)
    if not (0 <= left < right <= texture_width and 0 <= top < bottom <= texture_height):
        raise ValueError("The UV window must lie inside the texture.")
    span = math.radians(angle)
    height = radius * span * (bottom - top) / (right - left)

    positions = []
    normals = []
    texcoords = []
    indices = []
    for column in range(segments + 1):
        t = column / segments
        theta = (t - 0.5) * span
        x = radius * math.sin(theta)
        z = -radius * math.cos(theta)
        u = (left + t * (right - left)) / texture_width
        positions.extend(((x, base_y, z), (x, base_y + height, z)))
        normals.extend(((-math.sin(theta), 0, math.cos(theta)),) * 2)
        texcoords.extend(((u, bottom / texture_height), (u, top / texture_height)))
        if column < segments:
            first = column * 2
            indices.extend((first, first + 2, first + 1, first + 2, first + 3, first + 1))

    position_bytes = b"".join(struct.pack("<3f", *position) for position in positions)
    float32_positions = list(struct.iter_unpack("<3f", position_bytes))
    uv_bytes = b"".join(struct.pack("<2f", *uv) for uv in texcoords)
    normal_bytes = b"".join(struct.pack("<3f", *normal) for normal in normals)
    index_bytes = struct.pack(f"<{len(indices)}H", *indices)
    data = bytearray()
    views = []
    for payload, target in (
        (position_bytes, 34962), (uv_bytes, 34962), (index_bytes, 34963), (png, None),
        (normal_bytes, 34962)
    ):
        view = {"buffer": 0, "byteOffset": len(data), "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        views.append(view)
        data.extend(payload)
        data.extend(b"\x00" * (-len(data) % 4))

    materials = [{
        "name": name + " PBR Alpha",
        "pbrMetallicRoughness": {
            "baseColorFactor": [1, 1, 1, 1],
            "baseColorTexture": {"index": 0, "texCoord": 0},
            "metallicFactor": 0,
            "roughnessFactor": 1,
        },
        "alphaMode": "BLEND",
        "doubleSided": True,
    }]
    metadata = {
        "radiusMeters": radius, "spanDegrees": angle, "segments": segments,
        "baseMeters": base_y, "heightMeters": height,
        "textureSize": [texture_width, texture_height],
        "textureWindow": [left, top, right, bottom],
    }
    node = {"name": name, "mesh": 0, "extras": metadata}
    if yaw_degrees is not None:
        if not math.isfinite(yaw_degrees):
            raise ValueError("Yaw must be a finite number of degrees. / 旋转角须为有限数值。")
        half_yaw = math.radians(yaw_degrees % 360) / 2
        origin = [0.0, 0.0, 0.0]
        node["translation"] = origin
        node["rotation"] = [0.0, math.sin(half_yaw), 0.0, math.cos(half_yaw)]
        metadata.update({"originMeters": origin, "yawDegrees": float(yaw_degrees)})
    gltf = {
        "asset": {"version": "2.0", "generator": "ComfyUI-FarScenery"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [node],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1, "NORMAL": 3},
            "indices": 2, "material": 0,
        }]}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3",
             "min": [min(axis) for axis in zip(*float32_positions)],
             "max": [max(axis) for axis in zip(*float32_positions)]},
            {"bufferView": 1, "componentType": 5126, "count": len(texcoords), "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": len(indices), "type": "SCALAR"},
            {"bufferView": 4, "componentType": 5126, "count": len(positions), "type": "VEC3"},
        ],
        "materials": materials,
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "images": [{"bufferView": 3, "mimeType": "image/png"}],
        "buffers": [{"byteLength": len(data)}],
        "bufferViews": views,
    }
    description = json.dumps(gltf, separators=(",", ":")).encode()
    description += b" " * (-len(description) % 4)
    return b"".join((
        struct.pack("<4sII", b"glTF", 2, 28 + len(description) + len(data)),
        struct.pack("<I4s", len(description), b"JSON"), description,
        struct.pack("<I4s", len(data), b"BIN\x00"), data,
    )), metadata
