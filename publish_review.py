#!/usr/bin/env python3
"""
Publish daily analysis.md to capitalflow.uno as a market review.
Reads today's analysis file and POSTs it to the internal API.

Usage:
  python3 publish_review.py                    # publish today's analysis
  python3 publish_review.py 2026-04-26         # publish specific date
  python3 publish_review.py --draft            # publish as draft
"""

import os
import sys
import json
import re
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path

# Load .env
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_TOKEN  = os.environ.get("INTERNAL_API_TOKEN", "")
API_URL    = os.environ.get("CAPITALFLOW_API_URL", "https://capitalflow.uno/api/internal/market-reviews")
AUTHOR_EMAIL = os.environ.get("CAPITALFLOW_AUTHOR_EMAIL", "")


def load_analysis(date_str: str) -> str:
    path = Path(__file__).parent / "daily" / date_str / "analysis.md"
    if not path.exists():
        print(f"Файл не знайдено: {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def md_to_html(md: str) -> str:
    """Minimal markdown → HTML for basic structure."""
    lines = md.split("\n")
    html_lines = []
    in_table = False
    in_list = False

    for line in lines:
        # Tables
        if line.startswith("|"):
            if not in_table:
                html_lines.append('<div class="table-responsive"><table class="table table-sm">')
                in_table = True
            if re.match(r"^\|[-| :]+\|$", line):
                continue  # skip separator row
            cells = [c.strip() for c in line.strip("|").split("|")]
            tag = "th" if not any("<td>" in l for l in html_lines[-3:]) else "td"
            html_lines.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            continue
        elif in_table:
            html_lines.append("</table></div>")
            in_table = False

        # Lists
        if line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_inline(line[2:])}</li>")
            continue
        elif in_list:
            html_lines.append("</ul>")
            in_list = False

        # Headings
        if line.startswith("### "):
            html_lines.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("---"):
            html_lines.append("<hr>")
        elif line.strip() == "":
            html_lines.append("")
        else:
            html_lines.append(f"<p>{_inline(line)}</p>")

    if in_table:
        html_lines.append("</table></div>")
    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def _inline(text: str) -> str:
    """Bold, italic, code inline."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    text = re.sub(r"`(.+?)`",       r"<code>\1</code>",     text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    # Emoji signals → colored spans
    text = text.replace("✅", '<span class="text-success">✅</span>')
    text = text.replace("⚠️", '<span class="text-warning">⚠️</span>')
    text = text.replace("🔴", '<span class="text-danger">🔴</span>')
    text = text.replace("🟡", '<span class="text-warning">🟡</span>')
    text = text.replace("🟢", '<span class="text-success">🟢</span>')
    return text


def extract_summary(md: str) -> str:
    """First non-heading, non-empty paragraph."""
    for line in md.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("_") and not line.startswith("|") and not line.startswith("-"):
            clean = re.sub(r"[*_`]", "", line)
            return clean[:497] + "…" if len(clean) > 497 else clean
    return ""


def extract_title(md: str, date_str: str) -> str:
    for line in md.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return f"Ринковий огляд {date_str}"


def extract_tags(md: str) -> list:
    tags = []
    instruments = ["XAUUSD", "XAGUSD", "EURUSD", "USDJPY", "NAS100", "GER40"]
    for inst in instruments:
        if inst in md:
            tags.append(inst)
    if "FOMC" in md or "Fed" in md:
        tags.append("FOMC")
    if "NFP" in md:
        tags.append("NFP")
    return tags


def publish(date_str: str, draft: bool = False):
    if not API_TOKEN:
        print("Помилка: INTERNAL_API_TOKEN не знайдено в .env")
        sys.exit(1)

    md = load_analysis(date_str)
    html_content = md_to_html(md)
    title   = extract_title(md, date_str)
    summary = extract_summary(md)
    tags    = extract_tags(md)

    payload = {
        "title":          title,
        "summary":        summary,
        "content":        html_content,
        "category":       "weekly-review",
        "tags":           tags,
        "status":         "draft" if draft else "published",
        "is_featured":    False,
        "ai_generated":   True,
        "meta_description": summary[:160] if summary else "",
        "author_email":   AUTHOR_EMAIL,
    }

    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {API_TOKEN}",
            "Accept":        "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
        print(f"✓ Опубліковано: {result.get('url', '')}")
        print(f"  ID: {result.get('id')} | slug: {result.get('slug')}")
        return result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Помилка {e.code}: {body}")
        sys.exit(1)
    except Exception as e:
        print(f"Помилка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    args    = sys.argv[1:]
    draft   = "--draft" in args
    date_str = next((a for a in args if re.match(r"\d{4}-\d{2}-\d{2}", a)), date.today().isoformat())

    print(f"Публікую огляд за {date_str} {'(draft)' if draft else ''}...")
    publish(date_str, draft=draft)
