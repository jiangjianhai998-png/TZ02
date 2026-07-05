# TZ02 V3 Enterprise｜DeepSeek GitHub Actions 部署说明

这个版本已经内置 `.github/workflows/crawler.yml`，可以在 GitHub Actions 上独立运行，不需要本地终端一直开着。

## 必填 Repository Secrets

在 GitHub 仓库：`Settings` → `Secrets and variables` → `Actions` → `New repository secret` 添加或确认：

- `AI_API_KEY`：DeepSeek 官网 API Key
- `AI_PROVIDER`：`deepseek`
- `AI_MODEL`：`deepseek/deepseek-chat`
- `TELEGRAM_BOT_TOKEN`：Telegram Bot Token
- `TELEGRAM_CHAT_ID`：群组和频道 ID，用英文分号隔开，例如：`-1001234567890;-1009876543210`

也兼容旧写法：

- `DEEPSEEK_API_KEY`：优先级高于 `AI_API_KEY`
- `TELEGRAM_GROUP_CHAT_ID`
- `TELEGRAM_CHANNEL_CHAT_ID`

## 运行方式

- 自动运行：每 20 分钟一次
- 手动运行：GitHub → `Actions` → `TZ02 TrendRadar` → `Run workflow`

## 本版默认

- AI 服务商：DeepSeek
- AI 模型：`deepseek/deepseek-chat`
- API 地址：`https://api.deepseek.com`
- 时区：`Asia/Singapore`
- 本地缓存/日志数据保留：3 天
- Telegram 支持一个 Bot 同时推送多个 chat_id

## 注意

因为项目内部使用 LiteLLM 调用模型，所以即使你使用 DeepSeek 官网 API Key，`AI_MODEL` 也建议填写 `deepseek/deepseek-chat`，不要只填 `deepseek-chat`。
