# Safe Mini Agent

这是一个不依赖 LangChain、LangGraph、CrewAI 或 AutoGen 的命令行 Mini Agent。核心循环、模型接口、工具注册、安全边界与错误恢复都由项目自身实现，运行时只需要 Python 3.10+。

## 核心设计

`Agent.run()` 把用户请求和工具定义交给模型。模型可以直接回答，也可以返回若干 `ToolCall`。每次工具执行结果（成功或错误）都会作为 `tool` 消息加入历史并再次交给模型。模型不再请求工具时任务结束；达到 `max_steps` 时则安全停止。

内置四种工具：

- `list_files`：列出文件或目录；
- `read_file`：读取 UTF-8 文本；
- `search_text`：按普通文本或正则搜索；
- `write_file`：创建、覆盖或追加文件。

新增工具只需实现 `name`、`description`、`parameters`、`read_only` 与 `run()`，再注册到 `ToolRegistry`，不需要修改 Agent Loop。

为兼容题目提供的 starter 导入方式，项目保留以下稳定入口：

- `mini_agent.contracts`：`Model`、`ModelResponse`、`ToolCall`、`ToolResult` 等基础接口；
- `mini_agent.fake_model`：可按预设顺序返回响应的 `FakeModel`；
- `mini_agent.agent`：`Agent` 与 Agent Loop 实现。

内部模块可以继续拆分或扩展，而使用 starter 接口的代码无需随之修改。

## 快速运行

项目包含可按顺序返回预设响应的 `FakeModel`，因此无需 API Key：

```powershell
python -m mini_agent --workspace workspace --script examples/demo_script.json "列出工作区内容"
```

不提供末尾请求时会进入交互模式。FakeModel 在每个请求开始时重新加载脚本：

```powershell
python -m mini_agent --workspace workspace --script examples/demo_script.json
```

### `safe` 快捷指令（Windows）

项目根目录包含 `safe.cmd`。将项目目录加入当前用户的 `PATH` 后，新开一个 PowerShell 或 CMD 窗口即可直接运行：

```powershell
safe
safe "列出工作区内容"
```

快捷指令默认加载示例 FakeModel，并启用仅限 `workspace/` 的自动写入审批。要让同一个快捷指令使用自定义模型适配器，可以先设置 `SAFE_MODEL_FACTORY`：

```powershell
$env:SAFE_MODEL_FACTORY = "my_adapter:create_model"
safe "总结 materials 中与 Agent Loop 有关的内容"
```

FakeModel 脚本是 JSON 数组，例如：

```json
[
  {
    "content": "先搜索资料。",
    "tool_calls": [
      {
        "id": "search-1",
        "name": "search_text",
        "arguments": {"path": "materials", "query": "Agent Loop"}
      }
    ]
  },
  {"content": "根据工具返回的信息给出最终答复。"}
]
```

FakeModel 的回复是固定的，主要用于离线验证循环。接入真实或本地模型时，实现 `Model.complete(messages, tools) -> AssistantReply`，并提供一个零参数工厂：

```powershell
python -m mini_agent --workspace workspace --model-factory my_adapter:create_model "总结 materials"
```

厂商适配逻辑因此与 Agent Loop 分离。

### `mini` 全局快捷指令（Windows）

项目根目录还提供 `mini.cmd`。把项目目录加入当前用户的 `PATH` 后，重新打开 PowerShell，即可从任意目录启动：

```powershell
mini
mini "列出工作区内容"
```

`mini` 默认使用离线 FakeModel，且写操作仍会逐次询问。需要预先批准本次运行的写操作时使用：

```powershell
mini --approve-writes "生成报告"
```

项目内置 OpenAI-compatible 适配器。最简单的方式是打开项目根目录的 `config.json`，填写三个值：

```json
{
  "api_key": "你的 API Key",
  "base_url": "服务商提供的 API 地址",
  "model": "服务商提供的模型名称",
  "timeout": 60
}
```

保存后直接运行：

```powershell
mini
mini "总结 materials 中的资料"
```

`config.json` 已加入 `.gitignore`，不会被提交到 GitHub；`config.example.json` 是不含真实密钥的配置模板。OpenAI 官方接口使用 `https://api.openai.com/v1`，其他服务商需填写其 OpenAI-compatible 地址，并确保支持 Chat Completions 与 Function Calling。

也可以改用环境变量（环境变量优先于 `config.json`）：

```powershell
$env:MINI_API_KEY = "你的 API Key"
$env:MINI_BASE_URL = "服务商提供的 API 地址"
$env:MINI_MODEL = "服务商提供的模型名称"
mini "总结 materials 中的资料"
```

如果使用 OpenAI 官方接口，可以省略 `MINI_BASE_URL`。`mini.cmd` 检测到 `config.json` 或 `MINI_MODEL` 后会自动加载 `mini_agent.openai_compatible:create_model`。

首次使用真实模型前安装项目和依赖：

```powershell
python -m pip install -e .
```

适配器还兼容 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OPENAI_MODEL`。需要接入不兼容 Chat Completions 的厂商时，仍可设置自己的工厂：

```powershell
$env:MINI_MODEL_FACTORY = "my_adapter:create_model"
mini "总结 materials 中的资料"
```

## 写入权限

默认情况下，每次 `write_file` 都会展示动作和相对路径，并要求人工确认。适用于已明确授权的自动化场景时，可以为当前进程预授权：

```powershell
python -m mini_agent --workspace workspace --script my_script.json --approve-writes "生成 report.md"
```

`create` 模式不会覆盖已有文件；模型必须明确改用 `overwrite` 或 `append`。

## 安全边界与失败处理

- 仅接受相对路径，拒绝绝对路径、驱动器路径和 `..`；
- 路径在访问前会解析并校验仍位于 workspace 内，可阻止符号链接逃逸；
- 文件遍历不会跟随符号链接；
- 修改操作必须经权限策略批准；
- 未知工具、无效 JSON/参数、文件错误、权限拒绝都会变成结构化工具结果，让模型有机会调整；
- 模型异常和最大步数超限会返回明确的 `AgentResult`，而不是让程序崩溃。

## 测试

```powershell
python -m unittest discover -v
```

测试覆盖直接回答、工具循环、结果回传、starter 接口兼容、未知工具、模型异常、步数上限、读写权限、路径越界、参数错误、搜索和防覆盖行为。
