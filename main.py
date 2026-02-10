import flet as ft
import logging
import os
import sys
import threading
import time
from datetime import datetime
from engine import MeshEngine

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GuiLogHandler(logging.Handler):
    def __init__(self, log_list, page):
        super().__init__()
        self.log_list = log_list
        self.page = page

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_list.controls.append(ft.Text(msg, font_family="monospace", size=12))
            if len(self.log_list.controls) > 100:
                self.log_list.controls.pop(0)
            self.page.update()
        except Exception:
            # Page likely closed/destroyed
            pass

import json

SETTINGS_FILE = "settings.json"

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

from weather import WeatherPlugin

def main(page: ft.Page):
    page.title = "MeshUpGrade"
    page.padding = 20
    
    settings = load_settings()
    engine = MeshEngine()
    
    # Weather Settings
    lat_field = ft.TextField(label="Backup Latitude", value=settings.get("lat", "40.7128"), width=150)
    lon_field = ft.TextField(label="Backup Longitude", value=settings.get("lon", "-74.0060"), width=150)
    unit_picker = ft.Dropdown(
        label="Temperature Units",
        value=settings.get("unit", "F"),
        options=[ft.dropdown.Option("F", "Fahrenheit"), ft.dropdown.Option("C", "Celsius")],
        width=200
    )
    use_node_gps = ft.Switch(label="Use Sender's Node GPS (if available)", value=settings.get("use_gps", True))
    sync_shortname = ft.Switch(label="Sync Node Shortname with Status (ON/OFF)", value=settings.get("sync_shortname", False))
    sync_ping = ft.Switch(label="Broadcast Node Info after Status Change", value=settings.get("sync_ping", False))

    def get_location(sender_id):
        if use_node_gps.value and engine.interface:
            node = engine.interface.nodes.get(sender_id)
            if node and 'position' in node:
                pos = node['position']
                if 'latitude' in pos and 'longitude' in pos:
                    logging.info(f"Using GPS from node {sender_id}: {pos['latitude']}, {pos['longitude']}")
                    return pos['latitude'], pos['longitude']
        logging.info(f"Using backup location: {lat_field.value}, {lon_field.value}")
        return float(lat_field.value), float(lon_field.value)

    # Log Terminal Component
    log_terminal = ft.Column(scroll=ft.ScrollMode.ALWAYS, height=400, expand=True)
    gui_handler = GuiLogHandler(log_terminal, page)
    gui_handler.setFormatter(logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S'))
    logging.getLogger().addHandler(gui_handler)

    def send_reply(sender, text, channel_index=None):
        if channel_index is not None:
            engine.send_broadcast(text, channel_index=channel_index)
        else:
            engine.send_dm(sender, text)

    def process_command(msg, sender, packet, channel_index=None):
        # Help Menu handling
        if msg == "/HELP" or msg == "HELP":
            menu = "--Help Menu--\nDM me the following:\nWeather\n(Other features will be added later)"
            send_reply(sender, menu, channel_index)
            return

        if msg == "/STATUS":
            send_reply(sender, "Node is healthy.", channel_index)
            return

        # Weather handling (Publicly available commands)
        if msg == "WEATHER":
            menu = "-WX Menu-\nReply (eg. WX1, WX2)\nWX1-5dayforecast\nWX2-HRLYforecast\nWX3-GenForecast\nWX4-CustomFC\nWX5-HrlyCustom"
            send_reply(sender, menu, channel_index)
            return
        
        if msg.startswith("WX"):
            try:
                lat, lon = get_location(sender)
                wx = WeatherPlugin(lat, lon, unit=unit_picker.value)
                response = None
                if msg == "WX1": response = wx.format_wx1()
                elif msg == "WX2": response = wx.format_wx2()
                elif msg == "WX3": response = wx.format_wx3()
                elif msg == "WX4" or msg.startswith("WX4"):
                    date_str = msg.replace("WX4", "").strip()
                    response = wx.format_wx4(date_str)
                    if response is None:
                        response = "No Date, please insert date\n(Format- WX4 YYYY-MM-DD)\n(for example, WX4 2026-03-09)"
                elif msg == "WX5" or msg.startswith("WX5"):
                    time_str = msg.replace("WX5", "").strip()
                    response = wx.format_wx5(time_str)
                    if response is None:
                        response = "No Time, please insert time\n(Format- WX5 HH:MM)\n(for example, WX5 14:00)"
                
                if response:
                    send_reply(sender, response, channel_index)
            except Exception as e:
                logging.error(f"Error processing WX command: {e}")
                send_reply(sender, "Error processing weather request.", channel_index)
            return

        if use_signal_test.value:
            snr = packet.get('rxSnr', 'N/A')
            rssi = packet.get('rxRssi', 'N/A')
            resp = f"RXxed!\nSNR is {snr}\nRSSI is {rssi}"
            send_reply(sender, resp, channel_index)
        else:
            send_reply(sender, "Unknown command. DM 'help' for options.", channel_index)


    def on_message_received(packet):
        if 'decoded' in packet and packet['decoded'].get('portnum') == 'TEXT_MESSAGE_APP':
            msg = packet['decoded']['payload'].decode('utf-8').strip().upper()
            sender = packet['fromId']
            if packet.get('toId') != '^all':
                logging.info(f"DM from {sender}: {msg}")
                process_command(msg, sender, packet)
            else:
                # Handle Broadcasts on the Command Channel
                cmd_chan_idx = int(settings.get("cmd_channel", -1))
                if packet.get('channel') == cmd_chan_idx and cmd_chan_idx != -1:
                    logging.info(f"Command Channel broadcast from {sender}: {msg}")
                    process_command(msg, sender, packet, channel_index=cmd_chan_idx)
                else:
                    logging.info(f"Ignored broadcast from {sender}")

    engine.callback_on_message = on_message_received

    # Weather Alert Settings
    use_alerts = ft.Switch(label="Enable Weather Alerts (NWS)", value=settings.get("use_alerts", False))
    alert_channel = ft.Dropdown(
        label="Alert Channel",
        value=str(settings.get("alert_channel", "0")),
        options=[ft.dropdown.Option("0", "Primary (Index 0)")],
        width=250
    )
    alert_warning = ft.Text("⚠️ WARNING: Broadcasting on Channel 0 (LongFast) is highly discouraged and may result in a ban from some meshes.", color="red", visible=False)
    
    test_alert_field = ft.TextField(label="Test Alert Message", value="Test Weather Alert!", width=250)
    
    last_alert_ids = set()

    def update_channels_list():
        if engine.interface:
            chans = engine.get_channels()
            options = [ft.dropdown.Option(str(c['index']), f"Idx {c['index']}: {c['name']}") for c in chans]
            alert_channel.options = options
            cmd_channel.options = [ft.dropdown.Option("-1", "None (DM Only)")] + options
            page.update()

    def check_alerts():
        if not use_alerts.value or not engine.is_connected:
            threading.Timer(600, check_alerts).start()
            return
            
        logging.info("Checking for weather alerts...")
        lat, lon = float(lat_field.value), float(lon_field.value)
        wx = WeatherPlugin(lat, lon, unit=unit_picker.value)
        alerts = wx.get_alerts()
        
        for alert in alerts:
            aid = alert['id']
            if aid not in last_alert_ids:
                last_alert_ids.add(aid)
                # Meshtastic Alert Bell \a
                msg = f"\a⚠️ WX ALERT: {alert['event']} - {alert['severity']}\n{alert['headline']}"
                logging.info(f"Broadcasting Alert: {alert['event']}")
                engine.send_broadcast(msg, channel_index=int(alert_channel.value))
                # 7-second cooldown between multiple alerts to prevent packet loss
                time.sleep(7)
        
        threading.Timer(600, check_alerts).start()

    # Start monitor
    threading.Timer(10, check_alerts).start()

    def send_test_alert_click(e):
        msg = f"\a⚠️ WX TEST: {test_alert_field.value}"
        logging.info(f"Sending test broadcast on channel {alert_channel.value}")
        engine.send_broadcast(msg, channel_index=int(alert_channel.value))

    def alert_channel_change(e):
        alert_warning.visible = (alert_channel.value == "0")
        page.update()

    alert_channel.on_change = alert_channel_change

    # Command Routing Settings
    cmd_channel = ft.Dropdown(
        label="Command Channel (Broadcasts)",
        value=str(settings.get("cmd_channel", "-1")),
        options=[ft.dropdown.Option("-1", "None (DM Only)")],
        width=250
    )
    cmd_warning = ft.Text("⚠️ WARNING: Command channel cannot be the same as the Alert channel.", color="red", visible=False)

    def cmd_channel_change(e):
        if cmd_channel.value != "-1" and cmd_channel.value == alert_channel.value:
            cmd_warning.visible = True
        else:
            cmd_warning.visible = False
        page.update()

    cmd_channel.on_change = cmd_channel_change

    # UI Components
    status_text = ft.Text("Status: Disconnected")
    ip_address = ft.TextField(label="IP Address", value=settings.get("ip", "192.168.1.50"), width=200)
    serial_port = ft.TextField(label="Serial Port (Auto or /dev/...) ", value=settings.get("serial_port", ""), width=200)
    
    def reboot_recovery_task(short_name, was_planned=True):
        engine.last_short_name = short_name
        
        if was_planned:
            # Check if name already matches
            try:
                current_name = engine.interface.getShortName()
                if current_name == short_name:
                    logging.info(f"Node already named {short_name}. Skipping reboot.")
                    status_text.value = f"Status: Connected ({engine.last_conn_type.upper()}) - Already Optimized"
                    page.update()
                    return
            except:
                pass

            # 1-second settle time as requested
            logging.info(f"Interface settle window (1s) before {short_name} command...")
            time.sleep(1)
            
            if not engine.set_short_name(short_name):
                logging.error(f"Failed to set short name to {short_name}")
                return

            logging.info(f"Node rebooting for name change to {short_name}. Waiting 40s...")
            status_text.value = f"Status: Rebooting to {short_name} (40s)..."
            page.update()
            
            time.sleep(40)
        
        logging.info("Attempting to reconnect...")
        status_text.value = "Status: Reconnecting..."
        page.update()
        
        if engine.reconnect():
            logging.info("Reconnected successfully. Sending node info broadcast.")
            engine.send_node_info(short_name=short_name)
            status_text.value = f"Status: Connected ({engine.last_conn_type.upper()}) - Sync OK"
        else:
            logging.warning(f"Initial reconnect failed. Searching network for '{short_name}'...")
            status_text.value = f"Status: Searching network for {short_name}..."
            page.update()
            
            if engine.discover_node(short_name):
                logging.info(f"Node found and reconnected via Discovery! Sending info broadcast.")
                engine.send_node_info(short_name=short_name)
                status_text.value = f"Status: Connected (ADAPTIVE) - Sync OK"
            else:
                logging.error("Discovery failed. Node not found on subnet.")
                status_text.value = "Status: Reconnect Failed (Not Found)"
        page.update()

    def connect_tcp_click(e):
        success = engine.connect_tcp(ip_address.value)
        status_text.value = f"Status: {'Connected (TCP)' if success else 'Failed'}"
        if success:
            settings["ip"] = ip_address.value
            save_settings(settings)
            update_channels_list()
            if sync_shortname.value:
                threading.Thread(target=reboot_recovery_task, args=("ON", True), daemon=True).start()
        page.update()

    def connect_serial_click(e):
        port = serial_port.value.strip() if serial_port.value.strip() else None
        success = engine.connect_serial(port)
        status_text.value = f"Status: {'Connected (Serial)' if success else 'Failed'}"
        if success:
            settings["serial_port"] = serial_port.value
            save_settings(settings)
            update_channels_list()
            if sync_shortname.value:
                threading.Thread(target=reboot_recovery_task, args=("ON", True), daemon=True).start()
        page.update()

    def update_settings_click(e):
        settings.update({
            "lat": lat_field.value,
            "lon": lon_field.value,
            "unit": unit_picker.value,
            "use_gps": use_node_gps.value,
            "sync_shortname": sync_shortname.value,
            "sync_ping": sync_ping.value,
            "ip": ip_address.value,
            "serial_port": serial_port.value,
            "use_alerts": use_alerts.value,
            "alert_channel": int(alert_channel.value),
            "use_signal_test": use_signal_test.value,
            "cmd_channel": int(cmd_channel.value)
        })
        save_settings(settings)
        logging.info("Settings saved.")
        page.update()

    # Signal Test Toggle
    use_signal_test = ft.Switch(label="Signal Test (Auto-reply SNR/RSSI)", value=settings.get("use_signal_test", True))

    # View Switcher
    content_area = ft.Column(expand=True, scroll=ft.ScrollMode.ADAPTIVE)

    def show_connection(e):
        content_area.controls = [
            ft.Text("Connection", size=20),
            ft.Text("WiFi / TCP:", size=16, weight="bold"),
            ft.Text("Tip: Use 'node-name.local' to survive IP changes.", size=12, italic=True),
            ft.Row([ip_address, ft.ElevatedButton("Connect TCP", on_click=connect_tcp_click)]),
            ft.Divider(),
            ft.Text("USB / Serial:", size=16, weight="bold"),
            ft.Row([serial_port, ft.ElevatedButton("Connect Serial", on_click=connect_serial_click)]),
            ft.Divider(),
            status_text,
            ft.Divider(),
            ft.Text("Command Routing", size=18),
            cmd_channel,
            cmd_warning,
            ft.Divider(),
            ft.Text("Features", size=18),
            use_signal_test,
            sync_shortname,
            sync_ping,
            ft.Divider(),
            ft.Row([
                ft.ElevatedButton("Save Settings", on_click=update_settings_click),
                ft.ElevatedButton("End Program & Logout", on_click=lambda _: shutdown_app(), color="red"),
            ]),
        ]
        page.update()


    def show_weather(e):
        content_area.controls = [
            ft.Text("Weather Configuration", size=20),
            use_node_gps,
            ft.Text("Backup Location (if GPS unavailable):"),
            ft.Row([lat_field, lon_field]),
            unit_picker,
            ft.Divider(),
            ft.Text("Weather Alerts (Broadcasts)", size=18),
            use_alerts,
            alert_channel,
            alert_warning,
            ft.Row([test_alert_field, ft.ElevatedButton("Test Broadcast", on_click=send_test_alert_click)]),
            ft.ElevatedButton("Save Settings", on_click=update_settings_click),
        ]
        page.update()

    def show_terminal(e):
        content_area.controls = [
            ft.Text("Terminal", size=20),
            ft.Container(content=log_terminal, border=ft.border.all(1, "grey400"), padding=10, border_radius=5),
        ]
        page.update()

    nav_row = ft.Row([
        ft.ElevatedButton("Connection", on_click=show_connection),
        ft.ElevatedButton("Weather", on_click=show_weather),
        ft.ElevatedButton("Terminal", on_click=show_terminal),
    ])

    def shutdown_app():
        logging.info("Shutting down MeshUpGrade...")
        
        # Show a non-closable dialog to prevent further interaction
        shutdown_dialog = ft.AlertDialog(
            title=ft.Text("Shutting Down"),
            content=ft.Text("Performing final mesh sync (OFF status)...\nThis may take up to 45 seconds."),
            modal=True
        )
        page.dialog = shutdown_dialog
        shutdown_dialog.open = True
        page.update()

        def perform_shutdown_sync():
            try:
                if sync_shortname.value and engine.is_connected:
                    # Smart Sync check
                    try:
                        if engine.interface.getShortName() == "OFF":
                            logging.info("Node already named OFF. Skipping final reboot sync.")
                            engine.close()
                            os._exit(0)
                    except:
                        pass
                        
                    logging.info("Updating short name to OFF before logout...")
                    # Settle before command
                    time.sleep(1)
                    engine.set_short_name("OFF")
                    
                    if sync_ping.value:
                        logging.info("Waiting 40s for node reboot before final broadcast...")
                        # 40s wait while node reboots
                        time.sleep(40)
                        
                        if not engine.reconnect():
                            logging.info("IP may have changed. Attempting discovery for final broadcast...")
                            engine.discover_node("OFF")
                        
                        if engine.is_connected:
                            engine.send_node_info(short_name="OFF")
                        time.sleep(2) # Final buffer
                
                engine.close()
            except Exception as e:
                logging.debug(f"Shutdown sync error (suppressed): {e}")
            finally:
                # Hard exit
                os._exit(0)

        # Start shutdown sync in a background daemon thread
        threading.Thread(target=perform_shutdown_sync, daemon=True).start()

    def connection_watchdog():
        """Monitors connection and auto-reconnects if peer resets."""
        while True:
            time.sleep(30)
            # Only trigger if we WERE connected before (params exist) but aren't now
            if engine.last_conn_params and not engine.is_connected:
                # Avoid triggering if we are already in the middle of a recovery
                if status_text.value and "Rebooting" in status_text.value:
                    continue
                    
                logging.warning("Connection watchdog detected unexpected drop. Triggering recovery...")
                target_name = engine.last_short_name if engine.last_short_name else "ON"
                
                # For watchdog drops, skip the initial name-change wait (was_planned=False)
                threading.Thread(target=reboot_recovery_task, args=(target_name, False), daemon=True).start()

    # Start the watchdog
    threading.Thread(target=connection_watchdog, daemon=True).start()

    show_connection(None)
    page.add(nav_row, ft.Divider(), content_area)
    page.on_close = shutdown_app

if __name__ == "__main__":
    ft.app(target=main)
