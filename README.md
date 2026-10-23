# GT Studio — Resolve 功能重建项目

目标：以本机 DaVinci Resolve 21.1.1 为参照，逐项调查并实现独立的视频编辑软件，支持 MCP 操作。**目前为开发中的早期版本，尚未达到全部功能相同，也不兼容 Resolve 项目数据库。**

## 启动

双击 `GT Studio.app` 或 `Start GT Studio.command`，也可在本目录运行：

```bash
.venv/bin/python gt_studio.py ui
```

桌面界面与 MCP 共用本机服务 `http://127.0.0.1:18771`，操作同一个项目。关闭界面后服务仍可供 MCP 使用。项目需点击保存；撤销记录与渲染任务仅保存在服务内存中。

已安装的运行环境位于 `.venv`。换电脑安装：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

## 已实现的独立链路

- 新建/打开/原子保存 JSON 项目，媒体导入与探测。
- 轨道启用与锁定：`set_track_state(track_id, enabled?, locked?)`；界面选择轨道后使用 Enabled/Locked 和 Apply track state。视频开关控制画面，音频开关控制其音频；锁定阻止直接和间接关联片段修改，支持撤销/重做。原版锁轨 API 例外尚待运行对照。
- 多时间线、多视频/音频轨、按帧追加、分割、裁剪、移动、删除、同轨波纹删除、标记、撤销/重做；静态图片默认持续 5 秒。
- 基础曝光、对比度、饱和度、Gamma、音量、透明度、缩放、旋转、位移、视频和音频淡入淡出；真实 FFmpeg 多轨合成/混音，以及 H.264/AAC MP4、ProRes HQ/PCM MOV 和 PCM WAV 导出。
- 恒定变速、倒放和定格；可选择音高修正及同轨波纹调整。有理数源边界使非整数分割保留画面采样顺序。
- 独立音频片段：通过 Detach audio to track 或 MCP `detach_audio` 分离自带音频，保留源范围、变速、音量和淡入淡出，不重复混音；默认追加仍嵌入音频。
- 关联编辑：`detach_audio(..., linked=true)`、`link_clips(clip_ids)` 和 `unlink_clips(clip_id)` 管理链接。支持同步移动、速度/倒放/定格、两侧独立分组的分割、时间线边界裁剪，以及成员轨道波纹删除；普通删除只处理当前片段。
- 原子时序编辑：检查器 Apply clip timing 或 `trim_clip(clip_id, in_frame?, out_frame?, start_frame?)` 一次提交源范围和时间线位置，任一关联成员冲突则整体回滚。省略未改的源端点可保留分数帧相位；尚未完成原版所有检查器和链接选择规则。
- Cross Dissolve 交叉叠化：支持片段起点/终点添加、左/中/右对齐、按帧时长、删除、撤销和真实多轨合成；检查源素材余量。
- Unicode 多行 SRT 导入导出、按帧字幕编辑和样式；真实文字烧录及纯字幕尾段。
- 原生 PySide6 编辑界面；全部已公开编辑动作可通过 MCP 操作，共享实时状态。
- 后台渲染使用项目快照，编辑后的项目不会悄悄改变已经提交的渲染任务。

页面导航参照已安装软件的声明：Media、Photo、Cut、Edit、Fusion、Color、Fairlight、Deliver。页面标签不代表相应全部功能已实现；未完成能力会明确标注。

## MCP

启动 stdio 服务：

```bash
.venv/bin/python gt_studio.py mcp
```

Codex 配置使用绝对路径：

```toml
[mcp_servers.frameforge]
command = "/Users/zgt/agent/resolve-reconstruction/.venv/bin/python"
args = ["/Users/zgt/agent/resolve-reconstruction/gt_studio.py", "mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 450
```

重启 Codex 后，可请求：

> 用 GT Studio 新建项目，导入 `/绝对路径/视频.mp4`，加入时间线，在第 48 帧分割，将后半段饱和度设为 0，然后导出到 `/绝对路径/结果.mp4`。

