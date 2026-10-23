# MediaIn 电平与浮点节点对照

原版受控实验确认：本次未标记RGB24 QTRLE素材在Auto下与Video电平表现相同，Full结果不同。显式控制源电平和保留节点负值/超白值后，旧MediaIn Merge中心色差已消除；完整色管、HDR与Fusion功能仍未达到原版等效。

## 原版证据

专用`REA Reference · 2026-10-21`工程中，使用同一自有红色视频的三个独立文件副本，分别设置Auto、Full和Video，不改动旧媒体项或用户工程。每种设置读回成功，建立Blend=0/.25/.5/.75/1、前景蓝色Alpha=.5的五条时间线，共15个640×360/24fps/12帧ProRes HQ任务。精确任务ID读回全部Complete/100%，无活动渲染。

| Blend | 原版Auto/Video中心RGB | 原版Full中心RGB |
| --- | --- | --- |
| 0 | 252,0,0 | 249,0,0 |
| .25 | 238,0,45 | 217,0,61 |
| .5 | 203,0,111 | 186,0,126 |
| .75 | 168,0,176 | 154,0,188 |
| 1 | 134,0,243 | 124,0,252 |

探针为`probe_resolve_fusion_media_levels.lua`及精确任务状态脚本，运行标记、媒体摘要及测量保存在本地`fusion-media-levels-runtime-all.json`、`fusion-media-levels-status.json`与`fusion-media-levels-measurements.json`。一致性SQLite backup快照经REA检查，Evidence ID为`ev_91fe636e0957049629ccb190b2fc10496f8a2cf341d8d33051849b048ae3692d`，其范围是数据库身份、结构和采样行；节点行为证据来自原版脚本回读及实际导出，不能把SQLite结构当成算法证明。

## 实现与操作

媒体池属性`data_level`持久保存Auto、Full或Video，所有时间线实例共享，并支持一次撤销/重做。MCP新增`set_media_data_level(media_id, mode)`，公开工具共53个。桌面选择片段后，检查器的**Source data level**（提示说明所有实例共享）及**Apply source data level**操作同一媒体属性；变化后刷新渲染预览。源检视器双击媒体仍是原文件播放。

导入时记录编码与像素格式；旧工程在渲染时只读探测缺失信息，离线节点分支仍保持原错误保护。Auto对本次已验证QTRLE采用Video解释，其他格式继续使用解码器解释，不推断所有原版Auto规则已覆盖。RGB Video映射使用本组8位素材的16/235黑白电平，并在节点图内保留负值和超白值；非RGB显式Full/Video使用解码范围覆盖，其完整原版矩阵仍需专项对照。

五节点运算改用float32关联RGBA，Merge保留超白/负值，Transform使用全画布逆映射双线性采样。避免默认swscale浮点RGB转整数产生串色；RGB用zscale量化、Alpha独立映射为RGB后也经zimg量化，再用16位mergeplanes合并。曾尝试alphamerge会协商为8位，已淘汰。源缩放/pad及时间线/PNG导出仍有整数边界，不能据此声称完整HDR等效；PNG仍是关联RGBA16且会裁掉超出0..1的数值。

## 验证

新增15项原版案例、设置共享/保存/撤销/非法输入回滚、float节点经旋转缩放后保留负值/超白值，以及UI→HTTP设置/外部回读/撤销检查。原帧编号素材检查显式选择Full电平，因为断言直接比较源RGB标签；保留原帧序列和像素上限，不以增加容差掩盖错误。

已配置stdio MCP在私有服务重放15组，全部12帧参与比较：10组RGB逐字节相同，其余5组MAE不超过0.666667、MSE不超过1.333333（0..255尺度）。报告`fusion-media-levels-comparison-float32.json`，精简夹具`tests/fixtures/fusion-media-levels.json`保留自有素材测量与摘要。

旧六组48帧重新对照：Background、fanout和媒体恒等全序列RGB相同；Merge MAE由3.386092降至0.051766，MSE由44.760979降至0.894886，中心样点203/0/111相同。旋转MAE0.082462、缩放MAE0.085567，仍有边缘残差；PCM MSE3866.6410625仍未消除。报告`fusion-native-media-comparison-media-levels.json`。旧报告保留，不覆盖历史测量，也不把静态导出视作原版内部缓冲。

首次Linux完整测试265通过、2失败，精确诊断显示Alpha=.5实际输出33516而非32768，RGB正常。问题位于FFmpeg灰度浮点量化的范围解释；改为Alpha映射到独立RGB平面并经zimg量化，保留原断言上限，新增0/.25/.75/1的PNG Alpha精确量化检查。旧失败报告保留，远程验证以最新提交Actions为准。

Alpha量化修正后本机完整271项通过，0失败、0跳过，49.55秒；当前Linux结果以相应提交CI为准。

后续音频边缘与MOV PCM24校准已消除本页六组案例的PCM差异；原MSE数值保留为历史测量。新证据、八组独立音频案例和明确限制见 [AUDIO-BOUNDARIES.md](AUDIO-BOUNDARIES.md)。
