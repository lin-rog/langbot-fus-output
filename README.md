# Fus Output 1.2.1

LangBot 专用流水线的结构化文字投递插件。它校验字段，通过 `fus_send_message` 发送一条普通文字消息，并用本轮的短期凭据绑定目标和防止误投、重复投递。

## 在测试流水线中试用

1. 上传 `local-fus-output-1.2.1.lbpkg`。创建测试流水线，绑定 `local/fus-output`，如需基础命令可同时绑定 `langbot-team/EssentialCommands`。
2. 把 [示例预设](preset.example.txt) 的文本放入该流水线的预设。首轮需要至少 1000 个正文汉字，后续请求不设首轮字数门槛。
3. 发一条合成测试消息。预期工具成功投递一次普通文字，模型普通正文由该流水线拦截。此插件依赖宿主向 SDK 事件提供 `_pipeline_bound_plugins`，首次部署需确认宿主支持。

投递状态默认写入 `/app/data/comfy_bridge/fus-output/`，也可设置插件运行时环境变量 `FUS_OUTPUT_STATE_DIR`。挂载目录应持久化。

`python -m unittest discover -s tests` 运行离线测试。宿主 Wrapper 测试需要兼容的 LangBot 主程序源码，仅有 SDK 时会跳过。

[下载安装包](https://github.com/lin-rog/langbot-fus-output/releases/tag/v1.2.1)。