当前公开 51 个 MCP 工具。`add_transition` 使用 `clip_id`、`position="start"/"end"`、`duration_frames`、`alignment="left"/"center"/"right"` 添加 Cross Dissolve；`delete_transition` 使用 `transition_id` 删除。两个相邻片段必须保留足够的源素材余量，否则添加失败且项目保持不变。当前未实现其他转场；会破坏已有转场的结构编辑需要先删除该转场。

工具的 `get_capabilities` 返回当前实现边界。变速使用 `set_clip_speed`：`percentage=50` 为半速，`-100` 为倒放，`0` 为定格；显式链接成员同步接收速度和音高选项；`ripple=true` 改变成员时长并移动各成员轨道的后续片段；关闭波纹时尽量保留时间线时长，源素材边界可能使其缩短。`pitch_correction` 控制音高修正。定格可传 `freeze_frame` 指定时间线帧；位于片段中间时保留前缀运动片段并定格尾段；关联成员按同一相对偏移定格，前后两侧分别链接。不传时优先使用位于片段内的共享播放头，否则从片段起点定格。字幕使用 `add_subtitle`、`import_subtitles`、`export_subtitles` 等工具。`set_page`、`set_playhead`、`set_playback` 控制已打开的桌面窗口；`get_transport` 区分已请求状态、桌面实际回报状态及是否连接，窗口关闭时命令保持待处理。`get_state` 返回实时项目，时间轴位置以项目帧率计，`out_frame` 不包含末端帧。`split_clip.frame` 是时间线上的绝对帧位置。`submit_render` 返回任务 ID，使用 `get_render_job` 查询。

MCP 操作的是 GT Studio 自己的项目与引擎。它没有借用安装版 Resolve 执行剪辑，也没有把接口封装当作独立功能复刻完成。

## 证据与验证

- `research/evidence/resolve-plist.json`、`resolve-macho.json`、`resolve-artifact.json`：REA 原始静态证据，包含目标摘要与证据 ID。
- `research/feature-inventory.json`：已安装脚本 API 的 416 个方法声明、类型和行号；不代表功能已验证。
- `research/FIDELITY.md`：完整一致性要求和未完成项目。
- `research/REA-FINDINGS.md`：REA 分析结果与限制。

运行测试与完整示例：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/verify_demo.py
.venv/bin/python scripts/verify_retime_subtitles.py
.venv/bin/python scripts/verify_reference_retime.py
.venv/bin/python scripts/verify_reference_transitions.py --run-name precision
.venv/bin/python scripts/verify_detached_audio.py
.venv/bin/python scripts/verify_linked_split.py
.venv/bin/python scripts/verify_linked_move.py
.venv/bin/python scripts/verify_linked_trim.py
.venv/bin/python scripts/verify_linked_trim.py --source-fields
.venv/bin/python scripts/verify_linked_retime.py --run-name precision
.venv/bin/python scripts/verify_track_state.py
```

在桌面窗口已打开并载入示例项目后，可以验证已注册的 MCP 是否能驱动实际窗口：

```bash
.venv/bin/python scripts/verify_native_control.py
```

该验证会切换到 Color 页、跳到第 24 帧、播放后暂停。结果见 `research/native-mcp-verification.json`。

示例生成自有测试素材，经 MCP 导入、分割、调色、保存、后台导出，再用 FFmpeg 解码检验。结果写入 `research/demo-verification.json`，示例项目和视频位于 `workspace/`。这证明该测试工作流可运行，不能证明 Resolve 全功能一致。

## 后续仍需实现和对照验证

完整 Fusion 节点引擎（目前已有五节点子集）、完整调色/ACES/HDR/追踪/降噪、Fairlight DSP/总线/插件、AI 模型、RAW/完整编解码矩阵、完整字幕/标题系统、高级剪辑与变速曲线、数据库及协作、硬件与性能、完整交互及显示一致性。实际功能范围还需要结合本机运行行为、手册和专项素材逐项补齐。

产品名称为 **GT Studio**。内部 `frameforge` Python 模块、旧命令入口及现有 MCP 注册键保留兼容；MCP 初始化显示 GT Studio，资源使用 `gt-studio://`，同时接受旧资源 URI。

