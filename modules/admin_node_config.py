#!/usr/bin/env python3
# Node Settings sub-tabs with Meshtastic Companion-app parity: every Config / ModuleConfig
# section of the local node, owner, canned messages, ringtone and admin actions via Admin API.

from __future__ import annotations

import base64
import html
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from google.protobuf.descriptor import Descriptor, FieldDescriptor
from google.protobuf.message import Message

# lora.tx_power: no hard cap in Hessenbot (hardware/firmware limit applies); above the EU-safe level the admin must confirm.
TX_POWER_EU_SAFE_DBM = 14
TX_POWER_MAX_DBM = 30

TX_POWER_WARNING_TEXT = (
    f"Werte über {TX_POWER_EU_SAFE_DBM} dBm können die EU-868-Grenzwerte überschreiten "
    "(je nach Teilband 14 bzw. 27 dBm ERP, 1–10 % Duty Cycle). Mit einem PA-Modul (z. B. RAK13302, "
    "SKY66122, ca. +13 dB) liegt die Leistung an der Antenne deutlich über dem Einstellwert. "
    "Du bist selbst für die Einhaltung der Vorschriften verantwortlich; es wird nichts still begrenzt."
)

MESH_PARAMS_WARNING = (
    "Region, Preset, Frequenz-Slot und Modem-Parameter müssen im ganzen Mesh gleich sein — "
    "sonst ist die Node (und der Bot) vom Meshhessen-Netz getrennt. Das Gerät startet nach dem Speichern neu."
)
REGION_WARNING = (
    "Die Region muss zum Standort passen (Deutschland: EU_868). Eine falsche Region bedeutet "
    "unzulässigen Funkbetrieb und keinen Kontakt zum Mesh. " + MESH_PARAMS_WARNING
)
CONNECTION_WARNING = (
    "Ist der Bot über genau diese Verbindung mit der Node verbunden, bricht die Verbindung ab "
    "und der Bot kann die Node erst nach manuellem Eingriff wieder erreichen."
)

CONFIRM_VALUES = ("1", "on", "yes", "true")
FACTORY_RESET_WORD = "RESET"

_UINT32_MAX = 2**32 - 1
_INT32_MIN, _INT32_MAX = -(2**31), 2**31 - 1
_UINT64_MAX = 2**64 - 1


# --- Tab layout (Companion: Radio configuration / Module configuration / Administration) ---


@dataclass(frozen=True)
class TabSpec:
    key: str
    label: str
    group: str  # "radio" | "module" | "admin"
    kind: str  # "config" | "module" | "special"
    section: str = ""
    excluded_flag: str = ""
    intro: str = ""


TAB_GROUP_LABELS: Dict[str, str] = {
    "radio": "Radio-Konfiguration",
    "module": "Module",
    "admin": "Administration",
}

TABS: Tuple[TabSpec, ...] = (
    TabSpec("overview", "Übersicht", "radio", "special",
            intro="Name, Rolle, Intervalle und feste Position (Bot-Schnellzugriff)."),
    TabSpec("user", "Benutzer", "radio", "special",
            intro="Owner-Daten der Node (wie Companion → Benutzer)."),
    TabSpec("channels", "Kanäle", "radio", "special"),
    TabSpec("device", "Gerät", "radio", "config", "device"),
    TabSpec("position", "Position", "radio", "config", "position",
            intro="Feste Koordinaten setzt du im Tab Übersicht (Bot ohne GPS)."),
    TabSpec("power", "Energie", "radio", "config", "power"),
    TabSpec("network", "Netzwerk", "radio", "config", "network", "NETWORK_CONFIG"),
    TabSpec("display", "Display", "radio", "config", "display"),
    TabSpec("lora", "LoRa", "radio", "config", "lora"),
    TabSpec("bluetooth", "Bluetooth", "radio", "config", "bluetooth", "BLUETOOTH_CONFIG"),
    TabSpec("security", "Sicherheit", "radio", "config", "security"),
    TabSpec("mqtt", "MQTT", "module", "module", "mqtt", "MQTT_CONFIG"),
    TabSpec("serial", "Seriell", "module", "module", "serial", "SERIAL_CONFIG"),
    TabSpec("external_notification", "Ext. Benachrichtigung", "module", "module",
            "external_notification", "EXTNOTIF_CONFIG"),
    TabSpec("store_forward", "Store & Forward", "module", "module", "store_forward", "STOREFORWARD_CONFIG"),
    TabSpec("range_test", "Range Test", "module", "module", "range_test", "RANGETEST_CONFIG"),
    TabSpec("telemetry", "Telemetrie", "module", "module", "telemetry", "TELEMETRY_CONFIG"),
    TabSpec("canned_message", "Canned Messages", "module", "module", "canned_message", "CANNEDMSG_CONFIG"),
    TabSpec("audio", "Audio", "module", "module", "audio", "AUDIO_CONFIG"),
    TabSpec("remote_hardware", "Remote Hardware", "module", "module", "remote_hardware",
            "REMOTEHARDWARE_CONFIG"),
    TabSpec("neighbor_info", "Neighbor Info", "module", "module", "neighbor_info", "NEIGHBORINFO_CONFIG"),
    TabSpec("ambient_lighting", "Umgebungslicht", "module", "module", "ambient_lighting",
            "AMBIENTLIGHTING_CONFIG"),
    TabSpec("detection_sensor", "Detection Sensor", "module", "module", "detection_sensor",
            "DETECTIONSENSOR_CONFIG"),
    TabSpec("paxcounter", "Paxcounter", "module", "module", "paxcounter", "PAXCOUNTER_CONFIG"),
    TabSpec("statusmessage", "Statusnachricht", "module", "module", "statusmessage"),
    TabSpec("traffic_management", "Traffic Management", "module", "module", "traffic_management"),
    TabSpec("tak", "TAK", "module", "module", "tak"),
    TabSpec("admin", "Administration", "admin", "special",
            intro="Neustart, Herunterfahren, NodeDB- und Werksreset, Uhrzeit."),
)

DEFAULT_TAB = "overview"


def _local_config_descriptor() -> Descriptor:
    from meshtastic.protobuf import localonly_pb2

    return localonly_pb2.LocalConfig.DESCRIPTOR


def _local_module_descriptor() -> Descriptor:
    from meshtastic.protobuf import localonly_pb2

    return localonly_pb2.LocalModuleConfig.DESCRIPTOR


def _section_names(kind: str) -> List[str]:
    desc = _local_config_descriptor() if kind == "config" else _local_module_descriptor()
    return [f.name for f in desc.fields if f.type == FieldDescriptor.TYPE_MESSAGE]


def available_tabs() -> List[TabSpec]:
    """Tabs for the installed meshtastic protobufs; unknown future sections are appended generically."""
    known_cfg = set(_section_names("config"))
    known_mod = set(_section_names("module"))
    out: List[TabSpec] = []
    listed = set()
    for spec in TABS:
        if spec.kind == "config" and spec.section not in known_cfg:
            continue
        if spec.kind == "module" and spec.section not in known_mod:
            continue
        out.append(spec)
        listed.add((spec.kind, spec.section))
    admin_tab = out.pop()  # keep Administration last
    for kind, names, group in (("config", known_cfg, "radio"), ("module", known_mod, "module")):
        for name in sorted(names):
            if (kind, name) not in listed:
                out.append(TabSpec(name, name, group, kind, name))
    out.append(admin_tab)
    return out


def tab_by_key(key: Optional[str]) -> TabSpec:
    tabs = available_tabs()
    for spec in tabs:
        if spec.key == (key or "").strip():
            return spec
    return tabs[0]


# --- Field metadata (German labels, ranges, warnings) ---


@dataclass(frozen=True)
class FieldMeta:
    label: str
    help: str = ""
    unit: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    maxlen: Optional[int] = None
    max_items: Optional[int] = None
    widget: str = ""  # bitmask | ip | nodelist | b64list | secret | secret_b64 | pins | readonly_b64
    flags_enum: str = ""  # enum path for bitmask widgets
    danger: str = ""
    danger_when: Optional[Callable[[Any, Any], bool]] = None
    readonly: bool = False


def _changed(old: Any, new: Any) -> bool:
    return old != new


def _turned_on(old: Any, new: Any) -> bool:
    return bool(new) and not bool(old)


def _turned_off(old: Any, new: Any) -> bool:
    return bool(old) and not bool(new)


def _tx_power_needs_confirm(old: Any, new: Any) -> bool:
    return int(new) != int(old) and int(new) > TX_POWER_EU_SAFE_DBM


_ROUTER_ROLES = {2, 3, 4, 11}


def _router_role(old: Any, new: Any) -> bool:
    return int(new) != int(old) and int(new) in _ROUTER_ROLES


S = "s"
MS = "ms"

