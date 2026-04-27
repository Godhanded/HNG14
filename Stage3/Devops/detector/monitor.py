"""
monitor.py — Log File Tailer and Parser

This module continuously reads new lines from the Nginx JSON access log,
similar to how `tail -f` works in Linux. Each new line is parsed as JSON
and handed off to a callback function for processing.

Why we tail instead of reading the whole file:
  - The log file grows forever. We only care about NEW lines (new requests).
  - Reading from the current end means we never re-process old data.
  - We sleep briefly (0.05s) when no new data is available to avoid
    burning 100% CPU in a busy-wait loop.
"""

import os
import json
import time
import logging

logger = logging.getLogger(__name__)


def tail_log(log_file: str, callback) -> None:
    """
    Continuously tail a log file and call `callback(entry)` for each new line.

    Args:
        log_file: Absolute path to the Nginx JSON access log.
        callback: A function that receives a dict (the parsed JSON log entry).

    This function runs forever — call it in a background thread.
    """

    # ── Wait for the log file to exist ────────────────────────────────────────
    # The nginx container might take a few seconds to start and create the file.
    # We keep checking every second rather than crashing immediately.
    while not os.path.exists(log_file):
        logger.info(f"Waiting for log file to appear: {log_file}")
        time.sleep(1)

    logger.info(f"Log file found. Starting to tail: {log_file}")

    with open(log_file, 'r') as f:
        # ── Jump to the END of the file ────────────────────────────────────────
        # seek(0, 2) moves the read cursor to position 0 bytes from the END.
        # This means we skip all historical log entries and only read NEW ones
        # that arrive after the daemon starts. Without this, the detector would
        # try to process potentially millions of old log lines on startup.
        f.seek(0, 2)

        while True:
            line = f.readline()

            if not line:
                # readline() returns an empty string when there's no new data.
                # Sleep briefly to avoid spinning the CPU at 100%.
                time.sleep(0.05)
                continue

            line = line.strip()
            if not line:
                continue  # Skip blank lines

            # ── Parse JSON ─────────────────────────────────────────────────────
            # Each line in the Nginx access log is a JSON object like:
            # {"timestamp":"2025-04-26T10:00:01+00:00","source_ip":"1.2.3.4",...}
            try:
                entry = json.loads(line)
                callback(entry)
            except json.JSONDecodeError:
                # Malformed line — nginx sometimes writes partial lines during
                # log rotation. Just skip it.
                logger.debug(f"Skipping malformed log line: {line[:80]}")


def parse_source_ip(entry: dict) -> str:
    """
    Extract the real client IP from a parsed log entry.

    Nginx logs $remote_addr which, after the real_ip module runs, should
    already be the real client IP. But if there's still a forwarded chain
    in x_forwarded_for, we take the first (leftmost) IP — that's the
    original client, not the proxy.

    Returns an empty string if no valid IP could be found.
    """
    # First choice: source_ip (set by nginx real_ip module from X-Forwarded-For)
    ip = entry.get('source_ip', '').strip()

    # If that's a private/docker IP, check the x_forwarded_for chain
    if ip and not _is_private(ip):
        return ip

    # Fall back: take the first IP from the X-Forwarded-For header chain
    x_fwd = entry.get('x_forwarded_for', '').strip()
    if x_fwd and x_fwd != '-':
        first = x_fwd.split(',')[0].strip()
        if first:
            return first

    return ip  # Return whatever we have, even if private


def _is_private(ip: str) -> bool:
    """Returns True if the IP is a private/loopback address."""
    return (
        ip.startswith('127.')
        or ip.startswith('10.')
        or ip.startswith('172.')
        or ip.startswith('192.168.')
        or ip == '::1'
    )
