"""Core logic for the Nifty 500 volume scanner and backtester.

No Streamlit code in here, so it can be tested on its own.
All price data is held as "panels": one DataFrame per field
(Open/High/Low/Close/Volume) with dates as rows and symbols as columns.
"""
import io

import numpy as np
import pandas as pd
import requests

NSE_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
FIELDS = ["Open", "High", "Low", "Close", "Volume"]
HORIZONS = (1, 3, 5)  # forward returns measured N trading days after the signal day


# ----------------------------------------------------------------------------
# Loading data
# ----------------------------------------------------------------------------
def load_constituents() -> pd.DataFrame:
    """Nifty 500 list from NSE; falls back to a local nifty500.csv if NSE blocks."""
    try:
        r = requests.get(NSE_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        df = pd.read_csv("nifty500.csv")  # same format as the NSE file
    df.columns = [c.strip() for c in df.columns]
    df = df[["Company Name", "Industry", "Symbol"]].dropna()
    df["Symbol"] = df["Symbol"].str.strip()
    return df.reset_index(drop=True)


def fetch_panels(symbols, period="1y") -> dict:
    """Download daily OHLCV for all symbols from Yahoo Finance into panels."""
    import yfinance as yf  # imported here so the module is importable without it

    tickers = [f"{s}.NS" for s in symbols]
    series = {f: {} for f in FIELDS}

    for i in range(0, len(tickers), 100):
        batch = tickers[i : i + 100]
        try:
            data = yf.download(
                batch,
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
        except Exception:
            continue
        if data is None or data.empty:
            continue

        for t in batch:
            try:
                d = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                d = d[FIELDS].dropna(subset=["Close"])
            except KeyError:
                continue
            if d.empty:
                continue
            idx = pd.to_datetime(d.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            d = d.copy()
            d.index = idx.normalize()
            d = d[~d.index.duplicated(keep="last")]
            sym = t[:-3]  # strip ".NS"
            for f in FIELDS:
                series[f][sym] = d[f]

    panels = {f: pd.DataFrame(series[f]).sort_index() for f in FIELDS}
    close = panels["Close"]
    if close.empty:
        return panels
    # drop dates where fewer than half the stocks traded (holidays / partial rows)
    ok = close.notna().sum(axis=1) >= 0.5 * close.shape[1]
    return {f: df.loc[ok] for f, df in panels.items()}


# ----------------------------------------------------------------------------
# Single-day scan (+ forward tracking when the day is in the past)
# ----------------------------------------------------------------------------
def _avg_volume(vol: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Average volume of the `lookback` days BEFORE each day (today excluded)."""
    return vol.shift(1).rolling(lookback, min_periods=lookback).mean()


def scan_day(panels: dict, lookback: int, p: int, entry: str = "close") -> pd.DataFrame:
    """Scan one day (row position `p`) for every stock.

    If days exist after `p`, forward-return columns are added:
      Gap %        next-day open vs signal-day close
      D+1/3/5 %    close N trading days after the signal vs entry price
      Till Date %  latest close vs entry price
      Max High %   best price reached after the signal vs entry
      Max Low %    worst price reached after the signal vs entry
    entry = "close" -> buy at signal-day close, "open" -> buy at next-day open.
    """
    o, h, l, c, v = (panels[f] for f in FIELDS)
    n = len(c)

    close = c.iloc[p]
    df = pd.DataFrame(
        {
            "LTP": close,
            "Change %": (close / c.iloc[p - 1] - 1) * 100,
            "Volume": v.iloc[p],
            "Avg Volume": _avg_volume(v, lookback).iloc[p],
        }
    )
    df["Volume Multiple"] = df["Volume"] / df["Avg Volume"]
    df["Value (Cr)"] = df["LTP"] * df["Volume"] / 1e7
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    df = df[(df["Volume"] > 0) & (df["Avg Volume"] > 0)].copy()
    df["Volume"] = df["Volume"].astype("int64")
    df["Avg Volume"] = df["Avg Volume"].astype("int64")
    df.index.name = "Symbol"

    if p + 1 <= n - 1:
        syms = df.index
        next_open = o.iloc[p + 1].reindex(syms)
        entry_px = next_open if entry == "open" else df["LTP"]

        df["Gap %"] = (next_open / df["LTP"] - 1) * 100
        for k in HORIZONS:
            if p + k <= n - 1:
                df[f"D+{k} %"] = (c.iloc[p + k].reindex(syms) / entry_px - 1) * 100
            else:
                df[f"D+{k} %"] = np.nan
        df["Till Date %"] = (c.iloc[-1].reindex(syms) / entry_px - 1) * 100
        df["Max High %"] = (h.iloc[p + 1 :].max().reindex(syms) / entry_px - 1) * 100
        df["Max Low %"] = (l.iloc[p + 1 :].min().reindex(syms) / entry_px - 1) * 100

    return df.round(2)


def price_path(panels: dict, symbols, p: int, entry: str = "close") -> pd.DataFrame:
    """% move of each symbol from its entry price, day by day after the signal."""
    c, o = panels["Close"], panels["Open"]
    symbols = list(symbols)
    if entry == "open" and p + 1 <= len(c) - 1:
        base, path = o.iloc[p + 1][symbols], c.iloc[p + 1 :][symbols]
    else:
        base, path = c.iloc[p][symbols], c.iloc[p:][symbols]
    return (path / base - 1) * 100


# ----------------------------------------------------------------------------
# Multi-day backtest
# ----------------------------------------------------------------------------
def multi_day_signals(
    panels: dict,
    lookback: int,
    start_pos: int,
    end_pos: int,
    min_mult: float,
    direction: str = "All",
    min_price: float = 0.0,
    min_value_cr: float = 0.0,
    entry: str = "close",
) -> pd.DataFrame:
    """Every signal fired between row positions start_pos..end_pos, with forward returns.

    end_pos must be <= len(close) - 2 so that at least the next day exists.
    """
    o, h, l, c, v = (panels[f] for f in FIELDS)
    n = len(c)
    end_pos = min(end_pos, n - 2)

    mult = v / _avg_volume(v, lookback)
    chg = (c / c.shift(1) - 1) * 100
    value = c * v / 1e7

    mask = (mult >= min_mult) & (v > 0) & (c >= min_price) & (value >= min_value_cr)
    if direction == "Gainers":
        mask &= chg > 0
    elif direction == "Losers":
        mask &= chg < 0

    m = mask.values.copy()
    m[:start_pos] = False
    m[end_pos + 1 :] = False
    rows, cols = np.where(m)

    c_v, o_v = c.values, o.values
    entry_px = o_v[rows + 1, cols] if entry == "open" else c_v[rows, cols]

    out = pd.DataFrame(
        {
            "Date": c.index[rows],
            "Symbol": c.columns[cols],
            "LTP": c_v[rows, cols],
            "Change %": chg.values[rows, cols],
            "Volume Multiple": mult.values[rows, cols],
            "Gap %": (o_v[rows + 1, cols] / c_v[rows, cols] - 1) * 100,
        }
    )
    for k in HORIZONS:
        r2 = rows + k
        valid = r2 <= n - 1
        vals = np.full(len(rows), np.nan)
        vals[valid] = (c_v[r2[valid], cols[valid]] / entry_px[valid] - 1) * 100
        out[f"D+{k} %"] = vals

    num_cols = out.columns.drop(["Date", "Symbol"])
    out[num_cols] = out[num_cols].round(2)
    return out


def horizon_summary(signals: pd.DataFrame) -> pd.DataFrame:
    """Win rate / average / median return for each holding horizon."""
    recs = []
    for k in HORIZONS:
        s = signals[f"D+{k} %"].dropna()
        if s.empty:
            continue
        recs.append(
            {
                "Horizon": f"D+{k}",
                "Signals": len(s),
                "Win rate %": round((s > 0).mean() * 100, 1),
                "Avg %": round(s.mean(), 2),
                "Median %": round(s.median(), 2),
                "Best %": round(s.max(), 2),
                "Worst %": round(s.min(), 2),
            }
        )
    return pd.DataFrame(recs)


def daily_summary(signals: pd.DataFrame) -> pd.DataFrame:
    """One row per signal date: how many signals and how they did next day."""
    if signals.empty:
        return pd.DataFrame()
    g = signals.groupby("Date")
    d = g.agg(Signals=("Symbol", "count"), avg1=("D+1 %", "mean"), avg5=("D+5 %", "mean"))
    d["Win rate D+1 %"] = g["D+1 %"].apply(
        lambda s: (s.dropna() > 0).mean() * 100 if s.notna().any() else np.nan
    )
    d = d.rename(columns={"avg1": "Avg D+1 %", "avg5": "Avg D+5 %"})
    return d.round(2).sort_index(ascending=False)