FIELD_META: Dict[str, FieldMeta] = {
    # Config.DeviceConfig
    "device.role": FieldMeta(
        "Rolle", "CLIENT ist Standard. Router-Rollen nur an exponierten Standorten und nach Absprache.",
        danger="Router-/Repeater-Rollen leiten aggressiver weiter und verändern das Verhalten des ganzen Mesh.",
        danger_when=_router_role),
    "device.serial_enabled": FieldMeta("Serielle Konsole (veraltet, siehe Sicherheit)"),
    "device.button_gpio": FieldMeta("GPIO Taster", "0 = Board-Standard"),
    "device.buzzer_gpio": FieldMeta("GPIO Buzzer", "0 = Board-Standard"),
    "device.rebroadcast_mode": FieldMeta("Rebroadcast-Modus"),
    "device.node_info_broadcast_secs": FieldMeta("NodeInfo-Intervall", "0 = Firmware-Standard", S,
                                                 min=0, max=_UINT32_MAX),
    "device.double_tap_as_button_press": FieldMeta("Doppeltipp als Tastendruck"),
    "device.is_managed": FieldMeta(
        "Managed Mode (veraltet, siehe Sicherheit)",
        danger="Im Managed Mode lässt sich die Konfiguration nur noch per Admin-Schlüssel ändern.",
        danger_when=_turned_on),
    "device.disable_triple_click": FieldMeta("Dreifachklick deaktivieren"),
    "device.tzdef": FieldMeta("Zeitzone (POSIX-TZ)", "Deutschland: CET-1CEST,M3.5.0,M10.5.0/3", maxlen=64),
    "device.led_heartbeat_disabled": FieldMeta("Heartbeat-LED aus"),
    "device.buzzer_mode": FieldMeta("Buzzer-Modus"),
    # Config.PositionConfig
    "position.position_broadcast_secs": FieldMeta("Positions-Intervall", "0 = Firmware-Standard", S,
                                                  min=0, max=_UINT32_MAX),
    "position.position_broadcast_smart_enabled": FieldMeta("Smart Position"),
    "position.fixed_position": FieldMeta("Feste Position", "Koordinaten im Tab Übersicht setzen."),
    "position.gps_enabled": FieldMeta("GPS aktiv (veraltet, siehe GPS-Modus)"),
    "position.gps_update_interval": FieldMeta("GPS-Update-Intervall", unit=S, min=0, max=_UINT32_MAX),
    "position.gps_attempt_time": FieldMeta("GPS-Fix-Versuchszeit (veraltet)", unit=S, min=0, max=_UINT32_MAX),
    "position.position_flags": FieldMeta("Positions-Flags", "Welche Zusatzfelder Positionspakete enthalten.",
                                         widget="bitmask", flags_enum="Config.PositionConfig.PositionFlags"),
    "position.rx_gpio": FieldMeta("GPS RX-GPIO", "0 = Board-Standard"),
    "position.tx_gpio": FieldMeta("GPS TX-GPIO", "0 = Board-Standard"),
    "position.broadcast_smart_minimum_distance": FieldMeta("Smart: Mindestdistanz", unit="m", min=0,
                                                           max=_UINT32_MAX),
    "position.broadcast_smart_minimum_interval_secs": FieldMeta("Smart: Mindestintervall", unit=S, min=0,
                                                                max=_UINT32_MAX),
    "position.gps_en_gpio": FieldMeta("GPS-Enable-GPIO", "0 = Board-Standard"),
    "position.gps_mode": FieldMeta("GPS-Modus", "Der Bot hat kein GPS — DISABLED oder NOT_PRESENT ist üblich."),
    # Config.PowerConfig
    "power.is_power_saving": FieldMeta(
        "Energiesparmodus",
        danger="Bei ESP32 schaltet der Energiesparmodus Bluetooth/WLAN/Seriell zeitweise ab. " + CONNECTION_WARNING,
        danger_when=_turned_on),
    "power.on_battery_shutdown_after_secs": FieldMeta("Abschalten nach Akkubetrieb", "0 = nie", S, min=0,
                                                      max=_UINT32_MAX),
    "power.adc_multiplier_override": FieldMeta("ADC-Multiplikator", "0 = Standard", min=0, max=10),
    "power.wait_bluetooth_secs": FieldMeta("Bluetooth-Wartezeit", unit=S, min=0, max=_UINT32_MAX),
    "power.sds_secs": FieldMeta("Super-Deep-Sleep", unit=S, min=0, max=_UINT32_MAX),
    "power.ls_secs": FieldMeta("Light-Sleep", unit=S, min=0, max=_UINT32_MAX),
    "power.min_wake_secs": FieldMeta("Minimale Wachzeit", unit=S, min=0, max=_UINT32_MAX),
    "power.device_battery_ina_address": FieldMeta("I²C-Adresse INA-Akkusensor", "0 = keiner", min=0, max=127),
    "power.powermon_enables": FieldMeta("PowerMon-Bitmaske", "Nur für Strommessungs-Entwicklung", min=0,
                                        max=_UINT64_MAX),
    # Config.NetworkConfig
    "network.wifi_enabled": FieldMeta("WLAN aktiv", danger=CONNECTION_WARNING, danger_when=_turned_off),
    "network.wifi_ssid": FieldMeta("WLAN-SSID", maxlen=32),
    "network.wifi_psk": FieldMeta("WLAN-Passwort", widget="secret", maxlen=64),
    "network.ntp_server": FieldMeta("NTP-Server", "Standard: meshtastic.pool.ntp.org", maxlen=32),
    "network.eth_enabled": FieldMeta("Ethernet aktiv", danger=CONNECTION_WARNING, danger_when=_turned_off),
    "network.address_mode": FieldMeta(
        "Adressmodus", danger="Falsche statische IP-Daten machen die Node im Netz unerreichbar. " + CONNECTION_WARNING,
        danger_when=_changed),
    "network.ipv4_config.ip": FieldMeta("Statische IP", widget="ip"),
    "network.ipv4_config.gateway": FieldMeta("Gateway", widget="ip"),
    "network.ipv4_config.subnet": FieldMeta("Subnetz", widget="ip"),
    "network.ipv4_config.dns": FieldMeta("DNS", widget="ip"),
    "network.rsyslog_server": FieldMeta("Rsyslog-Server", "host:port", maxlen=32),
    "network.enabled_protocols": FieldMeta("Netzwerk-Protokolle", "UDP_BROADCAST = Mesh-Pakete per UDP im LAN",
                                           widget="bitmask", flags_enum="Config.NetworkConfig.ProtocolFlags"),
    "network.ipv6_enabled": FieldMeta("IPv6"),
    # Config.DisplayConfig
    "display.screen_on_secs": FieldMeta("Bildschirm an", "0 = Standard", S, min=0, max=_UINT32_MAX),
    "display.gps_format": FieldMeta("Koordinatenformat"),
    "display.auto_screen_carousel_secs": FieldMeta("Karussell-Intervall", "0 = aus", S, min=0, max=_UINT32_MAX),
    "display.compass_north_top": FieldMeta("Kompass: Norden oben"),
    "display.flip_screen": FieldMeta("Bildschirm drehen"),
    "display.units": FieldMeta("Einheiten"),
    "display.oled": FieldMeta("OLED-Typ"),
    "display.displaymode": FieldMeta("Anzeigemodus"),
    "display.heading_bold": FieldMeta("Überschrift fett"),
    "display.wake_on_tap_or_motion": FieldMeta("Aufwecken bei Tippen/Bewegung"),
    "display.compass_orientation": FieldMeta("Kompass-Ausrichtung"),
    "display.use_12h_clock": FieldMeta("12-Stunden-Uhr"),
    "display.use_long_node_name": FieldMeta("Langen Node-Namen anzeigen"),
    "display.enable_message_bubbles": FieldMeta("Nachrichten-Blasen"),
    # Config.LoRaConfig
    "lora.use_preset": FieldMeta("Modem-Preset verwenden", danger=MESH_PARAMS_WARNING, danger_when=_changed),
    "lora.modem_preset": FieldMeta("Modem-Preset", "Meshhessen: Preset laut Netz-Absprache",
                                   danger=MESH_PARAMS_WARNING, danger_when=_changed),
    "lora.bandwidth": FieldMeta("Bandbreite", "Nur ohne Preset (z. B. 125, 250, 500)", "kHz", min=0,
                                max=_UINT32_MAX, danger=MESH_PARAMS_WARNING, danger_when=_changed),
    "lora.spread_factor": FieldMeta("Spreading Factor", "Nur ohne Preset (7–12)", min=0, max=12,
                                    danger=MESH_PARAMS_WARNING, danger_when=_changed),
    "lora.coding_rate": FieldMeta("Coding Rate", "Nur ohne Preset (5–8 = 4/5 … 4/8)", min=0, max=8,
                                  danger=MESH_PARAMS_WARNING, danger_when=_changed),
    "lora.frequency_offset": FieldMeta("Frequenz-Offset", "Kalibrierung des Quarzes", "Hz", min=-1e6, max=1e6),
    "lora.region": FieldMeta("Region", danger=REGION_WARNING, danger_when=_changed),
    "lora.hop_limit": FieldMeta("Hop-Limit", "Firmware erlaubt 0–7", min=0, max=7),
    "lora.tx_enabled": FieldMeta(
        "Senden (TX) aktiv",
        danger="TX nur mit angeschlossener Antenne einschalten. Ausgeschaltet sendet die Node — und damit der Bot — nichts.",
        danger_when=_changed),
    "lora.tx_power": FieldMeta("Sendeleistung", f"0 = Firmware-Standard, {TX_POWER_MAX_DBM} = Volllast; kein harter Cap",
                               "dBm", min=0, max=TX_POWER_MAX_DBM, danger=TX_POWER_WARNING_TEXT,
                               danger_when=_tx_power_needs_confirm),
    "lora.channel_num": FieldMeta("Frequenz-Slot", "0 = aus Kanalname berechnet", min=0, max=_UINT32_MAX,
                                  danger=MESH_PARAMS_WARNING, danger_when=_changed),
    "lora.override_duty_cycle": FieldMeta(
        "Duty-Cycle-Limit ignorieren",
        danger="Hebt das gesetzliche Duty-Cycle-Limit auf (EU 868: 1–10 %). Nur zulässig, wenn du dazu berechtigt bist.",
        danger_when=_turned_on),
    "lora.sx126x_rx_boosted_gain": FieldMeta("SX126x RX Boosted Gain"),
    "lora.override_frequency": FieldMeta("Frequenz überschreiben", "0 = aus", "MHz", min=0, max=3000,
                                         danger=MESH_PARAMS_WARNING, danger_when=_changed),
    "lora.pa_fan_disabled": FieldMeta("PA-Lüfter aus"),
    "lora.ignore_incoming": FieldMeta("Ignorierte Nodes", "Node-Nummern oder !hex, durch Komma getrennt",
                                      widget="nodelist", max_items=3),
    "lora.ignore_mqtt": FieldMeta("Pakete via MQTT ignorieren"),
    "lora.config_ok_to_mqtt": FieldMeta("OK für MQTT", "Erlaubt Weitergabe eigener Pakete an MQTT"),
    "lora.fem_lna_mode": FieldMeta("FEM-LNA-Modus"),
    "lora.serial_hal_only": FieldMeta("Nur serielles HAL", "Nur für Spezial-Hardware ändern"),
    # Config.BluetoothConfig
    "bluetooth.enabled": FieldMeta("Bluetooth aktiv", danger=CONNECTION_WARNING, danger_when=_turned_off),
    "bluetooth.mode": FieldMeta("Pairing-Modus"),
    "bluetooth.fixed_pin": FieldMeta("Fester PIN", "6 Ziffern, nur bei FIXED_PIN", min=0, max=999999),
    # Config.SecurityConfig
    "security.public_key": FieldMeta("Öffentlicher Schlüssel", widget="readonly_b64", readonly=True),
    "security.private_key": FieldMeta(
        "Privater Schlüssel", "leer = unverändert; „leeren“ erzeugt beim Neustart ein neues Schlüsselpaar",
        widget="secret_b64",
        danger="Ein neuer privater Schlüssel ist eine neue Identität: verschlüsselte DMs und Admin-Zugänge "
               "anderer Nodes passen danach nicht mehr.",
        danger_when=_changed),
    "security.admin_key": FieldMeta(
        "Admin-Schlüssel", "Base64, ein Schlüssel (32 Byte) pro Zeile", widget="b64list", max_items=3,
        danger="Admin-Schlüssel erlauben die Fernverwaltung dieser Node.", danger_when=_changed),
    "security.is_managed": FieldMeta(
        "Managed Mode",
        danger="Im Managed Mode lässt sich die Konfiguration nur noch per Admin-Schlüssel (Remote-Admin) ändern — "
               "Bot und Companion-App können lokal nichts mehr einstellen.",
        danger_when=_turned_on),
    "security.serial_enabled": FieldMeta(
        "Serielle Konsole/API",
        danger="Verbindet sich der Bot per USB/Seriell, verliert er den Zugriff. " + CONNECTION_WARNING,
        danger_when=_turned_off),
    "security.debug_log_api_enabled": FieldMeta("Debug-Log über API"),
    "security.admin_channel_enabled": FieldMeta(
        "Legacy-Admin-Kanal",
        danger="Erlaubt Fernverwaltung über einen Kanal namens „admin“ (veraltet und unsicher).",
        danger_when=_turned_on),
    # ModuleConfig.MQTTConfig
    "mqtt.enabled": FieldMeta("MQTT aktiv"),
    "mqtt.address": FieldMeta("Server", "leer = Standard-Server", maxlen=63),
    "mqtt.username": FieldMeta("Benutzername", maxlen=63),
    "mqtt.password": FieldMeta("Passwort", widget="secret", maxlen=63),
    "mqtt.encryption_enabled": FieldMeta("Verschlüsselt senden"),
    "mqtt.json_enabled": FieldMeta("JSON-Ausgabe"),
    "mqtt.tls_enabled": FieldMeta("TLS"),
    "mqtt.root": FieldMeta("Root-Topic", "z. B. msh/EU_868", maxlen=31),
    "mqtt.proxy_to_client_enabled": FieldMeta("Über Client proxyen"),
    "mqtt.map_reporting_enabled": FieldMeta("Karten-Report"),
    "mqtt.map_report_settings.publish_interval_secs": FieldMeta("Map-Report-Intervall", unit=S, min=0,
                                                                max=_UINT32_MAX),
    "mqtt.map_report_settings.position_precision": FieldMeta("Map-Report-Positionsgenauigkeit", "Bits, 0–32",
                                                             min=0, max=32),
    "mqtt.map_report_settings.should_report_location": FieldMeta("Standort im Map-Report"),
    # ModuleConfig.SerialConfig
    "serial.enabled": FieldMeta("Serial-Modul aktiv"),
    "serial.echo": FieldMeta("Echo"),
    "serial.rxd": FieldMeta("RX-GPIO"),
    "serial.txd": FieldMeta("TX-GPIO"),
    "serial.baud": FieldMeta("Baudrate"),
    "serial.timeout": FieldMeta("Timeout", unit=MS, min=0, max=_UINT32_MAX),
    "serial.mode": FieldMeta("Modus"),
    "serial.override_console_serial_port": FieldMeta(
        "Konsolen-Port übernehmen", danger="Übernimmt den seriellen Konsolen-Port. " + CONNECTION_WARNING,
        danger_when=_turned_on),
    # ModuleConfig.ExternalNotificationConfig
    "external_notification.enabled": FieldMeta("Modul aktiv"),
    "external_notification.output_ms": FieldMeta("Ausgabedauer", unit=MS, min=0, max=_UINT32_MAX),
    "external_notification.output": FieldMeta("GPIO Ausgang (LED)"),
    "external_notification.output_vibra": FieldMeta("GPIO Vibration"),
    "external_notification.output_buzzer": FieldMeta("GPIO Buzzer"),
    "external_notification.active": FieldMeta("Ausgang active-high"),
    "external_notification.alert_message": FieldMeta("Nachricht: LED"),
    "external_notification.alert_message_vibra": FieldMeta("Nachricht: Vibration"),
    "external_notification.alert_message_buzzer": FieldMeta("Nachricht: Buzzer"),
    "external_notification.alert_bell": FieldMeta("Glocke: LED"),
    "external_notification.alert_bell_vibra": FieldMeta("Glocke: Vibration"),
    "external_notification.alert_bell_buzzer": FieldMeta("Glocke: Buzzer"),
    "external_notification.use_pwm": FieldMeta("PWM-Buzzer"),
    "external_notification.nag_timeout": FieldMeta("Wiederholen für", unit=S, min=0, max=_UINT32_MAX),
    "external_notification.use_i2s_as_buzzer": FieldMeta("I²S als Buzzer"),
    # ModuleConfig.StoreForwardConfig
    "store_forward.enabled": FieldMeta("Modul aktiv"),
    "store_forward.heartbeat": FieldMeta("Heartbeat senden"),
    "store_forward.records": FieldMeta("Datensätze", "0 = automatisch", min=0, max=_UINT32_MAX),
    "store_forward.history_return_max": FieldMeta("Max. Rückgabe", min=0, max=_UINT32_MAX),
    "store_forward.history_return_window": FieldMeta("Rückgabe-Zeitfenster", unit="min", min=0, max=_UINT32_MAX),
    "store_forward.is_server": FieldMeta("Als Server"),
    # ModuleConfig.RangeTestConfig
    "range_test.enabled": FieldMeta("Modul aktiv"),
    "range_test.sender": FieldMeta(
        "Sende-Intervall", "0 = nur empfangen", S, min=0, max=_UINT32_MAX,
        danger="Range Test sendet regelmäßig Pakete — auf öffentlichen Meshes wie Meshhessen belastet das das Netz.",
        danger_when=lambda old, new: int(new) > 0 and int(new) != int(old)),
    "range_test.save": FieldMeta("Als CSV speichern (nur ESP32)"),
    "range_test.clear_on_reboot": FieldMeta("Beim Neustart löschen"),
    # ModuleConfig.TelemetryConfig
    "telemetry.device_update_interval": FieldMeta("Geräte-Intervall", unit=S, min=0, max=_UINT32_MAX),
    "telemetry.environment_update_interval": FieldMeta("Umwelt-Intervall", unit=S, min=0, max=_UINT32_MAX),
    "telemetry.environment_measurement_enabled": FieldMeta("Umweltsensoren"),
    "telemetry.environment_screen_enabled": FieldMeta("Umwelt auf Display"),
    "telemetry.environment_display_fahrenheit": FieldMeta("Fahrenheit"),
    "telemetry.air_quality_enabled": FieldMeta("Luftqualität"),
    "telemetry.air_quality_interval": FieldMeta("Luftqualität-Intervall", unit=S, min=0, max=_UINT32_MAX),
    "telemetry.power_measurement_enabled": FieldMeta("Strommessung"),
    "telemetry.power_update_interval": FieldMeta("Strom-Intervall", unit=S, min=0, max=_UINT32_MAX),
    "telemetry.power_screen_enabled": FieldMeta("Strom auf Display"),
    "telemetry.health_measurement_enabled": FieldMeta("Gesundheitssensoren"),
    "telemetry.health_update_interval": FieldMeta("Gesundheit-Intervall", unit=S, min=0, max=_UINT32_MAX),
    "telemetry.health_screen_enabled": FieldMeta("Gesundheit auf Display"),
    "telemetry.device_telemetry_enabled": FieldMeta("Geräte-Telemetrie ins Mesh senden"),
    "telemetry.air_quality_screen_enabled": FieldMeta("Luftqualität auf Display"),
    # ModuleConfig.CannedMessageConfig
    "canned_message.rotary1_enabled": FieldMeta("Drehgeber"),
    "canned_message.inputbroker_pin_a": FieldMeta("GPIO Pin A"),
    "canned_message.inputbroker_pin_b": FieldMeta("GPIO Pin B"),
    "canned_message.inputbroker_pin_press": FieldMeta("GPIO Taster"),
    "canned_message.inputbroker_event_cw": FieldMeta("Ereignis im Uhrzeigersinn"),
    "canned_message.inputbroker_event_ccw": FieldMeta("Ereignis gegen Uhrzeigersinn"),
    "canned_message.inputbroker_event_press": FieldMeta("Ereignis Tastendruck"),
    "canned_message.updown1_enabled": FieldMeta("Hoch/Runter-Taster"),
    "canned_message.enabled": FieldMeta("Modul aktiv"),
    "canned_message.allow_input_source": FieldMeta("Eingabequelle", "z. B. rotEnc1, upDownEnc1, cardkb; leer = alle",
                                                   maxlen=15),
    "canned_message.send_bell": FieldMeta("Glocke mitsenden"),
    # ModuleConfig.AudioConfig
    "audio.codec2_enabled": FieldMeta("Codec2 aktiv"),
    "audio.ptt_pin": FieldMeta("PTT-GPIO"),
    "audio.bitrate": FieldMeta("Bitrate"),
    "audio.i2s_ws": FieldMeta("I²S WS"),
    "audio.i2s_sd": FieldMeta("I²S SD"),
    "audio.i2s_din": FieldMeta("I²S DIN"),
    "audio.i2s_sck": FieldMeta("I²S SCK"),
    # ModuleConfig.RemoteHardwareConfig
    "remote_hardware.enabled": FieldMeta(
        "Modul aktiv", danger="Erlaubt anderen Nodes, GPIOs dieser Node zu lesen und zu schalten.",
        danger_when=_turned_on),
    "remote_hardware.allow_undefined_pin_access": FieldMeta(
        "Zugriff auf nicht definierte Pins", danger="Erlaubt Zugriff auf beliebige GPIOs — auch kritische.",
        danger_when=_turned_on),
    "remote_hardware.available_pins": FieldMeta(
        "Freigegebene Pins", "Eine Zeile pro Pin: GPIO;Name;Typ (DIGITAL_READ / DIGITAL_WRITE)",
        widget="pins", max_items=4),
    # ModuleConfig.NeighborInfoConfig
    "neighbor_info.enabled": FieldMeta("Modul aktiv"),
    "neighbor_info.update_interval": FieldMeta("Intervall", "Firmware-Minimum beachten", S, min=0,
                                               max=_UINT32_MAX),
    "neighbor_info.transmit_over_lora": FieldMeta("Über LoRa senden", "Auf dem Standardkanal von der Firmware ignoriert"),
    # ModuleConfig.AmbientLightingConfig
    "ambient_lighting.led_state": FieldMeta("LED an"),
    "ambient_lighting.current": FieldMeta("Strom", unit="mA", min=0, max=_UINT32_MAX),
    "ambient_lighting.red": FieldMeta("Rot", min=0, max=255),
    "ambient_lighting.green": FieldMeta("Grün", min=0, max=255),
    "ambient_lighting.blue": FieldMeta("Blau", min=0, max=255),
    # ModuleConfig.DetectionSensorConfig
    "detection_sensor.enabled": FieldMeta("Modul aktiv"),
    "detection_sensor.minimum_broadcast_secs": FieldMeta("Mindestintervall", unit=S, min=0, max=_UINT32_MAX),
    "detection_sensor.state_broadcast_secs": FieldMeta("Status-Intervall", "0 = nur bei Änderung", S, min=0,
                                                       max=_UINT32_MAX),
    "detection_sensor.send_bell": FieldMeta("Glocke mitsenden"),
    "detection_sensor.name": FieldMeta("Name", maxlen=19),
    "detection_sensor.monitor_pin": FieldMeta("Überwachter GPIO"),
    "detection_sensor.detection_trigger_type": FieldMeta("Auslöser"),
    "detection_sensor.use_pullup": FieldMeta("Pull-up verwenden"),
    # ModuleConfig.PaxcounterConfig
    "paxcounter.enabled": FieldMeta("Modul aktiv"),
    "paxcounter.paxcounter_update_interval": FieldMeta("Intervall", unit=S, min=0, max=_UINT32_MAX),
    "paxcounter.wifi_threshold": FieldMeta("WLAN-Schwelle", "RSSI, z. B. -80", "dBm", min=-127, max=0),
    "paxcounter.ble_threshold": FieldMeta("BLE-Schwelle", "RSSI, z. B. -80", "dBm", min=-127, max=0),
    # ModuleConfig.StatusMessageConfig
    "statusmessage.node_status": FieldMeta("Status-Text", "Wird mit der NodeInfo verteilt", maxlen=80),
    # ModuleConfig.TrafficManagementConfig
    "traffic_management.enabled": FieldMeta("Modul aktiv"),
    "traffic_management.position_dedup_enabled": FieldMeta("Positions-Duplikate filtern"),
    "traffic_management.position_precision_bits": FieldMeta("Positionsgenauigkeit", "Bits, 0–32", min=0, max=32),
    "traffic_management.position_min_interval_secs": FieldMeta("Mind. Positions-Intervall", unit=S, min=0,
                                                               max=_UINT32_MAX),
    "traffic_management.nodeinfo_direct_response": FieldMeta("NodeInfo direkt beantworten"),
    "traffic_management.nodeinfo_direct_response_max_hops": FieldMeta("NodeInfo-Antwort max. Hops", min=0, max=7),
    "traffic_management.rate_limit_enabled": FieldMeta("Rate-Limit"),
    "traffic_management.rate_limit_window_secs": FieldMeta("Rate-Limit-Fenster", unit=S, min=0, max=_UINT32_MAX),
    "traffic_management.rate_limit_max_packets": FieldMeta("Max. Pakete je Fenster", min=0, max=_UINT32_MAX),
    "traffic_management.drop_unknown_enabled": FieldMeta("Unbekannte Pakete verwerfen"),
    "traffic_management.unknown_packet_threshold": FieldMeta("Schwelle unbekannte Pakete", min=0, max=_UINT32_MAX),
    "traffic_management.exhaust_hop_telemetry": FieldMeta("Telemetrie: Hops aufbrauchen"),
    "traffic_management.exhaust_hop_position": FieldMeta("Position: Hops aufbrauchen"),
    "traffic_management.router_preserve_hops": FieldMeta("Router: Hops erhalten"),
    # ModuleConfig.TAKConfig
    "tak.team": FieldMeta("Team-Farbe"),
    "tak.role": FieldMeta("TAK-Rolle"),
}


