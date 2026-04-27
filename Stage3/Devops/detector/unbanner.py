"""
unbanner.py — Automatic IP Unban with Progressive Backoff

Instead of blocking an IP forever after the first offence, we use a
progressive backoff schedule:
  1st ban → unban after 10 minutes
  2nd ban → unban after 30 minutes
  3rd ban → unban after 2 hours
  4th ban → PERMANENT (never automatically unbanned)

Why progressive backoff?
  - Legitimate users might accidentally trigger the detector (e.g. a bug in
    their app making rapid retries). A 10-minute ban gives them time to stop
    and lets them recover automatically.
  - Persistent attackers get progressively longer punishments until eventually
    they're permanently blocked.
  - We notify Slack on every unban so the team knows who came back.

How the scheduler works:
  A single background thread wakes up every 10 seconds and checks whether
  any IPs are past their scheduled unban time. If so, it removes the
  iptables rule and notifies Slack.
  Using a sleep loop (rather than per-IP timers) keeps the code simple
  and avoids spawning hundreds of threads during an attack.
"""

import time
import threading
import logging

logger = logging.getLogger(__name__)


class UnbanScheduler:
    """
    Watches the list of blocked IPs and automatically unbans them
    according to the progressive backoff schedule in config.yaml.
    """

    def __init__(self, config: dict, blocker, detector, on_unban):
        """
        Args:
            config:    Loaded config.yaml dict.
            blocker:   IPBlocker instance (to call unblock()).
            detector:  AnomalyDetector instance (to call unflag_ip() after unban).
            on_unban:  Callback(ip, ban_count) — fired after each successful unban.
        """
        # The unban schedule from config: [600, 1800, 7200] seconds by default.
        # Index 0 = duration for 1st ban, index 1 = 2nd ban, etc.
        # If ban_count >= len(schedule), the ban is permanent.
        self._schedule = config.get('unban_schedule_seconds', [600, 1800, 7200])

        self._blocker  = blocker
        self._detector = detector
        self._on_unban = on_unban

        # ip → how many times this IP has been banned (used to pick the schedule index)
        self._ban_counts: dict = {}

        # ip → unix timestamp when it should be unbanned
        # IPs with permanent bans are NOT in this dict.
        self._pending: dict = {}

        self._lock = threading.Lock()

        # Start the scheduler background thread
        t = threading.Thread(target=self._scheduler_loop, daemon=True, name='unbanner')
        t.start()

    # ── Public API ─────────────────────────────────────────────────────────────

    def schedule_unban(self, ip: str) -> int | None:
        """
        Record a new ban for `ip` and schedule its automatic unban.

        Returns the ban duration in seconds, or None if the ban is permanent.
        Called by main.py immediately after blocker.block() succeeds.
        """
        with self._lock:
            # How many times has this IP been banned before (0 for first time)?
            count = self._ban_counts.get(ip, 0)

            if count >= len(self._schedule):
                # This IP has exhausted all grace periods — permanent ban
                self._ban_counts[ip] = count + 1
                logger.info(f"[UNBAN-SCHED] {ip} has been banned {count+1} times — permanent ban, no unban scheduled")
                return None

            # Schedule the unban at now + duration_seconds
            duration      = self._schedule[count]
            unban_at      = time.time() + duration
            self._pending[ip]    = unban_at
            self._ban_counts[ip] = count + 1   # increment AFTER reading count

            logger.info(f"[UNBAN-SCHED] {ip} will be unbanned in {_fmt(duration)} (ban #{count+1})")
            return duration

    def get_pending_unbans(self) -> dict:
        """
        Returns {ip: seconds_until_unban} for all IPs with a scheduled unban.
        Negative values mean the unban is overdue (will be processed next tick).
        """
        with self._lock:
            now = time.time()
            return {ip: max(0.0, t - now) for ip, t in self._pending.items()}

    def get_ban_counts(self) -> dict:
        """Returns {ip: total_ban_count} for all IPs seen."""
        with self._lock:
            return dict(self._ban_counts)

    # ── Internal scheduler ─────────────────────────────────────────────────────

    def _scheduler_loop(self) -> None:
        """
        Wakes every 10 seconds and processes any IPs whose unban time has passed.
        Running a single loop here is simpler and lighter than spawning one
        timer thread per banned IP (which could be hundreds during an attack).
        """
        while True:
            time.sleep(10)

            now = time.time()
            with self._lock:
                # Collect IPs whose unban time has arrived
                due = [ip for ip, t in self._pending.items() if now >= t]

            for ip in due:
                success = self._blocker.unblock(ip)
                if success:
                    # Allow the detector to flag this IP again if it reoffends
                    self._detector.unflag_ip(ip)

                    with self._lock:
                        self._pending.pop(ip, None)
                        ban_count = self._ban_counts.get(ip, 1)

                    logger.info(f"[UNBAN] {ip} automatically unbanned (ban #{ban_count})")
                    self._on_unban(ip, ban_count)
                else:
                    # Unblock failed — remove from pending anyway to avoid retrying forever
                    with self._lock:
                        self._pending.pop(ip, None)
                    logger.error(f"[UNBAN] Failed to unblock {ip} — removing from pending anyway")


def _fmt(seconds: int) -> str:
    """Format a duration in seconds as a human-readable string."""
    if seconds < 3600:
        return f"{seconds // 60} minutes"
    return f"{seconds // 3600} hours"
