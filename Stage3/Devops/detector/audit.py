"""
audit.py — Structured Audit Logger

Every significant security event is written to the audit log in a structured
format that's easy to grep, parse, and review.

Required format from the task spec:
  [timestamp] ACTION ip | condition | rate | baseline | duration

Examples:
  [2025-04-26T10:00:01Z] BAN ip=1.2.3.4 | condition=z-score=4.21 | rate=12.300 | baseline=mean=1.500,stddev=0.300 | duration=10m
  [2025-04-26T10:10:01Z] UNBAN ip=1.2.3.4 | condition=ban_count=1
  [2025-04-26T10:01:01Z] BASELINE_RECALC | condition=window_size=1800 | baseline=mean=1.502,stddev=0.301 | duration=hour_slot=10
"""

import logging
import threading
import time
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Writes structured one-line audit entries for bans, unbans, and
    baseline recalculations to a dedicated log file.
    """

    def __init__(self, log_file: str = '/var/log/detector/audit.log'):
        self._log_file = log_file
        self._lock     = threading.Lock()

        # Ensure the directory exists before opening the file
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # ── Public logging methods ─────────────────────────────────────────────────

    def log_ban(self, ip: str, condition: str, rate: float,
                mean: float, stddev: float, duration_seconds: int | None) -> None:
        """Log a ban event."""
        dur = f"{duration_seconds // 60}m" if duration_seconds else "PERMANENT"
        self._write(
            "BAN",
            f"ip={ip}",
            f"condition={condition}",
            f"rate={rate:.3f}",
            f"baseline=mean={mean:.3f},stddev={stddev:.3f}",
            f"duration={dur}",
        )

    def log_unban(self, ip: str, ban_count: int) -> None:
        """Log an unban event."""
        self._write(
            "UNBAN",
            f"ip={ip}",
            f"condition=ban_count={ban_count}",
        )

    def log_baseline_recalc(self, mean: float, stddev: float,
                             window_size: int, slot: str) -> None:
        """Log a baseline recalculation event."""
        self._write(
            "BASELINE_RECALC",
            f"condition=window_size={window_size}",
            f"baseline=mean={mean:.3f},stddev={stddev:.3f}",
            f"duration=hour_slot={slot}",
        )

    # ── Internal helper ────────────────────────────────────────────────────────

    def _write(self, action: str, *fields: str) -> None:
        """
        Build a log line: [timestamp] ACTION field1 | field2 | ...
        and append it to the audit log file.
        """
        ts   = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        line = f"[{ts}] {action} " + " | ".join(fields) + "\n"

        with self._lock:
            try:
                with open(self._log_file, 'a') as f:
                    f.write(line)
            except OSError as e:
                # Don't crash the whole daemon just because the audit log failed
                logger.error(f"Failed to write audit log: {e}")
