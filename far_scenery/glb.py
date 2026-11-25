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
    yaw_offset = 0.0
    if yaw_degrees is not None:
        if not math.isfinite(yaw_degrees):
            raise ValueError("Yaw must be a finite number of degrees. / 旋转角须为有限数值。")
        # Increasing theta turns toward +X, opposite positive glTF Y rotation.
        yaw_offset = -math.radians(yaw_degrees % 360)

    positions = []
    normals = []
    texcoords = []
    indices = []
    for column in range(segments + 1):
        t = column / segments
        theta = (t - 0.5) * span + yaw_offset
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
        origin = [0.0, 0.0, 0.0]
        node["translation"] = origin
        node["rotation"] = [0.0, 0.0, 0.0, 1.0]
        metadata.update({
            "originMeters": origin, "yawDegrees": float(yaw_degrees), "yawBakedIntoMesh": True,
        })
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
    return pack_glb(gltf, data), metadata


def pack_glb(gltf, data):
    description = json.dumps(gltf, separators=(",", ":")).encode()
    description += b" " * (-len(description) % 4)
    return b"".join((
        struct.pack("<4sII", b"glTF", 2, 28 + len(description) + len(data)),
        struct.pack("<I4s", len(description), b"JSON"), description,
        struct.pack("<I4s", len(data), b"BIN\x00"), data,
    ))


def read_ring_glb(glb):
    magic, version, length, json_length, json_type = struct.unpack_from("<4sIII4s", glb)
    binary_offset = 20 + json_length
    binary_length, binary_type = struct.unpack_from("<I4s", glb, binary_offset)
    if (magic, version, length, json_type, binary_type) != (b"glTF", 2, len(glb), b"JSON", b"BIN\x00"):
        raise ValueError("GLB 文件头无效。")
    if json_length % 4 or binary_length % 4 or binary_offset + 8 + binary_length != length:
        raise ValueError("GLB 数据块长度无效。")
    gltf = json.loads(glb[20:binary_offset])
    node, = gltf["nodes"]
    if (
        gltf["asset"]["generator"] != "ComfyUI-FarScenery"
        or node["translation"] != [0, 0, 0]
        or node["rotation"] != [0, 0, 0, 1]
        or not node.get("extras", {}).get("yawBakedIntoMesh")
    ):
        raise ValueError("请用最新版「远景固定模板 GLB」重新导出。")
    return gltf, glb[binary_offset + 8:], node["extras"]


def merge_ring_glbs(glbs, name):
    """Join fixed-template assets as five primitives of one mesh."""
    if len(glbs) != 5:
        raise ValueError("请连接五路远景 GLB。")
    keys = ("radiusMeters", "spanDegrees", "segments", "baseMeters", "heightMeters", "textureSize", "textureWindow")
    primitives = []
    merged = {key: [] for key in ("bufferViews", "accessors", "materials", "textures", "images", "samplers")}
    data = bytearray()
    angles = []
    template = None

    for index, glb in enumerate(glbs, 1):
        try:
            source, binary, geometry = read_ring_glb(glb)
            settings = {key: geometry[key] for key in keys}
            if template is not None and settings != template:
                raise ValueError("五片须使用同一版固定模板。")
            template = settings
            yaw = geometry["yawDegrees"]
            if not math.isfinite(yaw):
                raise ValueError("方位角须为有限数值。")
            if any(other % 360 == yaw % 360 for other in angles):
                raise ValueError("方向重复，请核对连线和 yaw_degrees。")
            angles.append(yaw)

            offsets = {key: len(merged[key]) for key in merged}
            for view in source["bufferViews"]:
                view["byteOffset"] = view.get("byteOffset", 0) + len(data)
            data.extend(binary)
            for accessor in source["accessors"]:
                accessor["bufferView"] += offsets["bufferViews"]
            for image in source["images"]:
                image["bufferView"] += offsets["bufferViews"]
            for texture in source["textures"]:
                texture["source"] += offsets["images"]
                texture["sampler"] += offsets["samplers"]
            for material in source["materials"]:
                material["pbrMetallicRoughness"]["baseColorTexture"]["index"] += offsets["textures"]
            for key in merged:
                merged[key].extend(source[key])

            primitive, = source["meshes"][source["nodes"][0]["mesh"]]["primitives"]
            primitive["attributes"] = {
                key: value + offsets["accessors"] for key, value in primitive["attributes"].items()
            }
            primitive["indices"] += offsets["accessors"]
            primitive["material"] += offsets["materials"]
            primitives.append(primitive)
        except (KeyError, IndexError, TypeError, struct.error, ValueError) as error:
            detail = error if type(error) is ValueError else "GLB 内容无效，请重新导出。"
            raise ValueError(f"第 {index} 路 GLB：{detail}") from error

    geometry = {**template, "originMeters": [0, 0, 0], "pieceCount": len(angles), "yawAnglesDegrees": angles}
    gltf = {
        "asset": {"version": "2.0", "generator": "ComfyUI-FarScenery"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0, "translation": [0, 0, 0], "rotation": [0, 0, 0, 1], "extras": geometry}],
        "meshes": [{"name": name, "primitives": primitives}],
        "buffers": [{"byteLength": len(data)}],
        **merged,
    }
    return pack_glb(gltf, data), geometry
