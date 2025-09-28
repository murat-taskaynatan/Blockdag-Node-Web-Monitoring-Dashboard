# BlockDAG Web Dashboard

A lightweight Flask-based web dashboard for monitoring BlockDAG testnet or mainnet nodes inside Docker.  
It auto-detects whether `docker` or `sudo docker` is needed, fetches health endpoints, tails logs, and parses node status in real time.



<img width="996" height="624" alt="image" src="https://github.com/user-attachments/assets/db5c5324-a0a3-4062-8506-305919dbefc7" />

---

## ✨ Features
- **Docker auto-detect**: Works with `docker` or `sudo docker -n`.
- **Health endpoints**: Queries `/readyz` and `/healthz` inside the container (via `docker exec curl`).
- **Log parsing**: Extracts peers, height, hashrate, last log timestamp.
- **Status detection**: Shows mining/healthy/syncing/error states.
- **Web UI**: Modern, responsive design with live auto-refresh every 10s.
- **Configurable**: Change container name, `--since`, and `--tail` via the UI or query string.

---

## 🚀 Quick start

### 1. Install dependencies
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv
cd ~/blockdag-scripts
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# Run locally
./.venv/bin/python app.py

Open http://localhost:8080

# Run as a service (systemd)

Create /etc/systemd/system/blockdag-dashboard.service:

[Unit]
Description=BlockDAG Web Dashboard
After=network-online.target docker.service
Wants=network-online.target

[Service]
WorkingDirectory=/home/ubuntu/blockdag-scripts
ExecStart=/home/ubuntu/blockdag-scripts/.venv/bin/python /home/ubuntu/blockdag-scripts/app.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target

# Enable:
sudo systemctl daemon-reload
sudo systemctl enable --now blockdag-dashboard

Now visit http://<VM_IP>:8080.

⚙️ Usage

Default container: blockdag-testnet-network

# Change container in the UI or via query params:
http://<host>:8080/?container=my-node&since=5m&tail=800
Auto-refresh: 10s
# If health endpoints show “—”, install curl inside the container:
docker exec -it my-node apt-get update && docker exec -it my-node apt-get install -y curl
