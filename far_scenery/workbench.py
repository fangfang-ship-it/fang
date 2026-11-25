"""Use the current ByteArtist request to resolve download URLs per execution."""

from contextvars import ContextVar
import re
import sys
from urllib.parse import urlsplit


WORKBENCH_HOST = re.compile(r"bench-[0-9]+\.byteartist-workbench\.bytedance\.net")
EXPORT_NODES = ("FarSceneryExportGLB", "FarSceneryExportRingGLB", "FarSceneryMergeRingGLB")
request_origin = ContextVar("far_scenery_workbench_origin", default=None)


def workbench_origin(headers):
    for name in ("Host", "X-Forwarded-Host", "Origin", "Referer"):
        value = headers.get(name, "").split(",", 1)[0].strip()
        if name in ("Host", "X-Forwarded-Host"):
            value = "https://" + value
        try:
            parts = urlsplit(value)
            if (parts.scheme == "https" and WORKBENCH_HOST.fullmatch(parts.hostname or "")
                    and parts.username is None and parts.port in (None, 443)):
                return f"https://{parts.hostname}"
        except ValueError:
            continue
    return None


def use_workbench_origin(prompt_request):
    origin = request_origin.get()
    prompt = prompt_request.get("prompt")
    if origin and isinstance(prompt, dict):
        for node in prompt.values():
            if (isinstance(node, dict) and node.get("class_type") in EXPORT_NODES
                    and isinstance(node.get("inputs"), dict)):
                # This edits the execution payload only. Including the origin in
                # the inputs also keeps cached URL outputs scoped to their room.
                node["inputs"]["workbench_url"] = origin
    return prompt_request


def install_workbench_url_detection():
    server_type = getattr(sys.modules.get("server"), "PromptServer", None)
    server = getattr(server_type, "instance", None)
    if server is None or server.app.frozen or getattr(server, "_far_scenery_workbench_urls", False):
        return

    from aiohttp import web

    @web.middleware
    async def capture_workbench_origin(request, handler):
        if request.method != "POST" or not request.path.rstrip("/").endswith("/prompt"):
            return await handler(request)
        token = request_origin.set(workbench_origin(request.headers))
        try:
            return await handler(request)
        finally:
            request_origin.reset(token)

    server.app.middlewares.append(capture_workbench_origin)
    server.add_on_prompt_handler(use_workbench_origin)
    server._far_scenery_workbench_urls = True
