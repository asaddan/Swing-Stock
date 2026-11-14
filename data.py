"""Data layer (NSE only in v1). Prices: yfinance. Delivery %: NSE security-wise bhavcopy."""
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

log = logging.getLogger("scanner.data")
CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"}
FALLBACK = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC", "LT", "AXISBANK",
            "BHARTIARTL", "MARUTI", "SUNPHARMA", "TATAMOTORS", "TITAN", "BAJFINANCE", "NTPC"]


def universe(name: str = "nifty200") -> list[str]:
    urls = {"nifty200": "ind_nifty200list.csv", "nifty500": "ind_nifty500list.csv"}
    f = CACHE / urls.get(name, urls["nifty200"])
    try:
        if not f.exists():
            r = requests.get("https://archives.nseindia.com/content/indices/" + f.name, headers=HEADERS, timeout=20)
            r.raise_for_status()
            f.write_bytes(r.content)
        return pd.read_csv(f)["Symbol"].str.strip().tolist()
    except Exception:
        return FALLBACK


def _clean(d):
    if d is None or d.empty:
        return None
    d = d.rename(columns=str.lower).dropna(subset=["close"])
    if not {"open", "high", "low", "close", "volume"} <= set(d.columns):
        return None
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    return d[["open", "high", "low", "close", "volume"]]


def _frame(raw, ticker):
    """One ticker out of a yfinance frame, whatever column layout this yfinance version returns."""
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        for lvl in (0, 1):
            if ticker in raw.columns.get_level_values(lvl):
                return raw.xs(ticker, axis=1, level=lvl)
        return None
    return raw  # single ticker, flat columns


def _daily(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Daily bars for NSE symbols. NOTE: yfinance only accepts fixed periods ('150d' is invalid), so use '1y'."""
    if not symbols:
        return {}
    raw = None
    try:
        raw = yf.download([s + ".NS" for s in symbols], period="1y", interval="1d",
                          auto_adjust=True, group_by="ticker", progress=False, threads=True)
    except Exception as e:
        log.warning("yfinance bulk download failed: %s", e)
    out = {}
    for s in symbols:
        d = None
        try:
            d = _clean(_frame(raw, s + ".NS"))
            if d is None and len(symbols) <= 10:  # slow path, only for small lists like a watchlist
                d = _clean(yf.Ticker(s + ".NS").history(period="1y", auto_adjust=True))
        except Exception as e:
            log.warning("No data for %s: %s", s, e)
        if d is not None and len(d) >= 60:
            out[s] = d
        else:
            log.warning("%s: no usable price data (rows=%s)", s, 0 if d is None else len(d))
    return out


IST = "Asia/Kolkata"


def _intraday(symbols: list[str], delay_min: int) -> dict:
    """Today's 5-minute bars, only those that finished at least `delay_min` minutes ago."""
    try:
        raw = yf.download([s + ".NS" for s in symbols], period="1d", interval="5m",
                          auto_adjust=True, group_by="ticker", progress=False, threads=True)
    except Exception as e:
        log.warning("intraday download failed: %s", e)
        return {}
    now = pd.Timestamp.now(tz=IST)
    cutoff = now - pd.Timedelta(minutes=delay_min)
    out = {}
    for s in symbols:
        try:
            d = _frame(raw, s + ".NS")
            if d is None:
                continue
            d = d.rename(columns=str.lower).dropna(subset=["close"])
            idx = d.index.tz_localize("UTC") if d.index.tz is None else d.index
            d.index = idx.tz_convert(IST)
            d = d[(d.index.normalize() == now.normalize()) & (d.index + pd.Timedelta(minutes=5) <= cutoff)]
            if d.empty:
                continue
            candle = dict(open=d.open.iloc[0], high=d.high.max(), low=d.low.min(),
                          close=d.close.iloc[-1], volume=d.volume.sum())
            out[s] = (candle, d.index[-1] + pd.Timedelta(minutes=5))
        except Exception as e:
            log.warning("intraday %s: %s", s, e)
    return out


def prices(symbols: list[str], delay_min: int | None = None) -> dict[str, pd.DataFrame]:
    """Daily history. With delay_min set, today's candle is rebuilt from 5-minute bars up to
    (now - delay_min), so a click at 3:15 PM with delay 15 sees data as of ~3:00 PM."""
    out = _daily(symbols)
    if delay_min is None or not out:
        return out
    today = pd.Timestamp(pd.Timestamp.now(tz=IST).date())
    for s, (c, asof) in _intraday(list(out), delay_min).items():
        df = out[s].copy()
        df.loc[today] = [c["open"], c["high"], c["low"], c["close"], c["volume"]]
        df = df.sort_index()
        df.attrs["asof"] = asof.strftime("%Y-%m-%d %H:%M")
        out[s] = df
    return out


def _bhav(d: date) -> pd.DataFrame | None:
    f = CACHE / f"bhav_{d:%Y%m%d}.csv"
    if not f.exists():
        url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
        except requests.RequestException:
            return None
        if r.status_code != 200 or len(r.content) < 1000:
            return None  # holiday, weekend, or not yet published
        f.write_bytes(r.content)
    df = pd.read_csv(f, skipinitialspace=True)
    df.columns = df.columns.str.strip()
    df = df[df["SERIES"].str.strip() == "EQ"].copy()
    df["symbol"] = df["SYMBOL"].str.strip()
    df["deliv_per"] = pd.to_numeric(df["DELIV_PER"], errors="coerce")
    df["deliv_qty"] = pd.to_numeric(df["DELIV_QTY"], errors="coerce")
    df["date"] = pd.Timestamp(d)
    return df[["date", "symbol", "deliv_per", "deliv_qty"]]


def delivery_history(sessions: int = 21) -> pd.DataFrame:
    """Latest `sessions` trading days of delivery data (today's file only if already published)."""
    frames, d = [], date.today()
    for _ in range(60):
        if d.weekday() < 5:
            b = _bhav(d)
            if b is not None:
                frames.append(b)
        if len(frames) >= sessions:
            break
        d -= timedelta(days=1)
    return pd.concat(frames) if frames else pd.DataFrame(columns=["date", "symbol", "deliv_per", "deliv_qty"])
