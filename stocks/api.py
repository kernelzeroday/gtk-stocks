"""Market data from Yahoo Finance's public chart/search endpoints."""

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from gi.repository import GLib

USER_AGENT = "Mozilla/5.0 (X11; Linux) GTK-Stocks/0.1"
BASE = "https://query1.finance.yahoo.com"

# label -> (yahoo range, interval)
RANGES = {
    "1D": ("1d", "5m"),
    "1W": ("5d", "15m"),
    "1M": ("1mo", "60m"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "YTD": ("ytd", "1d"),
    "1Y": ("1y", "1d"),
    "2Y": ("2y", "1wk"),
    "5Y": ("5y", "1wk"),
    "10Y": ("10y", "1mo"),
    "ALL": ("max", "1mo"),
}

_pool = ThreadPoolExecutor(max_workers=8)


def run_async(callback, fn, *args):
    """Run fn(*args) on a worker thread; call callback(result, error) on the main loop."""

    def job():
        try:
            result, error = fn(*args), None
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            result, error = None, e

        def deliver():
            callback(result, error)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(deliver)

    _pool.submit(job)


def _get(path, params=None, raw=False):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
    return data if raw else json.loads(data)


def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


@dataclass
class Quote:
    symbol: str
    name: str
    currency: str
    exchange: str
    timezone: str
    gmtoffset: int
    price: float
    prev_close: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: int | None
    high52: float | None
    low52: float | None
    market_time: int
    regular_start: int
    regular_end: int
    decimals: int = 2

    @property
    def change(self):
        if self.prev_close is None:
            return 0.0
        return self.price - self.prev_close

    @property
    def change_pct(self):
        if not self.prev_close:
            return 0.0
        return self.change / self.prev_close * 100


@dataclass
class Series:
    range_key: str
    times: list = field(default_factory=list)
    values: list = field(default_factory=list)
    baseline: float | None = None  # previous close (1D only)
    start: int = 0
    end: int = 0
    time_based: bool = False  # x positioned by time (1D) instead of index
    gmtoffset: int = 0
    decimals: int = 2

    @property
    def reference(self):
        if self.baseline is not None:
            return self.baseline
        return self.values[0] if self.values else 0.0

    @property
    def change(self):
        return (self.values[-1] - self.reference) if self.values else 0.0

    @property
    def change_pct(self):
        ref = self.reference
        return self.change / ref * 100 if ref else 0.0


def fetch_chart(symbol, range_key="1D"):
    rng, interval = RANGES[range_key]
    data = _get(
        f"/v8/finance/chart/{urllib.parse.quote(symbol)}",
        {"range": rng, "interval": interval, "includePrePost": "false"},
    )
    chart = data.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(chart["error"].get("description") or "Unknown symbol")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"No data for {symbol}")

    meta = result["meta"]
    timestamps = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = q.get("close") or []
    opens = q.get("open") or []

    times, values = [], []
    for t, c in zip(timestamps, closes):
        if c is not None:
            times.append(t)
            values.append(c)

    price = meta.get("regularMarketPrice")
    if price is None and values:
        price = values[-1]
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    decimals = meta.get("priceHint", 2)
    gmtoffset = meta.get("gmtoffset", 0)
    prev_close = meta.get("previousClose", meta.get("chartPreviousClose"))
    is_1d = range_key == "1D"

    quote = Quote(
        symbol=meta.get("symbol", symbol),
        name=meta.get("shortName") or meta.get("longName") or symbol,
        currency=meta.get("currency") or "",
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        timezone=meta.get("timezone") or "",
        gmtoffset=gmtoffset,
        price=price or 0.0,
        prev_close=prev_close if is_1d else None,
        open=next((o for o in opens if o is not None), None) if is_1d else None,
        high=meta.get("regularMarketDayHigh"),
        low=meta.get("regularMarketDayLow"),
        volume=meta.get("regularMarketVolume"),
        high52=meta.get("fiftyTwoWeekHigh"),
        low52=meta.get("fiftyTwoWeekLow"),
        market_time=meta.get("regularMarketTime", 0),
        regular_start=period.get("start", 0),
        regular_end=period.get("end", 0),
        decimals=decimals,
    )

    # Make sure the line ends at the live price on the intraday chart.
    if is_1d and values and price is not None:
        values[-1] = price

    start = times[0] if times else 0
    end = times[-1] if times else 0
    if is_1d and times:
        start = min(start, period.get("start", start))
        end = max(end, period.get("end", end))

    series = Series(
        range_key=range_key,
        times=times,
        values=values,
        baseline=prev_close if is_1d else None,
        start=start,
        end=end,
        time_based=is_1d,
        gmtoffset=gmtoffset,
        decimals=decimals,
    )
    return quote, series


SEARCH_TYPES = {"EQUITY", "ETF", "INDEX", "MUTUALFUND", "CRYPTOCURRENCY", "FUTURE", "CURRENCY"}


def search(query):
    data = _get("/v1/finance/search", {"q": query, "quotesCount": 12, "newsCount": 0})
    out = []
    for item in data.get("quotes", []):
        if item.get("quoteType") not in SEARCH_TYPES or not item.get("symbol"):
            continue
        out.append(
            {
                "symbol": item["symbol"],
                "name": item.get("longname") or item.get("shortname") or item["symbol"],
                "exchange": item.get("exchDisp") or item.get("exchange") or "",
                "type": item.get("typeDisp") or "",
            }
        )
    return out


def fetch_news(symbol, count=8):
    data = _get("/v1/finance/search", {"q": symbol, "quotesCount": 0, "newsCount": count})
    out = []
    for item in data.get("news", []):
        thumb = None
        res = (item.get("thumbnail") or {}).get("resolutions") or []
        small = [r for r in res if r.get("width", 9999) <= 300]
        if small or res:
            thumb = (small or res)[0].get("url")
        out.append(
            {
                "title": item.get("title", ""),
                "publisher": item.get("publisher", ""),
                "link": item.get("link", ""),
                "time": item.get("providerPublishTime", 0),
                "thumb": thumb,
            }
        )
    return out
