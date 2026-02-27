from __future__ import annotations

import math


def detect_market_regime(candles):
    closes = _extract_closes(candles)
    if len(closes) < 30:
        return {
            "regime": "ranging",
            "volatility_state": "normal",
            "momentum": 0.0,
            "confidence": 0.0,
        }

    returns = _returns(closes)
    ema_fast = _ema(closes, 12)
    ema_slow = _ema(closes, 26)
    last_close = closes[-1]
    momentum = (last_close - closes[-20]) / closes[-20] if closes[-20] else 0.0
    trend_gap = abs(ema_fast - ema_slow) / last_close if last_close else 0.0
    volatility = _stdev(returns[-30:]) * math.sqrt(30)

    regime = "trending" if trend_gap > 0.012 or abs(momentum) > 0.03 else "ranging"
    volatility_state = "high_volatility" if volatility > 0.06 else "normal"
    confidence = max(0.0, min(1.0, trend_gap * 30 + abs(momentum) * 4))

    return {
        "regime": regime,
        "volatility_state": volatility_state,
        "momentum": momentum,
        "confidence": confidence,
    }


def select_active_strategies(agent_config, regime: str):
    regime_map = agent_config.get("regime_strategy_map", {})
    if regime in regime_map and regime_map[regime]:
        return list(regime_map[regime])
    return list(agent_config.get("strategies", []))


def score_trade_opportunity(
    candles,
    strategies,
    regime_info,
    sentiment_score: float = 0.0,
):
    strategy_scores = {}
    weights = {
        "mean_reversion": 1.0,
        "trend_follow": 1.0,
        "breakout_confirmation": 0.9,
        "sentiment_filter": 0.6,
    }

    regime = regime_info.get("regime", "ranging")
    if regime == "trending":
        weights["trend_follow"] = 1.3
        weights["mean_reversion"] = 0.6
    else:
        weights["trend_follow"] = 0.8
        weights["mean_reversion"] = 1.2

    for strategy in strategies:
        if strategy == "mean_reversion":
            strategy_scores[strategy] = score_mean_reversion(candles)
        elif strategy == "trend_follow":
            strategy_scores[strategy] = score_trend_follow(candles)
        elif strategy == "breakout_confirmation":
            strategy_scores[strategy] = score_breakout_confirmation(candles)
        elif strategy == "sentiment_filter":
            strategy_scores[strategy] = score_sentiment_filter(sentiment_score)
        else:
            strategy_scores[strategy] = 0.0

    total_weight = sum(abs(weights.get(name, 1.0)) for name in strategy_scores) or 1.0
    weighted_sum = sum(
        strategy_scores[name] * weights.get(name, 1.0) for name in strategy_scores
    )
    combined = weighted_sum / total_weight

    if regime_info.get("volatility_state") == "high_volatility":
        combined *= 0.85

    combined = _clamp(combined, -1.0, 1.0)
    return {
        "strategy_scores": strategy_scores,
        "total_score": round(combined, 4),
        "regime": regime,
        "volatility_state": regime_info.get("volatility_state", "normal"),
    }


def decision_from_score(score: float, buy_threshold: float = 0.3, sell_threshold: float = -0.3):
    if score >= buy_threshold:
        return "BUY"
    if score <= sell_threshold:
        return "SELL"
    return "HOLD"


def score_mean_reversion(candles):
    closes = _extract_closes(candles)
    if len(closes) < 20:
        return 0.0
    window = closes[-20:]
    mean = sum(window) / len(window)
    std = _stdev(window)
    if std == 0:
        return 0.0
    zscore = (closes[-1] - mean) / std
    return _clamp(-zscore / 2.0, -1.0, 1.0)


def score_trend_follow(candles):
    closes = _extract_closes(candles)
    if len(closes) < 30:
        return 0.0
    ema_fast = _ema(closes, 9)
    ema_slow = _ema(closes, 21)
    rsi = _rsi(closes, 14)
    if closes[-1] == 0:
        return 0.0
    trend_component = _clamp(((ema_fast - ema_slow) / closes[-1]) * 20.0, -1.0, 1.0)
    if rsi > 55:
        rsi_component = _clamp((rsi - 55) / 20.0, -1.0, 1.0)
    elif rsi < 45:
        rsi_component = -_clamp((45 - rsi) / 20.0, -1.0, 1.0)
    else:
        rsi_component = 0.0
    return _clamp(trend_component * 0.7 + rsi_component * 0.3, -1.0, 1.0)


def score_breakout_confirmation(candles):
    closes = _extract_closes(candles)
    if len(closes) < 25:
        return 0.0
    recent = closes[-21:-1]
    if not recent:
        return 0.0
    recent_high = max(recent)
    recent_low = min(recent)
    close = closes[-1]
    if close > recent_high:
        distance = (close - recent_high) / recent_high if recent_high else 0.0
        return _clamp(0.6 + distance * 20.0, -1.0, 1.0)
    if close < recent_low:
        distance = (recent_low - close) / recent_low if recent_low else 0.0
        return _clamp(-0.6 - distance * 20.0, -1.0, 1.0)
    center = (recent_high + recent_low) / 2.0
    if center == 0:
        return 0.0
    return _clamp((close - center) / center, -0.25, 0.25)


def score_sentiment_filter(sentiment_score: float):
    return _clamp(sentiment_score, -1.0, 1.0)


def _extract_closes(candles):
    return [float(candle["close"]) for candle in candles if "close" in candle]


def _returns(values):
    out = []
    for i in range(1, len(values)):
        if values[i - 1] == 0:
            out.append(0.0)
        else:
            out.append((values[i] - values[i - 1]) / values[i - 1])
    return out


def _ema(values, period):
    if not values:
        return 0.0
    alpha = 2 / (period + 1)
    ema = values[0]
    for value in values[1:]:
        ema = (value * alpha) + (ema * (1 - alpha))
    return ema


def _rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = values[-i] - values[-i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _stdev(values):
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _clamp(value, lower, upper):
    return max(lower, min(upper, value))