def field_meta(section: str, path: str) -> FieldMeta:
    meta = FIELD_META.get(f"{section}.{path}")
    if meta is not None:
        return meta
    return FieldMeta(path.rsplit(".", 1)[-1].replace("_", " "))


# --- Descriptor walking and value conversion ---


@dataclass(frozen=True)
class FieldRef:
    path: str
    fd: FieldDescriptor


def iter_section_fields(desc: Descriptor, prefix: str = "") -> List[FieldRef]:
    """Leaf fields of a section; singular nested messages are flattened (``a.b``)."""
    out: List[FieldRef] = []
    for fd in desc.fields:
        path = f"{prefix}{fd.name}"
        if fd.type == FieldDescriptor.TYPE_MESSAGE and not _is_repeated(fd):
            out.extend(iter_section_fields(fd.message_type, path + "."))
        else:
            out.append(FieldRef(path, fd))
    return out


def _is_repeated(fd: FieldDescriptor) -> bool:
    rep = getattr(fd, "is_repeated", None)
    if isinstance(rep, bool):
        return rep
    return fd.label == FieldDescriptor.LABEL_REPEATED


def _is_deprecated(fd: FieldDescriptor) -> bool:
    try:
        return bool(fd.GetOptions().deprecated)
    except Exception:
        return False


