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

`Load Image → Douyin3D Image-to-3D`

生成与 GLB 保存已经合并为一个节点。节点会自动选择第一个可用 AI Studio 项目，不再显示 `project_id`；也不再输出 `asset_id` 和 `status_json`。

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

参数会直接映射到网页使用的供应商参数，不再经过会覆盖手动值的质量预设。项目 ID 会通过 `/api/v1/projects/list` 自动获取。生成成功后，节点会自动下载 GLB 到：

```text
ComfyUI/output/douyin3d/<asset_name>_<asset_id>.glb
```

节点直接输出 `saved_glb_path` 和 `download_glb_url`，并显示明显的 **“下载到本机 / Download”** 按钮。点击后浏览器直接下载最终 GLB。如果需要对同一图片和参数重新生成，请开启 `force_regenerate`。

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

## 360°旋转 GIF 节点

将生成节点的 `saved_glb_path` 连接到 `GLB Turntable GIF / 模型360°旋转 GIF`：

- 尺寸：256 / 384 / 512 / 768
- 帧数：12–120，推荐36
- FPS：1–30，推荐12
- 可调相机俯视角、透明/白/黑/灰背景、旋转方向
- 只读取已生成的GLB，不会重新调用图生3D或消耗积分

运行节点后会直接在 ComfyUI 后端渲染并保存真正的 GIF，不再打开网页。GIF 会作为节点预览直接显示在画布里，同时输出 `gif_path` 和全部渲染帧 `IMAGE`，文件保存在：

```text
ComfyUI/output/douyin3d/<filename_prefix>_turntable.gif
```

首次安装会通过 `requirements.txt` 安装 `trimesh` 与 `pyrender`，因此更新插件后必须重启房间。

相机与环绕轴按 glTF 标准的 **Y轴向上** 处理，角色会保持站立，不再横躺。

如需像 `Save Image` 一样显式保存，可将 `frames` 输出连接到：

```text
Save GIF / 保存 GIF
```

该节点可设置文件名前缀、FPS和循环播放，保存后同样会在画布中直接预览，文件位于 `ComfyUI/output/douyin3d/`。

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
