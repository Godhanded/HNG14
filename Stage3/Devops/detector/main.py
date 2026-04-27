"""
main.py — HNG Anomaly Detection Engine Entry Point

This is the file you run. It:
  1. Loads config from config.yaml (+ env var overrides)
  2. Creates all the components (baseline, detector, blocker, unbanner, notifier, audit)
  3. Wires them together with callback functions
  4. Starts the log monitor in a background thread
  5. Starts the dashboard web server in a background thread
  6. Keeps the main thread alive (printing a heartbeat every minute)

Think of this file as the "main office" — it doesn't do any detection itself,
it just hires the right specialists and makes sure they can talk to each other.
"""

import os
import sys
import time
import threading
import logging
import yaml

# ── Our own modules ────────────────────────────────────────────────────────────
from monitor   import tail_log, parse_source_ip
from baseline  import BaselineTracker
from detector  import AnomalyDetector
from blocker   import IPBlocker
from unbanner  import UnbanScheduler
from notifier  import SlackNotifier
from dashboard import run_dashboard
from audit     import AuditLogger


# ─── Logging Setup ─────────────────────────────────────────────────────────────
# Configure the root logger so that ALL modules (baseline, detector, etc.)
# automatically write to both stdout AND the log file.
def setup_logging(log_file: str) -> None:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    fmt     = '%(asctime)s [%(name)-12s] %(levelname)-8s %(message)s'
    datefmt = '%Y-%m-%d %H:%M:%S'

    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.StreamHandler(sys.stdout),                    # print to terminal
            logging.FileHandler(log_file, encoding='utf-8'),      # write to file
        ]
    )

logger = logging.getLogger('main')


