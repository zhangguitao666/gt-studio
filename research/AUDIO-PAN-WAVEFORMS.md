# 声像波形：自动淡变应在声像增益之前

原版七组新波形揭示了直流基准无法区分的计算顺序。旧实现对六组非零声像的片尾合计有11个PCM24标量差异，每个差异为一个量化单位。改为先执行源样本自动淡变，再乘float32声像增益后，七组完整流精确一致；既有14组PCM24和3组PCM32基准继续成立。没有放宽容差或使用原版PCM作为渲染查找表。

## 原版运行和可复跑材料

仅使用专用 `REA Reference · 2026-10-21` 工程和自有两秒S16测试源。工程/导出48kHz、时间线24fps、48帧、音量0dB、默认双声道总线。单声道正弦测试pan=13/37/67/100，双声道不同波形测试pan=-37/0/100。脚本为 `probe_resolve_audio_pan_waveform.lua`，另有保存精确任务ID的状态脚本。七项任务均最终Complete/100%，rendering=false；导出为实际的双声道MOV PCM24。属性、时长和声像启用状态均已读回。

`tests/fixtures/audio-pan-waveforms.json` 保存两个输入完整S16 PCM、七个完整导出S32载体PCM的压缩数据和SHA256、原始导出文件摘要、任务终态及属性读回。每个输出96000样本帧、192000个声道标量，共768000字节S32载体。夹具只包含自有合成信号，没有原版程序、数据库或用户媒体。

保存标记从SQLite一致性backup快照提取，快照SHA256为 `4ff4c67d2d0b8287b93222d6e71f9d9018b5b82ba897fefcf271ab3a9bc3ab53`。REA MCP本轮因其运行时缺少DatabaseSync.limits而返回capability_unavailable；使用本机已有Node24.22.1运行REA CLI成功，Evidence `ev_3b0d7724c153c41f51e2f94a69976240839fd949d4722226ec98f4061dbaf843`。检查仅覆盖快照身份、表结构与一行主键，不把它称为DSP反编译或标记语义验证。行为证据来自保存的探测记录、精确任务终态和真实导出PCM。

## 数值顺序

旧实现为 `float32(float32(source*panGain)*float32(edge))`，新的受控波形要求 `float32(float32(source*edgeDouble)*panGain)`。自动边缘仍是48kHz下72样本线性淡变；源淡变使用afade的双精度系数，结果进入float32声像乘法。直流源为二进制精确幅度，不能唯一确定这两个步骤的顺序，因此首轮直流匹配不足以证明一般波形正确。

|案例|修正前不同标量数|修正后|
|---|---:|---:|
|sine_13|1|0|
|sine_37|1|0|
|sine_67|1|0|
|sine_100|2|0|
|stereo_neg37|1|0|
|stereo_0|0|0|
|stereo_100|5|0|

`tests/test_audio_pan_waveforms.py`严格比较全流；没有片尾豁免。`compare_native_audio_pan.py --run-name NAME --fixture tests/fixtures/audio-pan-waveforms.json`通过配置中的stdio MCP重建并保存重开工程，比较同一批全流。默认不带fixture参数仍重放原有14组直流。新七组、旧14组MCP重放均已精确一致。本机完整330项通过，远程结果按对应提交核验。

## 导出采样率探测与剩余边界

原版混音设置始终为48000Hz。另三个导出请求中，44100和48000Hz任务最终Complete，实际文件分别为88200和96000样本帧；96000Hz这一整组MOV/PCM24设置被SetRenderSettings拒绝，没有任务。此结果不证明原版一般不支持96kHz。

44.1kHz导出PCM的SHA256为 `96823879c80d3067e47c40f3f998b65666626023dab304a0b3c12223f51ebe78`，48kHz为 `7f9e9feaa2e9730fd7da4835453fbd9872dc64018ea53097f320898b73b9e7f3`。左右声道首次出现差异的位置分别为样本119和129。将48kHz成品用FFmpeg默认swresample转为44.1kHz，虽输出长度一致，176400个标量仍全部不同，不能把此方案当作原版的重采样实现。产品非48kHz非零pan限制继续保留。

参数自动化、用户显式淡变、非单位音量与声像组合、任意源/时间线偏移、其他总线和声道布局仍需原版验证。GT Studio窗口读取本轮仍超时，实际窗口控件验收未完成；没有用后台心跳或Qt测试代替实窗验收。完整Resolve功能目标继续开放。
