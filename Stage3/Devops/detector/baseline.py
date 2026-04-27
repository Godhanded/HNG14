"""
baseline.py — Rolling Baseline Tracker

This module answers the question: "What is NORMAL traffic on this server?"

How it works:
1. Every request calls record_request(), which increments a per-second counter.
2. Every second, that counter is flushed into a rolling deque (the 30-min window).
3. Every 60 seconds, a background thread recomputes mean and stddev from that window.
4. We also maintain per-HOUR slots so that "rush hour" traffic doesn't contaminate
   "quiet hour" baselines. If the current hour has >= 5 minutes of data, we use it
   instead of the full 30-minute window.

Why not hardcode the mean?
  The task explicitly forbids hardcoded baselines. Traffic varies:
  - Low at 3am, high at 9pm
  - Different on weekdays vs weekends
  - Different before vs after going public
  A rolling window adapts automatically to whatever patterns exist.

Why mean + stddev?
  We use z-score detection: z = (current_rate - mean) / stddev.
  If z > 3.0, the current rate is 3 standard deviations above normal.
  Statistically, that happens by chance less than 0.3% of the time,
  so it's a strong signal that something unusual is happening.
"""

import time
import threading
import statistics
import logging
from collections import deque

logger = logging.getLogger(__name__)


class BaselineTracker:
    """
    Maintains a 30-minute rolling window of per-second request counts and
    computes a live mean and standard deviation for anomaly detection.
    """

    def __init__(self, config: dict, on_recalc=None):
        """
        Args:
            config: The loaded config.yaml dict.
            on_recalc: Optional callback called after each recalculation.
                       Signature: on_recalc(mean, stddev, window_size, hour_slot)
        """
        self.window_minutes       = config.get('baseline_window_minutes', 30)
        self.recalc_interval      = config.get('baseline_recalc_interval_seconds', 60)
        self.min_mean             = config.get('baseline_minimum_mean', 1.0)
        self.min_stddev           = config.get('baseline_min_stddev', 0.1)
        self.hourly_min_samples   = config.get('baseline_hourly_min_samples', 300)
        self.on_recalc            = on_recalc  # audit log callback

        # ── Rolling window ─────────────────────────────────────────────────────
        # Stores one integer per second for the last 30 minutes.
        # maxlen automatically evicts the oldest entry when the deque is full.
        # 30 minutes × 60 seconds = 1800 slots maximum.
        max_slots = self.window_minutes * 60
        self.counts_window = deque(maxlen=max_slots)    # req counts per second
        self.error_counts_window = deque(maxlen=max_slots)  # error (4xx/5xx) counts

        # ── Per-hour slots ─────────────────────────────────────────────────────
        # dict: hour (0–23) → deque of per-second counts for that hour.
        # Each slot can hold up to 3600 values (one per second for 1 hour).
        # When the current hour has enough data, we prefer it over the 30-min window
        # so that a baseline from 2am doesn't affect 2pm detection.
        self.hourly_slots = {}

        # ── Computed baseline (updated every 60 seconds) ───────────────────────
        self.effective_mean   = self.min_mean
        self.effective_stddev = self.min_stddev
        self.error_mean       = 0.01
        self.error_stddev     = 0.01

        # ── Baseline history for the dashboard graph ──────────────────────────
        # Stores (timestamp, mean, stddev, hour_slot) for every recalculation.
        # The dashboard chart reads this to show how the baseline changes over time.
        self.history = deque(maxlen=200)  # keep last 200 recalculations (~3.3 hours)

        # ── Current-second accumulator ────────────────────────────────────────
        # We count requests in the current second, then flush to the window
        # when the second changes. This avoids writing to the deque on every request.
        self._lock            = threading.Lock()
        self._current_second  = int(time.time())
        self._current_count   = 0
        self._current_errors  = 0

        # Start background thread that recalculates baseline every 60 seconds
        t = threading.Thread(target=self._recalc_loop, daemon=True, name='baseline-recalc')
        t.start()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_request(self, is_error: bool = False) -> None:
        """
        Called for every incoming HTTP request parsed from the log.
        Increments the counter for the current second.
        """
        now = int(time.time())

        with self._lock:
            if now != self._current_second:
                # A new second has started — flush the previous second's totals
                # into the rolling window before starting fresh counts.
                self._flush_second(self._current_second, self._current_count, self._current_errors)
                self._current_second = now
                self._current_count  = 0
                self._current_errors = 0

            self._current_count += 1
            if is_error:
                self._current_errors += 1

    def get_baseline(self) -> tuple:
        """Returns (effective_mean, effective_stddev) — thread-safe."""
        with self._lock:
            return self.effective_mean, self.effective_stddev

    def get_error_baseline(self) -> tuple:
        """Returns (error_mean, error_stddev) for error-surge detection."""
        with self._lock:
            return self.error_mean, self.error_stddev

    def get_history(self) -> list:
        """Returns list of (timestamp, mean, stddev) tuples for the dashboard graph."""
        with self._lock:
            return list(self.history)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _flush_second(self, second: int, count: int, errors: int) -> None:
        """
        Append counts for a completed second into the rolling window
        and the appropriate hourly slot.
        Called while holding self._lock.
        """
        self.counts_window.append(count)
        self.error_counts_window.append(errors)

        # Determine which hour this second belongs to
        hour = time.localtime(second).tm_hour
        if hour not in self.hourly_slots:
            self.hourly_slots[hour] = deque(maxlen=3600)
        self.hourly_slots[hour].append(count)

    def _recalc_loop(self) -> None:
        """Background thread: recalculate baseline every recalc_interval seconds."""
        while True:
            time.sleep(self.recalc_interval)
            self._recalculate()

    def _recalculate(self) -> None:
        """
        Compute new mean and stddev from the best available data source.

        Data source priority:
          1. Current hour's slot — if it has >= hourly_min_samples (5 min of data).
             We prefer this because traffic patterns differ by hour.
          2. Full 30-minute rolling window — fallback when the current hour is new.
        """
        with self._lock:
            current_hour = time.localtime().tm_hour
            hour_data    = self.hourly_slots.get(current_hour, deque())

            # Pick the best data source
            if len(hour_data) >= self.hourly_min_samples:
                data      = list(hour_data)
                slot_used = f"hour_{current_hour}"
            else:
                data      = list(self.counts_window)
                slot_used = "rolling_30min"

            if len(data) < 2:
                # Not enough data to compute statistics yet — keep defaults
                return

            # statistics.mean / pstdev are from the standard library.
            # pstdev = population standard deviation (all data = the population).
            mean   = statistics.mean(data)
            stddev = statistics.pstdev(data)

            # Apply floor values to prevent z = 0/0 division errors
            self.effective_mean   = max(mean,   self.min_mean)
            self.effective_stddev = max(stddev, self.min_stddev)

            # Recalculate error rate baseline too
            error_data = list(self.error_counts_window)
            if len(error_data) >= 2:
                self.error_mean   = max(statistics.mean(error_data),   0.01)
                self.error_stddev = max(statistics.pstdev(error_data), 0.01)

            # Save a snapshot for the dashboard history graph
            self.history.append((time.time(), self.effective_mean, self.effective_stddev, slot_used))

        # Fire the audit log callback (outside the lock to avoid deadlocks)
        logger.info(
            f"Baseline recalculated — mean={self.effective_mean:.3f}, "
            f"stddev={self.effective_stddev:.3f}, source={slot_used}, samples={len(data)}"
        )
        if self.on_recalc:
            self.on_recalc(self.effective_mean, self.effective_stddev, len(data), slot_used)