# ─── Config Loading ─────────────────────────────────────────────────────────────
def load_config() -> dict:
    """
    Load config.yaml from the same directory as this script.
    Environment variables override specific keys:
      SLACK_WEBHOOK_URL → config['slack_webhook_url']
    """
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    with open(config_path, encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Allow the Slack webhook to be injected via environment variable
    # (so it doesn't have to be hardcoded in the config file)
    env_slack = os.environ.get('SLACK_WEBHOOK_URL', '').strip()
    if env_slack:
        config['slack_webhook_url'] = env_slack

    return config


# ─── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    config = load_config()

    setup_logging(config.get('detector_log_file', '/var/log/detector/detector.log'))

    logger.info("=" * 60)
    logger.info("  HNG Anomaly Detection Engine — Starting Up")
    logger.info("=" * 60)

    # ── Create audit logger ────────────────────────────────────────────────────
    # This writes structured entries for every ban, unban, and baseline recalc.
    audit = AuditLogger(config.get('audit_log_file', '/var/log/detector/audit.log'))

    # ── Create baseline tracker ────────────────────────────────────────────────
    # Pass the audit logger as the on_recalc callback so every baseline
    # recalculation is automatically logged to the audit file.
    def on_recalc(mean, stddev, window_size, slot):
        audit.log_baseline_recalc(mean, stddev, window_size, slot)

    baseline = BaselineTracker(config, on_recalc=on_recalc)

    # ── Create blocker (iptables) ──────────────────────────────────────────────
    blocker = IPBlocker()

    # ── Create Slack notifier ──────────────────────────────────────────────────
    notifier = SlackNotifier(config.get('slack_webhook_url', ''))

    # ── Define event callbacks ─────────────────────────────────────────────────
    # These functions are called by the detector when anomalies are found.
    # We define them here (in main) so they have access to blocker, notifier,
    # audit, and unbanner — avoiding circular imports between modules.

    def on_ip_anomaly(ip: str, rate: float, mean: float, stddev: float, condition: str) -> None:
        """
        Fired by detector.py when a single IP's rate looks anomalous.
        We must: block the IP, schedule its unban, alert Slack, and audit-log it.
        The task requires this to happen within 10 seconds of detection.
        """
        logger.warning(f"[ANOMALY-IP] {ip} | {condition} | rate={rate:.3f}")

        # Block via iptables — this is fast (<100ms)
        blocked = blocker.block(ip)
        if not blocked:
            return  # Already blocked or iptables failed

        # Schedule automatic unban (unbanner will call on_unban when the time comes)
        duration = unbanner.schedule_unban(ip)

        # Alert Slack (done in a background thread so it doesn't slow down detection)
        threading.Thread(
            target=notifier.send_ban_alert,
            args=(ip, rate, mean, stddev, condition, duration),
            daemon=True
        ).start()

        # Write to audit log
        audit.log_ban(ip, condition, rate, mean, stddev, duration)

    def on_global_anomaly(rate: float, mean: float, stddev: float, condition: str) -> None:
        """
        Fired by detector.py when the GLOBAL request rate is anomalous.
        No IP ban — just alert Slack. (Could be a distributed attack or viral traffic.)
        """
        logger.warning(f"[ANOMALY-GLOBAL] {condition} | rate={rate:.3f}")
        threading.Thread(
            target=notifier.send_global_alert,
            args=(rate, mean, stddev, condition),
            daemon=True
        ).start()

    def on_unban(ip: str, ban_count: int) -> None:
        """
        Fired by unbanner.py when an IP's ban duration expires.
        We alert Slack and audit-log the release.
        """
        logger.info(f"[UNBAN] {ip} released (ban #{ban_count})")
        threading.Thread(
            target=notifier.send_unban_alert,
            args=(ip, ban_count),
            daemon=True
        ).start()
        audit.log_unban(ip, ban_count)

    # ── Create detector ────────────────────────────────────────────────────────
    # Now that we have the callbacks, we can create the detector.
    detector = AnomalyDetector(config, baseline, on_ip_anomaly, on_global_anomaly)

    # ── Create unbanner (needs detector so it can unflag IPs after releasing them) ──
    unbanner = UnbanScheduler(config, blocker, detector, on_unban)

    # ── Define the log-line processor ──────────────────────────────────────────
    def process_log_entry(entry: dict) -> None:
        """
        Called by monitor.py for every new line parsed from the Nginx access log.
        This runs on the monitor thread — keep it fast (no sleeps, no I/O).
        """
        ip     = parse_source_ip(entry)
        status = int(entry.get('status', 200))

        # We don't care about requests with no IP (e.g. health checks from localhost)
        if not ip:
            return

        is_error = status >= 400   # 4xx and 5xx are errors

        # 1. Update the rolling baseline with this data point
        baseline.record_request(is_error=is_error)

        # 2. Feed it to the detector — this is where anomaly checks happen
        detector.record(ip, is_error=is_error)

    # ── Start the log monitor thread ──────────────────────────────────────────
    log_file = config.get('log_file', '/var/log/nginx/hng-access.log')
    logger.info(f"Starting log monitor: {log_file}")

    monitor_thread = threading.Thread(
        target=tail_log,
        args=(log_file, process_log_entry),
        daemon=True,
        name='log-monitor'
    )
    monitor_thread.start()

    # ── Start the dashboard server thread ─────────────────────────────────────
    dashboard_port = config.get('dashboard_port', 8888)
    logger.info(f"Starting dashboard on port {dashboard_port}")

    dashboard_thread = threading.Thread(
        target=run_dashboard,
        args=(detector, baseline, blocker, unbanner, dashboard_port),
        daemon=True,
        name='dashboard'
    )
    dashboard_thread.start()

    logger.info("All components running. Watching for anomalies...")
    logger.info(f"Dashboard: http://localhost:{dashboard_port}")

    # ── Keep the main thread alive (heartbeat loop) ────────────────────────────
    # Daemon threads die when the main thread dies, so we must keep this alive.
    # Every 60 seconds we log a heartbeat so it's easy to confirm the daemon is
    # still running when you look at the logs.
    try:
        while True:
            time.sleep(60)
            mean, stddev    = baseline.get_baseline()
            blocked_count   = len(blocker.get_blocked_ips())
            global_rate     = detector.get_global_rate()
            logger.info(
                f"[HEARTBEAT] rate={global_rate:.3f} req/s | "
                f"mean={mean:.3f} | stddev={stddev:.3f} | "
                f"blocked_ips={blocked_count}"
            )
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt — shutting down.")
        sys.exit(0)


if __name__ == '__main__':
    main()
