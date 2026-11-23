# 远景透明圆弧 GLB

这个插件把有透明背景的远景图装到以地形中心为圆心的圆弧网格上，导出单文件 GLB。GLB 内嵌 RGBA 贴图，材质采用 glTF 的标准 PBR、Alpha Blend 和双面显示。默认半径 1600、圆弧 74°、32 段、底部高度 −26，对应 64 个三角面。节点使用 ComfyUI 已有的 NumPy 和 Pillow。

## 在 ByteArtist 验证透明 PNG 到 GLB

1. 打开 **Manager → 通过URL链接下载 → 插件下载**。类型选 `branch`，Git 链接填 `https://github.com/fangfang-ship-it/fang.git`，分支填 `far-scenery-pbr`。下载后按平台提示重启。
2. 新建 **加载图像（Load Image）**，选一张已扣好的透明 PNG。新建 **远景透明圆弧 GLB（FarSceneryExportGLB）**。把 `IMAGE` 接 `image`，把 `MASK` 接 `mask`。`mask_mode` 保持 `ComfyUI mask (white = transparent)`。
3. 填一个英文资源名，例如 `gobi-mesa`，运行。节点输出 `glb_path`、`download_url` 和 `report`。需要在画布上查看链接时，可把 `download_url` 接到环境里的文本预览节点。链接以当前 ComfyUI 工作台服务为基址，托管平台是否代理该文件下载由平台决定。
4. 把下载的 GLB 导入造世界编辑器 3，核对山体颜色、周围透明和相机移动时的效果。山脚高度可通过 `base_y` 或编辑器摆放调整。

每次导出把 `.glb`、`.png` 和 `manifest.json` 写入 `output/far-scenery/<asset_id>-<内容摘要>/`。同一输入和参数复用同一目录。标准 ComfyUI 也可以拖入 [两节点工作流](workflows/png_to_glb.json)，再选本地 PNG。

## 接入参考图生图

保留现有参考图和文本节点。文本节点负责规划素材，每个 **读取远景方案（FarSceneryPlanItem）** 取其中一项，再各自接生图、分割去底和导出。生图节点可同时接原参考图与该项 `prompt`，便于保持原画风格。导出的资源名可把 `asset_id` 转为输入后接同一项的 `asset_id`，也可以手工填写。

```text
参考图 ──→ 文本规划 ──→ 读取远景方案 #1 ──→ 生图 ──→ 分割去底 ──→ 导出 GLB #1
                   ├─→ 读取远景方案 #2 ──→ 生图 ──→ 分割去底 ──→ 导出 GLB #2
                   └─→ …（每种形态用一组节点，index 对应清单中的位置）
```

文本节点可以先用下面的提示词。JSON 的 `assets` 顺序对应分支编号，允许 1–10 项。

```text
参考输入图的地貌、岩层、颜色和光照，设计五种轮廓明显不同的远景地形。
每项只包括一个完整的自然地貌，可包含连在一起的多座山峰。
为每项写独立的生图提示词，描述轮廓、岩层或积雪、色调以及山脚。
构图为横向，主体和山脚完整保留。画面只出地形素材，天空、云、水面、建筑、人物都不入图。
生图提示词要求纯色背景，便于下一步分割去底。保持五项的色彩和画风一致。
只返回 JSON，结构为 {"assets":[{"asset_id":"far-ridge-01","prompt":"完整的生图提示词"}]}。
每个 asset_id 以英文字母或数字开头，只使用英文字母、数字、下划线和连字符，且不重复。
```

分割节点需要传出单张 `IMAGE` 和一张同尺寸 `MASK`。白色是山体时，导出的 `mask_mode` 选 `Foreground alpha (white = opaque)`。白色是背景时，保留默认模式。分割若只提供 RGBA 文件，先用 **加载图像** 重新读入透明 PNG，再按上面两条连线接到导出节点。

首轮建议先验证一张 PNG 到 GLB。确认造世界编辑器 3 成功读到贴图以后，把一组生图到导出的连线跑通，再复制到五组。生图和分割复用 ByteArtist 环境中可用的节点和模型。
