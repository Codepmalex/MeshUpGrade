# MeshUpGrade v0.1.2.4

# READ THIS BEFORE READING THE REST!!!!!!!!!
Human here, TLDR I basically vibe coded the shittt out of this so I don't knwo if thats against the rules here (Take it down if it is ill be happy vibing lol) or whatever but I'm too lazy to write code or even a proper readme so please bear with me. 
I wanted to create this because I have absolutley no node friends so I guess a program is better than humans (what has this world come to)
I am planning to add an AI funtction soon but thats pretty low on the list. I don't want this program to be ai-focused (oh the irony) but soon I do want to add an ai funtction.
Lastly I know Meshtastic has a bit of a stringe licencing thing so please if I'm doing anything wrong don't sue or some crap just submit a takedown request and have this project shut down by github and I might fix it. Anyways thank you for reading this far and I hope you enjoy my project!

Oh and by the way this is BETABETABETA its SO BETA so please expect the worst.

## Description
MeshUpGrade is a (not so) modern, cross-platform GUI and plugin engine for Meshtastic nodes. It allows users to monitor their mesh network, configure weather alerts, and provide automated services (like weather forecasts and signal testing) to other nodes via DMs and specific channels.

## ✨ Features

- 🖥️ **Modern GUI**: Built with Flet for a smooth, responsive desktop experience.
- 🌦️ **Weather Plugin**: 
  - Automated forecasts (current, hourly, 5-day).
  - NWS Alert Monitoring: Automatically broadcasts local weather alerts to a specified channel.
  - Shortcut commands (WX1-WX5) for quick mesh interaction.
- 📡 **Signal Testing**: Automatically reply to unknown DMs with SNR and RSSI data (Toggleable).
- 🔄 **Channel Command Routing**: Process mesh-wide broadcasts on a specific channel as if they were DMs.
- 🔒 **Security**: Built-in 200-character enforcement for all outgoing mesh messages.
- 💾 **Persistence**: Automatically saves your settings, IP addresses, and preferences.
- 🏷️ **Node Status Sync**: Automatically change your node's short name to **ON** when the app is running and **OFF** when it closes (Toggleable).

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
   - Set your **Backup Location** (Lat/Lon) in the Weather tab for accurate NWS/Meteo data.
   - Pick an **Alert Channel** to broadcast NWS warnings to your mesh.
   - Choose a **Command Channel** to allow public mesh commands (e.g., "WEATHER").

## 🌦️ Mesh Commands

Users can DM your node (or broadcast on the Command Channel) the following:

- `WEATHER`: Shows the weather menu.
- `WX1`: 5-Day Concise Forecast.
- `WX2`: 5-Hour Forecast.
- `WX3`: General Written Forecast.
- `WX4 YYYY-MM-DD`: Custom date forecast.
- `WX5 HH:MM`: Custom hour forecast (Today).
- `HELP`: Shows the help menu.
- Any other message: Replies with Signal Strength (SNR/RSSI) if Signal Test is enabled.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
