# HNG Anomaly Detection Engine

A real-time DDoS/anomaly detection daemon built for the HNG DevSecOps Stage 3 task.

---

## Live Links (fill in after deployment)

| Resource | URL |
|---|---|
| Nextcloud (attack target) | `http://3.83.81.91:8080` — send test traffic here |
| Server IP | `3.83.81.91` |
| Metrics Dashboard | `https://godand.duckdns.org` |
| GitHub Repo | `https://github.com/Godhanded/HNG14/tree/main/Stage3/Devops` |
| Blog Post | `https://medium.com/@Godand/i-built-a-real-time-ddos-detection-engine-from-scratch-heres-how-it-works-a825dbd69956` |

---

## Language Choice: Python

Python was chosen because:
- `collections.deque` is built-in and perfectly suited for sliding windows (O(1) append and popleft)
- `statistics` module provides mean/stddev without external dependencies
- `subprocess` makes `iptables` calls trivial
- Flask lets us build the dashboard in few lines
- Rapid development: the project has many moving parts; Python lets you iterate fast

---

## How the Sliding Window Works

Each IP gets its own `deque` of **request timestamps** (not counts):

```
ip_windows["1.2.3.4"] = deque([100.01, 100.45, 101.2, 101.8, 102.0, ...])
```

When a new request arrives at time `t`:
1. Append `t` to the deque (O(1) right-side append)
2. **Evict** all timestamps from the left side that are older than `t - 60`:
   ```python
   while window and window[0] < t - 60:
       window.popleft()   # O(1) left-side removal
   ```
3. `len(window) / 60` = average requests per second over the last 60 seconds

Why deque and not a list?  
`list.pop(0)` is O(n) because it shifts every element. `deque.popleft()` is O(1).  
During an attack with thousands of requests per second, this matters.

---

## How the Baseline Works

**Goal:** know what "normal" traffic looks like so we can spot deviations.

**Per-second accumulator → rolling window:**
1. Every request increments a counter for the current second.
2. When the second changes, the count is flushed into a `deque(maxlen=1800)` (30 min × 60 sec).
3. Old seconds automatically fall off the left when the deque is full.

**Recalculation (every 60 seconds):**
```
effective_mean   = statistics.mean(window)
effective_stddev = statistics.pstdev(window)
```

**Hourly slots:**  
Each hour (0–23) gets its own deque of per-second counts. If the current hour has ≥ 5 minutes of data, we use it instead of the 30-minute window — so 3am traffic doesn't contaminate a 3pm baseline.

**Floor values:**  
`effective_mean = max(mean, 1.0)` prevents divide-by-zero during quiet periods.  
`effective_stddev = max(stddev, 0.1)` prevents z-score from exploding at near-zero stddev.

---

## How Detection Works

Two checks run on every request — **whichever fires first** triggers the alert:

### 1. Z-Score Check
```
z = (current_rate - effective_mean) / effective_stddev
flag if z > 3.0
```
A z-score of 3.0 means the rate is 3 standard deviations above normal.  
Statistically, this happens by random chance less than 0.3% of the time.

### 2. Rate Multiplier Check
```
flag if current_rate > 5 × effective_mean
```
This catches attacks when the traffic is very flat (tiny stddev), where the z-score might not fire even though the rate is clearly wrong.

### Error Surge
If an IP's 4xx/5xx rate is 3× the baseline error rate, we tighten both thresholds by 30% — because attackers often generate lots of errors (scanning for endpoints, trying bad passwords, etc.).

---

## How iptables Blocking Works

```bash
# Block:
iptables -I INPUT -s 1.2.3.4 -j DROP

# Unblock:
iptables -D INPUT -s 1.2.3.4 -j DROP
```

- `-I INPUT` = Insert at the **top** of the INPUT chain (highest priority, fires before other rules)
- `-s 1.2.3.4` = Match packets where the **source** is this IP
- `-j DROP` = Silently discard the packet (attacker gets no response)

Bans are automatically lifted on a progressive schedule: 10 min → 30 min → 2 hours → permanent.

---

## Setup Instructions (Fresh VPS)

### 1. Provision the VPS
- Minimum 2 vCPU, 2 GB RAM
- Ubuntu 22.04 LTS recommended
- Open ports: 22 (SSH), 80 (HTTP), 443 (HTTPS), 8080 (Docker Nginx), 8888 (Dashboard)

### 2. Install Docker & Docker Compose
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 3. Clone the repo
```bash
git clone https://github.com/Godhanded/HNG14.git
cd HNG14/Stage3/Devops
```

### 4. Configure environment
```bash
cp .env.example .env
nano .env   # Fill in VPS_IP, DB passwords, SLACK_WEBHOOK_URL
```

### 5. Configure your host Nginx (with SSL)
Add these blocks to your host Nginx config:

```nginx
# Nextcloud — accessible by IP only (no domain)
# Users access it at http://YOUR_VPS_IP:8080

# Dashboard — served at your monitor subdomain
server {
    listen 443 ssl;
    server_name monitor.yourdomain.com;

    # (Your SSL cert lines here)

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### 6. Launch the stack
```bash
docker-compose up -d --build
```

### 7. Verify everything is running
```bash
docker-compose ps                        # All services should show "Up"
docker-compose logs -f detector          # Watch the anomaly detector logs
docker-compose logs -f nginx             # Watch nginx access logs
curl http://localhost:8888/health        # Should return {"status":"ok"}
```

### 8. Check iptables (to confirm blocking works)
```bash
sudo iptables -L INPUT -n --line-numbers
```

---

## Repository Structure

```
Stage3/Devops/
├── docker-compose.yml        # Orchestrates all services
├── .env.example              # Environment variable template
├── nginx/
│   └── nginx.conf            # JSON access logs + reverse proxy config
├── detector/
│   ├── Dockerfile            # Python + iptables image
│   ├── requirements.txt      # Python dependencies
│   ├── config.yaml           # All thresholds and settings
│   ├── main.py               # Entry point — wires everything together
│   ├── monitor.py            # Tails and parses the Nginx access log
│   ├── baseline.py           # Rolling 30-min baseline (mean + stddev)
│   ├── detector.py           # Z-score and rate-multiplier anomaly detection
│   ├── blocker.py            # iptables DROP rule management
│   ├── unbanner.py           # Progressive backoff auto-unban scheduler
│   ├── notifier.py           # Slack webhook alerts
│   ├── dashboard.py          # Flask web dashboard (auto-refreshes every 3s)
│   └── audit.py              # Structured audit log writer
├── docs/
│   └── architecture.png      # System architecture diagram
├── screenshots/              # Required submission screenshots
└── README.md
```

---

<!-- ## Screenshots Checklist

- [ ] `Tool-running.png` — Daemon running, processing log lines
- [ ] `Ban-slack.png` — Slack ban notification
- [ ] `Unban-slack.png` — Slack unban notification
- [ ] `Global-alert-slack.png` — Slack global anomaly notification
- [ ] `Iptables-banned.png` — `sudo iptables -L -n` showing a blocked IP
- [ ] `Audit-log.png` — Structured log with ban, unban, and baseline events
- [ ] `Baseline-graph.png` — Dashboard graph with two visibly different hourly slots -->
