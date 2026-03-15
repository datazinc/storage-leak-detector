"""Scheduler — runs periodic snapshots and anomaly detection."""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable

from sldd.api import SLDD
from sldd.models import AdaptiveConfig, CompactResult, Report, ScanPlan, WatchConfig

WatchCallback = Callable[[Report], None]
AdaptiveCallback = Callable[[ScanPlan, CompactResult | None], None]


class Watcher:
    """Run snapshot + detect on an interval. Thread-safe, stoppable.

    When adaptive=True (default), uses the adaptive scan engine which starts
    shallow, focuses on what changes, and compacts stable subtrees.
    """

    def __init__(
        self,
        config: WatchConfig,
        *,
        adaptive_config: AdaptiveConfig | None = None,
        on_report: WatchCallback | None = None,
        on_adaptive: AdaptiveCallback | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self.config = config
        self.adaptive_config = adaptive_config or AdaptiveConfig()
        self.on_report = on_report
        self.on_adaptive = on_adaptive
        self.on_error = on_error
        self._stop = threading.Event()
        self._api: SLDD | None = None

    def start(self) -> None:
        """Run the watch loop (blocking). Call stop() from another thread or signal handler."""
        self._api = SLDD(
            db_path=self.config.scan.db_path,
            scan_config=self.config.scan,
            detect_config=self.config.detect,
            adaptive_config=self.adaptive_config,
        )
        self._api.open()

        _install_signal_handler(self._stop)

        use_adaptive = self.adaptive_config.mode != "disabled"

        try:
            while not self._stop.is_set():
                try:
                    if use_adaptive:
                        result = self._api.adaptive_snapshot_and_detect()
                        report, plan, compact_result = result
                        if report and self.on_report:
                            self.on_report(report)
                        if self.on_adaptive:
                            self.on_adaptive(plan, compact_result)
                    else:
                        report = self._api.snapshot_and_detect()
                        if report and self.on_report:
                            self.on_report(report)
                        self._api.prune(keep=self.config.max_snapshots_kept)
                except Exception as exc:
                    if self.on_error:
                        self.on_error(exc)
                self._stop.wait(timeout=self.config.interval_seconds)
        finally:
            if self._api:
                self._api.close()

    def stop(self) -> None:
        self._stop.set()


def _install_signal_handler(stop_event: threading.Event) -> None:
    def _handler(signum: int, frame: object) -> None:
        stop_event.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
