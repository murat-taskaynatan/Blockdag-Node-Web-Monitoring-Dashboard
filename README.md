# BlockDAG Web Dashboard

A lightweight, self-hosted **Flask web dashboard** for monitoring BlockDAG nodes running inside Docker.  
It auto-detects whether to use `docker` or `sudo docker`, queries container health endpoints, parses logs, and displays node metrics in a modern web UI.

<img width="996" height="624" alt="image" src="https://github.com/user-attachments/assets/84e8ac80-9a39-47bc-93f6-294dd9b9e675" />


---

## Table of Contents
- [Features](#features)
- [Installation](#installation)
  - [Dependencies](#dependencies)
  - [Virtual Environment (Recommended)](#virtual-environment-recommended)
- [Running](#running)
  - [Local Run](#local-run)
  - [Systemd Service](#systemd-service)
- [Usage](#usage)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Features
- **Docker auto-detect** → Works with `docker` or `sudo docker -n`
- **Node health checks** → Calls `/readyz` and `/healthz` inside the container
- **Live metrics** → Displays peers, height, hashrate, and last log timestamp
- **Status detection** → Shows `✅ Healthy`, `⏳ Syncing`, `🔗 Connected`, or `❌ Error` based on logs + endpoints
- **Responsive UI** → Card-based layout with colored status pills and auto-refresh every 10s
- **Configurable** → Change container, `--since`, and `--tail` via the UI or query string

---

## Installation

### Dependencies
Install Python and pip:
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv

# Clone the repo
git clone https://github.com/<your-username>/blockdag-dashboard.git
cd blockdag-dashboard

# Virtual Environment (Recommended)
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

#Local run
./.venv/bin/python app.py

Systemd Service

# Create /etc/systemd/system/blockdag-dashboard.service:
[Unit]
Description=BlockDAG Web Dashboard
After=network-online.target docker.service
Wants=network-online.target

[Service]
WorkingDirectory=/home/ubuntu/blockdag-dashboard
ExecStart=/home/ubuntu/blockdag-dashboard/.venv/bin/python /home/ubuntu/blockdag-dashboard/app.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target

# Enable and Start
sudo systemctl daemon-reload
sudo systemctl enable --now blockdag-dashboard

Now open: http://<VM_IP>:8080

Usage

Default container: blockdag-testnet-network

#Override via query string:

http://<host>:8080/?container=my-node&since=5m&tail=800


# Health endpoints may show “—” if the container doesn’t have curl. Install with:

docker exec -it my-node apt-get update && docker exec -it my-node apt-get install -y curl


# If Docker requires sudo with a password:

sudo usermod -aG docker $USER && newgrp docker

Contributing

Pull requests are welcome!
For major changes, open an issue first to discuss what you’d like to change.

📊 Roadmap

 Recent log preview in UI
 Mini chart of peers/height over time
 Dark/light theme toggle
 Container selection dropdown



