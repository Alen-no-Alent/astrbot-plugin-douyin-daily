# astrbot_plugin_douyin_daily

让 AstrBot 里的 AI 角色在**深夜低价时段**（DeepSeek 峰谷折扣，北京时间 00:30–08:30）自己刷一轮抖音，挑几条有趣的，配一句口语化的推荐语，连同标题、作者、点赞数和链接推送给你。

> 这是一个 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件。它自己**不实现任何抖音接口**，只通过 MCP（stdio JSON-RPC）调用 [NEWJO123/dsh-douyin-scroll](https://github.com/NEWJO123/dsh-douyin-scroll) 提供的抓取能力。

## 特色

- **定时 + 低成本**：cron 默认 `0 3 * * *`，落在 DeepSeek 峰谷折扣时段，写推荐语的 token 更便宜。
- **按热度挑**：`digg + comment×6 + share×3` 打分，再乘新鲜度（48 小时内加权）和时长合理性，取前 `pick_count` 条。
- **口语化开场**：把挑中的几条交给模型，生成两三句带情绪的开场白，而不是干巴巴的列表。
- **多目标推送**：`target_umos` 可以填多个 UMO，一次推给多个人/群。
- **随时手动**：`/刷抖音` 立刻跑一轮，不用等定时。

## 依赖

1. **Node.js ≥ 18**（跑 MCP server）
2. [NEWJO123/dsh-douyin-scroll](https://github.com/NEWJO123/dsh-douyin-scroll)：

```bash
git clone https://github.com/NEWJO123/dsh-douyin-scroll
cd dsh-douyin-scroll
node tools/mcp-server.mjs --selftest     # 自检，会列出可用工具
```

3. AstrBot 侧需要：

```bash
pip install croniter
```

`croniter` 用于解析 cron 表达式；缺失时定时功能关闭，但 `/刷抖音` 手动指令仍可用。

## 安装

1. 把本目录放到 `AstrBot/data/plugins/astrbot_plugin_douyin_daily/`
2. 重启 AstrBot，或在 WebUI 插件页重载
3. 打开插件配置，**必填**两项：
   - `node_path`：Node 可执行文件路径（在 PATH 里可直接填 `node`）
   - `plugin_dir`：dsh-douyin-scroll 的解压目录
4. 填好 `target_umos`（收推送的会话）
5. （可选）在聊天里发 `/刷抖音` 验证一次

## 配置项

| 键 | 含义 | 默认 |
| --- | --- | --- |
| `enabled` | 是否开启定时分享 | `true` |
| `cron` | 定时表达式（本地时区） | `0 3 * * *` |
| `target_umos` | 推送目标 UMO 列表 | `[]`（必须填） |
| `candidate_count` | 每轮取多少条候选 | `10` |
| `pick_count` | 最终推几条 | `3` |
| `provider_id` | 写推荐语的模型（留空=默认） | 空 |
| `node_path` | Node 可执行文件路径 | 空（必须填） |
| `plugin_dir` | dsh-douyin-scroll 目录 | 空（必须填） |

UMO 格式：`<平台实例>:<消息类型>:<会话ID>`，例如 `snowluma:FriendMessage:1234567`。

## 命令

| 命令 | 作用 |
| --- | --- |
| `/刷抖音` | 立刻跑一轮并推送 |

## 登录与凭证

- 抖音的 Cookie / 登录态由 **dsh-douyin-scroll** 自己维护，通常放在它目录下的 `data/` 里。
- **本仓库不含任何 Cookie、账号信息或登录凭证**，请勿把自己抓到的 Cookie 提交到任何公开仓库。
- 首次使用前请按上游项目的说明完成登录。

## 说明与免责

- 只读：只获取视频信息与链接，**不点赞、不评论、不发布**。
- 抓取行为受抖音平台规则约束，频率过高可能触发风控；请自行控制使用场景，风险自负。
- 本项目与抖音官方无关，也与 dsh-douyin-scroll 作者无隶属关系。

## 致谢

- [NEWJO123/dsh-douyin-scroll](https://github.com/NEWJO123/dsh-douyin-scroll) —— 提供抖音数据抓取与 MCP server（本插件只调用其 `tools/mcp-server.mjs`，未复制其代码）。

## License

MIT