def _container(msg: Message, path: str) -> Tuple[Message, str]:
    parts = path.split(".")
    for part in parts[:-1]:
        msg = getattr(msg, part)
    return msg, parts[-1]


def get_value(msg: Message, ref: FieldRef) -> Any:
    holder, name = _container(msg, ref.path)
    val = getattr(holder, name)
    if _is_repeated(ref.fd):
        if ref.fd.type == FieldDescriptor.TYPE_MESSAGE:
            return [tuple(getattr(item, f.name) for f in ref.fd.message_type.fields) for item in val]
        return list(val)
    return val


def set_value(msg: Message, ref: FieldRef, value: Any) -> None:
    holder, name = _container(msg, ref.path)
    if _is_repeated(ref.fd):
        rep = getattr(holder, name)
        del rep[:]
        if ref.fd.type == FieldDescriptor.TYPE_MESSAGE:
            for row in value:
                item = rep.add()
                for f, v in zip(ref.fd.message_type.fields, row):
                    setattr(item, f.name, v)
        else:
            rep.extend(value)
        return
    setattr(holder, name, value)


def _enum_type(path: str):
    from meshtastic.protobuf import config_pb2, module_config_pb2

    root, _, rest = path.partition(".")
    obj: Any = {"Config": config_pb2.Config, "ModuleConfig": module_config_pb2.ModuleConfig}[root]
    for part in rest.split("."):
        obj = getattr(obj, part)
    return obj


def int_to_ip(value: int) -> str:
    """Firmware stores IPv4 as little-endian uint32 (first octet in the lowest byte)."""
    v = int(value) & _UINT32_MAX
    return ".".join(str((v >> shift) & 0xFF) for shift in (0, 8, 16, 24))


def ip_to_int(text: str) -> int:
    parts = text.strip().split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        raise ValueError(text)
    octets = [int(p) for p in parts]
    if any(o > 255 for o in octets):
        raise ValueError(text)
    return octets[0] | (octets[1] << 8) | (octets[2] << 16) | (octets[3] << 24)


def parse_node_num(token: str) -> int:
    t = token.strip()
    if t.startswith("!"):
        return int(t[1:], 16)
    if t.lower().startswith("0x"):
        return int(t[2:], 16)
    return int(t)


def _b64(data: bytes) -> str:
    return base64.b64encode(bytes(data)).decode("ascii") if data else ""


def _decode_key(text: str) -> bytes:
    t = text.strip()
    if t.lower().startswith("base64:"):
        t = t[7:].strip()
    pad = t + "=" * ((4 - len(t) % 4) % 4)
    return base64.b64decode(pad, validate=True)


def _getlist(form: Any, key: str) -> List[str]:
    getter = getattr(form, "getlist", None)
    if callable(getter):
        return [str(v) for v in getter(key)]
    val = form.get(key) if hasattr(form, "get") else None
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [str(v) for v in val]
    return [str(val)]


def _form_get(form: Any, key: str) -> str:
    vals = _getlist(form, key)
    return vals[-1] if vals else ""


def _is_checked(form: Any, key: str) -> bool:
    return _form_get(form, key).strip().lower() in CONFIRM_VALUES


def field_name(path: str) -> str:
    return f"f__{path}"


def confirm_name(path: str) -> str:
    return f"confirm__{path}"


def clear_name(path: str) -> str:
    return f"clear__{path}"


_INT_TYPES = {
    FieldDescriptor.TYPE_UINT32: (0, _UINT32_MAX),
    FieldDescriptor.TYPE_FIXED32: (0, _UINT32_MAX),
    FieldDescriptor.TYPE_INT32: (_INT32_MIN, _INT32_MAX),
    FieldDescriptor.TYPE_SINT32: (_INT32_MIN, _INT32_MAX),
    FieldDescriptor.TYPE_SFIXED32: (_INT32_MIN, _INT32_MAX),
    FieldDescriptor.TYPE_UINT64: (0, _UINT64_MAX),
    FieldDescriptor.TYPE_FIXED64: (0, _UINT64_MAX),
    FieldDescriptor.TYPE_INT64: (-(2**63), 2**63 - 1),
    FieldDescriptor.TYPE_SINT64: (-(2**63), 2**63 - 1),
    FieldDescriptor.TYPE_SFIXED64: (-(2**63), 2**63 - 1),
}
_FLOAT_TYPES = {FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE}


