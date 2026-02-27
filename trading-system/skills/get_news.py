from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as et
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ASSET_KEYWORDS = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ether", "ethereum"],
    "SOL": ["sol", "solana"],
    "BNB": ["bnb", "binance coin", "binance smart chain"],
    "XRP": ["xrp", "ripple"],
}

POSITIVE_WORDS = {
    "adoption",
    "approval",
    "breakout",
    "bull",
    "bullish",
    "gain",
    "growth",
    "high",
    "institutional",
    "rally",
    "surge",
    "uptrend",
    "win",
}

NEGATIVE_WORDS = {
    "ban",
    "bear",
    "bearish",
    "drop",
    "hack",
    "lawsuit",
    "loss",
    "low",
    "reject",
    "selloff",
    "slump",
    "warning",
}


def fetch_news(rss_feeds, max_items: int = 40, timeout: int = 8):
    items = []
    for feed in rss_feeds:
        try:
            request = urllib.request.Request(
                feed,
                headers={"User-Agent": "cryptoMaster/1.0"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content = response.read().decode("utf-8", errors="ignore")
            root = et.fromstring(content)
            for node in root.findall(".//item"):
                title = (node.findtext("title") or "").strip()
                description = (node.findtext("description") or "").strip()
                link = (node.findtext("link") or "").strip()
                published_raw = (node.findtext("pubDate") or "").strip()
                published_at = _normalize_timestamp(published_raw)
                items.append(
                    {
                        "title": title,
                        "description": description,
                        "link": link,
                        "source": feed,
                        "published_at": published_at,
                    }
                )
        except Exception:
            continue
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items[:max_items]


def fetch_asset_sentiment(assets, rss_feeds, max_items: int = 40, timeout: int = 8):
    news_items = fetch_news(rss_feeds, max_items=max_items, timeout=timeout)
    return build_asset_sentiment(news_items, assets)


def build_asset_sentiment(news_items, assets):
    sentiment_map = {asset: 0.0 for asset in assets}
    mentions = {asset: 0 for asset in assets}

    for item in news_items:
        text = f"{item.get('title', '')} {item.get('description', '')}".lower()
        score = score_sentiment(text)
        for asset in assets:
            if _mentions_asset(text, asset):
                sentiment_map[asset] += score
                mentions[asset] += 1

    for asset in assets:
        if mentions[asset]:
            sentiment_map[asset] = max(-1.0, min(1.0, sentiment_map[asset] / mentions[asset]))
    return sentiment_map


def score_sentiment(text: str) -> float:
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    if not tokens:
        return 0.0
    positive = sum(1 for token in tokens if token in POSITIVE_WORDS)
    negative = sum(1 for token in tokens if token in NEGATIVE_WORDS)
    raw = positive - negative
    if raw == 0:
        return 0.0
    return max(-1.0, min(1.0, raw / 3.0))


def _mentions_asset(text: str, asset: str) -> bool:
    keywords = ASSET_KEYWORDS.get(asset.upper(), [asset.lower()])
    return any(keyword in text for keyword in keywords)


def _normalize_timestamp(value: str) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()

