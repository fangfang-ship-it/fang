# Fang ComfyUI Custom Nodes

本仓库包含天空图处理、AI Studio 图生 3D、模型保存与浏览器 3D 预览节点。

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/fangfang-ship-it/fang.git
```

重启 ComfyUI 后，在节点菜单中搜索 `Fang/3D` 或 `Sky Tools`。

## Douyin3D 图生 3D

推荐直接导入 [`douyin3d_workflow.json`](douyin3d_workflow.json)。示例画布已经连接：

`Load Image → Douyin3D Image-to-3D → Save Douyin3D Model`

### 生成节点

`Douyin3DGenerate` 对应 AI Studio 当前图生模型页面，并可切换 Douyin3D、混元3D、Poly3D、Rodin、Seed3D 与 Tripo3D。模型档位和参数会按供应商映射到各自接口字段：

- 模型版本：V3.1-fast / V3.1
- 几何质量：低 / 中 / 高 / 超高
- 贴图质量：低 / 中 / 高 / 超高
- 贴图分辨率：1K / 2K / 4K
- 面数：100–1,000,000
- 生成贴图、PBR、去光影强度
- 拆分子模型、四边面重拓扑
- 独立的几何种子与贴图种子

参数会直接映射到网页使用的 `douyin3d_params`，不再经过会覆盖手动值的质量预设。

`project_id` 填 `0` 时会通过 `/api/v1/projects/list` 自动选择第一个可用项目；如需指定项目，请填写对应 ID。

### Cookie 鉴权

节点 `cookies` 输入支持：

- 从浏览器复制的完整 Cookie 字符串；
- `Cookie: ...` 格式；
- 仅填写 `AGW_CAS_SESSION` 的值。

也可在运行环境中设置：

```bash
export DOUYIN3D_COOKIES='<完整 Cookie 字符串>'
```

Cookie 输入会随 ComfyUI 工作流保存。请勿上传、分享或提交填写过真实 Cookie 的工作流；仓库示例中的该字段始终为空。

### 保存节点

`Douyin3DSaveModel` 接收生成节点的 `DOUYIN3D_ASSET` 输出，可选择：

- GLB
- FBX
- OBJ

如果所选格式尚不存在，节点会调用 AI Studio 转换接口并轮询完成状态，然后下载到：

```text
ComfyUI/output/douyin3d/<filename_prefix>_<asset_id>.<format>
```

节点同时输出保存路径、下载 URL 和资产 ID。模型保存成功后，节点会出现明显的 **“下载到本机 / Download”** 按钮；点击后浏览器直接下载服务器 `output/douyin3d` 中的最终文件，无需进入文件管理器。

## 其他 3D 节点

- `Douyin3DDownloadGLB`：下载已有的公开 GLB，用于验证下游链路。
- `FangGLBWebViewer`：在独立网页中预览 ComfyUI output 下的 GLB。
- `FangSaveGLB`：将已有 GLB 复制到稳定输出目录。

## 天空图节点

### Sky Bottom Stretch 2:1

保持宽度与上部像素不变，仅纵向拉伸底部指定比例，使输出达到严格 2:1。输入宽度必须为偶数，且原图宽高比不能小于 2:1。

### Sky Gaussian Blur Float

支持小数半径的 Pillow Gaussian Blur。`radius=0` 时原图直通；不改变图片尺寸，支持批量图片。

## 验证

```bash
python -m unittest tests.test_douyin3d tests.test_glb_viewer -v
```

完整测试还需要 ComfyUI/PyTorch 运行环境。仓库不会保存 Cookie、Token 或其他鉴权凭证。
