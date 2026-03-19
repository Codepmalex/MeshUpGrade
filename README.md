# MeshUpGrade v0.3.0

MeshUpGrade is a massive utility-focused autonomous information node for Meshtastic networks. It turns your node into an information-on-demand server, allowing other users on the mesh to query automated services like weather forecasts, active NWS alerts, local Bulletin Boards (BBS), cron-job reminders, and even a two-way SMS-to-Cellular gateway via APRS-IS.

## ✨ Core Purpose
The primary goal of MeshUpGrade is mesh utility. It runs as a background service on your PC/Mac/Linux machine or natively headless via Termux on Android. Once connected to a Meshtastic node, it responds to mesh queries entirely without human intervention!

## ⚙️ Features

- 🤖 **Autonomous Info Node**: Responds to DMs and channel broadcasts with useful system data, signal metrics, and utilities.
- 📱 **APRS-IS SMS Gateway**: Seamlessly route two-way text messages between standard cell phones and off-grid Mesh users! Features an intelligent SMS memory cache (`?L` quick-reply) and an offline spooling `INBOX`.
- 📌 **Local Bulletin Board System (BBS)**: Host localized textual boards with dynamic user subscriptions (`BBS SUB`) and auto-expiring messages (`BBSTX`).
- ⏰ **Background Cron Reminders**: Schedule localized future alerts and string deliveries via the `RMD` scheduler.
- 🌦️ **Weather Integration**: 
  - On-demand forecasts (current, hourly, 5-day).
  - `WXA`: Instantly poll for active, severe National Weather Service alerts!
- 🖥️ **Cross-Platform**: Run the full desktop Flet GUI on Mac/PC or deploy `headless.py` directly onto a Termux Android device for a robust, portable background server.
- 🏷️ **Status Sync**: Automatically updates your node's short name to **ON** when active and forcefully syncs it back to **OFF** when shutting down.

## 🚀 Getting Started

### Prerequisites

- Python 3.9 or higher
- A Meshtastic node with WiFi/TCP or Serial connectivity.

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Codepmalex/MeshUpGrade.git
   cd MeshUpGrade
   ```

2. **Setup virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## 🛠️ Usage

1. **Run the App**:
   ```bash
   # Desktop GUI
   python main.py
   
   # Android / Background Server
   python headless.py
   ```
2. **Connect**: Input your node's IP or Serial port and click **Connect**.
3. **Configure**:
   - Set up your HAM Callsign and APRS Passcode in the "SMS & APRS" tab to unlock cell-phone texting!
   - Configure local BBS boards and expiration limits under the "BBS" tab.

## 📟 Mesh Commands

Users can DM your node (or broadcast on the Command Channel) the following case-insensitive commands:

### Core System
- `HELP`: Displays the global system overview menu.
- `STATUS`: Returns a simple "Node is healthy." ping.
- `UPTIME`: Displays exactly how long the python background server has been actively routing on the network.
- `INBOX`: Fetches and manually flushes any pending messages stored in the node's offline SMS inbox.

### Weather System (NWS Integration)
- `WX` / `WEATHER`: Displays the weather sub-menu.
- `WXA`: Instantly triggers a localized National Weather Service backend poll and returns active structural alerts directly to your radio.
- `WX1` to `WX5`: Various short-term, 5-day, and localized time-specific forecasts.

### Bulletin Board System (BBS)
- `BBS`: Triggers the dynamic group-list and syntax menu.
- `BBSRX <group> [pX]`: Retrieves paginated messages from a targeted board (e.g. `BBSRX group1 p2`).
- `BBSTX <group> [exp<hours>] <msg>`: Posts a customized message directly onto a targeted board (e.g. `BBSTX group1 exp2 I'll be at the park!`). Messages vanish entirely at expiration.
- `BBS SUB <group>`: Subscribes your user ID directly to the specified group, allowing you to intercept delivery notifications anytime a user posts a message. 

### Local Cron Timers
- `RMD` / `REMIND`: Displays cron-job syntax helper menu.
- `RMD HH:MM [YYYY-MM-DD] <msg>`: Schedules a background chron-job that sweeps JSON every 60 seconds and pings you the appended text exactly at that scheduled time.

### SMS Gateway (APRS-IS)
- `?<phonenumber> <msg>`: Binds an active session directly to standard cellular networks and transmits your packet over APRS (e.g. `?15551234567 Hello There!`).
- `?L <msg>`: Utilizes the automatic memory cache to instantly fire a text message back to the absolute last 10-digit cellphone number engaged with your node ID (memory cache expires intelligently after 30 minutes).

## 🤝 Contributing

This project is open to contributions and ideas. Please post any ideas for others to add [here](https://github.com/Codepmalex/MeshUpGrade/discussions/categories/ideas)!

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
