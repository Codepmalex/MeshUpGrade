# MeshUpGrade v0.3.0

MeshUpGrade is a massive utility-focused autonomous information node for Meshtastic networks. It turns your node into an information-on-demand server, allowing other users on the mesh to query automated services like weather forecasts, active NWS alerts, local Bulletin Boards (BBS), cron-job reminders, a two-way SMS-to-Cellular gateway via APRS-IS, and a full **two-way APRS bridge** for licensed ham operators.

## ✨ Core Purpose
The primary goal of MeshUpGrade is mesh utility. It runs as a background service on your PC/Mac/Linux machine or natively headless via Termux on Android. Once connected to a Meshtastic node, it responds to mesh queries entirely without human intervention!

## ⚙️ Features

- 🤖 **Autonomous Info Node**: Responds to DMs and channel broadcasts with useful system data, signal metrics, and utilities.
- 📱 **APRS-IS SMS Gateway**: Seamlessly route two-way text messages between standard cell phones and off-grid Mesh users! Features an intelligent SMS memory cache (`?L` quick-reply) and an offline spooling `INBOX`.
- 📡 **Full Two-Way APRS Bridge** *(Ham License Required)*:
  - Send **APRS messages** to any station on the global APRS-IS network.
  - **Receive APRS messages** from other stations, automatically forwarded to your Meshtastic node as a DM.
  - Share your **live GPS location** to `aprs.fi` on demand or automatically mirror every beacon.
  - **Lookup any station** on `aprs.fi` in real-time with `APRS FIND` — see position, speed, altitude, and last-heard time.
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
- A valid **Ham Radio License** and APRS passcode to use APRS features.

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
   - Set up your HAM Callsign and APRS Passcode in the \"SMS & APRS\" tab to unlock cell-phone texting!
   - Configure local BBS boards and expiration limits under the \"BBS\" tab.

## 📟 Mesh Commands

Users can DM your node (or broadcast on the Command Channel) the following case-insensitive commands:

### Core System
- `HELP`: Displays the global system overview menu.
- `STATUS`: Returns a simple \"Node is healthy.\" ping.
- `UPTIME`: Displays exactly how long the python background server has been actively routing on the network.
- `INBOX`: Fetches and manually flushes any pending messages stored in the node's offline SMS inbox.

### Weather System (NWS Integration)
- `WX` / `WEATHER`: Displays the weather sub-menu.
- `WXA`: Instantly triggers a localized National Weather Service backend poll and returns active structural alerts directly to your radio.
- `WX1` to `WX5`: Various short-term, 5-day, and localized time-specific forecasts.

### Bulletin Board System (BBS)
- `BBS`: Triggers the dynamic group-list and syntax menu.
- `BBSRX <group> [pX]`: Retrieves paginated messages from a targeted board (e.g. `BBSRX group1 p2`)
- `BBSTX <group> [exp<hours>] <msg>`: Posts a customized message directly onto a targeted board. Messages vanish at expiration.
- `BBS SUB <group>`: Subscribes your user ID to the specified group for delivery notifications.

### Local Cron Timers
- `RMD` / `REMIND`: Displays cron-job syntax helper menu.
- `RMD HH:MM [YYYY-MM-DD] <msg>`: Schedules a background chron-job that pings you the text at the scheduled time.

### SMS Gateway (APRS-IS)
- `?<phonenumber> <msg>`: Routes a text message to a standard cell phone via APRS-IS (e.g. `?15551234567 Hello There!`).
- `?L <msg>`: Quick-replies to the last number engaged with your node (memory expires after 30 mins).

### 📡 APRS Gateway *(Ham License Required)*
Send `APRS` to see the full submenu. Key commands:

- `APRS SETUP`: Interactive wizard to link your APRS passcode, SSID suffix, and map icon.
- `APRS ON` / `APRS OFF`: Enable or disable your APRS profile.
- `APRS <callsign> <msg>`: Send a direct APRS message to any station globally (e.g. `APRS W1AW-9 Hello from Mesh!`).
- `APRS LOCATION`: Immediately publish your current GPS position to `aprs.fi`.
- `APRS AUTO LOCATION ON/OFF`: Automatically mirror every GPS beacon from your Meshtastic node to `aprs.fi`.
- `APRS FIND <callsign>`: 🔍 **Look up any ham station on `aprs.fi`** and get their last-known position, speed, altitude, and status comment delivered directly to your radio (e.g. `APRS FIND W1AW`).

> **Note**: Incoming APRS messages addressed to your registered callsign are automatically intercepted by the background daemon and forwarded to your Meshtastic node as a DM. No extra configuration needed!

### 🛰️ Satellite Tracker
Send `SAT` to see the sub-menu. No account or API key needed!

- `SAT ISS` : Live ISS position, altitude, speed and daylight status — updated in real time.
- `SAT PASS` : Next predicted ISS pass window over your configured location (±10 min estimate via orbital model).
- `SAT CREW` : Who is currently aboard the ISS.

> The ISS also carries an amateur radio transceiver (NA1SS / RS0ISS) — ham operators can make contact during a pass!

## 🤝 Contributing

This project is open to contributions and ideas. Please post any ideas for others to add [here](https://github.com/Codepmalex/MeshUpGrade/discussions/categories/ideas)!

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

