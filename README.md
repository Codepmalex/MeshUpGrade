# MeshUpGrade v0.1.2.5

MeshUpGrade is a utility-focused autonomous information node for Meshtastic networks. It turns your node into an information-on-demand server, allowing other users on the mesh to query automated services like weather forecasts and signal testing via DMs and specific channels.

## ✨ Core Purpose
The primary goal of MeshUpGrade is mesh utility. It runs as a background service on your PC/Mac/Linux machine, connected to a Meshtastic node, and responds to mesh queries without human intervention.

## ⚙️ Features

- 🤖 **Autonomous Info Node**: Responds to DMs and channel broadcasts with useful data.
- 🌦️ **Weather Plugin (Autonomous)**: 
  - On-demand forecasts (current, hourly, 5-day) triggered by mesh commands.
  - Automated NWS Alert Monitoring: Identifies local weather warnings and broadcasts them to a specified channel.
- 📡 **Signal Testing Service**: Automatically replies to mesh pings/DMs with SNR and RSSI data to help others test their link.
- 🔄 **Channel Command Routing**: Bridges public channel broadcasts to the autonomous engine.
- 🖥️ **Configuration GUI**: A simple Flet-based interface for easy setup of IP addresses, ports, and plugin preferences.
- 🔒 **Security**: Built-in 200-character enforcement for all outgoing mesh messages.
- 💾 **Persistence**: Automatically saves connection parameters and preferences.
- 🏷️ **Node Status Sync**: Automatically sets node short name to **ON** when active and **OFF** when shutting down.

## 🛠️ Future Features (Roadmap)
MeshUpGrade is constantly evolving. Please post any ideas for others to add [here](https://github.com/Codepmalex/MeshUpGrade/discussions/1)!

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

1. **Run the app**:
   ```bash
   python main.py
   ```
2. **Connect**: Input your node's IP address and click **Connect**.
3. **Configure**:
   - Set your **Backup Location** (Lat/Lon) in the Weather tab for NWS/Meteo data.
   - Pick an **Alert Channel** to broadcast NWS warnings.
   - Pick a **Command Channel** for public interaction (e.g., "WEATHER").

## 🌦️ Mesh Commands

Users can DM your node (or broadcast on the Command Channel) the following:

- `WEATHER`: Shows the autonomous weather menu.
- `WX1`: 5-Day Concise Forecast.
- `WX2`: 5-Hour Forecast.
- `WX3`: General Written Forecast.
- `WX4 YYYY-MM-DD`: Custom date forecast.
- `WX5 HH:MM`: Custom hour forecast (Today).
- `HELP`: Shows the help menu.
- Any other message: Replies with Signal Strength (SNR/RSSI) if Signal Test is enabled.

## 🤝 Contributing

This project is open to contributions and ideas. Please post any ideas for others to add [here](https://github.com/Codepmalex/MeshUpGrade/discussions/1)! Also, feel free to fork and modify the project for your own needs.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
