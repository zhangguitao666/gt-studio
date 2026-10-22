# Fusion 文件结构与只读检查

GT Studio 已能通过共享 HTTP/MCP 读取本地 `.setting` 和 `.comp` 的字面表结构。本阶段建立节点引擎的导入依据，尚未导入到时间线，也不执行节点、表达式或 Lua。

## 原版证据

REA 对原版 `Contents/Libraries/Fusion/fuscript` 执行 open_binary 和 inspect_macho：x86_64/arm64 通用 Mach-O、arm64 选定切片、5 个依赖。记录见 `evidence/fuscript-macho-rea.json`，完整检查 Evidence ID 为 `ev_4324aebeb2584fe392a19861dcbb441b482b063b4a08027428314c1052b06979`。导入/导出符号不保证穷尽；静态记录不证明执行了合成。

有界 `fuscript -h` 退出 0，仅返回解释器横幅。尚未建立可用的无界面合成 API 或渲染入口，没有更改原版配置或绕过版本、授权和锁屏限制。

安装目录 Developer 提供三个模板及一个示例合成：

| 文件 | 活动节点 | 显式连接 | 当前作用域未解析连接 |
| --- | ---: | ---: | ---: |
| Gradient.setting | 2 | 26 | 0 |
| Rounded Window.setting | 2 | 11 | 0 |
| Noise Dissolve.setting | 4 | 22 | 1 |
| FuseExamples.comp | 75 | 74 | 3 |

83 个节点包含宏、曲线、LUT 和图像工具，不是 83 个已实现功能。CustomData 中的历史设置不重复计入活动图。源路径、字节数、SHA-256 和完整节点页面见 `fusion-settings-verification.json`。

Noise Dissolve 的 Dissolve1.Mix 指向外层 AnimCurves1；示例还有跨组 HS18_1、Merge2 引用。同名节点列为 candidate_source_node_ids，跨作用域原版绑定规则尚无运行验证，因此保留未解析状态，不静默选择来源。

随软件提供的 Example 1 Bright Contrast.fuse 声明先亮度偏移，再围绕 0.5 缩放对比度，随后在 YUV 空间缩放色度。该示例的调用顺序不能证明内置 BrightnessContrast 的所有算法或色彩空间行为；当前检查器也未实现这些处理。

## MCP 入口

```json
{
  "path": "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Fusion Templates/Generators/Gradient.setting",
  "detail": "nodes",
  "offset": 0,
  "limit": 25
}
```

工具名为 inspect_fusion_settings。默认 detail=summary 返回节点种类、连接数量、摘要和限制。detail=nodes 返回节点页面、该页节点的端口与连接、原始关键帧数据和未求值表达式。coverage.next_offset 用于下一页，它是节点分页。宏接口保留 InstanceInput/InstanceOutput，尚未展开为可渲染 DAG。

解析器保留有序字段、构造器、数字/字符串键、长字符串、注释及常见 Lua 转义。没有 Lua 解释器或 eval。不支持的函数调用、运算代码、重复字段或未闭合输入会报错；限制为 8 MiB、128 层、200,000 个表字段。成功或失败均不改变项目及撤销历史，无需先创建项目。

## 验证与下一步

17 项新增测试覆盖宏作用域/同名节点、来源候选、端口、关键帧、表达式、分页、转义、错误/资源限制、项目与历史不变。完整回归 189 passed，见 test-results-fusion.xml。

scripts/verify_fusion_settings.py 使用实际配置 MCP 启动器及私有测试端口，核对四个原版文件的完整节点页面，拒绝可执行输入，检查调用前后项目为空。45 个公开工具和只读注解已实测。

共享服务已保存并恢复高精度演示，实测 Gradient 2 节点/26 连接且项目内容不变，见 fusion-live-service-verification.json。服务重启重置内存撤销栈；旧 MCP 会话的工具清单需要重连刷新。

后续必需：可持久化和编辑的节点图，媒体输入/输出及节点计算，关键帧与表达式规则，宏/组/蒙版/3D/GPU/插件，Fusion 页面真实交互，以及原版同素材输出对照。结构检查不是节点执行证据，完整 Resolve 一致性仍未完成。真实窗口验收待手动解锁后重载检查。
