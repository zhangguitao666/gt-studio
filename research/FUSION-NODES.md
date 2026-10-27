# 可编辑节点图与首批节点执行

GT Studio 已加入片段局部节点图、Fusion 画布、共享 MCP 编辑和独立渲染。当前实现 MediaIn、MediaOut、Background、Transform、Merge 五种节点，是完整 Fusion 实现的第一步；不能证明原版功能或像素一致。

## 数据与操作

节点图保存在视频片段的 fusion_graph 字段。旧项目无需迁移或自动写入，读取缺省图返回 MediaIn1→MediaOut1。节点 ID 仅在单个片段内生效，因此分割可复制独立图。分离音频时不会把图带入音频片段。

节点图编辑提供六个公开 MCP 工具，另有节点检查点导出；当前合计 53 个公开工具：

| 工具 | 行为 |
| --- | --- |
| get_fusion_graph | 只读返回图、节点参数目录、输出完整性及限制 |
| add_fusion_node | 增加 MediaIn、Background、Transform 或 Merge |
| update_fusion_node | 更改参数、名称或画布位置 |
| connect_fusion_nodes | 连接来源 Output；省略 source_node_id 即断开 |
| delete_fusion_node | 删除节点并断开消费者，保留指定 MediaOut |
| clear_fusion_graph | 移除图，恢复直接媒体路径 |
| render_fusion_frame | 指定节点及片段内帧，导出进入片段/时间线处理之前的 RGBA16 PNG |

编辑通过原有事务和撤销机制；锁定轨道拒绝图变化。拒绝重复 ID、未知类型/参数、无效端口、缺失来源、循环及损坏的保存文件，失败整组回滚。图最多 64 个节点。编辑状态可以包含未连完整的节点，但视频渲染要求输出可达路径完整；未使用的节点不参与计算。渲染失败不覆盖已有导出。

Fusion 页面提供片段选择、节点画布、拖动布局、参数面板、连接/断开、删除及重置。它编辑的就是 MCP 所读数据，不另建界面副本。图变化进入已有时间线预览更新流程。未连完整的输出显示原因，避免不断提交必然失败的自动预览。

## 当前计算定义

MediaIn 是同一片段变速/倒放/定格后的源帧，先适配项目画布；不支持选择其他媒体或原版全尺寸/代理/缓存规则。MediaOut 指定唯一图输出。

Background 使用项目大小，RGBA 范围 0..1，并提供 Depth 0..4 图像位深选择（默认在当前模型中为8位）。Transform 提供统一 Size、逆时针 Angle、归一化 CenterX/CenterY，坐标原点在左下；当前使用逆映射浮点采样及相邻变换合并，暂不支持 Pivot、Aspect、边界模式、运动模糊或原版采样器。Merge 只支持关联 alpha-over、Blend 与中心位置，无效果蒙版或其他混合模式。Blend同时缩放前景RGB和Alpha；图输出经过关联值对应的片段透明度、淡化与时间线合成，再编码。音频路径保持原样。

编译器按输出可达子图排序，并为共享节点创建显式分支。恒等 MediaIn→MediaOut 走原先媒体处理路径，即使存在未使用节点也不额外转码滤镜；清空图后的实际解码 RGB/PCM 已与无图基准逐字节对照。

## 历史精度诊断与后续修正

真实像素测试暴露：当前打包 FFmpeg 的 auto/10-bit overlay 在透明画布上将蓝色压暗。半透明纯蓝经变换后，读取 RGBA16 的蓝通道只有约 16248，预期为 65535。显式 RGB 后约 65281，alpha 约 32896；详见 fusion-alpha-diagnostic.json 及可复跑脚本 diagnose_fusion_alpha.py。

检查点阶段因此临时使用8位RGB边界。后续原版Alpha/Blend/下层受控实验显示应保留关联RGB，包括Alpha=0的非零颜色。现已改为16位整数关联合成，Transform用pad/crop定位，Merge和Fusion主时间线显式计算背景衰减与前景相加，移除了该8位边界。仍在0..1饱和裁切，未达到浮点HDR、线性光色管或原版Fusion全算法等效。普通媒体恒等路径保持原样。详见 [FUSION-ASSOCIATED-ALPHA.md](FUSION-ASSOCIATED-ALPHA.md)。

## 验证

