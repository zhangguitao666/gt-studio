# Fusion 预乘 Alpha 与受控原版对照

已根据原版运行结果改为关联（预乘）RGBA合成，修正生成器颜色在主时间线与Merge中被重复乘Alpha的问题。MediaIn参与Merge时仍有色彩残差；颜色管理、HDR和完整节点等效尚未实现。

## 原版实验

在专用 `REA Reference · 2026-10-21` 工程中新建13组静态640×360/24fps/12帧时间线，分别导出ProRes422HQ RGB和ProRes4444 RGBA，共26个任务。案例覆盖蓝色Background的Alpha=0/.25/.5/1、黑色/绿色下层、红色生成器背景上的Blend=.25/.5/.75，以及媒体输入背景。

首轮因无Alpha编码设置中附带Alpha参数以及双层追加未限定媒体类型而失败，13条失败记录保留于 `fusion-alpha-ramp-runtime.json`；没有将其算作成功。第二版明确仅视频追加、分开RGB/RGBA设置，13条均完成创建。按精确任务ID查询到26条Complete/100%，且无活动渲染，见 `fusion-alpha-ramp-status.json`。RGB任务的实际队列信息为ExportAlpha=false。没有修改用户工程或全局首选项。

一致性SQLite backup快照经REA检查，Evidence ID为 `ev_bda78ae1fcc958ab8b21bd2b40c5fb5b766f932574eec078c61da070a8389ea7`。该证据限定于快照身份、表结构和采样行；运行语义来自守卫Lua回读及保留的导出文件，未把SQLite检查当作算法证明。探针、快照、标记JSON及解码器摘要保留在本地研究记录中。

## 观察与推断

原版蓝色生成器的Alpha为0、.25、.5和1时，无Alpha导出的蓝通道均为253；带Alpha导出中的Alpha分别为0、16448、32896和65520。Alpha=.5叠到绿色下层后，RGB为 `[0,126,253]`，而旧实现为 `[0,126,125]`。

生成器Merge背景为不透明红，前景为蓝、Alpha=.5、Blend=.5时，原版RGB为 `[187,0,126]`，旧实现为 `[188,0,61]`。这些受控结果支持关联合成规则：

`Cout = Cf * Blend + Cb * (1 - Af * Blend)`

`Aout = Af * Blend + Ab * (1 - Af * Blend)`

这是对本组行为的推断，不是读取到的原版内部代码或浮点缓冲。RGB可以大于Alpha，因此“先转成直通Alpha再叠加”会裁掉发光贡献；FFmpeg的普通overlay还会跳过Alpha=0的非零RGB，不能直接替代上述计算。

## 实现

节点保持16位整数平面RGBA。Transform采用透明pad/crop定位，保留Alpha=0处RGB；Merge将Blend同时作用于RGB和Alpha，显式计算背景衰减后加前景。移除了原先Transform/Merge的8位RGB overlay边界。MediaIn在进入实际处理图时转为关联值；恒等MediaIn→MediaOut继续使用原路径。

主时间线对处理后的Fusion输出使用同一关联合成规则，按帧补齐透明前后空段并施加片段/叠化窗口，避免错位片段丢帧。透明度、淡入/淡出同时缩放关联RGB和Alpha。涉及Fusion的交叉叠化保留关联中间值，包括另一侧仍走普通媒体路径的情况。

整数结果在0..65535范围饱和，尚不能保留原版HDR/超白浮点值。插值、取整、源颜色解释及其余原版节点行为仍需校准。节点PNG保存关联RGBA原始样本；普通PNG查看器可能按直通Alpha显示它，不能把查看器观感当作节点数值。

## 对照结果

`compare_fusion_alpha_ramp.py` 使用已配置MCP和私有服务重建13组，比较每组全部12帧。旧/新记录分别为 `fusion-alpha-ramp-comparison-baseline.json` 和 `fusion-alpha-ramp-comparison-associated.json`，最终源码状态再次重放到独立 `fusion-alpha-ramp-comparison-verified.json`。9组全序列解码RGB逐字节相同；其余3个生成器案例MAE为0.666667、1.333333和1.0（0..255尺度）。媒体输入Merge的MAE从22.333333降至10.333333，仍有明显差异，没有宣称通过原版等效。

原先六组48帧案例也分别重放，旧报告保持不变，新报告为 `fusion-native-media-comparison-associated.json`：

| 案例 | 旧RGB MAE | 新RGB MAE | 旧RGB MSE | 新RGB MSE |
| --- | ---: | ---: | ---: | ---: |
| 半透明背景 | 42.666667 | 0 | 5461.333333 | 0 |
| 共享背景分支 | 21.333333 | 0 | 1365.333333 | 0 |
| 媒体恒等 | 1 | 1 | 3 | 3 |
| 半混合Merge | 6.317713 | 3.386092 | 232.773485 | 44.760979 |
| 90度旋转 | 0.088695 | 0.082462 | 3.956698 | 3.341927 |
| 右上缩小变换 | 10.623762 | 0.085567 | 1351.634013 | 2.923880 |

没有做颜色拟合、增益补偿或丢弃差异帧。原版导出经过颜色和编码处理，不等于内部缓冲；上述静态案例不能证明完整色管、运动、任意参数或应用功能一致。

## 验证与版本控制

新增17项测试：12个原版生成器案例、错位片段起止帧、Alpha=0的透明度/淡化、双Fusion及混合普通媒体的叠化、超过8位的节点数值精度。更新旧直通Alpha假设下的像素期望；Qt视频帧也应显示全蓝而非半蓝。完整241项通过，见 `test-results-fusion-associated.xml`。

主服务/窗口已保存并重开同一演示工程，当前Fusion页、第0帧暂停。CUA真实保存Transform节点PNG，再用已配置MCP对同一节点/帧保存，两个文件逐字节相同，工程与保存文件一致。样点为 `[27,0,65534,32767]`，说明缩放后仍有27/65535的红残差及一个蓝通道等级差，不能声称精确内部浮点等效。GUI实际生成的预览任务内侧RGB为 `[187,0,126]`，先前为约 `[186,0,61]`。证据为 `fusion-associated-live-verification.json`、`fusion-associated-native.png` 和完整AX文本。公开MCP工具仍为52个。

代码使用现有 [GitHub仓库](https://github.com/zhangguitao666/gt-studio) 做版本控制。节点检查点与首轮原版研究已推送为 `8fd1764`；本阶段修正另行提交。数据库、原版二进制、机器专属报告和截图按现有忽略规则留在本地；仓库保留实现、探针、说明和精简的自有合成样本测量夹具。

下一步是进一步对照MediaIn颜色解释、原版实际节点精度和边缘采样，再扩充节点、色管与其余完整功能。全功能一致目标仍未完成。
