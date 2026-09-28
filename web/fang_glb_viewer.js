import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "fang.glb.web-viewer",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "FangGLBWebViewer") return;

    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      originalCreated?.apply(this, args);
      this.fangViewerUrl = "";
      this.addWidget("button", "打开 3D Viewer / Open Viewer", null, () => {
        if (!this.fangViewerUrl) {
          app.extensionManager?.toast?.add?.({
            severity: "warn",
            summary: "请先运行节点",
            detail: "模型校验成功后才能打开 Viewer。",
            life: 3000,
          });
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
  },
});
