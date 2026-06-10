"""Hyperliquid public REST API client.

Endpoint: ``POST https://api.hyperliquid.xyz/info``
Authentication: none for read-only calls.

Two operations used by Phase 0:
- ``metaAndAssetCtxs``  → mark price, 24h volume, OI, current funding for all perps
- ``candleSnapshot``    → OHLCV history for a single coin & interval
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass
class HyperliquidPerp:
    coin: str
    mark_price_usd: float
    prev_day_price_usd: float
    day_volume_usd: float
    open_interest_coin: float
    open_interest_usd: float
    funding_rate_hourly: float
    max_leverage: int

    @property
    def funding_rate_apr(self) -> float:
        return self.funding_rate_hourly * 24 * 365


@dataclass
class Candle:
    coin: str
    interval: str
    open_time_ms: int   # bar open (ms since epoch)
    close_time_ms: int  # bar close (ms since epoch)
    open: float
    high: float
    low: float
    close: float
    volume: float       # base-asset volume
    trades: int


class HyperliquidClient:
    def __init__(self, *, user_agent: str = "hl-swing-bot/0.1", timeout: float = 15.0):
        self._headers = {"User-Agent": user_agent, "Content-Type": "application/json"}
        self._timeout = timeout
        self._client: httpx.Client | None = None

    def __enter__(self) -> "HyperliquidClient":
        self._client = httpx.Client(headers=self._headers, timeout=self._timeout)
        return self

    def __exit__(self, *exc) -> None:
        if self._client:
            self._client.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _post(self, body: dict[str, Any]) -> Any:
        assert self._client is not None, "use as context manager"
        resp = self._client.post(INFO_URL, json=body)
        resp.raise_for_status()
        return resp.json()

    def fetch_all_perps(self) -> list[HyperliquidPerp]:
        """All active perpetuals with mark/volume/OI/funding snapshot."""
        data = self._post({"type": "metaAndAssetCtxs"})
        meta, ctxs = data
        universe = meta["universe"]

        out: list[HyperliquidPerp] = []
        for u, c in zip(universe, ctxs):
            try:
                mark = float(c["markPx"])
                prev = float(c["prevDayPx"])
                vol = float(c["dayNtlVlm"])
                oi_coin = float(c["openInterest"])
                funding = float(c["funding"])
            except (KeyError, ValueError, TypeError) as e:
                log.warning("skipping %s: malformed ctx (%s)", u.get("name"), e)
                continue
            out.append(
                HyperliquidPerp(
                    coin=u["name"],
                    mark_price_usd=mark,
                    prev_day_price_usd=prev,
                    day_volume_usd=vol,
                    open_interest_coin=oi_coin,
                    open_interest_usd=oi_coin * mark,
                    funding_rate_hourly=funding,
                    max_leverage=int(u.get("maxLeverage", 0)),
                )
            )
        log.info("hyperliquid: fetched %d perpetuals", len(out))
        return out

    def fetch_perp(self, coin: str) -> HyperliquidPerp | None:
        for p in self.fetch_all_perps():
            if p.coin == coin:
                return p
        return None

    def fetch_candles(
        self,
        coin: str,
        *,
        interval: str = "1m",
        start_ms: int | None = None,
        end_ms: int | None = None,
        lookback_minutes: int = 120,
    ) -> list[Candle]:
        """OHLCV for ``coin`` between ``start_ms`` and ``end_ms`` (UTC ms).

        If ``start_ms``/``end_ms`` omitted, fetches the last ``lookback_minutes``.
        Hyperliquid returns at most ~5000 bars per call.
        """
        now_ms = int(time.time() * 1000)
        if end_ms is None:
            end_ms = now_ms
        if start_ms is None:
            start_ms = end_ms - lookback_minutes * 60 * 1000

        body = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        }
        raw = self._post(body)
        out: list[Candle] = []
        for c in raw or []:
            try:
                out.append(
                    Candle(
                        coin=coin,
                        interval=interval,
                        open_time_ms=int(c["t"]),
                        close_time_ms=int(c["T"]),
                        open=float(c["o"]),
                        high=float(c["h"]),
                        low=float(c["l"]),
                        close=float(c["c"]),
                        volume=float(c["v"]),
                        trades=int(c.get("n", 0)),
                    )
                )
            except (KeyError, ValueError, TypeError) as e:
                log.warning("skipping malformed candle: %s", e)
                continue
        log.info("hyperliquid: fetched %d %s candles for %s", len(out), interval, coin)
        return out


    def fetch_funding_history(
        self, coin: str, *, start_ms: int, end_ms: int | None = None,
    ) -> list[tuple[int, float]]:
        """Settled hourly funding records as (hour_ms, rate), oldest first.

        The endpoint returns ~500 records per call; we paginate by advancing
        startTime past the last received record. Timestamps arrive with small
        ms offsets (e.g. ...00014) — we floor to the hour.
        """
        if end_ms is None:
            end_ms = int(time.time() * 1000)
        out: dict[int, float] = {}
        cursor = start_ms
        for _ in range(100):  # hard cap: 100 pages = ~50k hours
            raw = self._post({
                "type": "fundingHistory", "coin": coin,
                "startTime": cursor, "endTime": end_ms,
            })
            if not raw:
                break
            for rec in raw:
                try:
                    t = int(rec["time"])
                    out[t - (t % 3_600_000)] = float(rec["fundingRate"])
                except (KeyError, ValueError, TypeError):
                    continue
            last_t = max(int(r["time"]) for r in raw)
            if last_t >= end_ms or len(raw) < 2:
                break
            cursor = last_t + 1
        rows = sorted(out.items())
        log.info("hyperliquid: fetched %d hourly funding records for %s", len(rows), coin)
        return rows


@contextmanager
def open_client(user_agent: str = "hl-swing-bot/0.1") -> Iterator[HyperliquidClient]:
    with HyperliquidClient(user_agent=user_agent) as c:
        yield c
