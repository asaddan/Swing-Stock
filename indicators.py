import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """Returns the Supertrend line and a boolean `buy` column (True = bullish)."""
    a = atr(df, period)
    hl2 = (df.high + df.low) / 2
    ub, lb = (hl2 + mult * a).values, (hl2 - mult * a).values
    c = df.close.values
    n = len(df)
    fu, fl = ub.copy(), lb.copy()
    up = np.ones(n, dtype=bool)
    line = np.zeros(n)
    line[0] = fl[0]
    for i in range(1, n):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        up[i] = c[i] >= fl[i] if up[i - 1] else c[i] > fu[i]
        line[i] = fl[i] if up[i] else fu[i]
    return pd.DataFrame({"supertrend": line, "buy": up}, index=df.index)


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def poc(df: pd.DataFrame, lookback: int = 60, bins: int = 30) -> float:
    """Approximate Point of Control from DAILY bars: each day's volume goes to its typical-price bucket.
    A real volume profile needs intraday data, so treat this as an estimate."""
    d = df.tail(lookback)
    edges = np.linspace(d.low.min(), d.high.max(), bins + 1)
    typ = (d.high + d.low + d.close) / 3
    idx = np.clip(np.digitize(typ, edges) - 1, 0, bins - 1)
    k = int(np.bincount(idx, weights=d.volume.values, minlength=bins).argmax())
    return float((edges[k] + edges[k + 1]) / 2)