新增引擎检查覆盖持久化、分割图隔离、音频分离、撤销/重做、轨道锁定、错误回滚、损坏工程拒绝、未完整图、真实透明合成、共享节点分支、恒等精确输出、逆时针非对称旋转、分数帧率和非零时间线起点。Qt→HTTP 测试覆盖真实按钮、鼠标拖动、连接、参数修改、外部变化回显、锁定控件和实际预览。

verify_fusion_nodes.py 使用已配置的 MCP 启动器与私有服务，实际创建并保存 5 节点演示，导出 48 帧 MOV，检查三个时间位置的 RGB。带音频导出解码 PCM 与直接路径完全相同，分支合成、清空后的恒等 RGB/PCM、失败保留旧输出和工程重开均通过，见 fusion-node-verification.json。

用户手动解锁后，原生 CUA 验收已确认：MCP 切换 Fusion 页面、选中片段和节点、MCP CenterX=.6 回显、原生键盘输入并 Apply 将 .75 写回共享状态，播放/定位后可见合成。初次加载暂停预览黑屏问题也由真实窗口发现：Qt 的 Stopped 状态只加载元数据，不提交视频帧。现改为 LoadedMedia 后暂停解码，不短暂播放音频；冷启动后第 0 帧可见，且 MCP 请求历史没有播放命令。证据见 fusion-native-window-verification.json、fusion-native-final.png、fusion-native-paused-start.png。离屏截图另存 fusion-canvas-offscreen.png，不与真实窗口证据混淆。

仍需：扩充原版节点采样对照并校准已知差异、设置文件导入与宏绑定、关键帧和表达式、更多 2D/3D 节点、蒙版、GPU/插件、缓存/性能及完整交互。当前五节点目录、可执行导出和通过测试，均不是完整 Resolve 一致性的证明。

## 原版运行对照更新

已新增六组同尺寸原版输出及十二个带Alpha导出，24个选定原版任务均读回完成。测量暴露半透明输出、Merge颜色和音频残差，当前五节点仍不等效；详细结果及下一步校准见 [FUSION-REFERENCE.md](FUSION-REFERENCE.md)。

## 节点检查点更新

`render_fusion_frame` 的 frame 从0开始，按片段变速后的局部时间解释；省略 node_id 则取 MediaOut。它只计算所选节点可达分支，不经过片段调色、位置、透明度、轨道和字幕。生成器独立分支即使源媒体离线也可导出；锁定轨道允许导出，工程和撤销历史不变。失败保留既有输出，禁止覆盖源媒体和工程。

Fusion 页面所选节点面板底部提供 **Save selected node PNG…**。检查点阶段真实窗口保存与已配置MCP导出同一Transform/第0帧的PNG逐字节相同，新增12项回归，当时完整224项通过。此后预乘修正新增17项，当前242项通过。PNG保存16位关联样本，普通查看器可能按直通Alpha显示；不能把查看器观感等同于数值。历史六案例检查点测量见 [FUSION-CHECKPOINTS.md](FUSION-CHECKPOINTS.md)，当前算法与受控校准见 [FUSION-ASSOCIATED-ALPHA.md](FUSION-ASSOCIATED-ALPHA.md)。

Linux完整构建对照进一步发现混合叠化的普通媒体一侧仍走旧透明overlay画布；现将涉及Fusion的两侧统一为直接定位的关联画布，并在混合前确定两侧类型，补齐Fusion位于左/右两侧的回归。普通媒体对普通媒体的既有叠化路径不变。当前242项本机回归通过；远程结果见Actions。

媒体电平后续阶段已使用float32节点运算及逆映射变换，添加共享媒体电平设置。源缩放和时间线/PNG仍有整数边界，具体证据与限制见 [FUSION-MEDIA-LEVELS.md](FUSION-MEDIA-LEVELS.md)。

## 图像位深更新

后续编译器已采用 float32 载体、按节点位深量化及默认相邻 Transform 合并采样，取代上文历史 pad/crop/统一整数边界。18个原版 FFV1 RGBA16 案例首末帧经配置 MCP 重建共36幅摘要相同；最终编码颜色仍有残差，原版偏好继承和完整 Fusion 尚未实现。详见 [FUSION-IMAGE-PRECISION.md](FUSION-IMAGE-PRECISION.md)。
