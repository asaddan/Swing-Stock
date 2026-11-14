# 3:15 PM Swing Scanner (NSE, v1)

## Run locally

On first use, install the dependencies from PowerShell in this folder:

    python -m pip install -r requirements.txt

After that, double-click `Start Swing Stock.bat` in this folder or the
`Swing Stock Scanner` shortcut on your Desktop. The app opens at
http://127.0.0.1:8000. Keep the terminal window open while using the app;
press Ctrl+C there to stop it.

To start it manually instead:

    python -m uvicorn main:app --host 127.0.0.1 --port 8000

Pipeline: liquidity -> delivery % (green candle) -> closing strength -> 20/50 EMA + Supertrend -> trade plan.
All thresholds are editable in the sidebar. Defaults are assumptions: check them against the video.

- Prices: yfinance (".NS"). Delivery %: NSE `sec_bhavdata_full_DDMMYYYY.csv`, cached in `cache/`.
- Live mode uses the latest *published* delivery day (today's file appears after the close).
- Entry is above the signal candle's high, so it is a next-session trigger.
- Watchlist: add or remove NSE symbols any time (saved in `watchlist.json`); each is checked against every rule.
- Not built yet: BSE, charts, trade journal, backtest, scheduler, tests.
