# 原版变速与定格对照

原始目标仍是完整独立重建。以下仅描述原版专用参考项目中的有限调用，不能替代画面、音频或全部功能一致性证明。

## 原始证据

Resolve 内置 Console 执行修正后的 `scripts/probe_resolve_retime.lua`，创建七条全新时间线。与首次失败的构造不同，这次逐次追加两个片段，检查数量及相邻边界，再读取操作前后状态。七次 SetSpeed 均返回 true。源码输入为自制 motion.mp4；项目 24 fps，第一段持续 47 帧，第二段原始起点为时间线相对第 47 帧。

结果作为 JSON 写入各自时间线的标记 note/customData，随参考项目保存；SQLite backup API 产生一致性快照 `evidence/reference-retime-v2.sqlite`，SHA-256 `022e9aca082b2e6f5e60c363d851480e66d3056f4f88714e1d5fd7dd101dcfb7`。REA 检查 `BtLockableBlob` 的 ID 和 FieldsBlob：`evidence/resolve-retime-v2-markers.json`，Evidence ID `ev_9780513f99f12321f7089237e6c48243b1ce66eb360bd246683009751a0ae899`。

当前 MCP 的 SQLite worker 缺少所需 Node DatabaseSync.limits；本次证据由现有 Node 24 运行的 REA 6.7.0 CLI 取得，并未调整客户端或系统设置。

`scripts/extract_resolve_retime_markers.py` 只读离线快照，使用已安装 libzstd 解压标准帧，单条输出上限 1 MiB。只提取包含本项目自写标记名的 JSON，保留源主键、blob/解压内容/JSON 摘要和字节偏移；每条标记中的两份 JSON 完全相同。没有推断外围私有二进制结构。完整七组调用见 `retime-runtime-v2.json`。

| 百分比 | 波纹 | 原版首段时长 | 原版后段相对起点 |
| --- | --- | --- | --- |
| 100 | 关闭 | 47 | 47 |
| 200 | 关闭 | 36 | 47 |
| 50 | 关闭 | 47 | 47 |
| 200 | 开启 | 23 | 23 |
| 50 | 开启 | 94 | 94 |
| -100 | 关闭 | 47 | 47 |
| 0 | 关闭 | 47 | 47 |

关闭波纹时并非总按源范围除以速度改变时间线时长。原版在这些案例中保留时长并改变源使用范围，源边界限制了 200% 案例。开启波纹的 47/2 得到 23 帧，与此前独立实现的四舍五入 24 帧不同。不能仅由这几个数字推导所有帧率、重复变速、倒放和源范围的取舍。

## 定格播放头实验

通过原版 Workspace > Scripts 执行 `scripts/probe_resolve_freeze.lua`，分别将播放头设为片段内第 0、12、46 帧。SetCurrentTimecode 和 SetSpeed 均成功。首次读回发现原片段句柄只指向分割后的前缀，补充读取全部片段后确认：

| 播放头 | 原版结果（时间线相对起点 / 时长 / 速度） |
| --- | --- |
| 0 | 0 / 47 / 0%；47 / 47 / 100% |
| 12 | 0 / 12 / 100%；12 / 35 / 0%；47 / 47 / 100% |
| 46 | 0 / 46 / 100%；46 / 1 / 0%；47 / 47 / 100% |

定格尾段的源起止读回均为播放头对应源帧。快照 `evidence/reference-freeze-all-v3.sqlite` 与提取报告 `freeze-all-runtime-v3.json` 保留原始内容和摘要。报告还包含此前案例，最新含 after.all 的三条记录才覆盖完整片段列表。

## 独立实现验证范围

`scripts/verify_reference_retime.py` 通过独立 stdio MCP 重放七组变速与三组定格，并将视频片段数量、相对起点、时长及速度和原版读回比较。结果保存在 `reference-retime-comparison.json`；只有报告明确标为 passed 才表示这十组结构比较通过。

源边界 API 与内部有理数半开区间不直接等同。原版与独立输出的解码像素/音频、原版关联音频项、其他轨道波纹范围、播放头位于片段外、变速曲线和光流均不在此项比较范围。完整一致性仍未达到。
