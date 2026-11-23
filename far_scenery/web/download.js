import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";

const exportNodes = new Set(["FarSceneryExportGLB", "FarSceneryExportRingGLB"]);

app.registerExtension({
    name: "FarScenery.GLBDownload",
    nodeCreated(node) {
        if (!exportNodes.has(node.comfyClass) || typeof node.addDOMWidget !== "function") return;

        const link = document.createElement("a");
        link.style.cssText = "display:block;text-align:center;border-radius:4px;padding:6px;" +
            "background:#1453a5;color:#fff;text-decoration:none;font-size:13px;";
        link.textContent = "运行后下载 GLB";
        link.setAttribute("aria-disabled", "true");
        node.addDOMWidget("glb_download", "glb_download", link, {
            serialize: false,
            getMinHeight: () => 32,
        });

        const previous = node.onExecuted;
        node.onExecuted = function (output, ...args) {
            previous?.call(this, output, ...args);
            const file = output?.["3d"]?.[0];
            if (typeof file?.filename !== "string" || !file.filename.endsWith(".glb")) return;

            const query = new URLSearchParams({
                filename: file.filename,
                subfolder: file.subfolder ?? "",
                type: "output",
            });
            link.href = api.apiURL(`/view?${query}`);
            link.download = file.filename;
            link.textContent = `下载 ${file.filename}`;
            link.removeAttribute("aria-disabled");
        };
    },
});
