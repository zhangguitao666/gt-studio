# Fusion 缩小时的采样覆盖率

已在独立 Transform 中加入随缩小比例扩展的三角采样足迹。依据是已捕获的原版 Size=0.5 导出边界；其他比例是同一模型的推广，尚未获得原版运行验证。没有改变 Size>=1 的现有采样路径，也没有把本次修正视为完整 Fusion 等效。

## 原版证据与精度边界

原版 DaVinci Resolve 21.1.1.10 free 的参考案例为 640×360、24fps：Background Blue=1、Alpha=0.5，接 Transform Size=0.5、Center=(0.75,0.75)。原版导出 `REA_FUSION_20261022_164830_transform_upper_right_alpha1.mov` 的 SHA256 为 `ea1f6487e441b7ebf5a7a3979694fb261fc8c7b86cf56d7674449023869c8c59`。

解码第一帧 RGBA64 的 Alpha：矩形内部为32896；在 x=480 处，y=179 为28784、y=180 为4112、y=181 为0。在 y=90 处，x=319 为4112、x=320 为28784。这相当于内部 Alpha 的7/8和1/8覆盖率。原实现只有双线性点采样和硬边界，缺少这部分覆盖。

本次模型在源坐标中使用半径 `1/Size` 的可分离三角权重。归一化包含源图像之外的透明黑采样点，不能只对有效像素重新归一化。四个通道分别过滤，保留负值、超白值和零 Alpha 下的关联 RGB。

原版导出的 Alpha 载体在这个案例中相当于 `v8=round(alpha*255)` 后扩展为 `(v8*257)&0xfff0`。独立 PNG 先做相同的精度映射，再比较整个230400像素 Alpha 平面，结果完全一致。该载体平面的 little-endian SHA256 为 `8c926c9b93b8b510af1c5bff8bff9b128d6b8a800863eb497a52e3d6aa838ecb`。测试夹具保存目标身份、参数和摘要，没有发布原版程序或媒体。这证明选定导出载体的空间覆盖率一致，不证明内部浮点缓冲区、默认 FilterMethod 名称或所有编码器精度一致。

## 完整序列对照

通过配置中的 stdio MCP 启动独立临时服务，重新创建并渲染六组48帧案例。使用原有 `scripts/compare_native_fusion.py --run-name triangle-aa` 比较全部解码 RGB 和 PCM。本机报告位于被忽略的 `research/fusion-native-media-comparison-triangle-aa.json`。

|案例|RGB MAE 修正前→后|RGB MSE 修正前→后|最大通道差 修正前→后|
|---|---:|---:|---:|
|merge_half|0.0517665→0.0263354|0.894886→0.363995|42→24|
|rotation_90|0.0824624→0.0593533|3.341924→1.821168|74→41|
|transform_upper_right|0.0855671→0.0394748|2.923880→1.001972|78→43|

background_half、fanout、identity 三组仍是全部48帧 RGB 精确一致；六组 PCM 全流仍一致。没有放宽容差或更换编码器。此前隔离编码器的实验表明，只把相同中间载体换成 VideoToolbox 编码器，不能解释这些边界残差；本次调整发生在节点采样阶段。

## 验证和未完成部分

`tests/test_fusion_minify.py` 包含整帧原版 Alpha 摘要检查，以及 Size=0.01/0.37/0.5/0.99 的浮点参考测试。后者使用旋转、非整数平移、负值、超白和独立 Alpha，验证模型计算及边界，不作为这些参数的原版等效证据。Eval 循环使滤镜表达式长度不随采样足迹平方膨胀，避免最小 Size 导致命令行长度超限。计算量仍高于点采样，尚未验证实时预览性能。

本阶段连续旋转案例第一帧还有181个 Alpha 像素与原版不同。后续相邻Transform合并采样已将这组差异降为0，并补充了纹理的缩小/放大和旋转还原实验，见[FUSION-CONCATENATION.md](FUSION-CONCATENATION.md)。这并未实现完整DoD：原版强制展开后也能保存画布外图像，而独立实现尚不支持。三个变换案例的RGB仍有残差。旧节点检查记录已捕获FilterMethod=2、FlattenTransform=0，先前夹具中“未捕获FilterMethod”的说明现已纠正；数值对应的显示名称未验证。关键帧和原版可选滤波模式仍需实验；实际GT Studio窗口验收未完成。
