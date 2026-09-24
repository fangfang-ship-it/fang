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

