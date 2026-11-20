# Nifty 500 Volume Scanner + Backtester

Streamlit app with three tabs:

| Tab | What it does |
|---|---|
| 🔴 Live scan | Nifty 500 stocks trading at ≥ X times their average volume (slider, default 2x) on the latest trading day. Gainers and losers shown in separate tables |
| ⏪ Backtest: one day | Pick any past trading day (default: previous day). Shows what the scanner flagged that day and how each stock performed afterwards: gap, D+1 / D+3 / D+5, till-date return, max high / max low, plus charts to track them |
| 📊 Backtest: many days | Runs the scan on every day of the last N trading days and reports win rate, average and median return by holding period, and a per-day summary |

Sidebar filters apply everywhere: volume multiple (default 2x), lookback days, gainers/losers, min price,
min traded value, industry, and entry price (signal-day close or next-day open).

Price direction defaults to **All** (gainers and losers both). With "Show Gainers and Losers in separate
tables" ticked (default), the Live and one-day Backtest tabs show a Gainers table and a Losers table;
the many-days Backtest adds a Gainers-vs-Losers performance table.

## Files

```
app.py                Streamlit UI
scanner.py            scan + backtest logic (no Streamlit code)
requirements.txt      runtime dependencies
requirements-dev.txt  adds pytest
tests/                automated tests (no network needed)
nifty500.csv          optional fallback list (see below)
```

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use synthetic prices with hand-computed answers, a mocked Yahoo downloader and Streamlit's
`AppTest` to drive the real UI, so they run offline in a few seconds.

## Deploy (GitHub → Streamlit Community Cloud)

```bash
git init
git add app.py scanner.py requirements.txt requirements-dev.txt README.md tests pytest.ini
git commit -m "Nifty 500 volume scanner with backtest"
git branch -M main
git remote add origin https://github.com/<your-username>/nifty500-volume-scanner.git
git push -u origin main
```

Then go to https://share.streamlit.io → **Create app** → choose the repo, branch `main`,
main file `app.py` → **Deploy**.

If you already deployed the previous version, just push the new files; the app redeploys itself.

## If the NSE list fails to load

NSE sometimes blocks cloud IPs. Download `ind_nifty500list.csv` from https://www.niftyindices.com,
rename it to `nifty500.csv`, put it in the repo root, and push. The app falls back to it automatically.

## How it works

- **Volume multiple** = the day's volume ÷ average volume of the previous N days (that day excluded).
- **Backtest day**: the same calculation, run as of the chosen date using only data up to that date.
- **Returns**: D+N = close N trading days after the signal day, measured from your entry price.
  "Till date" uses the latest available close.

## Limitations

- Uses today's Nifty 500 constituents for past dates (survivorship bias).
- No brokerage, slippage or taxes. Data is Yahoo Finance daily bars (may be delayed or have gaps).
- About 1 year of history is loaded, so backtests cover roughly the last 10-11 months.
- Past performance does not guarantee future results; this is not investment advice.

## Changelog (this version)

- Default volume multiple is now 2x; gainers + losers shown together by default, with an optional split view.
- **Fixed:** many-day backtest counted stocks with zero average volume as infinite-x "signals" (live scan already ignored them), inflating signal counts and win rates.
- **Fixed:** a stock at 1.996x displayed as "2.00x" passed the filter in the Live/one-day tabs but not in the many-day backtest; both now compare the same rounded value.
- **Fixed:** an empty/failed Yahoo download was cached for 10 minutes; it is now discarded so a rerun retries.
- Yahoo downloads retry failed batches (rate limiting) before giving up.
- `nifty500.csv` fallback is now found next to `scanner.py` regardless of the working directory; duplicate symbols are dropped.
- `scan_day` raises a clear error for an invalid day index; zero/NaN entry prices no longer produce infinite returns.
- The "days to test" slider no longer crashes when history is very short.