原版实际媒体对照见 [NATIVE-MEDIA-COMPARISON.md](research/NATIVE-MEDIA-COMPARISON.md)，命名验收见 `research/branding-verification.json`。当前画面像素、变速音频及其他完整功能仍有差异。

当前专项证据：

- 交叉叠化：[TRANSITION-REFERENCE.md](research/TRANSITION-REFERENCE.md)。
- 音频分离与链接删除：`research/linked-audio-verification.json`。
- 关联分割：[LINKED-SPLIT-REFERENCE.md](research/LINKED-SPLIT-REFERENCE.md)。
- 关联移动：[LINKED-MOVE-REFERENCE.md](research/LINKED-MOVE-REFERENCE.md)。
- 关联时间线边界裁剪：[LINKED-TRIM-REFERENCE.md](research/LINKED-TRIM-REFERENCE.md)。

52个公开MCP工具。服务重连使用会话标识，窗口可在服务重启后重新接受低序号请求。上述专项仅证明报告中列出的操作、素材和输出，完整Resolve一致性仍未达到。

当前完整测试248项通过，52个公开MCP工具。高精度中间格式使十组原版样本MSE下降约30%–32%，仍有残差；详见 [COLOR-PRECISION.md](research/COLOR-PRECISION.md)。完整色彩管理和功能一致性尚未达到。Fusion 页面、MCP 参数回显/界面写回及暂停第0帧已完成真实窗口验收，其余专项窗口检查仍需补齐。

Fusion 文件检查入口 `inspect_fusion_settings(path, detail="summary"/"nodes", offset=0, limit=25)` 已实测本机三个模板及一个示例合成，共83个活动节点/133条显式连接；它只读结构，不导入或执行节点。详见 [FUSION-SETTINGS.md](research/FUSION-SETTINGS.md)。

可编辑节点图已接入 Fusion 页面及导出：`get_fusion_graph`、`add_fusion_node`、`update_fusion_node`、`connect_fusion_nodes`、`delete_fusion_node`、`clear_fusion_graph`。当前五节点为 MediaIn、MediaOut、Background、Transform、Merge；Transform/Merge 使用16位整数关联合成并在0..1饱和裁切，完整原版算法等效尚未验证。见 [FUSION-NODES.md](research/FUSION-NODES.md)。桌面演示单独保存到 `workspace/GT Studio Fusion Desktop Demo.json`，可复跑 MCP 验证使用独立工程和媒体。

原版Fusion运行对照已建立：六组640×360/24fps/48帧案例以及十二个带Alpha导出。当前透明输出和Merge存在显著差距，参见 [FUSION-REFERENCE.md](research/FUSION-REFERENCE.md)。248项测试是独立行为回归，不代表原版功能一致。

节点检查点可使用 `render_fusion_frame(clip_id, output, node_id?, frame=0)` 导出 RGBA16 PNG；Fusion 页面选中节点后点击 **Save selected node PNG…**，按钮位于节点面板底部。GUI 使用当前播放头对应的片段内帧，播放头不在该片段内则保存第0帧。真实窗口与已配置MCP保存的PNG已逐字节核对相同。六组检查点对照把时间线半透明变暗与Merge节点色差进一步分开，见 [FUSION-CHECKPOINTS.md](research/FUSION-CHECKPOINTS.md)。

关联Alpha合成修正已按原版26个导出任务校准：13个受控案例中9组全序列RGB逐字节相同，原先半透明背景/共享分支48帧也完全相同；MediaIn颜色与几何边缘仍有残差。当前248项回归通过，详见 [FUSION-ASSOCIATED-ALPHA.md](research/FUSION-ASSOCIATED-ALPHA.md)。代码持续推送到 [GitHub](https://github.com/zhangguitao666/gt-studio)。

Linux CI使用固定摘要的完整FFmpeg构建执行全部检查；字幕滤镜、意外错误框和巨大字节差异的诊断说明见 [CI-VALIDATION.md](research/CI-VALIDATION.md)。远程结果以 [GitHub Actions](https://github.com/zhangguitao666/gt-studio/actions) 为准，本机测试通过不代替远程结果或原版全功能验收。
