# 天空底色扩充至正方形

新增 ComfyUI 节点：

`Sky Extend Bottom Color Square / 天空底色扩充至正方形`

输入 2048×1024 的 2:1 图片，保持原图像素与尺寸不变，放在新画布上半幅；读取原图最底一整行的平均色，纯色填充新增的下半幅，输出 2048×2048。

## Byteartist

插件地址：`https://github.com/fangfang-ship-it/fang.git`

分支：`main`

更新或重新下载插件并重新加载运行环境后，搜索 `Sky Extend Bottom Color Square` 或 `天空底色扩充至正方形`。

连接：`加载图像 → 天空底色扩充至正方形 → 保存图像`

节点兼容其他严格 2:1 尺寸，例如 4096×2048 → 4096×4096。节点不缩放、不裁切、不横向复制原图，也不进行 AI 扩图。
