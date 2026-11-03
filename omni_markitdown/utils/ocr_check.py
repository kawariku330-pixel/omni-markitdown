"""OCR照合リスト: OCRで読んだ金額・日付・条番号・文献の巻号頁・番号を抜き出す

OCRは似た字（拠/贅、的/約）や、同じ字の連続（「四〇〇〇円」→「四〇〇〇〇円」）を読み違えることがある。
文章の意味からは正誤が判断できないので、原本と照らし合わせるための一覧を作る。
"""

from __future__ import annotations

import re
from typing import Dict, List

_N = r"[0-9０-９〇一二三四五六七八九十百千万億元]"
_SEP = r"[・.．]"

PATTERNS = [
    ("金額", re.compile(rf"{_N}[0-9０-９〇一二三四五六七八九十百千万億,，]*円")),
    ("日付", re.compile(rf"(?:明治|大正|昭和|平成|令和)?{_N}+年{_N}+月(?:{_N}+日)?")),
    ("日付", re.compile(rf"(?:明治|大正|昭和|平成|令和|[明大昭平令])元?{_N}*{_SEP}{_N}+{_SEP}{_N}+")),
    ("条番号", re.compile(rf"(?<![0-9０-９])第?{_N}+条(?:の{_N}+)?(?:第?{_N}+項)?(?:第?{_N}+号)?")),
    # 文献の巻号頁（「○○12巻3号45頁」「○○123号45頁」）
    ("文献", re.compile(rf"[\u3040-\u30ff\u3400-\u9fff]{{1,6}}\s*{_N}+[巻号](?:{_N}+号)?\s*{_N}+頁")),
    # 「令和2年（第3）15号」のような年・記号・号の番号
    ("番号", re.compile(rf"(?:平成|昭和|令和|[平昭令])?{_N}+年?[（(][^）)]{{1,4}}[）)]第?{_N}+号")),
]

# 同じ字の連続（〇〇〇、111）は特に読み違えやすい
RISKY = re.compile(r"(〇{3,}|0{3,}|０{3,}|1{3,}|１{3,})")


def extract_check_items(text: str, page: int) -> List[Dict]:
    items: List[Dict] = []
    seen = set()
    flat = text.replace("\n", "")
    for kind, pat in PATTERNS:
        for m in pat.finditer(flat):
            value = m.group(0)
            if (m.start(), value) in seen or len(value) < 2:
                continue
            seen.add((m.start(), value))
            ctx = flat[max(0, m.start() - 12):m.end() + 12].replace("|", "\\|")
            items.append({
                "page": page,
                "kind": kind,
                "value": value,
                "context": ctx,
                "risky": bool(RISKY.search(value)),
                "pos": m.start(),
            })
    items.sort(key=lambda d: d["pos"])
    for d in items:
        d.pop("pos")
    return items


def check_list_markdown(items: List[Dict], source_name: str) -> str:
    lines = [
        f"# OCR照合リスト: {source_name}",
        "",
        "> OCRで読み取った金額・日付・条番号・文献の巻号頁・番号です。OCRは数字や似た字を読み違えることがあるので、"
        "引用・転記する前に原本と照らし合わせてください。⚠ は同じ字が続いていて特に読み違えやすいものです。",
        "",
        f"件数: {len(items)} 件（うち ⚠ {sum(1 for d in items if d['risky'])} 件）",
        "",
        "| ページ | 種類 | 読み取り値 | 前後の文 | 確認 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for d in items:
        mark = "⚠ " if d["risky"] else ""
        lines.append(f"| {d['page']} | {d['kind']} | {mark}{d['value']} | {d['context']} | ☐ |")
    return "\n".join(lines) + "\n"
