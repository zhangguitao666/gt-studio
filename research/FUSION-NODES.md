# 可编辑节点图与首批节点执行

GT Studio 已加入片段局部节点图、Fusion 画布、共享 MCP 编辑和独立渲染。当前实现 MediaIn、MediaOut、Background、Transform、Merge 五种节点，是完整 Fusion 实现的第一步；不能证明原版功能或像素一致。

## 数据与操作

节点图保存在视频片段的 fusion_graph 字段。旧项目无需迁移或自动写入，读取缺省图返回 MediaIn1→MediaOut1。节点 ID 仅在单个片段内生效，因此分割可复制独立图。分离音频时不会把图带入音频片段。

新增六个公开 MCP 工具，合计 51 个：

| 工具 | 行为 |
| --- | --- |
| get_fusion_graph | 只读返回图、节点参数目录、输出完整性及限制 |
| add_fusion_node | 增加 MediaIn、Background、Transform 或 Merge |
| update_fusion_node | 更改参数、名称或画布位置 |
| connect_fusion_nodes | 连接来源 Output；省略 source_node_id 即断开 |
| delete_fusion_node | 删除节点并断开消费者，保留指定 MediaOut |
| clear_fusion_graph | 移除图，恢复直接媒体路径 |

编辑通过原有事务和撤销机制；锁定轨道拒绝图变化。拒绝重复 ID、未知类型/参数、无效端口、缺失来源、循环及损坏的保存文件，失败整组回滚。图最多 64 个节点。编辑状态可以包含未连完整的节点，但视频渲染要求输出可达路径完整；未使用的节点不参与计算。渲染失败不覆盖已有导出。

Fusion 页面提供片段选择、节点画布、拖动布局、参数面板、连接/断开、删除及重置。它编辑的就是 MCP 所读数据，不另建界面副本。图变化进入已有时间线预览更新流程。未连完整的输出显示原因，避免不断提交必然失败的自动预览。

## 当前计算定义

MediaIn 是同一片段变速/倒放/定格后的源帧，先适配项目画布；不支持选择其他媒体或原版全尺寸/代理/缓存规则。MediaOut 指定唯一图输出。

Background 使用项目大小，RGBA 范围 0..1。Transform 提供统一 Size、逆时针 Angle、归一化 CenterX/CenterY，坐标原点在左下；当前缩放尺寸取偶数，暂不支持 Pivot、Aspect、边界模式、运动模糊或原版采样器。Merge 只支持普通 alpha-over、Blend 与中心位置，无效果蒙版或其他混合模式。图输出先进入原有片段调色、变换、淡化和轨道合成，再编码。音频路径保持原样。

编译器按输出可达子图排序，并为共享节点创建显式分支。恒等 MediaIn→MediaOut 走原先媒体处理路径，即使存在未使用节点也不额外转码滤镜；清空图后的实际解码 RGB/PCM 已与无图基准逐字节对照。

## 精度诊断

真实像素测试暴露：当前打包 FFmpeg 的 auto/10-bit overlay 在透明画布上将蓝色压暗。半透明纯蓝经变换后，读取 RGBA16 的蓝通道只有约 16248，预期为 65535。显式 RGB 后约 65281，alpha 约 32896；详见 fusion-alpha-diagnostic.json 及可复跑脚本 diagnose_fusion_alpha.py。

因此 Transform/Merge 目前显式经过 8 位 RGB 合成边界，以保留正确的直通 alpha 行为。其它原有片段的 16 位中间格式/10 位主叠加路径未因此改动。不能将此实现描述为全 16 位合成、线性光或原版 Fusion 等效算法。

## 验证

新增引擎检查覆盖持久化、分割图隔离、音频分离、撤销/重做、轨道锁定、错误回滚、损坏工程拒绝、未完整图、真实透明合成、共享节点分支、恒等精确输出、逆时针非对称旋转、分数帧率和非零时间线起点。Qt→HTTP 测试覆盖真实按钮、鼠标拖动、连接、参数修改、外部变化回显、锁定控件和实际预览。

verify_fusion_nodes.py 使用已配置的 MCP 启动器与私有服务，实际创建并保存 5 节点演示，导出 48 帧 MOV，检查三个时间位置的 RGB。带音频导出解码 PCM 与直接路径完全相同，分支合成、清空后的恒等 RGB/PCM、失败保留旧输出和工程重开均通过，见 fusion-node-verification.json。

用户手动解锁后，原生 CUA 验收已确认：MCP 切换 Fusion 页面、选中片段和节点、MCP CenterX=.6 回显、原生键盘输入并 Apply 将 .75 写回共享状态，播放/定位后可见合成。初次加载暂停预览黑屏问题也由真实窗口发现：Qt 的 Stopped 状态只加载元数据，不提交视频帧。现改为 LoadedMedia 后暂停解码，不短暂播放音频；冷启动后第 0 帧可见，且 MCP 请求历史没有播放命令。证据见 fusion-native-window-verification.json、fusion-native-final.png、fusion-native-paused-start.png。离屏截图另存 fusion-canvas-offscreen.png，不与真实窗口证据混淆。

仍需：原版节点运行/采样输出对照、设置文件导入与宏绑定、关键帧和表达式、更多 2D/3D 节点、蒙版、GPU/插件、缓存/性能及完整交互。当前五节点目录、可执行导出和通过测试，均不是完整 Resolve 一致性的证明。
