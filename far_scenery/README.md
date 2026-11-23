# 远景透明圆弧 GLB

这个插件把有透明背景的远景图装到以地形中心为圆心的圆弧网格上，导出单文件 GLB。GLB 内嵌 RGBA 贴图，材质采用 glTF 的标准 PBR、Alpha Blend 和双面显示。提供固定尺寸的整圈模板和按贴图比例生成的单片模式。适配和导出都在 CPU 上完成。

## 五片围成一圈

在 ByteArtist 添加 **加载图像 → 远景贴图适配（FarSceneryFitTexture）→ 远景固定模板 GLB（FarSceneryExportRingGLB）**。每段各连 `IMAGE → image` 和 `MASK → mask`。标准 ComfyUI 可直接打开 [三节点工作流](workflows/ring_template.json)。

- `width_percent` 是山体占画布的宽度，默认 90%。缩放保持宽高比。`center_percent` 是横向中心，默认 50% 居中。
- `foot_line_px` 是从画布顶部量起的山脚线，默认 600。五片通常共用这个值。默认山脚线映射至 GLB 的 `Y=0`，画布下方还有 40 px。
- 用加载图像的遮罩时保持默认 `ComfyUI mask (white = transparent)`。用白色表示山体的分割遮罩时，在贴图适配节点选 `Foreground alpha (white = opaque)`。适配节点总是输出标准 ComfyUI 遮罩，直接接给固定模板导出节点。
- 固定模板使用 **2048 × 640** 整张画布、**500 m** 半径、**72°** 弧段、**32 段**、约 **628.3 m** 展开宽和约 **196.3 m** 高。同一套网格、原点和 UV 用于五个方位，透明留白按原样保留。
- 给每片不同的 `asset_id`，例如 `far-ring-01` 至 `far-ring-05`。在编辑器把模型原点放在同一个地形中心，依次绕竖直轴旋转 `0°、72°、144°、216°、288°`。山脊要连续时，在贴图阶段对齐相邻边缘。

## 在 ByteArtist 安装与单片导出

1. 打开 **Manager → 通过URL链接下载 → 插件下载**。类型选 `branch`，Git 链接填 `https://github.com/fangfang-ship-it/fang.git`，分支填 `far-scenery-pbr`。下载后按平台提示重启。
2. 单片模式新建 **加载图像（Load Image）**，选一张已扣好的透明 PNG。新建 **远景透明圆弧 GLB（FarSceneryExportGLB）**。把 `IMAGE` 接 `image`，把 `MASK` 接 `mask`。`mask_mode` 保持 `ComfyUI mask (white = transparent)`。单片模式默认半径 1600、圆弧 74°、32 段、底部高度 −26。
3. 填一个英文资源名，例如 `gobi-mesa`，运行。节点输出 `glb_path`、`download_url` 和 `report`。可把 `download_url` 接到环境里的文本预览节点。
4. 把下载的 GLB 导入造世界编辑器 3，核对山体颜色、周围透明和相机移动时的效果。山脚高度可通过 `base_y` 或编辑器摆放调整。

每次导出把 `.glb`、`.png` 和 `manifest.json` 写入 `output/far-scenery/<asset_id>-<内容摘要>/`。同一输入和参数复用同一目录。标准 ComfyUI 也可以拖入 [两节点工作流](workflows/png_to_glb.json)，再选本地 PNG。

## 下载 GLB

标准 ComfyUI 中，导出节点运行后提供蓝色「下载 … .glb」链接。节点同时提供标准的 3D 文件输出记录。工作台如果自带 3D 产物卡片，可通过产物卡片下载。

两个导出节点都有选填的 `workbench_url`。在 ByteArtist 填承载 ComfyUI 画布的工作台地址，例如 `https://workbench.example.com`。可直接粘贴工作台页面的网址，节点会提取域名生成完整的 `download_url`。在浏览器打开这个以 `https://` 开头的完整链接。

留空时 `download_url` 是 `/api/view?...` 形式的相对地址。需要在同一工作台域名下访问，单独粘贴到浏览器可能被当作本地文件。`glb_path` 是工作台机器上的文件路径。`manifest.json` 记录相对地址，便于输出在不同工作台间复用。

## 接入参考图生图

保留现有参考图和文本节点。把文本规划的输出接到一个 **拆分五条远景提示词（FarScenerySplitPlan）** 的 `plan` 输入口。右侧 `prompt_1` 至 `prompt_5` 按数组顺序分别接到五个图片生成节点的提示词。每个图片生成节点也接同一张参考图，然后各自接分割去底和导出。

```text
参考图 ──→ 文本规划 ──→ 拆分五条远景提示词 ── prompt_1 ──→ 生图 #1
                                        ├─ prompt_2 ──→ 生图 #2
                                        └─ …（分别接到第 5 路）
```

五路拆分要求 `assets` 恰好包含五项。也支持模型把五组交替出现的 `asset_id`、`prompt` 错写进一个对象的情况，按原顺序恢复五项。需要取单个提示词和对应资源名时，可以用 **读取远景方案（FarSceneryPlanItem）**，支持 1–10 项。

文本节点可以先用下面的提示词。

```text
参考输入图的地貌、岩层、颜色和光照，设计五种轮廓明显不同的远景地形。
每项只包括一个完整的自然地貌，可包含连在一起的多座山峰。
为每项写独立的生图提示词，描述轮廓、岩层或积雪、色调以及山脚。
构图为横向，主体和山脚完整保留。画面只出地形素材，天空、云、水面、建筑、人物都不入图。
生图提示词要求纯色背景，便于下一步分割去底。保持五项的色彩和画风一致。
只返回 JSON，根字段为 assets。assets 是数组，包含恰好五个独立对象。
每个对象恰好有一个 asset_id 和一个 prompt，相邻对象以逗号分隔。
每个 asset_id 以英文字母或数字开头，只使用英文字母、数字、下划线和连字符，且不重复。
```

分割节点需要传出单张 `IMAGE` 和一张同尺寸 `MASK`。白色是山体时，导出的 `mask_mode` 选 `Foreground alpha (white = opaque)`。白色是背景时，保留默认模式。分割若只提供 RGBA 文件，先用 **加载图像** 重新读入透明 PNG，再按上面两条连线接到导出节点。

首轮建议先验证一张 PNG 到 GLB。确认造世界编辑器 3 成功读到贴图以后，把一组生图到导出的连线跑通，再复制到五组。生图和分割复用 ByteArtist 环境中可用的节点和模型。
