from datetime import datetime

import pandas as pd
import streamlit as st

import scanner as sc

st.set_page_config(page_title="Nifty 500 Volume Scanner", page_icon="📈", layout="wide")


# ----------------------------------------------------------------------------
# Cached data access
# ----------------------------------------------------------------------------
@st.cache_data(ttl=24 * 3600, show_spinner=False)
def get_constituents() -> pd.DataFrame:
    return sc.load_constituents()


@st.cache_data(ttl=600, show_spinner=False)
def get_panels(symbols: tuple) -> dict:
    return sc.fetch_panels(list(symbols), period="1y")


# ----------------------------------------------------------------------------
# Sidebar filters (shared by all tabs)
# ----------------------------------------------------------------------------
st.title("📈 Nifty 500 Volume Scanner")
st.caption("Find stocks trading at a multiple of their average volume — and backtest what happened next.")

try:
    stocks = get_constituents()
except Exception:
    st.error(
        "Could not load the Nifty 500 list from NSE. Download `ind_nifty500list.csv` "
        "from niftyindices.com, save it as `nifty500.csv` in the repo root, and redeploy."
    )
    st.stop()

with st.sidebar:
    st.header("Scanner filters")
    min_mult = st.slider(
        "Min volume multiple (x)", 1.0, 20.0, 2.0, 0.5,
        help="Day's volume ÷ average volume of the previous N days",
    )
    lookback = st.slider("Average volume lookback (days)", 5, 60, 20, 5)
    direction = st.radio("Price direction", ["All", "Gainers", "Losers"], horizontal=True)
    split_view = st.checkbox(
        "Show Gainers and Losers in separate tables", value=True,
        help="Only applies when Price direction is 'All'",
    )
    min_price = st.number_input("Min price (₹)", min_value=0.0, value=0.0, step=10.0)
    min_value_cr = st.number_input("Min traded value (₹ Cr)", min_value=0.0, value=0.0, step=1.0)
    picked_industries = st.multiselect("Industry (optional)", sorted(stocks["Industry"].unique()))

    st.header("Backtest settings")
    entry_label = st.radio(
        "Entry price for returns",
        ["Signal-day close", "Next-day open"],
        help="Signal-day close: you buy at the close of the day the stock was flagged. "
        "Next-day open: you see the scan after close and buy at the next open.",
    )
    entry = "close" if entry_label == "Signal-day close" else "open"

    if st.button("🔄 Refresh data", width="stretch"):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Fetching 1 year of data for Nifty 500… (first load takes ~1 min)"):
    panels = get_panels(tuple(stocks["Symbol"]))

close_panel = panels["Close"]
n = len(close_panel)
if close_panel.empty or n < lookback + 3:
    get_panels.clear()  # never keep a failed/empty download cached
    st.warning("Not enough data returned. Yahoo Finance may be rate limiting — click Refresh in a minute.")
    st.stop()

