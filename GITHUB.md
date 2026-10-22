# GitHub 维护

GT Studio 是开发中的独立视频编辑器，支持原生桌面界面和 MCP。
完整 DaVinci Resolve 功能和行为一致性尚未实现，也未宣称兼容其项目数据库。

## 本地开发

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python gt_studio.py ui
```

运行测试：

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

MCP 使用 stdio，可运行 `.venv/bin/python gt_studio.py mcp`。
`get_capabilities` 返回当前支持范围。macOS 启动器位于仓库根目录；
其他平台可使用 Python 命令启动。

## 提交和同步

```sh
git status
git add <修改的源码、文档或测试>
git commit -m "Describe the change"
git push origin main
```

`main` 分支推送和 pull request 自动运行 GitHub Actions 测试。
CI 使用 Python 3.12、Qt offscreen 和 imageio-ffmpeg 提供的 FFmpeg。
原版软件的运行采集和真实桌面交互验收不属于该 CI 的验证范围。

## 公开内容边界

仓库包含独立源码、启动器、开发脚本、文档、测试和测试必需的八份运行参考数据。
这些参考数据来自专用 REA 测试项目；本地绝对路径是采集来源说明，
不是他人机器上可直接运行的路径，也不包含对应的原版数据库或素材。

`.venv/`、`workspace/`、原始证据目录、机器运行报告、截图、数据库、日志和密钥配置均不上传。
`research/` 文档可能引用这些仅在采集机器保留的文件；仓库不提供完整本机证据包。
部分原版运行采集脚本包含采集机器的固定路径和测试项目名称，复用前需要调整。

未在仓库内附带 DaVinci Resolve 程序、SDK 实现、商业插件或用户媒体。
