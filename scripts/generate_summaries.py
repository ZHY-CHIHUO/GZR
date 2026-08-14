# -*- coding: utf-8 -*-
"""批量生成章节摘要（需要 DEEPSEEK_API_KEY）。
用法：python scripts/generate_summaries.py [--start 1] [--end 2334] [--vol 第1卷：魔性不改] [--out data/summaries.json]
读 .env 的 key 调 deepseek-chat 给每章生成 150 字左右摘要，写入 summaries.json（可增量）。
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import KEY, BASE_URL, MODEL  # noqa: E402
from app.library import novel_volumes, chapter_text  # noqa: E402

PROMPT = (
    "你是《蛊真人》资深读者。请为下面这一章写一段中文摘要（约120~180字），"
    "要点：①主要人物与事件 ②关键设定/蛊虫/地点/势力名（保留专名） ③与前后文的剧情关联。"
    "只输出摘要正文，不要标题。\n\n"
)


def summarize(text: str, api_key: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "你是一名严谨的小说剧情摘要助手。"},
            {"role": "user", "content": PROMPT + text[:6000]},
        ],
        temperature=0.3,
        max_tokens=300,
    )
    return (resp.choices[0].message.content or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vol", default="第1卷：魔性不改")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=99999)
    ap.add_argument("--out", default=os.path.join("data", "summaries.json"))
    args = ap.parse_args()
    if not KEY:
        print("请先在 .env 配置 DEEPSEEK_API_KEY（或网页「设置」里填入）")
        sys.exit(1)

    existing = {}
    if os.path.isfile(args.out):
        existing = {(it["vol"], it["chapter"]) for it in json.load(open(args.out, encoding="utf-8"))}

    vols = novel_volumes()
    vol = next((v for v in vols if v["name"] == args.vol), None)
    if vol is None:
        print("未找到卷：", args.vol); sys.exit(1)

    items = json.load(open(args.out, encoding="utf-8")) if os.path.isfile(args.out) else []
    done = 0
    for c in vol["chapters"]:
        if c["n"] < args.start or c["n"] > args.end:
            continue
        if (args.vol, c["n"]) in existing:
            continue
        r = chapter_text(args.vol, c["n"])
        if r is None:
            continue
        try:
            s = summarize(r["text"], KEY)
        except Exception as e:
            print(f"第{c['n']}章失败: {e}")
            time.sleep(2)
            continue
        items.append({"vol": args.vol, "chapter": c["n"], "title": r["title"], "summary": s})
        done += 1
        print(f"第{c['n']}章 ✓ ({len(s)}字)")
        time.sleep(0.3)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    print(f"新增 {done} 条，共 {len(items)} 条 -> {args.out}")


if __name__ == "__main__":
    main()
