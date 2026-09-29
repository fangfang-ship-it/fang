import { app } from "../../scripts/app.js";

function toast(severity, summary, detail) {
  app.extensionManager?.toast?.add?.({ severity, summary, detail, life: 3000 });
}

app.registerExtension({
  name: "fang.glb.web-viewer",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name === "FangGLBWebViewer") {
      const originalCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function (...args) {
        originalCreated?.apply(this, args);
        this.fangViewerUrl = "";
        this.addWidget("button", "打开 3D Viewer / Open Viewer", null, () => {
          if (!this.fangViewerUrl) {
            toast("warn", "请先运行节点", "模型校验成功后才能打开 Viewer。");
            return;
          }
          window.open(new URL(this.fangViewerUrl, window.location.origin).href, "_blank", "noopener,noreferrer");
        });
      };

      const originalExecuted = nodeType.prototype.onExecuted;
      nodeType.prototype.onExecuted = function (message, ...args) {
        originalExecuted?.apply(this, [message, ...args]);
        const value = message?.viewer_url;
        this.fangViewerUrl = Array.isArray(value) ? value[0] : value || "";
        this.setDirtyCanvas?.(true, true);
        if (this.fangViewerUrl) {
          window.open(new URL(this.fangViewerUrl, window.location.origin).href, "_blank", "noopener,noreferrer");
        }
      };
      return;
    }

    if (["GLBTurntableGIF", "FangSaveGIF"].includes(nodeData.name)) {
      const originalCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function (...args) {
        originalCreated?.apply(this, args);
        const container = document.createElement("div");
        container.style.cssText = "width:100%;min-height:220px;display:flex;align-items:center;justify-content:center;background:#111;border-radius:8px;overflow:hidden";
        const image = document.createElement("img");
        image.alt = "GIF preview";
        image.style.cssText = "display:none;max-width:100%;max-height:420px;object-fit:contain";
        container.appendChild(image);
        this.fangGifPreviewImage = image;
        this.addDOMWidget?.("fang_gif_preview", "GIF Preview", container, {
          getValue: () => "",
          setValue: () => {},
        });
      };
      const originalExecuted = nodeType.prototype.onExecuted;
      nodeType.prototype.onExecuted = function (message, ...args) {
        originalExecuted?.apply(this, [message, ...args]);
        const value = Array.isArray(message?.gifs) ? message.gifs[0] : null;
        if (!value || !this.fangGifPreviewImage) return;
        const query = new URLSearchParams({
          filename: value.filename,
          subfolder: value.subfolder || "",
          type: value.type || "output",
          t: Date.now().toString(),
        });
        this.fangGifPreviewImage.src = `/view?${query.toString()}`;
        this.fangGifPreviewImage.style.display = "block";
        this.setDirtyCanvas?.(true, true);
      };
      return;
    }

    if (!["Douyin3DGenerate", "Douyin3DSaveModel", "Douyin3DDownloadAsset"].includes(nodeData.name)) return;

    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      originalCreated?.apply(this, args);
      this.fangModelDownloadUrl = "";
      this.addWidget("button", "下载到本机 / Download", null, () => {
        if (!this.fangModelDownloadUrl) {
          toast("warn", "请先运行保存节点", "模型保存成功后，按钮才会开始下载。");
          return;
        }
        const anchor = document.createElement("a");
        anchor.href = new URL(this.fangModelDownloadUrl, window.location.origin).href;
        anchor.download = "";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      });
    };

    const originalExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message, ...args) {
      originalExecuted?.apply(this, [message, ...args]);
      const value = message?.local_download_url;
      this.fangModelDownloadUrl = Array.isArray(value) ? value[0] : value || "";
      this.setDirtyCanvas?.(true, true);
      if (this.fangModelDownloadUrl) {
        toast("success", "模型已保存", "点击节点中的“下载到本机”按钮即可下载。");
      }
    };
  },
});