dates = list(close_panel.index)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def add_company_info(df: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(stocks.rename(columns={"Company Name": "Company"}), on="Symbol", how="left")
    if picked_industries:
        df = df[df["Industry"].isin(picked_industries)]
    tv = df["Symbol"].str.replace("&", "_", regex=False).str.replace("-", "_", regex=False)
    df["Chart"] = "https://in.tradingview.com/chart/?symbol=NSE:" + tv
    return df


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    m = (
        (df["Volume Multiple"] >= min_mult)
        & (df["LTP"] >= min_price)
        & (df["Value (Cr)"] >= min_value_cr)
    )
    if direction == "Gainers":
        m &= df["Change %"] > 0
    elif direction == "Losers":
        m &= df["Change %"] < 0
    return df[m].sort_values("Volume Multiple", ascending=False).reset_index(drop=True)


def show_table(df: pd.DataFrame, cols: list, price_label: str = "LTP") -> None:
    cols = [c for c in cols if c in df.columns]
    pct = st.column_config.NumberColumn(format="%.2f%%")
    config = {
        "LTP": st.column_config.NumberColumn(price_label, format="₹%.2f"),
        "Change %": pct,
        "Volume": st.column_config.NumberColumn(format="%d"),
        "Avg Volume": st.column_config.NumberColumn(format="%d"),
        "Volume Multiple": st.column_config.ProgressColumn(
            "Vol Multiple", format="%.2fx", min_value=0,
            max_value=float(max(20, df["Volume Multiple"].max())),
        ),
        "Value (Cr)": st.column_config.NumberColumn(format="₹%.2f"),
        "Gap %": pct, "D+1 %": pct, "D+3 %": pct, "D+5 %": pct,
        "Till Date %": pct, "Max High %": pct, "Max Low %": pct,
        "Chart": st.column_config.LinkColumn(display_text="Open"),
    }
    st.dataframe(
        df[cols], width="stretch", hide_index=True,
        height=min(750, 40 + 35 * len(df)), column_config=config,
    )


def show_split(df: pd.DataFrame, cols: list, price_label: str = "LTP") -> None:
    """Gainers and losers in two tables when direction is 'All', else one table."""
    if split_view and direction == "All":
        gainers = df[df["Change %"] > 0]
        losers = df[df["Change %"] < 0]
        st.markdown(f"#### 🟢 Gainers ({len(gainers)})")
        if gainers.empty:
            st.info("No gainers match the filters.")
        else:
            show_table(gainers, cols, price_label)
        st.markdown(f"#### 🔴 Losers ({len(losers)})")
        if losers.empty:
            st.info("No losers match the filters.")
        else:
            show_table(losers, cols, price_label)
    else:
        show_table(df, cols, price_label)


def csv_button(df: pd.DataFrame, name: str, key: str) -> None:
    st.download_button(
        "⬇️ Download CSV",
        df.drop(columns=["Chart"], errors="ignore").to_csv(index=False).encode(),
        file_name=f"{name}_{datetime.now():%Y%m%d}.csv",
        mime="text/csv",
        key=key,
    )


def fmt_pct(x) -> str:
    return "–" if pd.isna(x) else f"{x:+.2f}%"


LIVE_COLS = ["Symbol", "Company", "Industry", "LTP", "Change %", "Volume", "Avg Volume",
             "Volume Multiple", "Value (Cr)", "Chart"]
BT_COLS = ["Trend", "Symbol", "Company", "Industry", "LTP", "Change %", "Volume Multiple",
           "Value (Cr)", "Gap %", "D+1 %", "D+3 %", "D+5 %", "Till Date %",
           "Max High %", "Max Low %", "Chart"]

tab_live, tab_bt, tab_multi = st.tabs(["🔴 Live scan", "⏪ Backtest: one day", "📊 Backtest: many days"])

# ----------------------------------------------------------------------------
# Tab 1: live scan (latest trading day)
# ----------------------------------------------------------------------------
with tab_live:
    live = apply_filters(add_company_info(sc.scan_day(panels, lookback, n - 1).reset_index()))
    last_date = dates[-1]

    c1, c2, c3 = st.columns(3)
    c1.metric("Latest trading day", last_date.strftime("%d %b %Y"))
    c2.metric(f"Volume ≥ {min_mult:g}x", len(live))
    c3.metric("Gainers / Losers", f"{int((live['Change %'] > 0).sum())} / {int((live['Change %'] < 0).sum())}")

    if live.empty:
        st.info("No stocks match the current filters. Try lowering the volume multiple.")
    else:
        show_split(live, LIVE_COLS)
        csv_button(live, "nifty500_volume_scan", "dl_live")
    st.caption(
        "During market hours the latest bar has *partial* volume, so multiples look smaller "
        "until the close. Use the Backtest tabs to see how past signals played out."
    )

# ----------------------------------------------------------------------------
# Tab 2: backtest one day
# ----------------------------------------------------------------------------
with tab_bt:
    st.subheader("What would the scanner have shown on a past day — and how did those stocks do?")

    signal_dates = dates[lookback : n - 1][::-1]  # newest first, must have a next day
    if not signal_dates:
        st.warning("Not enough history for backtesting with this lookback.")
    else:
        chosen = st.selectbox(
            "Signal date (default = previous trading day)",
            signal_dates,
            format_func=lambda d: d.strftime("%a, %d %b %Y"),
        )
        p = dates.index(chosen)
        days_after = n - 1 - p

        bt = apply_filters(add_company_info(sc.scan_day(panels, lookback, p, entry).reset_index()))
        bt["Trend"] = bt["Till Date %"].apply(lambda x: "–" if pd.isna(x) else ("🟢" if x > 0 else "🔴"))

        st.caption(
            f"Scan as of **{chosen:%d %b %Y}** close · tracked for **{days_after}** trading day(s) "
            f"up to **{dates[-1]:%d %b %Y}** · entry: **{entry_label.lower()}**"
        )

        if bt.empty:
            st.info("No stocks matched the filters on that day. Try lowering the volume multiple or pick another date.")
        else:
            d1 = bt["D+1 %"].dropna()
            till = bt["Till Date %"].dropna()
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Signals", len(bt))
            m2.metric("Next-day win rate", "–" if d1.empty else f"{(d1 > 0).mean() * 100:.0f}%")
            m3.metric("Avg next-day", fmt_pct(d1.mean()) if len(d1) else "–")
            m4.metric("Avg till date", fmt_pct(till.mean()) if len(till) else "–")
            m5.metric("Best till date", fmt_pct(till.max()) if len(till) else "–")
            m6.metric("Worst till date", fmt_pct(till.min()) if len(till) else "–")

            show_split(bt, BT_COLS, price_label="Signal Close")
            csv_button(bt, f"backtest_{chosen:%Y%m%d}", "dl_bt")

            st.markdown("#### Track these stocks")
            left, right = st.columns(2)
            with left:
                st.caption("Return till date (%) per stock")
                st.bar_chart(bt.set_index("Symbol")["Till Date %"])
            with right:
                picks = st.multiselect(
                    "Price path since entry (% move)",
                    list(bt["Symbol"]),
                    default=list(bt["Symbol"][:5]),
                )
                if picks:
                    st.line_chart(sc.price_path(panels, picks, p, entry))

    st.caption(
        "Uses today's Nifty 500 list for every past date (survivorship bias) and ignores brokerage, "
        "slippage and taxes. Historical results are not a guarantee of future performance."
    )

# ----------------------------------------------------------------------------
# Tab 3: backtest many days
# ----------------------------------------------------------------------------
with tab_multi:
    st.subheader("How have 'high volume' signals performed over the last few months?")
    max_days = n - 2 - lookback
    if max_days > 10:
        test_days = st.slider(
            "Number of past trading days to test", 10, max_days,
            min(60, max_days) // 5 * 5 or 10, 5,
        )
    else:
        test_days = max(max_days, 1)
    start_pos = max(lookback, n - 1 - test_days)
    sig = sc.multi_day_signals(
        panels, lookback, start_pos, n - 2, min_mult, direction, min_price, min_value_cr, entry
    )
    if picked_industries and not sig.empty:
        sig = sig.merge(stocks[["Symbol", "Industry"]], on="Symbol", how="left")
        sig = sig[sig["Industry"].isin(picked_industries)].drop(columns="Industry")

    if sig.empty:
        st.info("No signals in this period with the current filters. Try lowering the volume multiple.")
    else:
        sig = sig.merge(stocks.rename(columns={"Company Name": "Company"})[["Symbol", "Company"]],
                        on="Symbol", how="left")
        sig = sig.sort_values(["Date", "Volume Multiple"], ascending=[False, False]).reset_index(drop=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total signals", len(sig))
        c2.metric("Trading days tested", n - 1 - start_pos)
        c3.metric("Avg signals / day", f"{len(sig) / (n - 1 - start_pos):.1f}")

        st.markdown("#### Performance by holding period")
        st.dataframe(sc.horizon_summary(sig), hide_index=True, width="stretch")
        if direction == "All":
            st.markdown("##### Gainers vs Losers")
            st.dataframe(sc.direction_summary(sig), hide_index=True, width="stretch")

        st.markdown("#### Signals per day")
        daily = sc.daily_summary(sig)
        st.bar_chart(daily["Avg D+1 %"], y_label="Avg next-day return %")
        st.dataframe(daily.reset_index().assign(Date=lambda x: x["Date"].dt.strftime("%d %b %Y")),
                     hide_index=True, width="stretch")

        st.markdown("#### All signals")
        pct = st.column_config.NumberColumn(format="%.2f%%")
        table = sig.assign(Date=sig["Date"].dt.strftime("%d %b %Y"))
        st.dataframe(
            table[["Date", "Symbol", "Company", "LTP", "Change %", "Volume Multiple",
                   "Gap %", "D+1 %", "D+3 %", "D+5 %"]],
            hide_index=True, width="stretch", height=500,
            column_config={
                "LTP": st.column_config.NumberColumn("Signal Close", format="₹%.2f"),
                "Change %": pct, "Gap %": pct, "D+1 %": pct, "D+3 %": pct, "D+5 %": pct,
                "Volume Multiple": st.column_config.NumberColumn("Vol Multiple", format="%.2fx"),
            },
        )
        csv_button(table, "multi_day_backtest", "dl_multi")

    st.caption(
        f"Returns measured from the {entry_label.lower()}. D+N = close N trading days after the signal day; "
        "recent signals have fewer horizons available. Survivorship bias applies."
    )
