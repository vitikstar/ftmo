#!/usr/bin/env python3
"""
Fetch and save daily news sentiment. Run ONCE per morning.
Skips API call if news for today already exists.

Usage:
  python3 fetch_news.py              # fetch all instruments
  python3 fetch_news.py --force      # re-fetch even if today's file exists
"""

import os
import re
import sys
import json
import time
import argparse
import urllib.request
from datetime import datetime
from pathlib import Path

# Load .env
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")

SYMBOLS = {
    "XAUUSD": {"ticker": "GLD",       "label": "Gold (XAUUSD)"},
    "XAGUSD": {"ticker": "SLV",       "label": "Silver (XAGUSD)"},
    "EURUSD": {"ticker": "FOREX:EUR", "label": "EUR/USD"},
    "USDJPY": {"ticker": "FOREX:JPY", "label": "USD/JPY"},
    "NAS100": {"ticker": "QQQ",       "label": "NAS100"},
    "GER40":  {"ticker": "EWG",       "label": "GER40"},
}

SENTIMENT_LABELS = {
    "Bearish":          "BEARISH  ",
    "Somewhat-Bearish": "bearish~ ",
    "Neutral":          "neutral  ",
    "Somewhat-Bullish": "bullish~ ",
    "Bullish":          "BULLISH  ",
}


def fetch(ticker: str) -> list[dict]:
    url = (
        "https://www.alphavantage.co/query"
        f"?function=NEWS_SENTIMENT"
        f"&tickers={ticker}"
        f"&limit=50"
        f"&sort=LATEST"
        f"&apikey={API_KEY}"
    )
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())

    if "Information" in data:
        print(f"    [!] Ліміт API: {data['Information'][:100]}")
        return []
    return data.get("feed", [])


def sentiment_for(article: dict, ticker: str):
    for ts in article.get("ticker_sentiment", []):
        if ts["ticker"].upper() == ticker.upper():
            return ts.get("ticker_sentiment_label", "Neutral"), float(ts.get("ticker_sentiment_score", 0))
    # fallback to overall
    return article.get("overall_sentiment_label", "Neutral"), float(article.get("overall_sentiment_score", 0))


def bias_label(avg: float) -> str:
    if avg >= 0.35:   return "BULLISH"
    if avg >= 0.15:   return "bullish~"
    if avg <= -0.35:  return "BEARISH"
    if avg <= -0.15:  return "bearish~"
    return "neutral"


def fmt_age(time_str: str) -> str:
    try:
        dt = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
        h = (datetime.utcnow() - dt).total_seconds() / 3600
        return f"{int(h)}год" if h < 24 else f"{int(h/24)}д"
    except Exception:
        return "?"


def build_summary(sym: str, articles: list[dict], ticker: str) -> dict:
    scores, recent = [], []
    for a in articles:
        label, score = sentiment_for(a, ticker)
        scores.append(score)
        if len(recent) < 5:
            recent.append({
                "time": a.get("time_published", ""),
                "source": a.get("source", ""),
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "label": label,
                "score": score,
            })

    avg = sum(scores) / len(scores) if scores else 0.0
    return {
        "symbol": sym,
        "ticker": ticker,
        "label": SYMBOLS[sym]["label"],
        "articles_total": len(articles),
        "avg_score": round(avg, 4),
        "bias": bias_label(avg),
        "recent": recent,
    }


def write_json(day_dir: Path, data: dict):
    path = day_dir / "news.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  Збережено: {path}")


def write_markdown(day_dir: Path, data: dict, date_str: str):
    lines = [
        f"# Новини {date_str}",
        f"_Отримано: {datetime.utcnow().strftime('%H:%M UTC')}_",
        "",
    ]

    for sym, info in data.items():
        lines += [
            f"## {info['label']}",
            f"**Bias:** {info['bias']}  |  avg score: {info['avg_score']:+.3f}  |  статей: {info['articles_total']}",
            "",
            "| Час | Джерело | Sentiment | Заголовок |",
            "|-----|---------|-----------|-----------|",
        ]
        for a in info["recent"]:
            age = fmt_age(a["time"])
            sent = SENTIMENT_LABELS.get(a["label"], a["label"]).strip()
            title = a["title"][:70] + ("…" if len(a["title"]) > 70 else "")
            lines.append(f"| -{age} | {a['source']} | {sent} | {title} |")

        lines += ["", "**Останні статті:**", ""]
        for a in info["recent"]:
            age = fmt_age(a["time"])
            lines.append(f"- [{a['title'][:80]}]({a['url']}) _{a['source']}, -{age}_")
        lines.append("")

    path = day_dir / "news.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Збережено: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-fetch even if today's news exist")
    args = parser.parse_args()

    if not API_KEY:
        print("Помилка: export ALPHA_VANTAGE_KEY=your_key  (або додай в .env)")
        sys.exit(1)

    date_str = datetime.now().strftime("%Y-%m-%d")
    day_dir = Path(__file__).parent / "daily" / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    news_md = day_dir / "news.md"
    news_json = day_dir / "news.json"

    if news_md.exists() and not args.force:
        print(f"Новини за {date_str} вже є → {news_md}")
        print("Щоб оновити: python3 fetch_news.py --force")
        return

    print(f"Завантажую новини за {date_str}...\n")

    all_data = {}
    for i, (sym, info) in enumerate(SYMBOLS.items()):
        print(f"  {info['label']}...")
        try:
            articles = fetch(info["ticker"])
            all_data[sym] = build_summary(sym, articles, info["ticker"])
            print(f"    → {len(articles)} статей, bias: {all_data[sym]['bias']}")
        except Exception as e:
            print(f"    [!] Помилка: {e}")
            all_data[sym] = {"symbol": sym, "label": info["label"], "error": str(e),
                             "articles_total": 0, "avg_score": 0, "bias": "unknown", "recent": []}

        if i < len(SYMBOLS) - 1:
            time.sleep(1.2)  # free plan: 1 req/sec

    print()
    write_json(day_dir, all_data)
    write_markdown(day_dir, all_data, date_str)
    print(f"\nГотово. Новини: daily/{date_str}/news.md")


if __name__ == "__main__":
    main()
