"""
detector.py — Anomaly Detection Engine

This module watches the per-IP and global request rates and decides whether
traffic is anomalous by comparing against the rolling baseline.

Two detection methods run in parallel — whichever fires first triggers the alert:
  1. Z-score: z = (rate - mean) / stddev  → flag if z > 3.0
     "This rate is 3 standard deviations above normal — very unlikely by chance."
  2. Rate multiplier: flag if rate > 5 × mean
     "This rate is 5× the average — something is definitely wrong."
     This catches anomalies even when the stddev is tiny (flat, predictable traffic).

The sliding window explained:
  Each IP has its own deque of request TIMESTAMPS (not counts).
  When a request comes in, we append time.time() to the deque.
  When we want the rate, we EVICT timestamps older than 60 seconds,
  then divide the remaining count by 60.

  Example deque after some requests at t=100:
    [98.1, 98.5, 99.0, 99.7, 100.0]  → 5 requests in last 60s → 0.083 req/s

  After a burst at t=110:
    [100.0, 110.0, 110.0, 110.0, ..., 110.0]  → many in last 60s → high rate

  Old entries (< t - 60) fall off the left side via popleft().
  This is an O(1) operation since deque supports fast removal from both ends.
"""

import time
import threading
import logging
from collections import deque, defaultdict

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """
    Maintains per-IP and global sliding windows and fires callbacks when
    anomalous traffic is detected.
    """

    def __init__(self, config: dict, baseline, on_ip_anomaly, on_global_anomaly):
        """
        Args:
            config:             Loaded config.yaml dict.
            baseline:           BaselineTracker instance for mean/stddev.
            on_ip_anomaly:      Callback(ip, rate, mean, stddev, condition)
            on_global_anomaly:  Callback(rate, mean, stddev, condition)
        """
        self.ip_window_secs     = config.get('ip_window_seconds', 60)
        self.global_window_secs = config.get('global_window_seconds', 60)
        self.z_threshold        = config.get('z_score_threshold', 3.0)
        self.rate_mult          = config.get('rate_multiplier_threshold', 5.0)
        self.error_mult         = config.get('error_rate_multiplier', 3.0)
        self.whitelisted        = set(config.get('whitelisted_ips', []))

        self.baseline          = baseline
        self.on_ip_anomaly     = on_ip_anomaly
        self.on_global_anomaly = on_global_anomaly

        # ── Per-IP sliding windows ─────────────────────────────────────────────
        # ip → deque of float timestamps (seconds since epoch)
        # Each timestamp represents one request from that IP.
        self._ip_windows       = defaultdict(deque)
        self._ip_err_windows   = defaultdict(deque)  # only 4xx/5xx timestamps

        # ── Global sliding window ──────────────────────────────────────────────
        # One deque for ALL requests from ALL IPs combined.
        # Used to detect distributed attacks where no single IP is dominant.
        self._global_window    = deque()
        self._global_err_window = deque()

        # ── Deduplication ──────────────────────────────────────────────────────
        # Once we flag an IP, we don't fire again until it's been unbanned.
        # This prevents flooding Slack with duplicate alerts for the same attack.
        self._flagged_ips      = set()
        self._global_flagged   = False
        self._global_flag_time = 0.0   # when the global flag was last set

        self._lock             = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(self, ip: str, is_error: bool = False) -> None:
        """
        Record one request from `ip`. Evict stale window entries, then check
        whether the current rate crosses any anomaly threshold.

        This is called on EVERY log line, so it must be fast (no I/O, no sleeps).
        """
        # Never block IPs that are on the whitelist (localhost, private ranges, etc.)
        if self._is_whitelisted(ip):
            return

        now = time.time()

        with self._lock:
            # ── Append to sliding windows ─────────────────────────────────────
            self._ip_windows[ip].append(now)
            self._global_window.append(now)
            if is_error:
                self._ip_err_windows[ip].append(now)
                self._global_err_window.append(now)

            # ── Evict old timestamps (the "sliding" part of the sliding window) ─
            # popleft() removes from the LEFT (oldest end) of the deque.
            # We keep removing until the oldest entry is within our time window.
            ip_cutoff     = now - self.ip_window_secs
            global_cutoff = now - self.global_window_secs

            while self._ip_windows[ip] and self._ip_windows[ip][0] < ip_cutoff:
                self._ip_windows[ip].popleft()

            while self._ip_err_windows[ip] and self._ip_err_windows[ip][0] < ip_cutoff:
                self._ip_err_windows[ip].popleft()

            while self._global_window and self._global_window[0] < global_cutoff:
                self._global_window.popleft()

            while self._global_err_window and self._global_err_window[0] < global_cutoff:
                self._global_err_window.popleft()

            # ── Compute current rates ─────────────────────────────────────────
            # len(deque) / window_seconds = average requests per second
            ip_rate        = len(self._ip_windows[ip])       / self.ip_window_secs
            ip_err_rate    = len(self._ip_err_windows[ip])   / self.ip_window_secs
            global_rate    = len(self._global_window)        / self.global_window_secs
            already_flagged = ip in self._flagged_ips

        # ── Fetch baseline (outside the window lock to avoid contention) ──────
        mean,       stddev       = self.baseline.get_baseline()
        error_mean, error_stddev = self.baseline.get_error_baseline()

        # ── Error-surge: tighten thresholds if this IP is making lots of errors ─
        # If the IP's error rate is 3× the baseline error rate, lower the bar
        # for flagging it. Attackers often generate lots of 4xx responses.
        tightened = (error_mean > 0 and ip_err_rate >= self.error_mult * error_mean)
        if tightened:
            z_threshold = self.z_threshold * 0.7    # 30% tighter z-score threshold
            rate_mult   = self.rate_mult   * 0.7    # 30% tighter rate multiplier
        else:
            z_threshold = self.z_threshold
            rate_mult   = self.rate_mult

        # ── Per-IP anomaly check ───────────────────────────────────────────────
        ip_zscore = (ip_rate - mean) / stddev if stddev > 0 else 0.0
        ip_anomalous = (ip_zscore > z_threshold) or (ip_rate > rate_mult * mean and ip_rate > 1.0)

        if ip_anomalous and not already_flagged:
            with self._lock:
                # Double-check inside the lock (another thread might have flagged it)
                if ip not in self._flagged_ips:
                    self._flagged_ips.add(ip)

            # Build a human-readable description of which condition fired
            if ip_zscore > z_threshold:
                condition = f"z-score={ip_zscore:.2f} (threshold={z_threshold:.1f})"
            else:
                condition = f"rate={ip_rate:.2f} req/s > {rate_mult:.1f}x mean ({mean:.2f})"
            if tightened:
                condition += " [error-surge: thresholds tightened]"

            logger.warning(f"IP anomaly: {ip} | {condition}")
            self.on_ip_anomaly(ip, ip_rate, mean, stddev, condition)

        # ── Global anomaly check ───────────────────────────────────────────────
        # Global anomaly = the ENTIRE site is being hit, not just from one IP.
        # We only re-alert after 5 minutes to avoid spamming Slack.
        global_zscore  = (global_rate - mean) / stddev if stddev > 0 else 0.0
        global_anomalous = (
            (global_zscore > self.z_threshold) or
            (global_rate > self.rate_mult * mean and global_rate > 1.0)
        )
        now2 = time.time()
        if global_anomalous and (not self._global_flagged or now2 - self._global_flag_time > 300):
            self._global_flagged   = True
            self._global_flag_time = now2

            if global_zscore > self.z_threshold:
                condition = f"global z-score={global_zscore:.2f} (threshold={self.z_threshold:.1f})"
            else:
                condition = f"global rate={global_rate:.2f} req/s > {self.rate_mult:.1f}x mean ({mean:.2f})"

            logger.warning(f"Global anomaly: {condition}")
            self.on_global_anomaly(global_rate, mean, stddev, condition)

    def unflag_ip(self, ip: str) -> None:
        """
        Remove `ip` from the flagged set so it can be re-detected if it
        misbehaves again after being unbanned.
        """
        with self._lock:
            self._flagged_ips.discard(ip)

    def get_global_rate(self) -> float:
        """Current global request rate in req/s."""
        with self._lock:
            now    = time.time()
            cutoff = now - self.global_window_secs
            while self._global_window and self._global_window[0] < cutoff:
                self._global_window.popleft()
            return len(self._global_window) / self.global_window_secs

    def get_top_ips(self, n: int = 10) -> list:
        """
        Returns the top N IPs by request rate over the last window, as
        [(ip, rate), ...] sorted descending by rate.
        """
        with self._lock:
            now    = time.time()
            cutoff = now - self.ip_window_secs
            rates  = {}
            for ip, window in self._ip_windows.items():
                # Evict while we're here
                while window and window[0] < cutoff:
                    window.popleft()
                if window:
                    rates[ip] = len(window) / self.ip_window_secs

        return sorted(rates.items(), key=lambda x: x[1], reverse=True)[:n]

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _is_whitelisted(self, ip: str) -> bool:
        """Check if an IP matches any entry in the whitelist."""
        if ip in self.whitelisted:
            return True
        # Simple CIDR prefix check for private ranges
        for prefix in ('127.', '10.', '172.16.', '172.17.', '192.168.'):
            if ip.startswith(prefix):
                return True
        return False
