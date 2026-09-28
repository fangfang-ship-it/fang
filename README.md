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



## AI Studio 3D Generate & Download / 3D 生成并下载

节点分类：`Fang/3D`。节点支持选择 AI Studio 供应商，提交生成任务、轮询状态，并将成功结果下载为 `output/douyin3d/douyin3d_<asset_id>.glb`。

当前供应商选项：

- `Douyin3D`：V3.1-fast / V3.1
- `混元3D`：3.0 / 3.1 / Express
- `Poly3D`：文字生成，并支持低模玩具、黏土手办、机械积木风格
- `Rodin`：Gen-1 / Gen-2 / Gen-2.5
- `Seed3D`：Seed3D 2.0
- `Tripo3D`：v3.1 / v3.0 / v2.5 / P1 / P2 Preview

`quality_preset` 提供快速预览、标准、高质量、超高质量和自定义。选择“推荐（随供应商）”时，节点会自动使用该供应商的推荐模型；误选其他供应商的模型名称时也会安全回退到当前供应商默认模型。

### 安全配置

凭证只从运行环境读取，不会写入节点参数或工作流 JSON。若要临时复用 `3d.bytedance.net` 的网站登录态并消耗该账号的网站积分，可在 ByteArtist/ComfyUI **运行环境**中注入：

```bash
export DOUYIN3D_CAS_SESSION='<仅填写 AGW_CAS_SESSION 的值>'
```

节点会在请求时生成 `Cookie: AGW_CAS_SESSION=<value>`。该环境变量优先于 API Key；不要填写完整的 `Cookie:` 请求头，也不要把它放入节点输入、工作流、截图、聊天记录或仓库。CAS 会话会过期，失效后需要在运行环境中更新并重启服务，因此此模式仅适合短期联调。

若已经取得服务端 Key，仍可使用更稳定的正式方式：

```bash
export DOUYIN3D_API_KEY='由服务负责人提供的服务端 Key'
export DOUYIN3D_AUTH_HEADER='Authorization'
export DOUYIN3D_AUTH_SCHEME='Bearer'
```

如果接口使用 `X-API-Key: <key>`，设置：

```bash
export DOUYIN3D_AUTH_HEADER='X-API-Key'
export DOUYIN3D_AUTH_SCHEME=''
```

不要把真实 Key、Cookie、CAS Session 或临时 ticket 提交到 GitHub。

### 最小链路

1. 安装本仓库并重启 ByteArtist/ComfyUI。
2. 搜索 `AI Studio 3D Generate & Download / 3D生成并下载`（旧工作流中的节点 ID 保持兼容）。
3. 选择供应商、模型和质量预设；首次测试建议 `Douyin3D + 推荐（随供应商）+ 快速预览`。
4. 成功后读取 `glb_path`、`glb_url`、`asset_id`；GLB 文件保存在 ComfyUI 输出目录。
5. 在原生 `Load 3D` / `Preview 3D` 中选择该 GLB，即可用鼠标旋转、缩放和平移查看。

图生 3D 可将 BA/ComfyUI 文生图节点的 `IMAGE` 直接连接到 `image`；PE/文本节点的输出可连接到 `prompt_input`，其内容会优先于节点内手填的 `prompt`。节点会将批次中的第一张图编码为 PNG，通过 AI Studio `POST /api/v1/files/upload` 上传，再把返回的 URL 传给生成接口；也保留 `image_url` 作为调试入口。Poly3D 当前仅开放文字生成，连接图片时会明确报错。

### 当前接口

- 提交：`POST /api/v1/assets/generate`
- 查询状态：`POST /api/v1/assets/status`
- 资产详情：`POST /api/v1/assets/detail`

节点会自动生成写接口所需的时间 ticket。正式环境建议使用可用于服务端调用的 Key；`DOUYIN3D_CAS_SESSION` 仅作为网站积分链路的短期联调方案，会随网站会话过期。

### 无 Key 的下游验证节点

`Douyin3D Download Existing GLB / 下载已有3D模型` 用于下载已经成功生成、且具有公开 URL 的 GLB，不调用生成 API，也不读取 Key。将其 `glb_path` 输出直接连接到原生 `Preview 3D` 的 `model_file`，可先验证“GLB 下载 → ByteArtist 3D 预览 → 鼠标旋转/缩放/平移”链路。

该节点仅用于验证生成后的下游链路；它不能替代正式的 Douyin3D 生成鉴权。
