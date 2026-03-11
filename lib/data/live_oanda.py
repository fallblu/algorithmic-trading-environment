"""LiveOandaFeed — DataFeed subclass for OANDA forex live data."""

import logging
import queue
from datetime import datetime

from data.feed import DataFeed
from data.oanda_api import fetch_candles
from data.oanda_stream import OandaStream
from models.bar import Bar
from models.instrument import Instrument

log = logging.getLogger(__name__)


class LiveOandaFeed(DataFeed):
    """Real-time forex market data from OANDA streaming API.

    Uses OandaStream for real-time bar construction and
    oanda_api for historical bar fetching (warmup).
    """

    def __init__(self, record_ticks: bool = False):
        self._bar_queue: queue.Queue[Bar] = queue.Queue(maxsize=1000)
        self._stream: OandaStream | None = None
        self._instruments: list[Instrument] = []
        self._timeframe: str = "1h"
        self._record_ticks = record_ticks

    def subscribe(self, instrument: Instrument, timeframe: str) -> None:
        self._instruments.append(instrument)
        self._timeframe = timeframe

        if self._stream is None:
            symbols = [inst.symbol for inst in self._instruments]
            self._stream = OandaStream(
                instruments=symbols,
                timeframe=timeframe,
                record_ticks=self._record_ticks,
            )
            self._stream.on_bar(self._on_bar_callback)
            self._stream.start()

    def subscribe_all(self, instruments: list[Instrument], timeframe: str) -> None:
        self._instruments = list(instruments)
        self._timeframe = timeframe

        symbols = [inst.symbol for inst in instruments]
        self._stream = OandaStream(
            instruments=symbols,
            timeframe=timeframe,
            record_ticks=self._record_ticks,
        )
        self._stream.on_bar(self._on_bar_callback)
        self._stream.start()

    def next_bar(self) -> Bar | None:
        try:
            return self._bar_queue.get_nowait()
        except queue.Empty:
            return None

    def historical_bars(
        self,
        instrument: Instrument,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        return fetch_candles(
            symbol=instrument.symbol,
            timeframe=timeframe,
            since=start,
        )

    def shutdown(self) -> None:
        if self._stream is not None:
            self._stream.stop()
        log.info("LiveOandaFeed shut down")

    @property
    def is_connected(self) -> bool:
        return self._stream is not None and self._stream._running

    def _on_bar_callback(self, bar: Bar) -> None:
        """Callback from OandaStream when a bar completes."""
        try:
            self._bar_queue.put_nowait(bar)
        except queue.Full:
            try:
                self._bar_queue.get_nowait()
            except queue.Empty:
                pass
            self._bar_queue.put_nowait(bar)
