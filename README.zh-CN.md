# ComfyUI-Video-Segment-Writer

**视频分段保存与合成**

[English](README.md) | [简体中文](README.zh-CN.md)

用于 MieLoop v3 工作流，将每段解码后的画面与音频流式写入磁盘，循环完成后直接复制码流拼接成 MP4。适用于 H3，也可用于其他能输出标准 IMAGE/AUDIO 的视频工作流。

本插件不会去除续写重叠，也不校验口型同步。每段独立编码 AAC；不足的视频时长会由静音补齐，多余音频按视频时长截断。对严格连续音轨需求，使用 ComfyUI-H3-AV-Continuation。

## 安装

将本仓库克隆或解压至 `ComfyUI/custom_nodes/ComfyUI-Video-Segment-Writer/`，该目录内须直接包含 `__init__.py`。使用运行 ComfyUI 的同一个 Python 安装依赖：

```bash
python -m pip install -r custom_nodes/ComfyUI-Video-Segment-Writer/requirements.txt
```

Windows 便携版（在便携版根目录执行）：

```powershell
.\python_embeded\python.exe -m pip install -r .\ComfyUI\custom_nodes\ComfyUI-Video-Segment-Writer\requirements.txt
```

重启 ComfyUI 并刷新浏览器。需要 FFmpeg 支持 `libx264` 与 `aac`；优先使用 PATH 中的 FFmpeg，否则使用 imageio-ffmpeg 自带程序。

需要提供 `MIE_LOOP_CTX` v3 的 MieLoop 插件。该上下文至少含 `version=3`、24 位小写十六进制 `run_id`、从 0 开始的 `index`、正整数 `count`。本仓库不包含循环节点。

## 语言与兼容性

节点所属插件分类、节点标题、参数名称、输入输出名称、提示说明及下拉选项均提供中英文。跟随 ComfyUI 设置中的 `Comfy > Locale > Language`（`Comfy.Locale`）显示；`zh` 为简体中文，其余未提供的语言回退英文。

翻译使用 ComfyUI 原生 `locales/en` 与 `locales/zh`；前端扩展在语言切换时同步更新已存在的画布节点。自定义标题会保留。需使用支持 `/api/i18n` 的 ComfyUI；旧前端若未刷新节点搜索菜单，请刷新页面。GitHub 仓库名和安装文件夹名固定，不随语言更改。

Original node IDs, socket keys, input order, defaults and output directories are preserved for existing workflows.

迁移时仅安装新文件夹，移走旧 `h3_disk_video`，避免重复注册同一节点。

[ComfyUI 官方多语言文档](https://docs.comfy.org/custom-nodes/i18n)

## 典型连接方式

1. 将 MieLoop 的 `loop_ctx`、本段解码 `images` 与 `audio` 接入分段保存节点，所有段使用相同分辨率、帧率、声道与编码设置。
2. 将保存节点返回的 `loop_ctx` 接回循环，确保落盘后再推进下一段。
3. 循环结束后的 `loop_ctx` 与 `done` 接入分段合成，输出最终 MP4。

## 节点及参数

### 视频分段保存（H.264 + AAC）

`H3DiskEncodeSegment`

将一段解码后的音画流式写入磁盘 MP4，并在有序清单中记录帧数。

| 输入（内部标识） | 显示名称 | 类型 / 默认值 | 用途 |
| --- | --- | --- | --- |
| `loop_ctx` | 循环上下文 | MIE_LOOP_CTX | 连接 MieLoop v3 的循环上下文，用于识别本次运行及当前分段序号。 |
| `images` | 视频帧 | IMAGE | 解码后的 RGB IMAGE 批次，形状为 [帧数, 高, 宽, 3]；H.264 要求宽高为偶数。 |
| `audio` | 本段音频 | AUDIO | 与画面同段的解码 AUDIO，含 [1, 声道, 采样点] waveform 和正数 sample_rate。 |
| `fps` | 帧率 | INT / `24` | 每秒帧数；同一次运行中所有分段须保持一致。 |
| `crf` | H.264 质量（CRF） | INT / `19` | 恒定质量系数，范围 0–51；数值越小质量越高、文件越大，默认 19。 |
| `preset` | H.264 编码速度预设 | medium/fast/veryfast/slow | medium 为均衡；fast/veryfast 缩短编码时间；slow 在相同 CRF 下花更多时间改善压缩。 |

| 输出序号 | 显示名称 | 类型 | 含义 |
| --- | --- | --- | --- |
| 0 | 循环上下文 | `MIE_LOOP_CTX` | 连接 MieLoop v3 的循环上下文，用于识别本次运行及当前分段序号。 |
| 1 | 分段 MP4 路径 | `STRING` | 已编码的 H.264/AAC 分段 MP4 的绝对路径。 |

### 视频分段合成（直接复制码流）

`H3DiskConcat`

循环完成后，将全部已提交 MP4 分段直接复制码流拼接，不重新编码视频或音频。

| 输入（内部标识） | 显示名称 | 类型 / 默认值 | 用途 |
| --- | --- | --- | --- |
| `loop_ctx` | 循环上下文 | MIE_LOOP_CTX | 连接 MieLoop v3 的循环上下文，用于识别本次运行及当前分段序号。 |
| `done` | 循环已完成 | BOOLEAN / 须连接 | 连接 MieLoop 的完成标记；仅在值为真且所有段已提交时执行拼接。 |

| 输出序号 | 显示名称 | 类型 | 含义 |
| --- | --- | --- | --- |
| 0 | 最终 MP4 路径 | `STRING` | 拼接后的最终 MP4 绝对路径，同时含画面与音频。 |

## 文件与故障排查

输出目录：`ComfyUI/output/h3_long_video/<run_id>/`，兼容原插件路径。

- `manifest.json`：按提交顺序记录分段；`final.mp4`：最终成片；`*.log`：FFmpeg 日志。
- 至少预留 2 GiB 空闲磁盘空间。合成时还需大于分段总大小加 1 GiB 的剩余空间。磁盘不足时已完成分段保留。
- 发生覆盖、清单或段序号错误时，检查连接并使用新的循环 run_id；不要删除清单后继续沿用旧分段。分段必须按顺序执行，不能并行写同一 run_id。

每个 `segment_*.mp4` 都含 H.264 视频与 48 kHz 双声道 AAC 音频。最终直接拼接这些已编码段；不会修正独立 AAC 编码造成的接缝、延迟或填充。

## 开发验证

```bash
python -m unittest discover -s tests -v
node --test tests/localization.test.mjs
```

测试覆盖双语节点/参数/选项完整性、旧节点与参数兼容、语言切换保留连接和值、主要计划或循环控制分支。真实模型生成需在安装了 H3 与 MieLoop 的 ComfyUI 中验证。
