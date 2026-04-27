"""
notifier.py — Slack Alert Sender

Sends formatted messages to a Slack channel via an Incoming Webhook URL.
Every alert includes: condition fired, current rate, baseline, timestamp,
and ban duration (where applicable).

To set up a Slack webhook:
  1. Go to https://api.slack.com/apps and create an app (or use an existing one).
  2. Enable "Incoming Webhooks" under Features.
  3. Click "Add New Webhook to Workspace" and select a channel.
  4. Copy the Webhook URL into your .env file as SLACK_WEBHOOK_URL.
"""

import requests
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SlackNotifier:
    """
    Wraps Slack's Incoming Webhook API.
    If the webhook URL is not configured, alerts are logged locally instead.
    """

    def __init__(self, webhook_url: str):
        # Treat missing or placeholder URLs as "disabled"
        self._url     = webhook_url
        self._enabled = bool(
            webhook_url
            and webhook_url.startswith('https://hooks.slack.com/')
        )
        if not self._enabled:
            logger.warning("Slack webhook not configured — alerts will only appear in logs")

    # ── Public alert methods ───────────────────────────────────────────────────

    def send_ban_alert(self, ip: str, rate: float, mean: float, stddev: float,
                       condition: str, duration_seconds: int | None) -> None:
        """
        Fired when an IP is blocked by iptables.
        Includes: IP, condition, current rate, baseline, ban duration.
        """
        if duration_seconds is None:
            duration_str = "*PERMANENT*"
        elif duration_seconds < 3600:
            duration_str = f"{duration_seconds // 60} minutes"
        else:
            duration_str = f"{duration_seconds // 3600} hours"

        msg = (
            f":rotating_light: *IP BANNED* — {_ts()}\n"
            f">*IP:* `{ip}`\n"
            f">*Condition:* {condition}\n"
            f">*Current Rate:* `{rate:.3f} req/s`\n"
            f">*Baseline:* mean=`{mean:.3f}` stddev=`{stddev:.3f}`\n"
            f">*Ban Duration:* {duration_str}"
        )
        self._send(msg)

    def send_unban_alert(self, ip: str, ban_count: int) -> None:
        """
        Fired when an IP is automatically unbanned.
        The ban_count tells the team how many times this IP has been a problem.
        """
        msg = (
            f":white_check_mark: *IP UNBANNED* — {_ts()}\n"
            f">*IP:* `{ip}`\n"
            f">*Total Bans:* {ban_count}\n"
            f">*Note:* IP will be re-banned automatically if it misbehaves again"
        )
        self._send(msg)

    def send_global_alert(self, rate: float, mean: float, stddev: float,
                          condition: str) -> None:
        """
        Fired when the GLOBAL request rate is anomalous.
        No IP ban is issued — this could be a legitimate viral spike or a
        distributed attack where no single IP stands out.
        """
        msg = (
            f":warning: *GLOBAL TRAFFIC ANOMALY* — {_ts()}\n"
            f">*Condition:* {condition}\n"
            f">*Global Rate:* `{rate:.3f} req/s`\n"
            f">*Baseline:* mean=`{mean:.3f}` stddev=`{stddev:.3f}`\n"
            f">_No individual IP blocked — spike may be distributed or legitimate_"
        )
        self._send(msg)

    # ── Internal helper ────────────────────────────────────────────────────────

    def _send(self, text: str) -> None:
        """POST a message to the Slack webhook. Logs locally if webhook is disabled."""
        if not self._enabled:
            logger.info(f"[SLACK-DISABLED] {text}")
            return

        try:
            resp = requests.post(
                self._url,
                json={"text": text},
                timeout=5   # Don't let a slow Slack response block the detector
            )
            if resp.status_code != 200:
                logger.error(f"Slack returned {resp.status_code}: {resp.text}")
        except requests.exceptions.Timeout:
            logger.error("Slack webhook timed out")
        except requests.exceptions.RequestException as e:
            logger.error(f"Slack notification failed: {e}")


def _ts() -> str:
    """Current UTC timestamp formatted for Slack messages."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
