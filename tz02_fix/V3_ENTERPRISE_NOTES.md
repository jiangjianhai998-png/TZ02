# TZ02 V3 Enterprise 升级说明

本版本保留 DeepSeek，不切换 OpenAI。

## 主要升级

- DeepSeek 默认模型：`deepseek/deepseek-chat`
- DeepSeek API Base：`https://api.deepseek.com`
- GitHub Actions 默认读取：`DEEPSEEK_API_KEY`，兼容备用 `AI_API_KEY`
- AI 筛选最低分提高到 0.80
- 内容优先级调整为：体育赛事视频/赛果 > 中文体育内容 > 博彩行业热点 > 德州扑克 > 反赌风险教育 > AI/支付辅助信息
- AI 分析提示词重写为 Telegram + YouTube Shorts 生产导向
- 加强重复事件过滤、中文/视频/体育/博彩行业权重排序

## GitHub Secrets 必填

- `DEEPSEEK_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` 或 `TELEGRAM_GROUP_CHAT_ID` + `TELEGRAM_CHANNEL_CHAT_ID`

## 注意

本项目只做行业资讯、合规动态、体育赛事信息、风险教育与短视频选题，不生成下注建议、赔率推荐、盘口预测或赌博获客广告。
