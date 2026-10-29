# OpenRouter 可用性核查

核查时间：2026-10-28 11:48–11:50，北京时间。只访问公开元数据和官方文档；没有模型生成请求、充值或开发/测试数据传输，实验继续暂停。

结论：当前公开目录支持付费的 Qwen3.8-27B，但没有可用的同款免费端点。不能据此判断免费供给是否会恢复。

## 直接请求官方 API 的结果

- `GET https://openrouter.ai/api/v1/models`：HTTP 200，464 个模型条目，其中 16 个零输入/输出价格的 `:free` 条目；没有 `qwen/qwen3.8-27b:free`。
- `GET https://openrouter.ai/api/v1/models/qwen/qwen3.8-27b:free/endpoints`：HTTP 200，`endpoints: []`。返回头为 `cache-control: private, no-store`、`cf-cache-status: BYPASS`。
- 普通版本 `qwen/qwen3.8-27b`：公开接口列出 21 个端点，输入/输出均不是同时为零。
- 正对照：目录中的 `recursive/flint-v1.0:free` 返回 1 个免费端点，表明同一查询方式能够显示免费模型后端。这只是元数据对照，没有调用其他模型。

原始时间戳、模型属性、价格、端点信息保存在 `openrouter_public_20261028.json` 与 `openrouter_control_20261028.json`。模型页面及搜索快照中保留的历史流量/可用性不能证明当前仍有免费供给。

## 免费配额

官方限额文档的 Markdown 原文显示：累计购买额度不足 10 时，普通免费档为 20 请求/分钟、50 请求/天；达到 10 时为 20 请求/分钟、1,000 请求/天。实际账户天配额以 `GET /api/v1/key` 的 `free_model_daily_requests` 为准，官方注明存在豁免与阈值舍入情况。

提高账户免费请求配额不会产生当前不存在的模型端点。仅剩余 32 道题按每题两次必需调用计算就有 64 次请求，还不包括条件反向调用；普通 50 次/日档即便模型恢复，也不足以在一个额度日内处理这一批。

## 非思考与输出格式

付费模型目录声明 `reasoning.mandatory=false`，支持 `none`，默认思考为开启。OpenRouter 使用 `reasoning: {"effort": "none"}` 关闭思考；`exclude: true` 和 `include_reasoning: false` 只隐藏思考输出，不能作为关闭思考的替代。

同一模型的各端点有不同的量化精度及参数支持情况。迁移实验需固定端点，设置 `provider.require_parameters=true`，核验 JSON Schema、seed、非思考模式等实际支持情况，并在同平台成对评测。不能用自动选择其他模型的 `openrouter/free` 路由替代固定的 Qwen-27B。

本地未配置 `OPENROUTER_API_KEY`，所以此次没有做带认证的实际生成验证。没有声称实测收到该模型生成的 404/429；上述结论来自两次公共目录/端点检查和免费模型正对照。

## 官方来源

- [模型目录](https://openrouter.ai/api/v1/models)
- [同款免费端点](https://openrouter.ai/api/v1/models/qwen/qwen3.8-27b:free/endpoints)
- [付费端点](https://openrouter.ai/api/v1/models/qwen/qwen3.8-27b/endpoints)
- [免费配额](https://openrouter.ai/docs/api_reference/limits)
- [免费变体](https://openrouter.ai/docs/guides/routing/model-variants/free)
- [思考控制](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
- [提供商路由与参数支持](https://openrouter.ai/docs/guides/routing/provider-selection)
- [免费模型自动路由](https://openrouter.ai/docs/guides/routing/routers/free-router)
