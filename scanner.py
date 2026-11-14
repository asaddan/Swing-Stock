import math
import time

from pydantic import BaseModel

import data
from indicators import atr, ema, poc, rsi, supertrend


class Settings(BaseModel):
    universe: str = "nifty200"
    mode: str = "live"            # "live" (3:15 PM) or "close" (post-close)
    min_value_cr: float = 10.0    # 20-day avg traded value, crore
    min_price: float = 50.0
    min_delivery: float = 50.0    # %
    close_in_range: float = 0.70  # close in upper 30% of day range
    st_period: int = 10
    st_mult: float = 3.0
    entry_buffer: float = 0.1     # % above signal high
    atr_mult: float = 1.5
    min_rr: float = 2.0
    resistance_lookback: int = 60
    capital: float = 500000
    risk_pct: float = 1.0
    cost_pct: float = 0.25        # round-trip cost, % of traded value
    rsi_min: float = 40.0         # momentum zone (RSI 14)
    rsi_max: float = 70.0
    atr_min: float = 1.5          # ATR as % of price: enough movement, not too wild
    atr_max: float = 6.0
    poc_lookback: int = 60
    delay_min: int = 15           # use prices up to this many minutes ago (15-20 typical)


_cache: dict = {}


def _tick(x: float, up: bool = True) -> float:
    return round((math.ceil(x * 20) if up else math.floor(x * 20)) / 20, 2)


