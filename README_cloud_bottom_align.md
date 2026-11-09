# 最低云端识别数值解析与垂直对齐

该流程把语义判断和确定性像素处理分开：识图模型负责判断最低云端位置，自定义节点负责安全解析数值、移动图片和纯色补空。

## 推荐链路

`加载图像 → 识图模型`  
`识图模型文字输出 → Sky Parse Cloud Bottom %`  
`加载图像 + 解析出的 FLOAT → Sky Align Cloud Bottom → 保存图像`

## 识图模型提示词

请分析输入天空图，寻找画面中最低仍能辨认为云形轮廓的像素位置。不要把霞光、地平线亮带、纯色渐变、雾霾或填充区算作云。高度从画面顶边0%向下计算，底边为100%。只输出以下JSON，不要输出分析、单位、代码块或其他数字：

`{"cloud_bottom_percent":46.5}`

其中数值替换为实际结果，保留一位小数。

## 节点一：Sky Parse Cloud Bottom %

- 优先读取 `cloud_bottom_percent` 字段。
- 也接受唯一一个带 `%` 的数值或只有一个数字的纯文本。
- 文本含多个不明确数字时停止报错，避免误把分辨率、置信度等数值当成云底。
- 输出 `cloud_bottom_percent`（FLOAT）和解析说明。

## 节点二：Sky Align Cloud Bottom

- `cloud_bottom_percent`：连接解析节点，或手动输入。
- `target_percent`：默认 `49.7`，即当前参考线位置。
- `max_shift_percent`：默认 `15`。所需位移超过限制时停止，防止模型误识别导致整张图被大幅移动。
- `fill_sample_rows`：默认 `1`，用于计算露空区域的纯色。

图片仅做整数像素垂直平移，不缩放。向下移动时顶部空区使用原图顶边平均色；向上移动时底部空区使用原图底边平均色。输出移动后的图片、移动像素、识别位置、目标位置和处理说明。

例如：输入高度1024，识图结果46.5%，目标49.7%，节点向下移动约33像素，并在顶部补纯色。

## Byteartist

插件地址：`https://github.com/fangfang-ship-it/fang.git`

分支：`main`

更新插件并重新加载运行环境后，搜索 `Sky Parse Cloud Bottom` 和 `Sky Align Cloud Bottom`。