def _fmt_bound(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _check_range(meta: FieldMeta, value: float, lo: float, hi: float) -> Optional[str]:
    lo = meta.min if meta.min is not None else lo
    hi = meta.max if meta.max is not None else hi
    if not lo <= value <= hi:
        return f"{meta.label}: Wert zwischen {_fmt_bound(lo)} und {_fmt_bound(hi)} erwartet."
    return None


def parse_field(ref: FieldRef, meta: FieldMeta, form: Any, current: Any) -> Tuple[Any, Optional[str]]:
    """Parse one submitted field. Returns (new value, error). Never clamps — out-of-range is an error."""
    fd = ref.fd
    name = field_name(ref.path)
    raw = _form_get(form, name)
    text = raw.strip()

    if meta.widget == "bitmask":
        total = 0
        for item in _getlist(form, name):
            try:
                total |= int(item)
            except ValueError:
                return None, f"{meta.label}: ungültiger Wert."
        return total, None

    if meta.widget == "ip":
        if not text:
            return 0, None
        try:
            return ip_to_int(text), None
        except ValueError:
            return None, f"{meta.label}: IPv4-Adresse wie 192.168.1.10 erwartet."

    if meta.widget in ("secret", "secret_b64"):
        if _is_checked(form, clear_name(ref.path)):
            return (b"" if fd.type == FieldDescriptor.TYPE_BYTES else ""), None
        if not text:
            return current, None
        if meta.widget == "secret_b64":
            try:
                key = _decode_key(text)
            except Exception:
                return None, f"{meta.label}: ungültiges Base64."
            if len(key) != 32:
                return None, f"{meta.label}: 32 Byte erwartet, {len(key)} erhalten."
            return key, None
        if meta.maxlen is not None and len(raw.encode("utf-8")) > meta.maxlen:
            return None, f"{meta.label}: maximal {meta.maxlen} Byte."
        return raw, None

    if meta.widget == "nodelist":
        tokens = [t for t in re.split(r"[\s,;]+", text) if t]
        nums: List[int] = []
        for tok in tokens:
            try:
                n = parse_node_num(tok)
            except ValueError:
                return None, f"{meta.label}: „{tok}“ ist keine Node-Nummer."
            if not 0 < n <= _UINT32_MAX:
                return None, f"{meta.label}: „{tok}“ außerhalb des gültigen Bereichs."
            nums.append(n)
        if meta.max_items is not None and len(nums) > meta.max_items:
            return None, f"{meta.label}: höchstens {meta.max_items} Einträge (Firmware-Limit), {len(nums)} angegeben."
        return nums, None

    if meta.widget == "b64list":
        keys: List[bytes] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                key = _decode_key(line)
            except Exception:
                return None, f"{meta.label}: ungültiges Base64 in „{line.strip()[:16]}…“."
            if len(key) != 32:
                return None, f"{meta.label}: jeder Schlüssel muss 32 Byte haben ({len(key)} erhalten)."
            keys.append(key)
        if meta.max_items is not None and len(keys) > meta.max_items:
            return None, f"{meta.label}: höchstens {meta.max_items} Schlüssel (Firmware-Limit)."
        return keys, None

    if meta.widget == "pins":
        return _parse_pins(ref, meta, raw)

    if fd.type == FieldDescriptor.TYPE_BOOL:
        return _is_checked(form, name), None

    if fd.type == FieldDescriptor.TYPE_ENUM:
        try:
            val = int(text)
        except ValueError:
            return None, f"{meta.label}: ungültige Auswahl."
        if val not in {v.number for v in fd.enum_type.values}:
            return None, f"{meta.label}: unbekannter Wert {val}."
        return val, None

    if fd.type in _INT_TYPES:
        if not text:
            return None, f"{meta.label}: bitte eine Zahl eingeben."
        try:
            val = int(text)
        except ValueError:
            return None, f"{meta.label}: bitte eine ganze Zahl eingeben."
        lo, hi = _INT_TYPES[fd.type]
        err = _check_range(meta, val, lo, hi)
        return (None, err) if err else (val, None)

    if fd.type in _FLOAT_TYPES:
        try:
            fval = float(text.replace(",", ".")) if text else 0.0
        except ValueError:
            return None, f"{meta.label}: ungültige Zahl."
        if not math.isfinite(fval):
            return None, f"{meta.label}: ungültige Zahl."
        err = _check_range(meta, fval, -3.4e38, 3.4e38)
        return (None, err) if err else (fval, None)

    if fd.type == FieldDescriptor.TYPE_STRING:
        if meta.maxlen is not None and len(raw.encode("utf-8")) > meta.maxlen:
            return None, f"{meta.label}: maximal {meta.maxlen} Byte (aktuell {len(raw.encode('utf-8'))})."
        return raw.strip(), None

    return current, None


def _parse_pins(ref: FieldRef, meta: FieldMeta, raw: str) -> Tuple[Any, Optional[str]]:
    sub = ref.fd.message_type
    type_fd = sub.fields_by_name.get("type")
    rows: List[Tuple[Any, ...]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) != 3:
            return None, f"{meta.label}: Zeile „{line.strip()}“ — Format GPIO;Name;Typ."
        try:
            gpio = int(parts[0])
        except ValueError:
            return None, f"{meta.label}: GPIO „{parts[0]}“ ist keine Zahl."
        if not 0 <= gpio <= 255:
            return None, f"{meta.label}: GPIO {gpio} außerhalb 0–255."
        if len(parts[1].encode("utf-8")) > 14:
            return None, f"{meta.label}: Pin-Name „{parts[1]}“ zu lang (max. 14 Byte)."
        enum_val = type_fd.enum_type.values_by_name.get(parts[2].upper()) if type_fd else None
        if enum_val is None:
            return None, f"{meta.label}: Typ „{parts[2]}“ — DIGITAL_READ oder DIGITAL_WRITE."
        values = {"gpio_pin": gpio, "name": parts[1], "type": enum_val.number}
        rows.append(tuple(values.get(f.name, f.default_value) for f in sub.fields))
    if meta.max_items is not None and len(rows) > meta.max_items:
        return None, f"{meta.label}: höchstens {meta.max_items} Pins (Firmware-Limit)."
    return rows, None


# --- Section plan / apply ---


@dataclass
class SectionPlan:
    candidate: Optional[Message]
    changes: List[str]
    errors: List[str]
    unconfirmed: List[str]


def plan_section_update(section: str, current: Message, form: Any) -> SectionPlan:
    """Validate a submitted section form against the current protobuf without touching the device."""
    candidate = type(current)()
    candidate.CopyFrom(current)
    present = set(_getlist(form, "present"))
    changes: List[str] = []
    errors: List[str] = []
    unconfirmed: List[str] = []

    for ref in iter_section_fields(current.DESCRIPTOR):
        if ref.path not in present:
            continue
        meta = field_meta(section, ref.path)
        if meta.readonly:
            continue
        old = get_value(current, ref)
        new, err = parse_field(ref, meta, form, old)
        if err:
            errors.append(err)
            continue
        cmp_new = new
        if _is_repeated(ref.fd):
            cmp_new = list(new)
        if cmp_new == old:
            continue
        if meta.danger:
            needs = (meta.danger_when or _changed)(old, new)
            if needs and not _is_checked(form, confirm_name(ref.path)):
                unconfirmed.append(f"{meta.label}: {meta.danger}")
                continue
        set_value(candidate, ref, new)
        changes.append(meta.label)

    errors.extend(_cross_field_errors(section, candidate))
    return SectionPlan(candidate, changes, errors, unconfirmed)


def _cross_field_errors(section: str, msg: Message) -> List[str]:
    errs: List[str] = []
    if section == "lora" and hasattr(msg, "use_preset") and not msg.use_preset:
        if not 7 <= int(msg.spread_factor) <= 12:
            errs.append("Ohne Preset: Spreading Factor 7–12 erforderlich.")
        if not 5 <= int(msg.coding_rate) <= 8:
            errs.append("Ohne Preset: Coding Rate 5–8 erforderlich.")
        if int(msg.bandwidth) <= 0:
            errs.append("Ohne Preset: Bandbreite (kHz) erforderlich.")
    if section == "bluetooth" and hasattr(msg, "mode"):
        try:
            from meshtastic.protobuf import config_pb2

            fixed = config_pb2.Config.BluetoothConfig.PairingMode.Value("FIXED_PIN")
        except Exception:
            fixed = 1
        if int(msg.mode) == fixed and not 100000 <= int(msg.fixed_pin) <= 999999:
            errs.append("Bluetooth: Bei FIXED_PIN ist ein 6-stelliger PIN erforderlich.")
    if section == "security" and getattr(msg, "is_managed", False) and not list(msg.admin_key):
        errs.append("Managed Mode erfordert mindestens einen Admin-Schlüssel — sonst sperrst du dich aus.")
    return errs


def _node_for_iface(iface_id: int):
    from modules.admin_web_ops import _local_node_for_iface

    return _local_node_for_iface(iface_id)


def _ensure_session(node: Any) -> None:
    fn = getattr(node, "ensureSessionKey", None)
    if callable(fn):
        fn()


def _send_admin(node: Any, msg: Message, **kw: Any) -> Any:
    """Send an AdminMessage the way the meshtastic lib does (its helpers call sys.exit on bad input)."""
    _ensure_session(node)
    return node._sendAdmin(msg, **kw)


def _section_store(node: Any, kind: str) -> Message:
    return node.localConfig if kind == "config" else node.moduleConfig


def write_section(node: Any, kind: str, section: str, candidate: Message) -> None:
    from meshtastic.protobuf import admin_pb2

    p = admin_pb2.AdminMessage()
    target = p.set_config if kind == "config" else p.set_module_config
    getattr(target, section).CopyFrom(candidate)
    _send_admin(node, p)
    getattr(_section_store(node, kind), section).CopyFrom(candidate)


def apply_section(iface_id: int, tab_key: str, form: Any) -> Tuple[bool, str]:
    spec = tab_by_key(tab_key)
    if spec.kind not in ("config", "module") or spec.key != tab_key:
        return False, "Unbekannter Einstellungsbereich."
    node, err = _node_for_iface(iface_id)
    if err:
        return False, err
    store = _section_store(node, spec.kind)
    if store is None:
        return False, "Konfiguration der Node wurde noch nicht gelesen."
    current = getattr(store, spec.section)
    plan = plan_section_update(spec.section, current, form)
    if plan.errors:
        return False, f"{spec.label}: nicht gespeichert — " + " · ".join(plan.errors)
    if plan.unconfirmed:
        return False, (
            f"{spec.label}: nicht gespeichert — bitte die Warnung bestätigen. " + " · ".join(plan.unconfirmed)
        )
    if not plan.changes:
        return True, f"{spec.label}: keine Änderungen."
    try:
        write_section(node, spec.kind, spec.section, plan.candidate)
    except Exception as e:
        return False, f"{spec.label} konnte nicht geschrieben werden: {e!s}"
    return True, (
        f"{spec.label} gespeichert: {', '.join(plan.changes)}. "
        "Die Node startet bei manchen Änderungen neu — der Bot verbindet sich dann erneut."
    )


# --- Owner (Companion: Benutzer) ---

HAM_WARNING = (
    "Amateurfunk-Modus: Direktnachrichten werden nicht mehr Ende-zu-Ende verschlüsselt (gesetzliche Vorgabe), "
    "der Langname sollte dein Rufzeichen sein. Nur mit gültiger Lizenz aktivieren."
)


def _my_user(node: Any) -> Dict[str, Any]:
    iface = getattr(node, "iface", None)
    info = {}
    if iface is not None and callable(getattr(iface, "getMyNodeInfo", None)):
        info = iface.getMyNodeInfo() or {}
    return dict(info.get("user") or {})


def plan_owner_update(current: Mapping[str, Any], form: Any) -> Tuple[Dict[str, Any], List[str], Optional[str]]:
    long_name = (_form_get(form, "long_name") or "").strip()
    short_name = (_form_get(form, "short_name") or "").strip()
    if not long_name:
        return {}, [], "Langname darf nicht leer sein."
    if len(long_name.encode("utf-8")) > 39:
        return {}, [], "Langname: maximal 39 Byte."
    if not short_name or len(short_name) > 4:
        return {}, [], "Kurzname: 1–4 Zeichen erforderlich."
    if len(short_name.encode("utf-8")) > 4:
        return {}, [], "Kurzname: maximal 4 Byte (Emoji zählen mehrfach)."
    new = {
        "long_name": long_name,
        "short_name": short_name,
        "is_licensed": _is_checked(form, "is_licensed"),
        "is_unmessagable": _is_checked(form, "is_unmessagable"),
    }
    old = {
        "long_name": str(current.get("longName") or ""),
        "short_name": str(current.get("shortName") or ""),
        "is_licensed": bool(current.get("isLicensed")),
        "is_unmessagable": bool(current.get("isUnmessagable")),
    }
    labels = {"long_name": "Langname", "short_name": "Kurzname", "is_licensed": "Amateurfunk",
              "is_unmessagable": "Nicht anschreibbar"}
    changes = [labels[k] for k in new if new[k] != old[k]]
    if new["is_licensed"] and not old["is_licensed"] and not _is_checked(form, "confirm__is_licensed"):
        return {}, [], f"Amateurfunk-Modus nicht gespeichert: Bitte die Warnung bestätigen. {HAM_WARNING}"
    return new, changes, None


def apply_owner(iface_id: int, form: Any) -> Tuple[bool, str]:
    from meshtastic.protobuf import admin_pb2

    node, err = _node_for_iface(iface_id)
    if err:
        return False, err
    current = _my_user(node)
    new, changes, err = plan_owner_update(current, form)
    if err:
        return False, err
    if not changes:
        return True, "Benutzer: keine Änderungen."
    p = admin_pb2.AdminMessage()
    p.set_owner.long_name = new["long_name"]
    p.set_owner.short_name = new["short_name"]
    p.set_owner.is_licensed = new["is_licensed"]
    if "is_unmessagable" in p.set_owner.DESCRIPTOR.fields_by_name:
        p.set_owner.is_unmessagable = new["is_unmessagable"]
    try:
        _send_admin(node, p)
    except Exception as e:
        return False, f"Benutzer konnte nicht gesetzt werden: {e!s}"
    return True, f"Benutzer gespeichert: {', '.join(changes)}."


# --- Canned messages / ringtone (separate admin messages, not part of ModuleConfig) ---

CANNED_MESSAGES_MAX = 200
RINGTONE_MAX = 230


def request_admin_string(node: Any, request_field: str, response_field: str,
                         timeout: float = 3.0) -> Tuple[Optional[str], Optional[str]]:
    """Ask the node for a string-valued admin response with a timeout (lib helpers block forever)."""
    from meshtastic.protobuf import admin_pb2

    done = threading.Event()
    box: Dict[str, Any] = {}

    def on_response(packet: Dict[str, Any]) -> None:
        try:
            decoded = packet.get("decoded") or {}
            routing = decoded.get("routing") or {}
            if routing.get("errorReason", "NONE") != "NONE":
                box["error"] = str(routing.get("errorReason"))
            else:
                raw = (decoded.get("admin") or {}).get("raw")
                if raw is not None:
                    box["value"] = str(getattr(raw, response_field))
        except Exception as e:
            box["error"] = str(e)
        finally:
            done.set()

    p = admin_pb2.AdminMessage()
    setattr(p, request_field, True)
    try:
        _send_admin(node, p, wantResponse=True, onResponse=on_response)
    except Exception as e:
        return None, f"Anfrage fehlgeschlagen: {e!s}"
    if not done.wait(timeout):
        return None, "Keine Antwort der Node (Timeout)."
    if "error" in box:
        return None, f"Node meldet Fehler: {box['error']}"
    return box.get("value", ""), None


def plan_canned_messages(form: Any) -> Tuple[Optional[str], Optional[str]]:
    lines = [ln.strip() for ln in _form_get(form, "canned_messages").replace("\r", "").split("\n")]
    text = "|".join(ln for ln in lines if ln)
    if len(text.encode("utf-8")) > CANNED_MESSAGES_MAX:
        return None, (
            f"Canned Messages: zusammen maximal {CANNED_MESSAGES_MAX} Byte "
            f"(aktuell {len(text.encode('utf-8'))}) — bitte kürzen, es wird nichts abgeschnitten."
        )
    return text, None


def plan_ringtone(form: Any) -> Tuple[Optional[str], Optional[str]]:
    text = _form_get(form, "ringtone").strip()
    if len(text.encode("utf-8")) > RINGTONE_MAX:
        return None, f"Klingelton: maximal {RINGTONE_MAX} Byte (aktuell {len(text.encode('utf-8'))})."
    return text, None


def apply_canned_messages(iface_id: int, form: Any) -> Tuple[bool, str]:
    from meshtastic.protobuf import admin_pb2

    text, err = plan_canned_messages(form)
    if err:
        return False, err
    node, err = _node_for_iface(iface_id)
    if err:
        return False, err
    p = admin_pb2.AdminMessage()
    p.set_canned_message_module_messages = text or ""
    try:
        _send_admin(node, p)
    except Exception as e:
        return False, f"Canned Messages konnten nicht gesetzt werden: {e!s}"
    return True, f"Canned Messages gespeichert ({len((text or '').split('|')) if text else 0} Einträge)."


def apply_ringtone(iface_id: int, form: Any) -> Tuple[bool, str]:
    from meshtastic.protobuf import admin_pb2

    text, err = plan_ringtone(form)
    if err:
        return False, err
    node, err = _node_for_iface(iface_id)
    if err:
        return False, err
    p = admin_pb2.AdminMessage()
    p.set_ringtone_message = text or ""
    try:
        _send_admin(node, p)
    except Exception as e:
        return False, f"Klingelton konnte nicht gesetzt werden: {e!s}"
    return True, "Klingelton gespeichert."


# --- Administration actions ---


@dataclass(frozen=True)
class AdminAction:
    key: str
    label: str
    warning: str
    needs_word: bool = False
    needs_confirm: bool = True
    has_seconds: bool = False


ADMIN_ACTIONS: Tuple[AdminAction, ...] = (
    AdminAction("set_time", "Uhrzeit vom Bot-Rechner setzen",
                "Setzt die Uhr der Node auf die Systemzeit des Bot-Rechners.", needs_confirm=False),
    AdminAction("reboot", "Neustart", "Die Node startet neu; der Bot verbindet sich danach erneut.",
                has_seconds=True),
    AdminAction("shutdown", "Herunterfahren",
                "Die Node schaltet ab und ist erst nach Strom-Aus/-An bzw. Tastendruck wieder erreichbar.",
                has_seconds=True),
    AdminAction("nodedb_reset", "NodeDB zurücksetzen",
                "Löscht alle bekannten Nodes auf dem Gerät (Favoriten/Ignorierte inklusive)."),
    AdminAction("factory_reset_config", "Werksreset (Konfiguration)",
                "Setzt alle Einstellungen und Kanäle auf Werkseinstellung zurück — Region ist danach UNSET, "
                "die Node sendet nicht mehr, bis sie neu eingerichtet ist.", needs_word=True),
    AdminAction("factory_reset_device", "Werksreset (Gerät komplett)",
                "Wie Konfigurations-Reset, zusätzlich werden Schlüssel und NodeDB gelöscht — neue Identität.",
                needs_word=True),
)


def plan_admin_action(form: Any) -> Tuple[Optional[AdminAction], int, Optional[str]]:
    key = _form_get(form, "admin_op").strip()
    action = next((a for a in ADMIN_ACTIONS if a.key == key), None)
    if action is None:
        return None, 0, "Unbekannte Aktion."
    secs = 0
    if action.has_seconds:
        try:
            secs = int(_form_get(form, "seconds") or "5")
        except ValueError:
            return None, 0, "Verzögerung: bitte ganze Sekunden angeben."
        if not 0 <= secs <= 3600:
            return None, 0, "Verzögerung: 0–3600 Sekunden."
    if action.needs_confirm and not _is_checked(form, "confirm_admin"):
        return None, 0, f"{action.label} nicht ausgeführt: Bitte die Warnung bestätigen. {action.warning}"
    if action.needs_word and _form_get(form, "confirm_word").strip() != FACTORY_RESET_WORD:
        return None, 0, f"{action.label} nicht ausgeführt: Bitte zur Bestätigung „{FACTORY_RESET_WORD}“ eintippen."
    return action, secs, None


def _set_trigger(p: Message, field: str, value: int = 1) -> None:
    fd = p.DESCRIPTOR.fields_by_name[field]
    setattr(p, field, True if fd.type == FieldDescriptor.TYPE_BOOL else int(value))


def apply_admin_action(iface_id: int, form: Any) -> Tuple[bool, str]:
    from meshtastic.protobuf import admin_pb2

    action, secs, err = plan_admin_action(form)
    if err or action is None:
        return False, err or "Unbekannte Aktion."
    node, err = _node_for_iface(iface_id)
    if err:
        return False, err
    p = admin_pb2.AdminMessage()
    if action.key == "set_time":
        _set_trigger(p, "set_time_only", int(time.time()))
    elif action.key == "reboot":
        _set_trigger(p, "reboot_seconds", secs)
    elif action.key == "shutdown":
        _set_trigger(p, "shutdown_seconds", secs)
    else:
        _set_trigger(p, action.key)
    try:
        _send_admin(node, p)
    except Exception as e:
        return False, f"{action.label} fehlgeschlagen: {e!s}"
    when = f" in {secs} s" if action.has_seconds else ""
    return True, f"{action.label}{when} an die Node gesendet."


# --- HTML ---


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def build_tab_nav_html(current: str, *, iface_id: int, ifaces: Sequence[int], base_url: str,
                       excluded: Iterable[str] = ()) -> str:
    excluded_set = set(excluded)
    sep = "&" if "?" in base_url else "?"
    iface_links = " ".join(
        f'<a class="btn btn-sm {"btn-light" if i == iface_id else "btn-outline-secondary"}" '
        f'href="{_esc(base_url)}{sep}iface={i}&amp;tab={_esc(current)}">IF {i}</a>'
        for i in ifaces
    )
    rows = [f'<p class="small text-muted mb-2">Schnittstelle: {iface_links}</p>']
    tabs = available_tabs()
    for group, label in TAB_GROUP_LABELS.items():
        items = []
        for spec in tabs:
            if spec.group != group:
                continue
            active = spec.key == current
            cls = "nav-link py-1 px-2" + (" active" if active else "")
            aria = ' aria-current="page"' if active else ""
            muted = ' <span class="badge bg-secondary">n/v</span>' if spec.key in excluded_set else ""
            items.append(
                f'<li class="nav-item"><a class="{cls}" href="{_esc(base_url)}{sep}iface={iface_id}'
                f'&amp;tab={_esc(spec.key)}"{aria}>{_esc(spec.label)}{muted}</a></li>'
            )
        rows.append(
            f'<div class="d-flex flex-wrap align-items-center gap-2 mb-1">'
            f'<span class="small text-muted" style="min-width:9rem">{_esc(label)}</span>'
            f'<ul class="nav nav-pills small flex-wrap">{"".join(items)}</ul></div>'
        )
    return f'<div class="node-settings-tabs mb-3">{"".join(rows)}</div><hr class="mt-2 mb-3">'


def excluded_tab_keys(node: Any) -> List[str]:
    meta = getattr(getattr(node, "iface", None), "metadata", None)
    mask = int(getattr(meta, "excluded_modules", 0) or 0) if meta is not None else 0
    if not mask:
        return []
    try:
        from meshtastic.protobuf import mesh_pb2

        enum = mesh_pb2.ExcludedModules
    except Exception:
        return []
    out = []
    for spec in available_tabs():
        if spec.excluded_flag:
            try:
                if mask & enum.Value(spec.excluded_flag):
                    out.append(spec.key)
            except ValueError:
                continue
    return out


def _danger_block(path: str, meta: FieldMeta, *, repeat: bool = False) -> str:
    cid = f"cf-{path.replace('.', '-')}"
    if repeat:
        alert = ('<div class="small text-danger mt-2 mb-1"><i class="bi bi-exclamation-triangle"></i> '
                 "Warnung wie oben</div>")
    else:
        alert = (f'<div class="alert alert-danger small py-2 px-2 mt-2 mb-1"><strong>Warnung:</strong> '
                 f"{_esc(meta.danger)}</div>")
    return (
        f'{alert}<div class="form-check small"><input class="form-check-input" type="checkbox" id="{cid}" '
        f'name="{_esc(confirm_name(path))}" value="1"><label class="form-check-label" for="{cid}">'
        "Warnung gelesen — Änderung bewusst speichern</label></div>"
    )


def _input_html(section: str, ref: FieldRef, meta: FieldMeta, value: Any) -> str:
    fd = ref.fd
    path = ref.path
    fid = f"nf-{path.replace('.', '-')}"
    name = _esc(field_name(path))
    unit = f" ({_esc(meta.unit)})" if meta.unit else ""
    deprecated = ' <span class="badge bg-secondary">veraltet</span>' if _is_deprecated(fd) else ""
    label = f'<label class="form-label small mb-1" for="{fid}">{_esc(meta.label)}{unit}{deprecated}</label>'
    help_html = f'<div class="form-text">{_esc(meta.help)}</div>' if meta.help else ""
    tech = f'<div class="form-text font-monospace opacity-50">{_esc(section)}.{_esc(path)}</div>'

    if meta.widget == "readonly_b64":
        return (f'{label}<input class="form-control form-control-sm font-monospace" id="{fid}" readonly '
                f'value="{_esc(_b64(value) or "—")}">{help_html}{tech}')

    if meta.widget == "bitmask":
        enum = _enum_type(meta.flags_enum)
        boxes = []
        for vname, num in enum.items():
            if num == 0:
                continue
            chk = " checked" if int(value) & num else ""
            bid = f"{fid}-{num}"
            boxes.append(
                f'<div class="form-check form-check-inline small"><input class="form-check-input" type="checkbox" '
                f'id="{bid}" name="{name}" value="{num}"{chk}><label class="form-check-label" for="{bid}">'
                f"{_esc(vname)}</label></div>"
            )
        return f'<div class="small mb-1">{_esc(meta.label)}</div>{"".join(boxes)}{help_html}{tech}'

    if fd.type == FieldDescriptor.TYPE_BOOL and not _is_repeated(fd):
        chk = " checked" if value else ""
        return (
            f'<div class="form-check form-switch mt-4"><input class="form-check-input" type="checkbox" role="switch" '
            f'id="{fid}" name="{name}" value="1"{chk}><label class="form-check-label" for="{fid}">'
            f"{_esc(meta.label)}{deprecated}</label></div>{help_html}{tech}"
        )

    if fd.type == FieldDescriptor.TYPE_ENUM and not _is_repeated(fd):
        opts = "".join(
            f'<option value="{v.number}"{" selected" if v.number == int(value) else ""}>{_esc(v.name)}</option>'
            for v in fd.enum_type.values
        )
        if int(value) not in {v.number for v in fd.enum_type.values}:
            opts = f'<option value="{int(value)}" selected>{int(value)} (unbekannt)</option>' + opts
        return f'{label}<select class="form-select form-select-sm" id="{fid}" name="{name}">{opts}</select>{help_html}{tech}'

    if meta.widget in ("secret", "secret_b64"):
        state = "gesetzt" if value else "leer"
        clear_id = f"{fid}-clear"
        return (
            f'{label}<input class="form-control form-control-sm font-monospace" type="password" id="{fid}" '
            f'name="{name}" autocomplete="new-password" placeholder="leer = unverändert ({state})">'
            f'<div class="form-check small"><input class="form-check-input" type="checkbox" id="{clear_id}" '
            f'name="{_esc(clear_name(path))}" value="1"><label class="form-check-label" for="{clear_id}">leeren</label></div>'
            f"{help_html}{tech}"
        )

    if meta.widget == "ip":
        return (f'{label}<input class="form-control form-control-sm font-monospace" id="{fid}" name="{name}" '
                f'placeholder="0.0.0.0" value="{_esc(int_to_ip(value) if value else "")}">{help_html}{tech}')

    if meta.widget == "nodelist":
        txt = ", ".join(f"!{int(n):08x}" for n in value)
        return (f'{label}<input class="form-control form-control-sm font-monospace" id="{fid}" name="{name}" '
                f'value="{_esc(txt)}">{help_html}{tech}')

    if meta.widget == "b64list":
        txt = "\n".join(_b64(k) for k in value)
        return (f'{label}<textarea class="form-control form-control-sm font-monospace" rows="3" id="{fid}" '
                f'name="{name}">{_esc(txt)}</textarea>{help_html}{tech}')

    if meta.widget == "pins":
        sub = fd.message_type
        type_fd = sub.fields_by_name.get("type")
        lines = []
        for row in value:
            vals = dict(zip([f.name for f in sub.fields], row))
            tname = type_fd.enum_type.values_by_number[vals["type"]].name if type_fd else ""
            lines.append(f"{vals.get('gpio_pin', 0)};{vals.get('name', '')};{tname}")
        return (f'{label}<textarea class="form-control form-control-sm font-monospace" rows="4" id="{fid}" '
                f'name="{name}">{_esc(chr(10).join(lines))}</textarea>{help_html}{tech}')

    if fd.type in _INT_TYPES:
        lo, hi = _INT_TYPES[fd.type]
        lo = int(meta.min) if meta.min is not None else lo
        hi = int(meta.max) if meta.max is not None else hi
        return (f'{label}<input class="form-control form-control-sm" type="number" step="1" id="{fid}" '
                f'name="{name}" min="{lo}" max="{hi}" value="{int(value)}">{help_html}{tech}')

    if fd.type in _FLOAT_TYPES:
        return (f'{label}<input class="form-control form-control-sm" type="text" inputmode="decimal" id="{fid}" '
                f'name="{name}" value="{_esc(repr(float(value)) if value else "0")}">{help_html}{tech}')

    maxlen = f' maxlength="{meta.maxlen}"' if meta.maxlen else ""
    return (f'{label}<input class="form-control form-control-sm" id="{fid}" name="{name}"{maxlen} '
            f'value="{_esc(value)}">{help_html}{tech}')


def build_section_form_html(spec: TabSpec, current: Message, *, iface_id: int, reported: bool,
                            excluded: bool) -> str:
    cols = []
    hidden = []
    shown_warnings: set = set()
    for ref in iter_section_fields(current.DESCRIPTOR):
        meta = field_meta(spec.section, ref.path)
        value = get_value(current, ref)
        if not meta.readonly:
            hidden.append(f'<input type="hidden" name="present" value="{_esc(ref.path)}">')
        block = _input_html(spec.section, ref, meta, value)
        repeat = meta.danger in shown_warnings
        if meta.danger and not meta.readonly:
            block += _danger_block(ref.path, meta, repeat=repeat)
            shown_warnings.add(meta.danger)
        wide = meta.widget in ("bitmask", "b64list", "pins") or (bool(meta.danger) and not repeat)
        cols.append(
            f'<div class="{"col-12 col-lg-6" if wide else "col-sm-6 col-lg-4"}">'
            f'<div class="p-2 rounded border border-secondary-subtle h-100">{block}</div></div>'
        )
    notes = []
    if spec.intro:
        notes.append(f'<p class="small text-muted">{_esc(spec.intro)}</p>')
    if excluded:
        notes.append('<div class="alert alert-secondary small">Dieses Modul ist in der Firmware der Node nicht '
                     "enthalten (excluded_modules) — Werte werden gespeichert, aber nicht verwendet.</div>")
    if not reported:
        notes.append('<div class="alert alert-info small">Die Node hat diesen Bereich beim Verbinden nicht gemeldet '
                     "(ältere Firmware?). Angezeigt werden Standardwerte; Speichern schreibt sie auf das Gerät.</div>")
    return f"""
<h5 class="mb-2">{_esc(spec.label)}</h5>
{"".join(notes)}
<form method="post" class="node-config-form">
  <input type="hidden" name="action" value="save_section">
  <input type="hidden" name="iface_id" value="{iface_id}">
  <input type="hidden" name="section_tab" value="{_esc(spec.key)}">
  {"".join(hidden)}
  <div class="row g-2 mb-3">{"".join(cols)}</div>
  <button type="submit" class="btn btn-primary"
          onclick="return confirm('{_esc(spec.label)} auf dem Gerät speichern? Die Node startet ggf. neu.');">
    {_esc(spec.label)} auf Gerät speichern</button>
</form>
"""


def build_user_tab_html(user: Mapping[str, Any], *, iface_id: int) -> str:
    licensed = " checked" if user.get("isLicensed") else ""
    unmsg = " checked" if user.get("isUnmessagable") else ""
    return f"""
<h5 class="mb-2">Benutzer</h5>
<p class="small text-muted">Owner-Daten der Node. Hardware: <code>{_esc(user.get("hwModel") or "—")}</code>
  · ID <code>{_esc(user.get("id") or "—")}</code></p>
<form method="post" class="node-config-form">
  <input type="hidden" name="action" value="save_owner">
  <input type="hidden" name="iface_id" value="{iface_id}">
  <div class="row g-3 mb-3">
    <div class="col-md-8">
      <label class="form-label" for="us-long">Langname (max. 39 Byte)</label>
      <input class="form-control" id="us-long" name="long_name" maxlength="39" required
             value="{_esc(user.get("longName") or "")}">
    </div>
    <div class="col-md-4">
      <label class="form-label" for="us-short">Kurzname (max. 4)</label>
      <input class="form-control" id="us-short" name="short_name" maxlength="4" required
             value="{_esc(user.get("shortName") or "")}">
    </div>
    <div class="col-md-6">
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" role="switch" id="us-unmsg" name="is_unmessagable"
               value="1"{unmsg}>
        <label class="form-check-label" for="us-unmsg">Nicht anschreibbar (Infrastruktur-Node)</label>
      </div>
    </div>
    <div class="col-md-6">
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" role="switch" id="us-ham" name="is_licensed"
               value="1"{licensed}>
        <label class="form-check-label" for="us-ham">Lizenzierter Funkamateur (HAM)</label>
      </div>
      <div class="alert alert-danger small py-2 px-2 mt-2 mb-1"><strong>Warnung:</strong> {_esc(HAM_WARNING)}</div>
      <div class="form-check small">
        <input class="form-check-input" type="checkbox" id="us-ham-confirm" name="confirm__is_licensed" value="1">
        <label class="form-check-label" for="us-ham-confirm">Warnung gelesen — Amateurfunk-Modus bewusst aktivieren</label>
      </div>
    </div>
  </div>
  <button type="submit" class="btn btn-primary"
          onclick="return confirm('Benutzer auf dem Gerät speichern?');">Benutzer auf Gerät speichern</button>
</form>
"""


def build_canned_messages_html(text: Optional[str], err: Optional[str], *, iface_id: int) -> str:
    lines = "\n".join((text or "").split("|")) if text else ""
    status = (f'<div class="alert alert-warning small">Aktuelle Nachrichten nicht gelesen: {_esc(err)}</div>'
              if err else "")
    return f"""
<hr class="my-4">
<h5 class="mb-2">Canned-Message-Texte</h5>
{status}
<form method="post">
  <input type="hidden" name="action" value="save_canned_messages">
  <input type="hidden" name="iface_id" value="{iface_id}">
  <label class="form-label small" for="cm-text">Eine Nachricht pro Zeile (zusammen max. {CANNED_MESSAGES_MAX} Byte)</label>
  <textarea class="form-control font-monospace mb-2" rows="6" id="cm-text" name="canned_messages">{_esc(lines)}</textarea>
  <button type="submit" class="btn btn-outline-primary btn-sm"
          onclick="return confirm('Canned Messages auf dem Gerät speichern?');">Texte speichern</button>
</form>
"""


def build_ringtone_html(text: Optional[str], err: Optional[str], *, iface_id: int) -> str:
    status = (f'<div class="alert alert-warning small">Aktueller Klingelton nicht gelesen: {_esc(err)}</div>'
              if err else "")
    return f"""
<hr class="my-4">
<h5 class="mb-2">Klingelton (RTTTL)</h5>
{status}
<form method="post">
  <input type="hidden" name="action" value="save_ringtone">
  <input type="hidden" name="iface_id" value="{iface_id}">
  <label class="form-label small" for="rt-text">RTTTL, max. {RINGTONE_MAX} Byte</label>
  <input class="form-control font-monospace mb-2" id="rt-text" name="ringtone" value="{_esc(text or "")}">
  <button type="submit" class="btn btn-outline-primary btn-sm"
          onclick="return confirm('Klingelton auf dem Gerät speichern?');">Klingelton speichern</button>
</form>
"""


def _metadata_rows(node: Any) -> str:
    meta = getattr(getattr(node, "iface", None), "metadata", None)
    if meta is None:
        return '<p class="small text-muted">Keine Geräte-Metadaten vom Gerät erhalten.</p>'
    rows = []
    for fd in meta.DESCRIPTOR.fields:
        val = getattr(meta, fd.name)
        if fd.type == FieldDescriptor.TYPE_ENUM:
            try:
                val = fd.enum_type.values_by_number[int(val)].name
            except KeyError:
                pass
        rows.append(f"<tr><th class=\"fw-normal text-muted\">{_esc(fd.name)}</th><td><code>{_esc(val)}</code></td></tr>")
    return f'<table class="table table-sm small w-auto">{"".join(rows)}</table>'


def build_admin_tab_html(node: Any, *, iface_id: int) -> str:
    cards = []
    for a in ADMIN_ACTIONS:
        secs = ""
        if a.has_seconds:
            secs = (f'<div class="col-auto"><label class="form-label small mb-0" for="adm-s-{a.key}">Verzögerung (s)</label>'
                    f'<input class="form-control form-control-sm" style="width:6rem" type="number" min="0" max="3600" '
                    f'id="adm-s-{a.key}" name="seconds" value="5"></div>')
        confirm = ""
        if a.needs_confirm:
            confirm = (f'<div class="col-12"><div class="form-check small"><input class="form-check-input" '
                       f'type="checkbox" id="adm-c-{a.key}" name="confirm_admin" value="1">'
                       f'<label class="form-check-label" for="adm-c-{a.key}">Warnung gelesen — bewusst ausführen</label>'
                       "</div></div>")
        word = ""
        if a.needs_word:
            word = (f'<div class="col-auto"><label class="form-label small mb-0" for="adm-w-{a.key}">'
                    f'„{FACTORY_RESET_WORD}“ eintippen</label><input class="form-control form-control-sm" '
                    f'style="width:8rem" id="adm-w-{a.key}" name="confirm_word" autocomplete="off"></div>')
        tone = "danger" if a.needs_word or a.key in ("shutdown", "nodedb_reset") else "warning"
        if not a.needs_confirm:
            tone = "secondary"
        cards.append(f"""
<div class="col-md-6">
  <div class="card border-{tone}-subtle h-100"><div class="card-body py-2">
    <h6 class="card-title mb-1">{_esc(a.label)}</h6>
    <p class="small text-muted mb-2">{_esc(a.warning)}</p>
    <form method="post" class="row g-2 align-items-end">
      <input type="hidden" name="action" value="admin_action">
      <input type="hidden" name="iface_id" value="{iface_id}">
      <input type="hidden" name="admin_op" value="{_esc(a.key)}">
      {secs}{word}{confirm}
      <div class="col-auto"><button type="submit" class="btn btn-sm btn-outline-{tone if tone != "secondary" else "primary"}"
        onclick="return confirm('{_esc(a.label)} wirklich ausführen?');">{_esc(a.label)}</button></div>
    </form>
  </div></div>
</div>""")
    return f"""
<h5 class="mb-2">Administration</h5>
<p class="small text-muted">Aktionen gehen direkt an die lokal verbundene Node (Admin-API).
  Gefährliche Aktionen brauchen eine Bestätigung; Werksresets zusätzlich das Wort „{FACTORY_RESET_WORD}“.</p>
<div class="row g-3 mb-4">{"".join(cards)}</div>
<h6>Geräte-Metadaten</h6>
{_metadata_rows(node)}
"""


def build_config_tab_html(spec: TabSpec, node: Any, *, iface_id: int, read_strings: bool = True) -> str:
    store = _section_store(node, spec.kind)
    if store is None:
        return '<p class="alert alert-warning">Konfiguration der Node wurde noch nicht gelesen.</p>'
    current = getattr(store, spec.section)
    try:
        reported = store.HasField(spec.section)
    except ValueError:
        reported = True
    body = build_section_form_html(spec, current, iface_id=iface_id, reported=reported,
                                   excluded=spec.key in excluded_tab_keys(node))
    if spec.section == "canned_message":
        text, err = (request_admin_string(node, "get_canned_message_module_messages_request",
                                          "get_canned_message_module_messages_response")
                     if read_strings else (None, "nicht abgefragt"))
        body += build_canned_messages_html(text, err, iface_id=iface_id)
    if spec.section == "external_notification":
        text, err = (request_admin_string(node, "get_ringtone_request", "get_ringtone_response")
                     if read_strings else (None, "nicht abgefragt"))
        body += build_ringtone_html(text, err, iface_id=iface_id)
    return body


def build_node_settings_tab_page(tab_key: Optional[str], *, iface_id: int, ifaces: Sequence[int],
                                 base_url: str) -> str:
    """Full Node Settings page body: interface selector, Companion-style sub-tabs, active tab content."""
    from modules import admin_web_ops as ops

    spec = tab_by_key(tab_key)
    node, err = _node_for_iface(iface_id)
    excluded = excluded_tab_keys(node) if node is not None else []
    nav = build_tab_nav_html(spec.key, iface_id=iface_id, ifaces=ifaces, base_url=base_url, excluded=excluded)
    if err:
        return nav + f'<p class="alert alert-danger">{_esc(err)}</p>'

    if spec.key == "overview":
        read_err, settings = ops.fetch_local_node_settings(iface_id)
        if read_err or not settings:
            return nav + f'<p class="alert alert-danger">{_esc(read_err or "Unbekannter Fehler")}</p>'
        return nav + ops.build_node_settings_html(
            settings, iface_id=iface_id, ifaces=list(ifaces), form_action=base_url, show_iface_selector=False
        )
    if spec.key == "channels":
        ch_err, channels = ops.fetch_local_channels(iface_id)
        if ch_err:
            return nav + f'<h5>Mesh-Kanäle</h5><p class="alert alert-warning">{_esc(ch_err)}</p>'
        channels_html = ops.build_channels_settings_html(channels or [], iface_id=iface_id, form_action=base_url)
        return nav + channels_html.strip().removeprefix('<hr class="my-4">')
    if spec.key == "user":
        return nav + build_user_tab_html(_my_user(node), iface_id=iface_id)
    if spec.key == "admin":
        return nav + build_admin_tab_html(node, iface_id=iface_id)
    return nav + build_config_tab_html(spec, node, iface_id=iface_id)


def dispatch_post(iface_id: int, form: Any) -> Tuple[bool, str]:
    """Route a Node Settings POST by its ``action`` field."""
    from modules import admin_web_ops as ops

    action = _form_get(form, "action").strip()
    if action == "save_channel":
        return ops.apply_local_channel_settings(iface_id, form)
    if action == "save_section":
        return apply_section(iface_id, _form_get(form, "section_tab").strip(), form)
    if action == "save_owner":
        return apply_owner(iface_id, form)
    if action == "save_canned_messages":
        return apply_canned_messages(iface_id, form)
    if action == "save_ringtone":
        return apply_ringtone(iface_id, form)
    if action == "admin_action":
        return apply_admin_action(iface_id, form)
    return ops.apply_local_node_settings(iface_id, form)
