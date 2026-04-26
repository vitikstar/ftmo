#!/usr/bin/env python3
"""
News sentiment analysis for trading instruments.
Uses Alpha Vantage NEWS_SENTIMENT API (free: 25 req/day).

Usage:
  python3 news_analysis.py                        # all instruments
  python3 news_analysis.py XAUUSD EURUSD          # specific
  python3 news_analysis.py XAUUSD --hours 4 --limit 20
"""

import os
import re
import sys
import json
import time
import argparse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# Load .env from script directory if present
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")

# Alpha Vantage ticker format per instrument
SYMBOL_MAP = {
    "XAUUSD": {"ticker": "GLD",         "topics": None,  "label": "Gold (XAUUSD / GLD)"},
    "XAGUSD": {"ticker": "SLV",         "topics": None,  "label": "Silver (XAGUSD / SLV)"},
    "EURUSD": {"ticker": "FOREX:EUR",   "topics": None,  "label": "EUR/USD"},
    "USDJPY": {"ticker": "FOREX:JPY",   "topics": None,  "label": "USD/JPY"},
    "NAS100": {"ticker": "QQQ",         "topics": None,  "label": "NAS100 (QQQ)"},
    "GER40":  {"ticker": "EWG",         "topics": None,  "label": "GER40 (EWG)"},
}

SENTIMENT_LABELS = {
    "Bearish":          "BEARISH  ",
    "Somewhat-Bearish": "bearish~ ",
    "Neutral":          "neutral  ",
    "Somewhat-Bullish": "bullish~ ",
    "Bullish":          "BULLISH  ",
}

# Regex patterns for keyword matching (word boundaries to avoid false positives)
KEYWORDS_RE = {
    "XAUUSD": re.compile(r'\bgold\b(?! *man\b)|\bxauusd\b|\bbullion\b|\bprecious metal', re.I),
    "XAGUSD": re.compile(r'\bsilver\b|\bxagusd\b', re.I),
    "EURUSD": re.compile(r'\beurusd\b|\beur/usd\b|\beuro.*dollar\b|\bdollar.*euro\b', re.I),
    "USDJPY": re.compile(r'\busdjpy\b|\busd/jpy\b|\byen\b', re.I),
    "NAS100": re.compile(r'\bnasdaq\b|\bnas100\b|\btech stocks\b', re.I),
    "GER40":  re.compile(r'\bdax\b|\bger40\b|\bgerman.*(index|stock|market)\b', re.I),
}


def fetch_news(sym: str, hours_back: int, limit: int) -> list[dict]:
    info = SYMBOL_MAP[sym]

    params = [
        "function=NEWS_SENTIMENT",
        f"limit={limit}",
        "sort=LATEST",
        f"apikey={API_KEY}",
    ]
    if info["ticker"]:
        params.append(f"tickers={info['ticker']}")
    elif info["topics"]:
        params.append(f"topics={info['topics']}")

    url = "https://www.alphavantage.co/query?" + "&".join(params)

    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  [!] Помилка запиту: {e}")
        return []

    if "Information" in data:
        print(f"  [!] Ліміт API: {data['Information'][:120]}")
        return []
    if "Note" in data:
        print(f"  [!] {data['Note'][:120]}")
        return []

    articles = data.get("feed", [])

    # For commodities without ticker — filter by regex keywords
    pattern = KEYWORDS_RE.get(sym)
    if not info["ticker"] and pattern:
        articles = [
            a for a in articles
            if pattern.search(a.get("title", "") + " " + a.get("summary", ""))
        ]

    return articles


def get_sentiment(article: dict, ticker: str):
    if not ticker:
        return None
    for ts in article.get("ticker_sentiment", []):
        if ts["ticker"].upper() == ticker.upper():
            label = ts.get("ticker_sentiment_label", "Neutral")
            score = float(ts.get("ticker_sentiment_score", 0))
            return label, score
    return None


def overall_bias(articles: list[dict], sym: str) -> tuple:
    ticker = SYMBOL_MAP[sym]["ticker"]
    scores = []
    for a in articles:
        s = get_sentiment(a, ticker)
        if s:
            scores.append(s[1])
        else:
            # Use overall article sentiment when no ticker match
            score = float(a.get("overall_sentiment_score", 0))
            scores.append(score)
    if not scores:
        return 0.0, 0
    return sum(scores) / len(scores), len(scores)


def fmt_article(article: dict, sym: str) -> str:
    ticker = SYMBOL_MAP[sym]["ticker"]
    title = article.get("title", "—")
    source = article.get("source", "")
    time_str = article.get("time_published", "")
    url = article.get("url", "")

    try:
        dt = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
        age_h = (datetime.utcnow() - dt).total_seconds() / 3600
        if age_h < 24:
            age_str = f"{int(age_h)}год тому"
        else:
            age_str = f"{int(age_h/24)}д тому"
        time_fmt = dt.strftime("%d %b %H:%M") + f"  ({age_str})"
    except Exception:
        time_fmt = time_str

    s = get_sentiment(article, ticker)
    if s:
        label, score = s
        sent_str = f"{SENTIMENT_LABELS.get(label, label)} {score:+.3f}"
    else:
        score = float(article.get("overall_sentiment_score", 0))
        label = article.get("overall_sentiment_label", "Neutral")
        sent_str = f"{SENTIMENT_LABELS.get(label, label)} {score:+.3f}  (overall)"

    lines = [
        f"  {time_fmt}  [{source}]  {sent_str}",
        f"  {title}",
        f"  {url}",
        "",
    ]
    return "\n".join(lines)


def analyze(symbols: list[str], hours_back: int, limit: int):
    if not API_KEY:
        print("Помилка: export ALPHA_VANTAGE_KEY=your_key")
        sys.exit(1)

    print(f"\n{'='*64}")
    print(f"  NEWS SENTIMENT  |  -{hours_back}год  |  {datetime.utcnow().strftime('%d %b %Y %H:%M')} UTC")
    print(f"{'='*64}\n")

    for i, sym in enumerate(symbols):
        if sym not in SYMBOL_MAP:
            print(f"[!] Невідомий символ: {sym}")
            continue

        label = SYMBOL_MAP[sym]["label"]
        print(f"── {label} {'─' * (50 - len(label))}")

        articles = fetch_news(sym, hours_back=hours_back, limit=limit)

        if not articles:
            print("  Новин не знайдено\n")
        else:
            avg, count = overall_bias(articles, sym)
            if avg > 0.15:
                bias = "▲ BULLISH"
            elif avg < -0.15:
                bias = "▼ BEARISH"
            else:
                bias = "◆ NEUTRAL"

            print(f"  Bias: {bias}  avg={avg:+.3f}  статей в базі: {count}\n")
            for a in articles[:limit]:
                print(fmt_article(a, sym))

        # Rate limit: 1 req/sec on free plan
        if i < len(symbols) - 1:
            time.sleep(1.1)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("symbols", nargs="*", default=list(SYMBOL_MAP.keys()))
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else list(SYMBOL_MAP.keys())
    analyze(symbols, hours_back=args.hours, limit=args.limit)


if __name__ == "__main__":
    main()
