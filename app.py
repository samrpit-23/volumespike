import io
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Nifty 500 Volume Scanner", page_icon="📈", layout="wide")

NSE_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
@st.cache_data(ttl=24 * 3600, show_spinner=False)
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


@st.cache_data(ttl=300, show_spinner=False)
def fetch_volume_data(symbols: tuple, lookback: int) -> pd.DataFrame:
    """Download daily data in batches and compute volume multiple per stock."""
    tickers = [f"{s}.NS" for s in symbols]
    rows = []

    for i in range(0, len(tickers), 100):
        batch = tickers[i : i + 100]
        try:
            data = yf.download(
                batch,
                period="3mo",
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
                d = d[["Close", "Volume"]].dropna()
                d = d[d["Volume"] > 0]
            except KeyError:
                continue
            if len(d) < lookback + 2:
                continue

            last_close = float(d["Close"].iloc[-1])
            prev_close = float(d["Close"].iloc[-2])
            last_vol = float(d["Volume"].iloc[-1])
            avg_vol = float(d["Volume"].iloc[-(lookback + 1) : -1].mean())
            if avg_vol <= 0:
                continue

            rows.append(
                {
                    "Symbol": t.replace(".NS", ""),
                    "LTP": round(last_close, 2),
                    "Change %": round((last_close / prev_close - 1) * 100, 2),
                    "Volume": int(last_vol),
                    "Avg Volume": int(avg_vol),
                    "Volume Multiple": round(last_vol / avg_vol, 2),
                    "Value (Cr)": round(last_close * last_vol / 1e7, 2),
                    "Date": d.index[-1].strftime("%d-%b-%Y"),
                }
            )

    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
st.title("📈 Nifty 500 Volume Scanner")
st.caption("Finds stocks trading at a multiple of their average daily volume.")

with st.sidebar:
    st.header("Filters")

    min_mult = st.slider(
        "Min volume multiple (x)",
        min_value=1.0,
        max_value=20.0,
        value=5.0,
        step=0.5,
        help="Today's volume ÷ average volume of the previous N days",
    )
    lookback = st.slider("Average volume lookback (days)", 5, 60, 20, 5)
    direction = st.radio("Price direction", ["All", "Gainers", "Losers"], horizontal=True)
    min_price = st.number_input("Min price (₹)", min_value=0.0, value=0.0, step=10.0)
    min_value_cr = st.number_input("Min traded value (₹ Cr)", min_value=0.0, value=0.0, step=1.0)

    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    stocks = load_constituents()
except Exception:
    st.error(
        "Could not load the Nifty 500 list from NSE. Download "
        "`ind_nifty500list.csv` from niftyindices.com, save it as `nifty500.csv` "
        "in the repo root, and redeploy."
    )
    st.stop()

industries = sorted(stocks["Industry"].unique())
with st.sidebar:
    picked_industries = st.multiselect("Industry (optional)", industries)

with st.spinner("Fetching volume data for Nifty 500… (first load takes ~30–60 sec)"):
    df = fetch_volume_data(tuple(stocks["Symbol"]), lookback)

if df.empty:
    st.warning("No data returned. Yahoo Finance may be rate limiting — try Refresh in a minute.")
    st.stop()

df = df.merge(stocks, on="Symbol", how="left").rename(columns={"Company Name": "Company"})
df["Chart"] = "https://in.tradingview.com/chart/?symbol=NSE:" + df["Symbol"].str.replace("&", "_").str.replace("-", "_")

# apply filters
mask = df["Volume Multiple"] >= min_mult
if direction == "Gainers":
    mask &= df["Change %"] > 0
elif direction == "Losers":
    mask &= df["Change %"] < 0
mask &= df["LTP"] >= min_price
mask &= df["Value (Cr)"] >= min_value_cr
if picked_industries:
    mask &= df["Industry"].isin(picked_industries)

result = (
    df[mask]
    .sort_values("Volume Multiple", ascending=False)
    [["Symbol", "Company", "Industry", "LTP", "Change %", "Volume", "Avg Volume",
      "Volume Multiple", "Value (Cr)", "Date", "Chart"]]
    .reset_index(drop=True)
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stocks scanned", len(df))
c2.metric(f"Volume ≥ {min_mult:g}x", len(result))
c3.metric("Gainers", int((result["Change %"] > 0).sum()))
c4.metric("Losers", int((result["Change %"] < 0).sum()))
st.caption(f"Latest bar: {df['Date'].max()}  •  Refreshed: {datetime.now().strftime('%d-%b-%Y %H:%M')}")

if result.empty:
    st.info("No stocks match the current filters. Try lowering the volume multiple.")
else:
    st.dataframe(
        result,
        use_container_width=True,
        hide_index=True,
        height=min(750, 40 + 35 * len(result)),
        column_config={
            "LTP": st.column_config.NumberColumn(format="₹%.2f"),
            "Change %": st.column_config.NumberColumn(format="%.2f%%"),
            "Volume": st.column_config.NumberColumn(format="%d"),
            "Avg Volume": st.column_config.NumberColumn(format="%d"),
            "Volume Multiple": st.column_config.ProgressColumn(
                format="%.2fx", min_value=0, max_value=float(max(20, result["Volume Multiple"].max()))
            ),
            "Value (Cr)": st.column_config.NumberColumn(format="₹%.2f"),
            "Chart": st.column_config.LinkColumn(display_text="Open"),
        },
    )
    st.download_button(
        "⬇️ Download CSV",
        result.drop(columns="Chart").to_csv(index=False).encode(),
        file_name=f"nifty500_volume_scan_{datetime.now():%Y%m%d}.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    "Note: during market hours the latest daily bar has *partial* volume, so multiples "
    "look smaller until close. Data from Yahoo Finance may be delayed. "
    "For information only — not investment advice."
)
