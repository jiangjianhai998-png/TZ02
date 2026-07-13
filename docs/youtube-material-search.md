# YouTube 素材搜索模块

本模块负责从 YouTube Data API v3 搜索候选素材、读取许可证与视频元数据、计算候选分数，并输出给 n8n 或人工审核。

> 该模块不会下载视频。标准 YouTube 许可证视频默认只用于热点发现；只有自有频道、明确授权或 Creative Commons 候选才可进入后续复用审核。

## 1. 所需配置

在运行 TZ02 或 n8n 的环境中配置：

```env
YOUTUBE_API_KEY=your_youtube_data_api_key
YOUTUBE_REGION_CODE=US
YOUTUBE_OWNED_CHANNEL_IDS=UCxxxxxxxx,UCyyyyyyyy
```

- `YOUTUBE_API_KEY`：Google Cloud Console 中启用 YouTube Data API v3 后创建的 API Key。
- `YOUTUBE_REGION_CODE`：可选，默认 `US`。
- `YOUTUBE_OWNED_CHANNEL_IDS`：可选，逗号分隔。这里列出的频道会被标记为自有素材。

不要把 API Key 提交到 GitHub。

## 2. 命令行使用

默认只搜索 Creative Commons 候选：

```bash
python scripts/youtube_material_search.py "NBA basketball highlights" --max-results 10 --pretty
```

搜索所有许可证，但标准许可证候选只标记为发现用途：

```bash
python scripts/youtube_material_search.py "NBA basketball highlights" --all-licenses --pretty
```

限制发布时间：

```bash
python scripts/youtube_material_search.py "basketball game" \
  --published-after 2026-07-01T00:00:00Z \
  --pretty
```

## 3. 输出字段

每个候选包含：

- `video_id`
- `title`
- `channel_id`
- `channel_title`
- `published_at`
- `duration`
- `definition`
- `license`
- `embeddable`
- `view_count`
- `like_count`
- `thumbnail_url`
- `watch_url`
- `risk_level`
- `reusable`
- `score`
- `reason`

风险规则：

- `green`：自有频道或 YouTube 标记为 Creative Commons。
- `red`：标准 YouTube 许可证，仅用于选题发现，除非另有书面授权。

Creative Commons 仍需核验上传者是否有权授权，并按照许可要求署名。

## 4. n8n 工作流

导入：

```text
n8n/workflows/youtube-material-search.json
```

工作流暴露 Webhook：

```http
POST /webhook/tz02/youtube-material-search
Content-Type: application/json
```

请求示例：

```json
{
  "query": "basketball slam dunk",
  "max_results": 10,
  "creative_commons_only": true,
  "region_code": "US",
  "published_after": "2026-07-01T00:00:00Z"
}
```

响应是结构化候选素材清单，不执行下载。

## 5. 推荐业务链路

```text
TZ02 热点
→ DeepSeek 提取具体事件、人物和动作关键词
→ n8n 调用 YouTube 素材搜索 Webhook
→ 许可证和风险筛选
→ 人工快速确认来源与授权
→ 已授权素材进入素材库
→ 视频工厂剪辑
→ 成片审核
→ 发布
```

## 6. 下一阶段

后续应增加：

1. PostgreSQL 素材候选表与授权证据字段。
2. n8n 人工审批节点。
3. 自有 YouTube 频道 OAuth 读取。
4. 素材文件上传到对象存储。
5. 视频工厂只读取已批准素材，不再直接使用搜索结果。
