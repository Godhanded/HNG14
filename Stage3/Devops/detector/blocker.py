"""
blocker.py — iptables IP Blocking

This module manages firewall rules that DROP all packets from a banned IP.

How iptables works (simplified):
  iptables is the Linux kernel's built-in firewall.
  The INPUT chain processes all packets coming INTO the machine.
  A DROP rule tells the kernel to silently discard the packet — the sender
  gets no response, which is better than REJECT (which sends an error back).

  Command to block:   iptables -I INPUT -s <IP> -j DROP
    -I INPUT  = Insert at the TOP of the INPUT chain (takes priority)
    -s <IP>   = Match packets where the SOURCE is this IP
    -j DROP   = Jump to the DROP target (silently discard)

  Command to unblock: iptables -D INPUT -s <IP> -j DROP
    -D = Delete this specific rule from the chain

Why we use -I (insert) instead of -A (append):
  -A adds the rule at the BOTTOM of the chain. If there are many rules,
  packets from this IP would be processed by all preceding rules first.
  -I inserts at the TOP so the DROP fires immediately, before any other rules.
"""

import subprocess
import threading
import time
import logging

logger = logging.getLogger(__name__)


class IPBlocker:
    """
    Maintains a set of active iptables DROP rules for malicious IPs.
    Thread-safe: all operations acquire self._lock before modifying state.
    """

    def __init__(self):
        # ip → unix timestamp when it was blocked
        self._blocked: dict = {}
        self._lock = threading.Lock()

    def block(self, ip: str) -> bool:
        """
        Add an iptables DROP rule for `ip`.

        Returns True if the rule was added, False if the IP was already blocked
        or if the iptables command failed.
        """
        with self._lock:
            if ip in self._blocked:
                return False  # Already blocked — don't add a duplicate rule

            try:
                result = subprocess.run(
                    ['iptables', '-I', 'INPUT', '-s', ip, '-j', 'DROP'],
                    capture_output=True,
                    text=True,
                    timeout=5   # Don't hang if iptables is slow
                )
                if result.returncode == 0:
                    self._blocked[ip] = time.time()
                    logger.info(f"[BLOCK] iptables DROP added for {ip}")
                    return True
                else:
                    logger.error(f"[BLOCK] iptables failed for {ip}: {result.stderr.strip()}")
                    return False

            except subprocess.TimeoutExpired:
                logger.error(f"[BLOCK] iptables timed out for {ip}")
                return False
            except FileNotFoundError:
                # iptables binary not found — running outside of a privileged container?
                logger.error("[BLOCK] iptables not found. Is the container running with --privileged?")
                return False
            except Exception as e:
                logger.error(f"[BLOCK] Unexpected error blocking {ip}: {e}")
                return False

    def unblock(self, ip: str) -> bool:
        """
        Remove the iptables DROP rule for `ip`.

        Returns True if the rule was removed, False if the IP wasn't blocked
        or if the iptables command failed.
        """
        with self._lock:
            if ip not in self._blocked:
                return False  # Nothing to remove

            try:
                result = subprocess.run(
                    ['iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    del self._blocked[ip]
                    logger.info(f"[UNBLOCK] iptables DROP removed for {ip}")
                    return True
                else:
                    logger.error(f"[UNBLOCK] iptables failed for {ip}: {result.stderr.strip()}")
                    return False

            except Exception as e:
                logger.error(f"[UNBLOCK] Error unblocking {ip}: {e}")
                return False

    def is_blocked(self, ip: str) -> bool:
        """Returns True if this IP currently has an active iptables rule."""
        with self._lock:
            return ip in self._blocked

    def get_blocked_ips(self) -> dict:
        """Returns a copy of the blocked IPs dict: {ip: timestamp_blocked}."""
        with self._lock:
            return dict(self._blocked)
