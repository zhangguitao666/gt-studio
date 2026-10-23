# 原版 Fusion 六案例与 Alpha 输出测量

本轮首次将已有五节点实现与本机原版 Fusion 实际输出对照。结论是仍不等效，特别是半透明输出和 Merge；不能用此前独立像素测试通过来证明原版一致性。

## 采集范围和来源

只在原版专用工程 REA Reference · 2026-10-21 新建合成测试时间线，素材由独立 FFmpeg 生成，不改用户工程、原始媒体或应用首选项。CUA 从工作区脚本菜单运行本地 Lua 探针，使用 TimelineItem.AddFusionComp、Composition.AddTool、SetInput、ConnectInput 和 GetToolList 建图并读取参数及连接。

原版返回 21.1.1.10，节点类型实际为 MediaIn、MediaOut、Background、Transform、Merge。数字参数写入后读回校验，图中连接也从 GetConnectedOutput 的工具名和输出端口恢复。设置文件声明与本轮实际运行证据分开。

每个案例保留原版时间线标记 JSON。使用 SQLite backup API 创建一致性快照，再从 BtLockableBlob 中的 Zstd 数据提取标记；保留快照 SHA-256、字段/压缩帧/JSON 字节定位。REA CLI 对快照进行 SQLite 检查，证据为：

- 首批快照：reference-fusion-nodes-v1-rea-sqlite.json，Evidence ev_7b5c68cf243d1fe147410b4bac163dcfd5801a71c3b306380d66d269f3323517。
- 同尺寸快照：reference-fusion-nodes-v2-rea-sqlite.json，Evidence ev_39c2c1afa1b48f6dfb2c1e6573a0992a0d1c9e0b6b001c86832fb6187f5b36d8。

REA 在此证明快照身份、结构和受限行检查；节点语义来自原版 Lua 运行记录及落盘媒体，不能把 SQLite 检查说成自动验证了 Fusion 算法。

## 画布限制和两批 RGB 导出

首批请求 320×180，Timeline.SetSetting 返回 true，但实际 GetSetting 和导出高度为 256。合成帧格式仍为 320×180。这批 6 个结果完整保留，用来证明设置成功返回不等于尺寸按请求生效，不作为同尺寸误差基准。

第二批重新生成 640×360 素材，明确设置同尺寸时间线、Background 和导出。读回确认 640×360、24 fps，每条 48 帧。六种图为直接媒体、半透明蓝背景、右上方半尺寸变换、与红色媒体半混合、再逆时针旋转 90°、同一背景分支复用到 Merge 两输入。

使用已配置的 GT Studio MCP 启动器，在私有服务重建同一组数值参数并实际导出；当前公开工具 51 个。对全部 48 帧解码 RGB 计算误差，不以“命令成功”替代媒体对照。记录 fusion-native-media-comparison.json：

| 案例 | RGB MAE（0–255） | RGB MSE |
| --- | ---: | ---: |
| 直接媒体 | 1.000000 | 3.000000 |
| 半透明背景 | 42.666667 | 5461.333333 |
| 半尺寸变换 | 10.623762 | 1351.634013 |
| 半混合 | 6.317713 | 232.773485 |
| 90° 旋转 | 0.088695 | 3.956698 |
| 共享分支 | 21.333333 | 1365.333333 |

半透明背景原版蓝通道约 253，独立输出约 125；共享分支原版约 253，独立约 189。半混合区域原版约 [203,0,111]，独立约 [186,0,61]。旋转主要区域位置一致，阈值边界相差约 1–2 像素，仍有边缘滤波和编码残差。

六组音频都为相同长度，但解码 PCM 仍不完全相同，本组 MSE 为 3866.6410625。没有把音频差异归因于图像节点，也没有据此修改增益或拟合参数。

## 十二个带 Alpha 导出

在同一批六条原版图上导出 ProRes 4444，分别请求 ExportAlpha=true、AlphaMode=0/1。GetRenderJobList 元数据保留了两个模式，24 个选定任务（首批 6、同尺寸 6、Alpha 12）均由 GetRenderJobStatus 读回 Complete/100%，当前 IsRenderingInProgress=false，见 fusion-native-status.json。

每个 Alpha 文件用固定身份的 FFmpeg 解码全部 48 帧 RGBA16，保留逐帧 MD5、视频包 SHA-256 和采样值。两个模式在本批六对文件中，视频包及解码帧均相同。这是特定导出的观察，不能推广为 AlphaMode 在所有原版格式中无效。

示例 RGBA16：半透明背景约 [0,13,65322,32896]，共享分支约 [0,13,65322,49344]；混合区域约 [52736,0,29083,65520]。这些是导出文件的 FFmpeg 解码值，不能当作 Fusion 内部工作缓冲的直接读数。

通过当前 Lua 对象尝试读取图像像素时，GetPixel 未暴露，Pixel/FuPixel 也未提供；失败已记录为未知。第一版 Alpha 探针还误用了不存在的 GetRenderSettings，12 次均在 AddRenderJob 前失败；保留 attempt1 快照及错误后移除此调用重跑，未把失败尝试计入完成任务。

工程实际设置读回为 davinciYRGB、自动色管关闭，colorSpaceInput 为 Rec.709 Gamma 2.4，colorSpaceTimeline/colorSpaceOutput 为 Rec.709 (Scene)。初轮尝试的 timelineColorSpace 等别名返回空串，不能据空串推断工程没有颜色设置。以上设置和数据尚不足以唯一定位合成差异的原因。

## 重放和后续校准

运行 scripts/compare_native_fusion.py 可重建六组独立结果；改算法后应传 --run-name NAME，将新工程、媒体和报告保存到独立位置，保留当前基线。scripts/measure_native_fusion_alpha.py 复核原版 Alpha 媒体、逐帧身份和像素。

后续优先建立独立节点 RGBA 检查点，并增加透明/不透明下层、Blend/Alpha 梯度的受控案例，将节点计算、时间线底图、预乘约定、色彩处理和编码残差分开验证。不能仅给 MediaOut 硬编码“忽略 Alpha”来匹配纯蓝样本。当前生产代码未据不充分原因修改，原有 212 项测试和 51 工具不构成原版一致性证明。完整功能目标仍未完成。

后续音频边缘与MOV PCM24校准已消除本页六组案例的PCM差异；原MSE数值保留为历史测量。新证据、八组独立音频案例和明确限制见 [AUDIO-BOUNDARIES.md](AUDIO-BOUNDARIES.md)。
