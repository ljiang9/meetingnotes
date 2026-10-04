#!/usr/bin/env python3
"""meetingnotes —— 把杂乱的会议原始记录变成结构化会议纪要。

用法示例：
    python -m meetingnotes examples/raw-notes.txt --title "产品周会"
    cat notes.txt | python -m meetingnotes --from-stdin --title "周会" --action-only

只需要标准库。API Key 从环境变量 OPENAI_API_KEY（或 MEETINGNOTES_API_KEY）读取，
走 OpenAI 兼容的 /chat/completions 接口。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

VERSION = "0.1.0"

SYSTEM_PROMPT = """你是一名专业的会议纪要整理助手。用户会给你一份杂乱的会议原始记录。
请从中提取信息，只返回 JSON（不要输出其他任何文字），格式如下：

{
  "attendees": "参会人，用顿号分隔；若记录中未提及则填空字符串",
  "summary": "会议整体情况一句话摘要（50字以内）",
  "decisions": ["会议上明确拍板的结论1", "结论2"],
  "todos": [
    {"text": "待办事项描述", "owner": "负责人姓名", "due": "截止日期，尽量写成 YYYY-MM-DD；实在推断不出就填空字符串"}
  ],
  "questions": ["会上明确提出但没定论的问题1", "问题2"]
}

