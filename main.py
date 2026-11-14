from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import data
import watchlist
from scanner import Settings, analyze, run_scan

app = FastAPI(title="3:15 PM Swing Scanner")
INDEX = Path(__file__).parent / "index.html"


class NewStocks(BaseModel):
    symbols: str  # one or many, separated by commas, spaces or new lines


@app.get("/")
def index():
    return FileResponse(INDEX)


@app.get("/api/defaults")
def defaults():
    return Settings().model_dump()


@app.post("/api/scan")
def scan(s: Settings):
    return run_scan(s)


@app.get("/api/watchlist")
def get_watchlist():
    return watchlist.load()


@app.post("/api/watchlist")
def add_stocks(body: NewStocks):
    raw = [watchlist.clean(x) for x in body.symbols.replace(",", " ").split()]
    bad = [x for x in raw if not watchlist.VALID.match(x)]
    if not raw or bad:
        raise HTTPException(400, f"Not a valid NSE symbol: {', '.join(bad) or 'empty input'}")
    found = data.prices(raw)
    missing = [x for x in raw if x not in found]
    for x in raw:
        if x in found:
            watchlist.add(x)
    if missing:
        raise HTTPException(404, f"No NSE price data for: {', '.join(missing)}. Check the symbol. "
                                 f"{'The others were added.' if found else ''}".strip())
    return watchlist.load()


@app.delete("/api/watchlist/{symbol}")
def remove_stock(symbol: str):
    return watchlist.remove(watchlist.clean(symbol))


class AnalyzeReq(Settings):
    symbols: list[str]  # one page of the watchlist (max 50)


@app.post("/api/watchlist/analyze")
def analyze_watchlist(req: AnalyzeReq):
    mine = set(watchlist.load())
    return analyze([x for x in req.symbols if x in mine][:50], req)
