from __future__ import annotations

import random
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from json import loads

TIMEFRAME_MINUTES = {
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "1d": 1440,
}

SYMBOL_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
}

BASE_PRICE = {
    "BTC": 60000.0,
    "ETH": 3200.0,
    "SOL": 120.0,
    "BNB": 550.0,
    "XRP": 0.65,
}


def timeframe_to_minutes(timeframe: str) -> int:
    timeframe = timeframe.strip().lower()
    if timeframe in TIMEFRAME_MINUTES:
        return TIMEFRAME_MINUTES[timeframe]
    if timeframe.endswith("m"):
        return int(timeframe[:-1])
    if timeframe.endswith("h"):
        return int(timeframe[:-1]) * 60
    if timeframe.endswith("d"):
        return int(timeframe[:-1]) * 1440
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def validate_timeframe(timeframe: str, minimum_minutes: int = 15) -> int:
    minutes = timeframe_to_minutes(timeframe)
    if minutes < minimum_minutes:
        raise ValueError(
            f"Timeframe {timeframe} is below minimum {minimum_minutes} minutes."
        )
    return minutes


def asset_to_symbol(asset: str) -> str:
    key = asset.strip().upper()
    if key not in SYMBOL_MAP:
        raise ValueError(f"Unsupported asset: {asset}")
    return SYMBOL_MAP[key]


def _http_get_json(url: str, timeout: int = 8):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "cryptoMaster/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return loads(response.read().decode("utf-8"))


def fetch_ohlcv(
    asset: str,
    timeframe: str = "15m",
    limit: int = 160,
    minimum_minutes: int = 15,
    timeout: int = 8,
):
    validate_timeframe(timeframe, minimum_minutes)
    symbol = asset_to_symbol(asset)
    query = urllib.parse.urlencode({"symbol": symbol, "interval": timeframe, "limit": limit})
    url = f"https://api.binance.com/api/v3/klines?{query}"
    try:
        rows = _http_get_json(url, timeout=timeout)
        candles = []
        for row in rows:
            candles.append(
                {
                    "open_time": datetime.fromtimestamp(
                        row[0] / 1000, tz=timezone.utc
                    ).isoformat(),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": datetime.fromtimestamp(
                        row[6] / 1000, tz=timezone.utc
                    ).isoformat(),
                }
            )
        if candles:
            return candles
    except Exception:
        pass
    return _generate_synthetic_candles(asset=asset, timeframe=timeframe, limit=limit)


def fetch_top_market_snapshot(assets, timeout: int = 8):
    snapshot = {}
    for asset in assets:
        symbol = asset_to_symbol(asset)
        query = urllib.parse.urlencode({"symbol": symbol})
        url = f"https://api.binance.com/api/v3/ticker/24hr?{query}"
        try:
            data = _http_get_json(url, timeout=timeout)
            snapshot[asset] = {
                "last_price": float(data["lastPrice"]),
                "price_change_pct_24h": float(data["priceChangePercent"]),
                "quote_volume_24h": float(data["quoteVolume"]),
            }
        except Exception:
            fallback = _generate_synthetic_candles(asset=asset, timeframe="1h", limit=2)
            prev_close = fallback[-2]["close"]
            last_close = fallback[-1]["close"]
            pct = ((last_close - prev_close) / prev_close) * 100 if prev_close else 0.0
            snapshot[asset] = {
                "last_price": last_close,
                "price_change_pct_24h": pct,
                "quote_volume_24h": 0.0,
            }
    return snapshot


def _generate_synthetic_candles(asset: str, timeframe: str, limit: int):
    minutes = timeframe_to_minutes(timeframe)
    seed = sum(ord(char) for char in f"{asset}:{timeframe}:{limit}")
    randomizer = random.Random(seed)
    base = BASE_PRICE.get(asset.upper(), 100.0)
    now = datetime.now(timezone.utc)

    candles = []
    close = base * (1.0 + randomizer.uniform(-0.02, 0.02))
    for index in range(limit):
        drift = randomizer.uniform(-0.0035, 0.0035)
        close = max(0.0001, close * (1.0 + drift))
        high = close * (1.0 + abs(randomizer.uniform(0.0002, 0.0025)))
        low = close * (1.0 - abs(randomizer.uniform(0.0002, 0.0025)))
        open_price = close * (1.0 + randomizer.uniform(-0.001, 0.001))
        volume = randomizer.uniform(100, 10000)
        candle_time = now - timedelta(minutes=minutes * (limit - index))
        candles.append(
            {
                "open_time": candle_time.isoformat(),
                "open": round(open_price, 8),
                "high": round(max(high, open_price, close), 8),
                "low": round(min(low, open_price, close), 8),
                "close": round(close, 8),
                "volume": round(volume, 8),
                "close_time": (candle_time + timedelta(minutes=minutes)).isoformat(),
            }
        )
    return candles