要求：
- decisions 只收录会上明确拍板或达成一致的结论，不要臆测。
- todos 的 owner 从记录中找（如"小陈今天内修好"则 owner 为小陈）；找不到负责人时 owner 填空字符串。
- due 结合会议日期推断为具体日期（如"周三前"按会议日期推算）；推断不出填空字符串。
- questions 只收录会上明确提出但没定论的问题。
- 所有文本用简体中文。
"""


# ---------------------------------------------------------------------------
# 输入 / 输出
# ---------------------------------------------------------------------------

def read_notes(args: argparse.Namespace) -> str:
    if args.from_stdin:
        text = sys.stdin.read()
    else:
        if not args.notes:
            print("error: 请提供会议记录文件，或使用 --from-stdin 从标准输入读取", file=sys.stderr)
            sys.exit(2)
        try:
            with open(args.notes, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"error: 无法读取文件 {args.notes}：{e}", file=sys.stderr)
            sys.exit(1)
    if not text.strip():
        print("error: 输入为空，没有可整理的会议记录", file=sys.stderr)
        sys.exit(1)
    return text


def build_messages(title: str, date: str, notes: str) -> list[dict]:
    user_prompt = (
        f"会议标题：{title}\n"
        f"会议日期：{date}\n\n"
        f"以下是会议原始记录：\n---\n{notes}\n---\n\n"
        f"请按上述 JSON 格式输出。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


# ---------------------------------------------------------------------------
# API 调用
# ---------------------------------------------------------------------------

def chat_complete(base_url: str, api_key: str, model: str,
                  messages: list[dict], timeout: int = 120) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": 0.2}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"API 请求失败（HTTP {e.code}）：{detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络请求失败：{e.reason}")
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("API 返回格式异常：缺少 choices[0].message.content")


def extract_json(text: str) -> dict:
    """从模型回复中剥离 ```fence 并解析 JSON。"""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t)
    if m:
        t = m.group(1)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型返回中未找到合法的 JSON 对象")
    return json.loads(t[start:end + 1])


def coerce_minutes(data: object) -> dict:
    """防御性校验模型返回的 schema，缺字段时给空值而不是崩。"""
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")

    def str_list(v: object) -> list[str]:
        return [str(x) for x in v] if isinstance(v, list) else []

    todos: list[dict] = []
    raw_todos = data.get("todos")
    if isinstance(raw_todos, list):
        for t in raw_todos:
            if isinstance(t, dict):
                todos.append({
                    "text": str(t.get("text") or "").strip(),
                    "owner": str(t.get("owner") or "").strip(),
                    "due": str(t.get("due") or "").strip(),
                })
            elif isinstance(t, str):
                todos.append({"text": t.strip(), "owner": "", "due": ""})
    todos = [t for t in todos if t["text"]]

    return {
        "attendees": str(data.get("attendees") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "decisions": [d for d in str_list(data.get("decisions")) if d.strip()],
        "todos": todos,
        "questions": [q for q in str_list(data.get("questions")) if q.strip()],
    }


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def _cell(text: str) -> str:
    return text.replace("|", "／").replace("\n", " ")


def render_minutes(m: dict, title: str, date: str, attendees_flag: str) -> str:
    attendees = attendees_flag or m["attendees"] or "（未在记录中识别到）"
    lines = [
        f"# {title} · 会议纪要",
        "",
        f"- **时间**：{date}",
        f"- **参会**：{attendees}",
        "",
        "## 核心结论",
    ]
    if m["decisions"]:
        lines += [f"- {d}" for d in m["decisions"]]
    else:
        lines.append("- （本次未记录到明确结论）")
    lines += ["", "## 待办事项"]
    if m["todos"]:
        lines += ["| 事项 | 负责人 | 截止 |", "|---|---|---|"]
        for t in m["todos"]:
            lines.append(
                f"| {_cell(t['text'])} | {_cell(t['owner']) or '—'} | {_cell(t['due']) or '—'} |"
            )
    else:
        lines.append("（暂无待办事项）")
    lines += ["", "## 待确认问题"]
    if m["questions"]:
        lines += [f"- {q}" for q in m["questions"]]
    else:
        lines.append("- （无）")
    lines += ["", "## 原始记录摘要", m["summary"] or "（无）", ""]
    return "\n".join(lines)


def render_action_only(m: dict) -> str:
    if not m["todos"]:
        return "暂无待办事项"
    lines = ["| 事项 | 负责人 | 截止 |", "|---|---|---|"]
    for t in m["todos"]:
        lines.append(
            f"| {_cell(t['text'])} | {_cell(t['owner']) or '—'} | {_cell(t['due']) or '—'} |"
        )
    return "\n".join(lines) + "\n"


def render_json(m: dict, title: str, date: str, attendees_flag: str) -> str:
    out = {
        "title": title,
        "date": date,
        "attendees": attendees_flag or m["attendees"],
        "summary": m["summary"],
        "decisions": m["decisions"],
        "todos": m["todos"],
        "questions": m["questions"],
    }
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="meetingnotes",
        description="把杂乱的会议原始记录变成结构化会议纪要（走 OpenAI 兼容接口）。",
    )
    p.add_argument("notes", nargs="?",
                   help="会议原始记录文件路径；与 --from-stdin 二选一")
    p.add_argument("--from-stdin", action="store_true",
                   help="从标准输入读取会议记录")
    p.add_argument("--title", default="会议",
                   help="会议标题（默认：会议）")
    p.add_argument("--date", default=datetime.date.today().isoformat(),
                   help="会议日期 YYYY-MM-DD（默认：今天）")
    p.add_argument("--attendees", default="",
                   help="参会人（不填则由 AI 从记录中提取）")
    p.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                   help="模型名（默认取 OPENAI_MODEL，否则 gpt-4o-mini）")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印将要发送的 prompt，不调用网络")
    p.add_argument("-o", "--output", metavar="out.md",
                   help="把结果同时写入文件")
    p.add_argument("--json", action="store_true",
                   help="输出结构化 JSON（decisions/todos/questions）")
    p.add_argument("--action-only", action="store_true",
                   help="只打印待办事项表格（方便粘贴到任务工具）")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    notes = read_notes(args)
    messages = build_messages(args.title, args.date, notes)

    if args.dry_run:
        print("===== 将要发送给模型的 prompt（dry-run，未调用网络）=====\n")
        for msg in messages:
            print(f"--- {msg['role']} ---")
            print(msg["content"])
            print()
        return 0

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("MEETINGNOTES_API_KEY")
    if not api_key:
        print("error: 未找到 API Key。请先设置环境变量：export OPENAI_API_KEY=你的key",
              file=sys.stderr)
        return 1
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    try:
        raw = chat_complete(base_url, api_key, args.model, messages)
        minutes = coerce_minutes(extract_json(raw))
    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        output = render_json(minutes, args.title, args.date, args.attendees)
    elif args.action_only:
        output = render_action_only(minutes)
    else:
        output = render_minutes(minutes, args.title, args.date, args.attendees)

    print(output, end="" if output.endswith("\n") else "\n")
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output if output.endswith("\n") else output + "\n")
        except OSError as e:
            print(f"error: 无法写入 {args.output}：{e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
