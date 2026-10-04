# meetingnotes

把杂乱的会议原始记录，一键变成结构化会议纪要。

你只管在开会时随手记 bullet points，`meetingnotes` 会调用 LLM 帮你提取：
核心结论、待办事项（事项 / 负责人 / 截止）、待确认问题，并输出一份可直接粘贴到文档里的 Markdown 纪要。

## 安装

零依赖，Python 3.10+ 即可：

```bash
git clone https://github.com/ljiang9/meetingnotes.git
cd meetingnotes
```

设置 API Key（走 OpenAI 兼容的 `/chat/completions` 接口）：

```bash
export OPENAI_API_KEY=你的key
# 可选：换第三方兼容接口
export OPENAI_BASE_URL=https://你的网关/v1
export OPENAI_MODEL=gpt-4o-mini
```

## 快速开始

```bash
# 基础用法：原始记录 → Markdown 纪要
python -m meetingnotes examples/raw-notes.txt --title "产品周会" --date 2026-10-05

# 只想要待办表格，直接粘贴到任务工具
python -m meetingnotes examples/raw-notes.txt --title "产品周会" --action-only

# 结构化 JSON，给脚本/自动化消费
python -m meetingnotes examples/raw-notes.txt --json

# 从管道读取
cat notes.txt | python -m meetingnotes --from-stdin --title "周会"

# 同时落盘
python -m meetingnotes examples/raw-notes.txt --title "产品周会" -o 纪要.md
```

输出示例：

```markdown
# 产品周会 · 会议纪要

- **时间**：2026-10-05
- **参会**：大伟、Linda、小陈、老王

## 核心结论
- 优惠券先做不可叠加版本，叠加上线放到二期

## 待办事项
| 事项 | 负责人 | 截止 |
|---|---|---|
| 修复小程序登录页 iOS 18 闪退并发布 hotfix | 小陈 | 2026-10-05 |
| 支付页文案"立减"改为"下单立减" | Linda | 2026-10-08 |

## 待确认问题
- 分享海报老样式是否更换，待设计出图后定
- 阿K 请假期间回归测试由谁接手，尚未认领

## 原始记录摘要
本周聚焦双11大促页面开发与首页改版复盘……
```

## 参数

| 参数 | 说明 |
|---|---|
| `notes.txt` | 会议原始记录文件（与 `--from-stdin` 二选一） |
| `--title` | 会议标题（默认：会议） |
| `--date` | 会议日期 YYYY-MM-DD（默认：今天） |
| `--attendees` | 参会人（不填则由 AI 从记录中提取） |
| `--model` | 模型名（默认取 `OPENAI_MODEL`，否则 `gpt-4o-mini`） |
| `--dry-run` | 只打印将要发送的 prompt，不调用网络 |
| `-o out.md` | 把结果同时写入文件 |
| `--json` | 输出结构化 JSON（`decisions[]` / `todos[{text,owner,due}]` / `questions[]`） |
| `--action-only` | 只打印待办事项表格，方便粘贴到任务工具 |

## 局限

- 待办事项的负责人 / 截止日期提取质量取决于模型是否遵守 schema 指令；输出里 `—` 表示模型没能推断出来，需要人工补。
- 截止日期是模型结合会议日期推算的，跨月/节假日可能不准，重要 deadline 请人工核对。
- 不做流式输出，长记录需要等一次返回（超时 120 秒）。

## License

MIT，见 [LICENSE](LICENSE)。