def run_scan(s: Settings) -> dict:
    key = (s.universe, s.delay_min, int(time.time() // 60))
    if key not in _cache:
        syms = data.universe(s.universe)
        _cache.clear()
        _cache[key] = (data.prices(syms, s.delay_min), data.delivery_history())
    px, dlv = _cache[key]

    funnel = {"Universe": len(px)}
    rows, stage = [], {k: 0 for k in ["Liquidity", "Delivery", "Price action", "Trend", "Trade plan"]}
    dsym = {k: g.sort_values("date") for k, g in dlv.groupby("symbol")} if not dlv.empty else {}
    last_px_day = max(d.index[-1] for d in px.values()) if px else None

    for sym, df in px.items():
        c, last, prev = df.close, df.iloc[-1], df.iloc[-2]
        val = (c * df.volume).tail(20).mean() / 1e7
        if val < s.min_value_cr or last.close < s.min_price:
            continue
        stage["Liquidity"] += 1

        g = dsym.get(sym)
        if g is None or len(g) < 5:
            continue
        # live mode: ignore a delivery row dated today if it only reflects a partial/unpublished day
        if s.mode == "live" and g.date.iloc[-1] == last_px_day and len(g) > 1:
            g = g.iloc[:-1]
        d_today, d_avg = float(g.deliv_per.iloc[-1]), float(g.deliv_per.iloc[:-1].tail(20).mean())
        d_date = g.date.iloc[-1]
        row = df.loc[d_date] if d_date in df.index else None
        prow = df.shift(1).loc[d_date] if d_date in df.index else None
        green = row is not None and row.close > row.open and row.close > prow.close
        if not (d_today >= s.min_delivery and d_today > d_avg and green):
            continue
        stage["Delivery"] += 1

        rng = last.high - last.low
        pos = (last.close - last.low) / rng if rng > 0 else 0
        vol_ratio = last.volume / df.volume.tail(21).iloc[:-1].mean()
        if not (pos >= s.close_in_range and last.close > prev.close and vol_ratio >= 1):
            continue
        stage["Price action"] += 1

        e20, e50 = ema(c, 20).iloc[-1], ema(c, 50).iloc[-1]
        st = supertrend(df, s.st_period, s.st_mult).iloc[-1]
        if not (last.close > e20 and last.close > e50 and e20 > e50 and bool(st.buy)):
            continue
        stage["Trend"] += 1

        a = atr(df, 14).iloc[-1]
        entry = _tick(last.high * (1 + s.entry_buffer / 100))
        stop = _tick(max(last.low, entry - s.atr_mult * a), up=False)
        risk = entry - stop
        if risk <= 0:
            continue
        target = _tick(entry + s.min_rr * risk)
        res = df.high.tail(s.resistance_lookback).max()
        if entry < res < target:  # nearest resistance blocks the 1:2 move
            continue
        cost = s.cost_pct / 100 * (entry + target)
        qty = int(s.capital * s.risk_pct / 100 // risk)
        stage["Trade plan"] += 1
        ex = extra_checks(df, s)  # survivors already pass the 5 core rules (weight 7 = 70%)
        rows.append({
            "symbol": sym, "close": round(last.close, 2), "delivery": round(d_today, 1),
            "delivery_avg": round(d_avg, 1), "delivery_date": str(d_date.date()),
            "close_pos": round(pos * 100), "vol_ratio": round(vol_ratio, 2),
            "ema20": round(e20, 2), "ema50": round(e50, 2), "supertrend": round(st.supertrend, 2),
            "atr_pct": round(a / last.close * 100, 2), "value_cr": round(val, 1),
            "extras": ex, "score": 70 + 10 * sum(WEIGHTS[k["name"]] for k in ex if k["ok"]),
            "entry": entry, "stop": stop, "target": target, "qty": qty,
            "rr": round((target - entry) / risk, 2),
            "net_rr": round(((target - entry) - cost) / (risk + cost), 2),
            "risk_amt": round(qty * risk), "resistance": round(res, 2),
        })
    funnel.update(stage)
    rows.sort(key=lambda r: r["delivery"] - r["delivery_avg"], reverse=True)
    asof = max((d.attrs["asof"] for d in px.values() if d.attrs.get("asof")), default=None)
    return {"rows": rows, "funnel": funnel, "asof": asof, "price_date": str(last_px_day.date()) if last_px_day is not None else None,
            "delivery_date": str(dlv.date.max().date()) if not dlv.empty else None}


# ---------- Watchlist analysis: every rule evaluated, nothing short-circuited ----------
_dc: dict = {}


def _delivery():
    k = int(time.time() // 300)
    if _dc.get("k") != k:
        _dc.clear()
        _dc.update(k=k, v=data.delivery_history())
    return _dc["v"]


def analyze(symbols: list[str], s: Settings) -> list[dict]:
    px = data.prices(symbols, s.delay_min) if symbols else {}
    dlv = _delivery()
    out = []
    for sym in symbols:
        df = px.get(sym)
        if df is None:
            out.append({"symbol": sym, "error": "No price data (needs 60+ sessions of NSE history)."})
            continue
        c, last, prev = df.close, df.iloc[-1], df.iloc[-2]
        checks = []

        val = (c * df.volume).tail(20).mean() / 1e7
        checks.append({"name": "Liquidity", "ok": bool(val >= s.min_value_cr and last.close >= s.min_price),
                       "detail": f"₹{val:.1f} cr 20-day traded value, price ₹{last.close:.2f}"})

        g = dlv[dlv.symbol == sym].sort_values("date") if not dlv.empty else dlv
        if s.mode == "live" and len(g) > 1 and g.date.iloc[-1] == df.index[-1]:
            g = g.iloc[:-1]
        if len(g) >= 5:
            d_now, d_avg, d_date = float(g.deliv_per.iloc[-1]), float(g.deliv_per.iloc[:-1].tail(20).mean()), g.date.iloc[-1]
            green = d_date in df.index and df.loc[d_date].close > df.loc[d_date].open \
                and df.loc[d_date].close > df.close.shift(1).loc[d_date]
            checks.append({"name": "Delivery", "ok": bool(d_now >= s.min_delivery and d_now > d_avg and green),
                           "detail": f"{d_now:.1f}% vs {d_avg:.1f}% average on {d_date.date()}, "
                                     f"{'green' if green else 'not green'} candle"})
        else:
            checks.append({"name": "Delivery", "ok": False, "detail": "No delivery data found for this symbol."})

        rng = last.high - last.low
        pos = (last.close - last.low) / rng if rng > 0 else 0
        vr = last.volume / df.volume.tail(21).iloc[:-1].mean()
        checks.append({"name": "Closing strength", "ok": bool(pos >= s.close_in_range and last.close > prev.close and vr >= 1),
                       "detail": f"Closed in top {100 - pos * 100:.0f}% of range, volume {vr:.2f}x average"})

        e20, e50 = ema(c, 20).iloc[-1], ema(c, 50).iloc[-1]
        st = supertrend(df, s.st_period, s.st_mult).iloc[-1]
        checks.append({"name": "Trend", "ok": bool(last.close > e20 and last.close > e50 and e20 > e50 and st.buy),
                       "detail": f"20 EMA {e20:.2f}, 50 EMA {e50:.2f}, Supertrend {'buy' if st.buy else 'sell'} at {st.supertrend:.2f}"})

        a = atr(df, 14).iloc[-1]
        entry = _tick(last.high * (1 + s.entry_buffer / 100))
        stop = _tick(max(last.low, entry - s.atr_mult * a), up=False)
        risk = entry - stop
        res = df.high.tail(s.resistance_lookback).max()
        plan, rr_ok, rr_detail = None, False, "Stop is not below entry."
        if risk > 0:
            target = _tick(entry + s.min_rr * risk)
            blocked = entry < res < target
            cost = s.cost_pct / 100 * (entry + target)
            plan = {"entry": entry, "stop": stop, "target": target, "qty": int(s.capital * s.risk_pct / 100 // risk),
                    "net_rr": round(((target - entry) - cost) / (risk + cost), 2)}
            rr_ok = not blocked
            rr_detail = (f"Resistance at {res:.2f} sits inside the path to target {target}" if blocked
                         else f"Clear path to target {target}; risk ₹{risk:.2f} per share")
        checks.append({"name": "Risk:reward", "ok": rr_ok, "detail": rr_detail})

        checks += extra_checks(df, s)
        for k in checks:
            k["w"] = WEIGHTS[k["name"]]
        met = sum(k["ok"] for k in checks)
        score = sum(k["w"] for k in checks if k["ok"]) * 10
        out.append({"symbol": sym, "close": round(float(last.close), 2), "asof": df.attrs.get("asof"), "price_date": str(df.index[-1].date()), "met": met, "total": len(checks), "score": score,
                    "ready": met == len(checks), "checks": checks, "plan": plan})
    return out


# ---------- Weighted score: weights add up to 10, so each point = 10% ----------
WEIGHTS = {"Liquidity": 1, "Delivery": 2, "Closing strength": 1, "Trend": 2, "Risk:reward": 1,
           "Momentum (RSI)": 1, "Volatility (ATR)": 1, "Volume structure": 1}


def extra_checks(df, s: Settings) -> list[dict]:
    last = float(df.close.iloc[-1])
    r = float(rsi(df.close).iloc[-1])
    a = float(atr(df, 14).iloc[-1])
    ap = a / last * 100
    p = poc(df, s.poc_lookback)
    return [
        {"name": "Momentum (RSI)", "ok": bool(s.rsi_min <= r <= s.rsi_max),
         "detail": f"RSI(14) is {r:.1f}; healthy zone {s.rsi_min:g} to {s.rsi_max:g}"},
        {"name": "Volatility (ATR)", "ok": bool(s.atr_min <= ap <= s.atr_max),
         "detail": f"ATR is {ap:.2f}% of price (₹{a:.2f}); tradable range {s.atr_min:g}% to {s.atr_max:g}%"},
        {"name": "Volume structure", "ok": bool(last > p),
         "detail": f"Close ₹{last:.2f} vs estimated point of control ₹{p:.2f} (from daily bars)"},
    ]
