# MeshUpGrade Core Rules

> [!IMPORTANT]
> **RULE #1: MESSAGE LENGTH LIMIT**
> EVERY SINGLE MESSAGE sent by this program MUST be under **200 characters**. This is the highest priority constraint to ensure mesh reliability.

## Task Checklist
- [x] Modern Flet GUI with Navigation [x]
- [x] Core Meshtastic Engine (TCP & Serial) [x]
- [x] DM Context Filtering (Only DMs to node are processed) [x]
- [x] 200 Character Message Enforcement [x]
- [x] Weather Service Plugin (Forecasts & Automated NWS Alerts) [x]
- [x] Signal Testing (SNR/RSSI Auto-Replies) [x]
- [x] Node Status Monitoring (ON/OFF Shortname Sync) [x]
- [x] Reboot Recovery & Adaptive Reconnect (v0.1.2.4) [x]

> [!WARNING]
> **RULE #2: CONTROLLED BROADCASTS ONLY**
> This node prioritizes mesh silence and reliability.
> - NO unsolicited spam or high-volume traffic on public channels.
> - Broadcasts are STRICTLY limited to the configured **Alert Channel** for NWS weather warnings.
> - Minor broadcasts (Node Info Pings) are permitted only during status changes (ON/OFF).
> - All other interaction is strictly via Direct Message (DM) responses.

## Technical Constraints
- **Connectivity**: Native support for WiFi (TCP) and USB Serial.
- **Portability**: Native Python/Flet (Mac, Windows, Linux).
- **Security**: `.gitignore` must protect `settings.json` to prevent leaking IP addresses/Secrets.
- **Open Source**: Code must be clean, documented, and ready for GitHub.
