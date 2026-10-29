# 内网 Qwen3.8-27B API 调用说明

供本仓库的 Agent 和开发者连接用户提供的模型服务器。2026-10-29 已用真实请求验证模型列表和对话生成，均返回 HTTP 200。

## 连接参数

| 项目 | 值 |
| --- | --- |
| Base URL | `http://10.176.30.103:20027/v1` |
| 模型 ID | `qwen38-27b`，必须使用此名称 |
| 模型列表 | `GET /v1/models` |
| 对话生成 | `POST /v1/chat/completions` |
| 认证 | 请求头 `Authorization: Bearer <API Key>` |
| 请求格式 | `Content-Type: application/json`；OpenAI 兼容的 Chat Completions 格式 |
| 非思考模式 | 请求 JSON 中设置 `"chat_template_kwargs": {"enable_thinking": false}` |
| 已验证生成参数 | `temperature=0`、`max_tokens=64`、`stream=false` |

Base URL 已包含 `/v1`，拼接接口时不要重复添加。调用机器需要能访问该内网地址。

服务端模型列表报告 `owned_by=vllm`、权重路径 `/root/models/Qwen3.8-27B-w8a8`、`max_model_len=1048576`。
这些是服务端自报信息；尚未验证长上下文、流式输出、工具调用或 JSON Schema 约束。

## Key 的读取方式

用户已提供并授权本任务使用的本机文件：

```text
C:/Users/hp/Documents/WeChat Files/wxid_f369scgx0twr12/FileStorage/File/2026-10/key.txt
```

当前文件内容为单行原始 Key。使用 UTF-8（兼容 BOM）读取并去掉首尾空白即可；不要把文件内容当作命令执行。

下方示例优先读取进程环境变量 `QWEN_API_KEY`；未设置时，从 `QWEN_API_KEY_FILE` 指定的文件读取；该变量也未设置时，使用上面的本机路径。
这两个变量是本示例的约定，现有实验客户端不会自动读取它们。其他机器可设置自己的 Key 文件路径：

```powershell
$env:QWEN_API_KEY_FILE = 'C:\path\to\key.txt'
```

不要在日志、响应记录或 Git 文件中打印或保存 Key、认证请求头。文档只记录文件位置，不包含 Key 本身。
如果文件缺失或认证返回 401，再请用户提供有效 Key 或更新文件位置。

## 可直接执行的连通性检查

在仓库根目录的 PowerShell 中执行以下完整代码块。使用仓库已有虚拟环境和 `httpx` 依赖；如果环境尚未建立，先按 [README 的快速开始](../README.md#快速开始) 安装依赖。
示例只查询模型列表并发送一次固定测试提示，不读取实验数据。

```powershell
@'
import json
import os
import time
from pathlib import Path

import httpx

base_url = "http://10.176.30.103:20027/v1"
model = "qwen38-27b"
key = os.environ.get("QWEN_API_KEY", "").strip()
if not key:
    key_file = Path(os.environ.get(
        "QWEN_API_KEY_FILE",
        "C:/Users/hp/Documents/WeChat Files/wxid_f369scgx0twr12/"
        "FileStorage/File/2026-10/key.txt",
    ))
    key = key_file.read_text(encoding="utf-8-sig").strip()
if not key or "\n" in key or "\r" in key:
    raise SystemExit("API key must be a nonempty single-line value")

payload = {
    "model": model,
    "messages": [{
        "role": "user",
        "content": "Reply with exactly this text and nothing else: QWEN_CONNECTION_OK",
    }],
    "temperature": 0,
    "max_tokens": 64,
    "stream": False,
    "chat_template_kwargs": {"enable_thinking": False},
}

# Direct connection to the intranet; do not inherit system proxy settings.
with httpx.Client(
    base_url=base_url + "/",
    headers={"Authorization": "Bearer " + key},
    timeout=httpx.Timeout(90.0, connect=15.0),
    trust_env=False,
    follow_redirects=False,
) as client:
    models_response = client.get("models")
    models_response.raise_for_status()
    models = [item["id"] for item in models_response.json()["data"]]
    if model not in models:
        raise SystemExit("Requested model is absent from /v1/models")

    started = time.perf_counter()
    response = client.post("chat/completions", json=payload)
    response.raise_for_status()
    elapsed = round(time.perf_counter() - started, 2)
    result = response.json()
    choice = result["choices"][0]
    content = choice["message"].get("content") or ""
    summary = {
        "http_status": response.status_code,
        "model": result.get("model"),
        "content": content,
        "finish_reason": choice.get("finish_reason"),
        "usage": result.get("usage"),
        "elapsed_seconds": elapsed,
    }
    print(json.dumps(summary, ensure_ascii=True).replace(key, "[REDACTED]"))
    if content.strip() != "QWEN_CONNECTION_OK" or choice.get("finish_reason") != "stop":
        raise SystemExit("Unexpected smoke-test output; inspect the response")
'@ | .venv\Scripts\python.exe -
```

第一次实测结果：回复 `QWEN_CONNECTION_OK`，`finish_reason=stop`，约 0.8 秒；输入 26 tokens、输出 6 tokens，共 32 tokens，`reasoning_tokens=0`。耗时和 token 数是该次短请求的记录，不代表批量推理性能。

正式调用时替换 `messages`，并按任务设置 `max_tokens`；64 仅用于连通性检查。
生成文本位于 `choices[0].message.content`，用量位于 `usage`。如要求非思考模式，还应检查原始响应的 `reasoning` / `reasoning_content` 及 `usage` 中的 reasoning token 数；仓库已有 `ab_factcheck.model_client.nonthinking_check` 可复用。

## 与现有实验客户端的关系

- [LocalModelClient](../src/ab_factcheck/model_client.py) 只允许 loopback 地址，并依赖 llama.cpp 的 `/props` 等接口，不能直接传入本服务器地址。
- [GroqModelClient](../src/ab_factcheck/groq_client.py) 固定 Groq 域名、模型 `qwen/qwen3.8-27b` 和 `GROQ_API_KEY`，不能直接用于本服务器。本服务器的模型名是 `qwen38-27b`，使用独立 Key。
- 新实验接入时使用独立适配器或上面的 HTTP 调用方式，并建立新的实验配置及 run ID，记录服务地址、模型 ID 和实际生成参数。现有冻结实验配置及历史结果仍保留原来源。

## 常见问题

| 现象 | 检查方式 |
| --- | --- |
| HTTP 401 | 未带认证时已经实测会返回 401；检查 Key 文件、环境变量及 Bearer 请求头 |
| HTTP 404 / 模型不存在 | 检查路径是否重复 `/v1`，并重新查询 `/v1/models` 确认模型名 |
| 连接超时或拒绝连接 | 检查当前机器的内网连通性、端口及服务状态；示例已禁用环境代理 |
| HTTP 400 | 查看脱敏后的错误响应，检查参数支持情况；额外参数需单独验证 |
| `finish_reason=length` | 输出达到 token 上限；按任务调整预算并检查完整响应 |
