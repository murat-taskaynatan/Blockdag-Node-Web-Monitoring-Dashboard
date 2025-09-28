# BlockDAG Web Dashboard

A lightweight Flask-based web dashboard for monitoring BlockDAG testnet or mainnet nodes inside Docker.  
It auto-detects whether `docker` or `sudo docker` is needed, fetches health endpoints, tails logs, and parses node status in real time.



<img width="996" height="624" alt="image" src="https://github.com/user-attachments/assets/db5c5324-a0a3-4062-8506-305919dbefc7" />

---

## 🚀 Features
- **Docker auto-detect** → Works with `docker` or `sudo docker -n`
- **Node health checks** → Calls `/readyz` and `/healthz` inside the container
- **Live metrics** → Displays peers, height, hashrate, and last log timestamp
- **Status detection** → Shows `✅ Healthy`, `⏳ Syncing`, `🔗 Connected`, or `❌ Error` based on logs + endpoints
- **Responsive UI** → Card-based layout with colored status pills and auto-refresh every 10s
- **Configurable** → Change container, `--since`, and `--tail` via the UI or query string

---

## 📦 Installation

### 1. Clone the repo
```bash
git clone https://github.com/<your-username>/blockdag-dashboard.git
cd blockdag-dashboard
### 1. Clone the repo

git clone https://github.com/<your-username>/blockdag-dashboard.git
cd blockdag-dashboard
2. Install dependencies (venv recommended)
bash
Copy code
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv

python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
▶️ Running
Local run
bash
Copy code
./.venv/bin/python app.py
Open: http://localhost:8080

Systemd service
Create /etc/systemd/system/blockdag-dashboard.service:



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
Enable + start:


sudo systemctl daemon-reload
sudo systemctl enable --now blockdag-dashboard
Now visit http://<VM_IP>:8080.

⚙️ Usage
Default container: blockdag-testnet-network

Override via query string:


http://<host>:8080/?container=my-node&since=5m&tail=800
Health endpoints may show “—” if the container doesn’t have curl. Install with:


docker exec -it my-node apt-get update && docker exec -it my-node apt-get install -y curl
If Docker requires sudo with a password:


sudo usermod -aG docker $USER && newgrp docker
📊 Roadmap
 Recent log preview in UI

 Mini chart of peers/height over time

 Dark/light theme toggle

 Container selection dropdown

🤝 Contributing
Pull requests are welcome! Please open an issue first for major changes.


docker exec -it my-node apt-get update && docker exec -it my-node apt-get install -y curl
