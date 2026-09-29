# 天空自动排布 ComfyUI 测试链路 v0.1

> GitHub 集成版安装入口见仓库根目录 README.md；整仓下载时安装整个 fang，仅安装一次。下文“安装”段适用于独立节点压缩包。

这是开发端安装一次、每张图自动运行的 Load Image → ②检测 → ③排布 → ④渐变合成 → ⑤检查/保存链路。
不需要最终用户查看节点、框选云区、输入上下界或调整位移；不调用任何生成模型，不下载模型权重，不产生生图 API 费用。

## 先明确适用范围

- **工程测试版，不是已验收的全天气生产方案。** 当前自动检测利用云层的横向细节与低频天空背景的差别，不是语义分割模型。
- 面向“晴天/晚霞云群 + 大面积平滑天空”的已生成图。弱云影、极光外晕、稀疏雨丝、满幅层云、噪声或画面中的地景可能导致漏检/误判，尚未通过这些天气的验证。
- 没检测到内容时也返回失败，不把它擅自当成纯净背景。无法安全放置时不裁云、不压扁、不输出冒充成功的图片。
- 检测和位置检查通过只代表 `layout_pass`。接缝、球面观感与艺术质量没有自动验收，报告始终明确 `publishable: false`；需接入你自己的下游质量验收后才能作为产品成品发布。
- 本包输出 SDR PNG，不是包含真实光照动态范围的 HDR/EXR。

## 安装（开发人员操作一次）

1. 将整个 `comfyui_sky_auto_layout` 文件夹放进 `ComfyUI/custom_nodes/`。确保其下一层直接有 `__init__.py`，不要多套一层文件夹。
2. ComfyUI 通常已有 numpy、Pillow、torch；如提示缺依赖，用 ComfyUI 自己的 Python 环境执行 `python -m pip install -r custom_nodes/comfyui_sky_auto_layout/requirements.txt`。不要另装/替换 torch。
3. 重启 ComfyUI。搜索 `Sky Auto Layout` 应看到四个自定义节点。
4. 拖入 `workflows/01_strict_band.json`。Load Image 选择原始天空图片后执行。

若托管 Byteartist 环境禁止加载自定义 Python 节点，需要由平台/开发者部署本包；单独导入 JSON 不会安装节点。本版本发布于 fangfang-ship-it/fang 的 sky-auto-layout-v0.1 分支；没有在你的 Byteartist 实例安装。

## 两个预设不能混淆

| 文件 | 后台规则 | 不符合时 |
|---|---|---|
| `01_strict_band.json` | 默认严格版：完整云群及过渡边缘必须进入原21:9稿30%—45%范围；等比例形状不变，只平移 | 返回 `BAND_DOES_NOT_FIT`，不保存候选图 |
| `02_horizon_only.json` | 明确放宽云顶位置：允许进入原21:9稿3%—45%范围，保留形状并保证最终中线下方干净 | 太高或检测不可靠仍返回失败 |

第二个预设只是中线保底实验，**不等价于已经达到30%—45%的美术要求**；不会在严格版失败后悄悄切换。

默认 `coordinate_space=design_21_9`，百分比按宽度对应的21:9设计稿高度计算；输出直接是2:1。
例如宽度2100：设计稿高度900，30%—45%为270—405像素；最终高度1050，对应最终图约25.7%—38.6%。这延续原设计坐标，没有把原30%—45%改成最终图30%—45%。
开发端也可统一选择 `final_2_1`，此时所有目标百分比基于最终画布，属于另一种布局配置。不要逐图混用。

## ②—⑤具体做什么

② 自动检测：分析横向结构，计入所有检测到的分散云块，扩充柔边安全量，再找上下背景过渡空间。无人工框选。

③ 自动排布：按目标范围计算位移。保持原图横向顺序和原始云体像素；不裁掉云脚、不自动纵向压缩。奇数宽图只在最右补一个周期插值列以得到精确2:1，不缩放云形。

④ 自动背景：从输入图顶部、底部和保留区域两端取实际底色，用连续插值重建渐变。只在检测到的内容范围外羽化，保留区域核心不变；范围外强制使用横向均匀背景。背景没有新造 HEX，也不再让生图模型填云。

⑤ 检查/保存：检查2:1、保留核心的像素差、净区横向均匀性及区域边界。成功写候选 PNG + JSON；失败只写 JSON，不保存伪成品。左右差异仅记录，不宣称已经无缝。

`debug_only` 输出带线和英文提示，接 Preview Image 供开发端调试，不是用户成品。红线=当前预览图中线；橙线=检测保留范围；青线=核心/目标范围。

## 接入用户看不到的业务链路

- 本地验证时使用 Load Image。接入原有生图链路时，把 Seedream 节点的 IMAGE 输出直接接②的 `image`，替换 Load Image 即可；②—⑤不需要用户输入。
- `03_strict_band_api.json` 和 `04_horizon_only_api.json` 是 ComfyUI API prompt 格式。把节点1的 `image` 替换为已上传到 ComfyUI input 的文件名；不能直接填外部网址或本机任意路径。
- 一张图片对应一次队列请求；批量业务发送多次请求。本版本不接受单个多图 Tensor 批次。
- 服务端读取节点5的 `ui.text[0]` / history 中 `outputs["5"]["text"][0]` 的 JSON，以及 `images`。
- `status=retry_required`：无候选图，走后端失败分支。可以限次重试上游生图或使用经批准的兜底素材。**本包只有 Load Image 和后处理，没有包含上游生图，也不会自己启动重试。**建议重试次数由业务端限制，避免无限循环。
- `status=layout_pass`：取得 `candidate_file` 后进入既有艺术/接缝验收；`layout_pass` 不等于整体产品验收。
- 用户界面只收到你的业务状态和最终通过验收的图片，不需要接触上述参数。

常见失败码：

| code | 含义 |
|---|---|
| `NO_RELIABLE_CONTENT` | 无可靠内容，不将其当成空天空 |
| `CONTENT_TOUCHES_EDGE` | 无足够边缘空间，平移可能截断内容 |
| `CONTENT_TOO_BROAD` | 内容过宽或背景不符合假设 |
| `UNCLEAN_MARGIN` | 没找到可靠的干净过渡区 |
| `BAND_DOES_NOT_FIT` | 完整保留范围超过目标高度，拒绝形变 |
| `INPUT_GEOMETRY` | 输入不是约2:1/21:9的独立天空图 |
| `COMPOSITE_CHECK_FAILED` | 几何或像素保留检查未通过 |

## 测试与已知限制

见 `验证说明.md`。核心算法可运行 `python -m unittest discover -s tests -v`。
当前环境没有安装完整 ComfyUI/torch：已验证独立图像算法、JSON连线和导出失败分支，**未进行真实 ComfyUI 前端导入/队列执行验证，也未做 Byteartist 实例验收**。
参考图中的细微云影可能漏检；程序保证的是合成范围之外使用背景，不是保证所有云都被准确识别。全自动生产仍需更多原图批测和下游验收。

## 开发参考

- https://docs.comfy.org/custom-nodes/backend/server_overview
- https://docs.comfy.org/custom-nodes/backend/images_and_masks
- https://docs.comfy.org/specs/workflow_json_0.4

采用仍受支持的 V1 节点接口；IMAGE 遵循 `[B,H,W,C]` 的 ComfyUI 约定。
