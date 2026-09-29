# 天空自动排布 v0.1 · 自动测试链路

本分支包含自动检测 → 保持云形排布 → 渐变合成 → 检查/保存。最终用户无需框选、填写内容范围或调整位移。沿用仓库原有拉伸与小数半径模糊节点，不调用新的生成模型。

## 下载与分支

- Git 仓库：`https://github.com/fangfang-ship-it/fang`
- **本版本分支：`sky-auto-layout-v0.1`**
- [直接下载本分支 ZIP](https://github.com/fangfang-ship-it/fang/archive/refs/heads/sky-auto-layout-v0.1.zip)
- Byteartist 若支持按 Git 分支安装：下载类型选择 `branch`，仓库填上面地址，分支填写 `sky-auto-layout-v0.1`，下载后重新加载运行环境。
- 标准 ComfyUI：将解压后的整个仓库放入 `custom_nodes/fang/`，或在 `custom_nodes` 中执行 `git clone --branch sky-auto-layout-v0.1 --single-branch https://github.com/fangfang-ship-it/fang.git fang`，再重启。
- 已有 `fang` 时先备份原目录，更新原安装或切换分支；不要再平行安装一份相同节点，以免名称重复。不要只复制 `sky_auto_layout` 子文件夹后再同时保留整仓安装。

## 导入工作流

| 文件 | 用途 |
|---|---|
| [01_strict_band.json](sky_auto_layout/workflows/01_strict_band.json) | 严格30%—45%蓝区，完整云体放不下就返回失败，绝不暗中裁云或压扁 |
| [02_horizon_only.json](sky_auto_layout/workflows/02_horizon_only.json) | 中线保底实验，明确允许云顶更高；适合先观察自动平移效果 |
| [03_strict_band_api.json](sky_auto_layout/workflows/03_strict_band_api.json) | 后台 API 调用的严格版 |
| [04_horizon_only_api.json](sky_auto_layout/workflows/04_horizon_only_api.json) | 后台 API 调用的中线保底版 |

安装节点后将前两份之一拖入 ComfyUI，选择原始天空图片执行。后两份是 API 格式，不是画布格式。

[完整使用说明](sky_auto_layout/README_先读我.md) · [验证与限制](sky_auto_layout/验证说明.md)

**测试版限制：**自动检测是针对云群与平滑背景的图像算法，不是已验证的全天气语义识别。已完成11项独立工程测试；没有在真实 ComfyUI/Byteartist 环境运行验收。严格版可能返回放不下；失败只写 JSON，后端需接入有限次上游重试/兜底。本包不会自动重新生图。输出是 SDR PNG，未证明左右无缝或球面合格。

---

# 原有节点说明（以下 main 安装说明针对原有节点）

# 小数半径高斯模糊 / Sky Gaussian Blur Float

新增节点 `Sky Gaussian Blur Float / 高斯模糊（小数半径）`，分类 `Sky Tools`，内部类型 `SkyGaussianBlurFloat`。

- `radius`：默认 **1.5**，范围 0—100，步进 0.1；可以直接输入 1.25、1.5、1.75 等小数。
- `0`：原图直通；数值越大越模糊。不改变图片尺寸，支持批量图片。
- 使用与 Art Venture `ImageGaussianBlur` 相同的 Pillow `ImageFilter.GaussianBlur`，半径直接以小数传入，不取整、不混合两张整数模糊图。使用相同 Pillow 版本和普通 RGB 输入时，1、2 的结果与原节点一致。
- 沿用原节点的 8 位图像处理方式，适用于当前 PNG/JPG 天空图；正半径会量化到 8 位并截断超出 0—1 的值，不适合保留真正 HDR 浮点动态范围。
- 使用 ComfyUI 已有的 Pillow、NumPy、PyTorch，无模型下载。原有天空底部拉伸节点继续可用。

## Byteartist 更新与替换

1. 插件下载使用 `branch`，Git 地址 `https://github.com/fangfang-ship-it/fang`，分支 `main`，更新/重新下载后重新加载运行环境。
2. 在画布搜索 `Sky Gaussian Blur Float` 或 `高斯模糊（小数半径）`，添加新节点。旧封装节点不会自动变成小数输入。
3. 连接：**平铺偏移 → 新高斯模糊 → 画面对比度 → 保存图片**，替换旧高斯模糊节点。
4. 将 `radius` 设为 **1.5**；继续微调可试 1.4、1.6，或直接输入两位小数。

该节点不自动修复天空接缝。未在 Byteartist 实际运行环境验证界面；本地验证范围见 tests/test_gaussian_blur.py。

---

## Byteartist 安装

Git 仓库链接：`https://github.com/fangfang-ship-it/fang`

分支：`main`。下载后重新加载运行环境，搜索 `Sky Bottom Stretch` 或 `天空底部拉伸`。默认 `bottom_percent` 为30。

# 天空底部拉伸节点 / Sky Bottom Stretch 2:1

输入21:9天空图，保持宽度与上方70%像素不变，仅把底部30%纵向拉伸，输出严格2:1。
这是确定性的像素处理，不是AI扩图，无需模型、提示词或额外安装依赖（使用ComfyUI已有的numpy、torch）。

## 安装

1. 解压ZIP，将整个 `comfyui_sky_bottom_stretch` 文件夹放进你的 `ComfyUI/custom_nodes/`。
2. 确认路径为 `ComfyUI/custom_nodes/comfyui_sky_bottom_stretch/__init__.py`，不要多套一层文件夹。
3. 完全重启ComfyUI，刷新浏览器。
4. 双击画布，搜索 `Sky Bottom Stretch` 或 `天空底部拉伸`，分类为 `Sky Tools`。

Windows便携版一般放在 `ComfyUI_windows_portable/ComfyUI/custom_nodes/`。
桌面版使用实际ComfyUI后端目录下的 `custom_nodes`；托管服务需支持安装自定义节点。

## 使用

Load Image（加载图像） → Sky Bottom Stretch 2:1 → Save Image（保存图像）。

也可拖入包内 `example_workflow.json`，然后在Load Image中重新选择自己的图片。

参数 `bottom_percent` 默认30，代表“参与拉伸的原图底部百分比”，不是新增高度百分比。
输出 `image` 是结果图，`width`、`height` 是尺寸，`info` 是处理说明，可接文字显示节点。

## 计算例子

输入2100×900（21:9）：

- 目标高度：2100÷2=1050。
- 保留上方630行，完全不重采样。
- 原底部270行，拉伸至420行。
- 输出2100×1050（2:1）。

宽度不变化、不裁切、不水平插值；底部使用端点对齐的纵向线性插值，起始行和末行保持原像素。
图像批次、浮点数值和通道数保留，不转8位，不裁剪亮度到0—1。运算在CPU，返回输入设备与数据类型。
建议参与拉伸的区域是天空下方的纯色/渐变；其中若有云、星星等结构，它们也会被纵向拉长。

## 输入边界与限制

- 接受偶数宽度、宽高比大于或等于2:1的图像；不强制要求恰好21:9，适应平台实际导出尺寸。
- 已经2:1时保持图像不变。
- 奇数宽度报错：保持原宽度和整数像素高度无法同时满足严格2:1。
- 宽高比小于2:1时报错，不偷偷压缩画面。
- 底部行数按比例四舍五入，至少保留一行参与拉伸。
- 节点不检测天际线、不自动修复左右接缝，也不恢复真实HDR动态范围；保存HDR/EXR需另接相应格式的读写节点。
- 新图比例正确并不等于纠正了原图的球面投影。

## 为什么不能保证天际线居中

对精确21:9输入，输出高度是原来的7/6。若天际线在保留区，它的像素位置不变，相对高度变成原来的6/7。
例如原图70%高度处转换后是60%；原图约58.33%处转换后才是50%。
仅改变底部拉伸比例，也不能移动保留区内的天际线。精准居中需要单独指定天际线位置并重映射上下区域。

## 验证范围

已验证NumPy像素处理：目标比例、上部像素保留、端点保留、批次/通道、浮点范围、边界报错和相等左右边缘的保持。
当前制作环境未安装ComfyUI与PyTorch，未执行ComfyUI加载/界面运行测试；节点入口已作语法和注册结构检查。

参考官方接口：
- https://docs.comfy.org/custom-nodes/walkthrough
- https://docs.comfy.org/custom-nodes/backend/datatypes


