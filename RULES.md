# MeshUpGrade Core Rules

> [!IMPORTANT]
> **RULE #1: MESSAGE LENGTH LIMIT**
> EVERY SINGLE MESSAGE sent by this program MUST be under **200 characters**. This is the highest priority constraint to ensure mesh reliability.

## Task Checklist
- [x] Brainstorm features and architecture [x]
- [x] Create Implementation Plan [x]
- [ ] Ensure cross-platform compatibility [/]
- [ ] Setup Project Structure [/]
- [ ] Implement Core Meshtastic Connection (TCP/Serial/BT) [ ]
- [ ] Implement Message Handling Logic (DM only, 200 char limit) [ ]
- [ ] Develop Admin Mode (Security, 5 tries, cooldown) [ ]
- [ ] Develop Plugin System for Information Provision [ ]

> [!WARNING]
> **RULE #2: NO BROADCASTS**
> This node is for private, information-on-demand services only.
> - NO messages shall be broadcasted to `LongFast` (or any public channel).
> - NO messages shall be sent as unsolicited broadcasts.
> - Communication is strictly via Direct Message (DM) responses.

## Technical Constraints
- **Connectivity**: Support for WiFi (TCP), Serial, and Bluetooth.
- **Portability**: Must run on Mac, Windows, and Linux.
- **Open Source**: Code must be clean, documented, and ready for GitHub.

## Admin Mode Security
- **Auth**: Passcode-based authentication via DM.
- **Protection**: Max 5 attempts before a configurable cooldown.
- **Configurable**: Passcode and cooldown period editable via GUI.
