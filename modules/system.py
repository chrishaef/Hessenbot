# helper functions and init for system related tasks
# K7MHI Kelly Keeton 2024

import meshtastic.serial_interface #pip install meshtastic or use launch.sh for venv
import meshtastic.tcp_interface
import meshtastic.ble_interface
import time
import json
import asyncio
import urllib.request
import random
import re
import base64
# not ideal but needed?
import contextlib # for suppressing output on watchdog
import io # for suppressing output on watchdog
# homebrew 'modules'
from modules.settings import *
from modules.log import logger, getPrettyTime, CustomFormatter
from modules.paths import ensure_parent_dir, path_in_repo
import modules.nodedb as _ndb


def _mesh_leaderboard_pkl_path() -> str:
    return path_in_repo("data/leaderboard.pkl")


# Global Variables
trap_list = ("cmd","cmd?","bannode",) # base commands
from modules.locale_de import HELP_PREFIX

help_message = HELP_PREFIX
asyncLoop = asyncio.new_event_loop()
games_enabled = False
multiPingList = [{'message_from_id': 0, 'count': 0, 'type': '', 'deviceID': 0, 'channel_number': 0, 'startCount': 0}]
interface_retry_count = 3
_interface_reconnecting: set[int] = set()

# Ping Configuration
if ping_enabled:
    # ping, pinging, ack, testing, test, pong
    trap_list_ping = ("ping", "pinging", "ack", "testing", "test", "pong", "🔔", "cq","cqcq", "cqcqcq")
    trap_list = trap_list + trap_list_ping
    help_message = help_message + "ping"

# Echo Configuration
if enableEcho:
    trap_list_echo = ("echo",)
    trap_list = trap_list + trap_list_echo
    help_message = help_message + ", echo"

# Sitrep Configuration
if sitrep_enabled:
    trap_list_sitrep = ("sitrep", "lheard", "sysinfo", "leaderboard")
    trap_list = trap_list + trap_list_sitrep
    help_message = help_message + ", sitrep, sysinfo, leaderboard"

# MOTD Configuration
if motd_enabled:
    trap_list_motd = ("motd",)
    trap_list = trap_list + trap_list_motd
    help_message = help_message + ", motd"

# SMTP Configuration
if enableSMTP:
    from modules.smtp import * # from the spudgunman/meshing-around repo
    trap_list = trap_list + trap_list_smtp
    help_message = help_message + ", email:, sms:"

# Emergency Responder Configuration
if emergency_responder_enabled:
    trap_list_emergency = ("emergency", "911", "112", "999", "police", "fire", "ambulance", "rescue")
    trap_list = trap_list + trap_list_emergency
    
# whoami Configuration
if whoami_enabled:
    trap_list_whoami = ("whoami", "📍", "whois")
    trap_list = trap_list + trap_list_whoami
    help_message = help_message + ", whoami"

# Solar Conditions Configuration
if solar_conditions_enabled:
    from modules.space import * # from the spudgunman/meshing-around repo
    trap_list = trap_list + trap_list_solarconditions # items hfcond, solar, sun, moon
    help_message = help_message + ", sun, hfcond, solar, moon"
    if n2yoAPIKey != "":
        help_message = help_message + ", satpass"
else:
    hf_band_conditions = False

# Command History Configuration
if enableCmdHistory:
    trap_list = trap_list + ("history",)
    #help_message = help_message + ", history"
    
# Location Configuration
if location_enabled:
    from modules.locationdata import * # from the spudgunman/meshing-around repo
    trap_list = trap_list + trap_list_location
    help_message = help_message + ", whereami, wx, howfar, loc"
    if metar_enabled:
        from modules.metar import trap_list_metar

        trap_list = trap_list + trap_list_metar
        help_message = help_message + ", metar"
    if enableDEalerts:
        from modules.globalalert import * # from the spudgunman/meshing-around repo
        trap_list = trap_list + trap_list_location_de
        help_message = help_message + ", dealert, warning"
    
    # Open-Meteo Configuration for worldwide weather
    if use_meteo_wxApi:
        from modules.wx_meteo import * # from the spudgunman/meshing-around repo
    if wx_extra_commands and use_meteo_wxApi:
        from modules.wx_extra import trap_list_wx_extra

        trap_list = trap_list + trap_list_wx_extra
        help_message = help_message + ", uv, regen, blitz"
    if repeater_lookup != False:
        help_message = help_message + ", rlist"

    if solar_conditions_enabled:
        help_message = help_message + ", howtall"

# BBS Configuration
if bbs_enabled:
    from modules.bbstools import * # from the spudgunman/meshing-around repo
    trap_list = trap_list + trap_list_bbs # items bbslist, bbspost, bbsread, bbsdelete, bbshelp
    help_message = help_message + ", bbslist, bbshelp"
else:
    bbs_help = False
    bbs_list_messages = False

if polls_enabled:
    from modules.polls import *  # poll
    trap_list = trap_list + trap_list_polls
    help_message = help_message + ", poll"

if dxspotter_enabled:
    from modules.dxspot import handledxcluster
    trap_list = trap_list + ("dx",)
    help_message = help_message + ", dx"

# Wikipedia Search Configuration
if wikipedia_enabled or use_kiwix_server:
    from modules.wiki import get_wikipedia_summary, get_kiwix_summary, get_wikipedia_summary
    trap_list = trap_list + ("wiki",)
    help_message = help_message + ", wiki"

# RSS Feed Configuration
if rssEnable or enable_headlines:
    if rssEnable:
        from modules.rss import get_rss_feed
        trap_list = trap_list + ("readrss",)
        help_message = help_message + ", readrss"
    if enable_headlines:
        from modules.rss import get_newsAPI
        trap_list = trap_list + ("latest",)
        help_message = help_message + ", latest"

# LLM Configuration
if llm_enabled:
    from modules.llm import * # from the spudgunman/meshing-around repo
    trap_list = trap_list + trap_list_llm # items ask:
    help_message = help_message + ", askai"

gamesCmdList = ""

# Sentry Configuration
if sentry_enabled:
    from math import sqrt
    import geopy.distance # pip install geopy

# Store and Forward Configuration
if store_forward_enabled:
    trap_list = trap_list + ("messages",)
    help_message = help_message + ", messages"

# QRZ Configuration
if qrz_hello_enabled:
    from modules.qrz import * # from the spudgunman/meshing-around repo
    #trap_list = trap_list + trap_list_qrz # items qrz, qrz?, qrzcall
    #help_message = help_message + ", qrz"

# CheckList Configuration
if checklist_enabled:
    from modules.checklist import * # from the spudgunman/meshing-around repo
    trap_list = trap_list + trap_list_checklist # items checkin, checkout, checklist, purgein, purgeout
    help_message = help_message + ", checkin, checkout"

# Inventory and POS Configuration
if inventory_enabled:
    from modules.inventory import * # from the spudgunman/meshing-around repo
    trap_list = trap_list + trap_list_inventory # items item, itemlist, itemsell, etc.
    help_message = help_message + ", item, cart"

# File Monitor Configuration
if file_monitor_enabled or read_news_enabled or bee_enabled or enable_runShellCmd or cmdShellSentryAlerts:
    from modules.filemon import * # from the spudgunman/meshing-around repo
    if read_news_enabled:
        trap_list = trap_list + trap_list_filemon # items readnews
        help_message = help_message + ", readnews"
    # Bee Configuration uses file monitor module
    if bee_enabled:
        trap_list = trap_list + ("🐝",)
    # x: command for shell access
    if enable_runShellCmd and allowXcmd:
        trap_list = trap_list + ("x:",)

# clean up the help message
help_message = help_message.split(", ")
help_message.sort()
if len(help_message) > 20:
    # split in half for formatting
    help_message = help_message[:len(help_message)//2] + ["\nCMD?"] + help_message[len(help_message)//2:]
help_message = ", ".join(help_message)

# BLE dual interface prevention
ble_count = sum(1 for i in range(1, 10) if globals().get(f'interface{i}_type') == 'ble')
if ble_count > 1:
    logger.critical(f"System: Multiple BLE interfaces detected. Only one BLE interface is allowed. Exiting")
    exit()

def _tcp_host_port_for_interface(iface_num: int) -> tuple[str, int]:
    """Parse [interfaceN] hostname (optional host:port) for meshtasticd TCP."""
    host = globals().get(f"hostname{iface_num}", "127.0.0.1")
    port = 4403
    if isinstance(host, str) and ":" in host:
        maybe_host, maybe_port = host.rsplit(":", 1)
        if maybe_port.isdigit():
            host = maybe_host
            try:
                port = int(maybe_port)
            except ValueError:
                port = 4403
    return str(host), port


def open_mesh_interface(iface_num: int):
    """Open serial/tcp/ble interface (same options as startup and reconnect)."""
    interface_type = globals().get(f"interface{iface_num}_type")
    if interface_type == "serial":
        return meshtastic.serial_interface.SerialInterface(globals().get(f"port{iface_num}"))
    if interface_type == "tcp":
        host, port = _tcp_host_port_for_interface(iface_num)
        logger.debug(f"System: TCP interface{iface_num} -> {host}:{port}")
        return meshtastic.tcp_interface.TCPInterface(hostname=host, portNumber=port)
    if interface_type == "ble":
        return meshtastic.ble_interface.BLEInterface(globals().get(f"mac{iface_num}"))
    raise ValueError(f"Unsupported interface type: {interface_type!r}")


def mesh_interface_index(iface) -> int | None:
    for i in range(1, 10):
        if globals().get(f"interface{i}") is iface:
            return i
    return None


def mark_interface_for_retry(iface_num: int, reason: str = "") -> None:
    if 1 <= iface_num <= 9 and globals().get(f"interface{iface_num}_enabled"):
        globals()[f"retry_int{iface_num}"] = True
        if reason:
            logger.warning(f"System: interface{iface_num} queued for reconnect ({reason})")


# Initialize interfaces
logger.debug(f"System: Initializing Interfaces")
interface1 = interface2 = interface3 = interface4 = interface5 = interface6 = interface7 = interface8 = interface9 = None
retry_int1 = retry_int2 = retry_int3 = retry_int4 = retry_int5 = retry_int6 = retry_int7 = retry_int8 = retry_int9 = False
myNodeNum1 = myNodeNum2 = myNodeNum3 = myNodeNum4 = myNodeNum5 = myNodeNum6 = myNodeNum7 = myNodeNum8 = myNodeNum9 = 777
max_retry_count1 = max_retry_count2 = max_retry_count3 = max_retry_count4 = max_retry_count5 = max_retry_count6 = max_retry_count7 = max_retry_count8 = max_retry_count9 = interface_retry_count
for i in range(1, 10):
    interface_type = globals().get(f'interface{i}_type')
    if not interface_type or interface_type == 'none' or globals().get(f'interface{i}_enabled') == False:
        # no valid interface found
        continue
    try:
        if globals().get(f'interface{i}_enabled'):
            globals()[f'interface{i}'] = open_mesh_interface(i)
    except Exception as e:
        globals()[f'interface{i}'] = None
        mark_interface_for_retry(i, f"startup failed: {e}")
        logger.critical(
            f"System: Interface{i} not available at startup ({e}). "
            "Bot continues (web UI, watchdog); start meshtasticd or fix hostname/port."
        )

# Populate persistent nodeDB from all interfaces that came up
for _i in range(1, 10):
    _iface = globals().get(f'interface{_i}')
    if _iface is not None:
        _ndb.populate_from_interface(_iface)

# Get my node numbers for global use
my_node_ids = [globals().get(f'myNodeNum{i}') for i in range(1, 10)]

# Get the node number of the devices, check if the devices are connected meshtastic devices
for i in range(1, 10):
    if globals().get(f'interface{i}') and globals().get(f'interface{i}_enabled'):
        try:
            globals()[f'myNodeNum{i}'] = globals()[f'interface{i}'].getMyNodeInfo()['num']
            logger.debug(f"System: Initalized Radio Device{i} Node Number: {globals()[f'myNodeNum{i}']}")
        except Exception as e:
            logger.critical(f"System: critical error initializing interface{i} {e}")
    else:
        globals()[f'myNodeNum{i}'] = 777

# Fetch channel list from each device
_channel_cache = None

def build_channel_cache(force_refresh: bool = False):
    """
    Build and cache channel_list from interfaces once (or when forced).
    """
    global _channel_cache
    if _channel_cache is not None and not force_refresh:
        return _channel_cache

    cache = []
    for i in range(1, 10):
        if not globals().get(f'interface{i}') or not globals().get(f'interface{i}_enabled'):
            continue
        try:
            node = globals()[f'interface{i}'].getNode('^local')
            # Try to use the node-provided channel/hash table if available
            try:
                ch_hash_table_raw = node.get_channels_with_hash()
                #print(f"System: Device{i} Channel Hash Table: {ch_hash_table_raw}")
            except Exception:
                logger.warning(f"System: API version error update API `pip3 install --upgrade meshtastic[cli]`")
                ch_hash_table_raw = []

            channel_dict = {}
            # Use the hash table as the source of truth for channels
            if isinstance(ch_hash_table_raw, list):
                for entry in ch_hash_table_raw:
                    channel_name = entry.get("name", "").strip()
                    channel_number = entry.get("index")
                    ch_hash = entry.get("hash")
                    role = entry.get("role", "")
                    # Always add PRIMARY/SECONDARY channels, even if name is empty
                    if role in ("PRIMARY", "SECONDARY"):
                        channel_dict[channel_name if channel_name else f"Channel{channel_number}"] = {
                            "number": channel_number,
                            "hash": ch_hash
                        }
            elif isinstance(ch_hash_table_raw, dict):
                for channel_name, ch_hash in ch_hash_table_raw.items():
                    channel_dict[channel_name] = {"number": None, "hash": ch_hash}
            # Always add the interface, even if no named channels
            cache.append({"interface_id": i, "channels": channel_dict})
            logger.debug(f"System: Fetched Channel List from Device{i} (cached)")
        except Exception as e:
            logger.debug(f"System: Error fetching channel list from Device{i}: {e}")

    _channel_cache = cache
    return _channel_cache

def refresh_channel_cache():
    """Force rebuild of channel cache (call only when channel config changes)."""
    return build_channel_cache(force_refresh=True)

channel_list = build_channel_cache()
#print(f"System: Channel Cache Built: {channel_list}")

#### FUN-ctions ####
def resolve_channel_name(channel_number, rxNode=1, interface_obj=None):
    """
    Resolve a channel number/hash to its name using cached channel list.
    """
    try:
        # ensure cache exists (cheap)
        cached = build_channel_cache()
        # quick search in cache first (no node calls)
        for device in cached:
            if rxNode and device.get("interface_id") != rxNode:
                continue
            device_channels = device.get("channels", {}) or {}
            # info is dict: {name: {'number': X, 'hash': Y}}
            for chan_name, info in device_channels.items():
                try:
                    if isinstance(info, dict):
                        if str(info.get('number')) == str(channel_number) or str(info.get('hash')) == str(channel_number):
                            return (chan_name, info.get('number') or info.get('hash'))
                    else:
                        if str(info) == str(channel_number):
                            return (chan_name, info)
                except Exception:
                    continue
            if rxNode:
                break
        # fallback: any interface (e.g. dashboard without rxNode)
        if rxNode:
            for device in cached:
                device_channels = device.get("channels", {}) or {}
                for chan_name, info in device_channels.items():
                    try:
                        if isinstance(info, dict):
                            if str(info.get('number')) == str(channel_number) or str(info.get('hash')) == str(channel_number):
                                return (chan_name, info.get('number') or info.get('hash'))
                    except Exception:
                        continue
    except Exception as e:
        logger.debug(f"System: Error resolving channel name from cache: {e}")


def format_channel_label(channel_number, rxNode=1, interface_obj=None) -> str:
    """Configured Meshtastic channel name, e.g. '#1MeshHessen', or 'Kanal N'."""
    if channel_number is None:
        return "?"
    try:
        ch = int(channel_number)
    except (TypeError, ValueError):
        return str(channel_number)
    res = resolve_channel_name(ch, rxNode, interface_obj)
    if res and res[0] and str(res[0]).strip():
        name = str(res[0]).strip()
        if name.lower() != "unknown" and name != f"Channel{ch}":
            return name
    return f"Kanal {ch}"


def format_channel_log(channel_number, rxNode=1, interface_obj=None) -> str:
    """
    Log token: Channel:1|#1MeshHessen (index + name) or Channel:1 if unnamed.
    Parser-friendly; human-readable in meshbot.log.
    """
    if channel_number is None:
        return "Channel:?"
    try:
        ch = int(channel_number)
    except (TypeError, ValueError):
        return f"Channel:{channel_number}"
    label = format_channel_label(ch, rxNode, interface_obj)
    if label == f"Kanal {ch}":
        return f"Channel:{ch}"
    safe = label.replace("|", "/")
    return f"Channel:{ch}|{safe}"


def parse_channel_log_field(field: str, rxNode=1):
    """
    Parse Channel: token from logs. Returns (channel_index, display_label).
    Supports Channel:1, Channel:1|#1MeshHessen, Channel: 1 (legacy).
    """
    if field is None:
        return None, "?"
    raw = str(field).strip()
    if not raw.lower().startswith("channel:"):
        raw = f"Channel:{raw}"
    body = raw.split(":", 1)[1].strip()
    if "|" in body:
        num_s, name = body.split("|", 1)
        try:
            return int(num_s), name.strip()
        except ValueError:
            return None, name.strip()
    if body.isdigit():
        ch = int(body)
        return ch, format_channel_label(ch, rxNode)
    # name-only (new logs with named channel only)
    cached = build_channel_cache()
    for device in cached:
        if rxNode and device.get("interface_id") != rxNode:
            continue
        for chan_name, info in (device.get("channels") or {}).items():
            if chan_name == body and isinstance(info, dict) and info.get("number") is not None:
                return int(info["number"]), body
    return None, body


def cleanup_memory():
    """Clean up memory by limiting list sizes and removing stale entries"""
    global cmdHistory, seenNodes, multiPingList, waitingXroom
    current_time = time.time()
    
    try:
        # Limit cmdHistory size
        if 'cmdHistory' in globals() and len(cmdHistory) > MAX_CMD_HISTORY:
            cmdHistory = cmdHistory[-(MAX_CMD_HISTORY - 50):] # keep the most recent 50 entries
            logger.debug(f"System: Trimmed cmdHistory to {len(cmdHistory)} entries")
        
        # limit waitingXroom size by time
        if 'waitingXroom' in globals():
            initial_count = len(waitingXroom)
            to_delete = [key for key, (_, _, ts) in waitingXroom.items() if current_time - ts.timestamp() > xCmd2factor_timeout]
            for key in to_delete:
                del waitingXroom[key]
            cleaned_count = initial_count - len(waitingXroom)
            if cleaned_count > 0:
                logger.debug(f"System: Cleaned up {cleaned_count} stale entries from waitingXroom")

        # Clean up old seenNodes entries
        if 'seenNodes' in globals():
            initial_count = len(seenNodes)
            if len(seenNodes) > MAX_SEEN_NODES:
                # cut the list in half if it exceeds max size
                seenNodes = seenNodes[-(MAX_SEEN_NODES // 2):]
                logger.warning(f"System: Trimmed seenNodes to {len(seenNodes)} entries due to size limit of {MAX_SEEN_NODES}")
        
        # # Clean up multiPingList of completed or stale entries
        # if 'multiPingList' in globals():
        #     multiPingList[:] = [ping for ping in multiPingList
        #                       if ping.get('message_from_id', 0) != 0 and
        #                       ping.get('count', 0) > 0]

        # Clean up stale entries from cmd rate tracker
        if _cmd_rate_tracker:
            cutoff = current_time - cmdRateLimitWindow
            stale = [k for k, ts_list in _cmd_rate_tracker.items() if not any(t > cutoff for t in ts_list)]
            for k in stale:
                del _cmd_rate_tracker[k]

        # Clean up stale nodeDB entries (only when >1000 and older than 60 days)
        _ndb.cleanup_nodedb()

    except Exception as e:
        logger.error(f"System: Error during memory cleanup: {e}")

def decimal_to_hex(decimal_number):
    return f"!{decimal_number:08x}"


def _hop_count_label(hop_n: int | None) -> str:
    if hop_n is None:
        return "? Hops"
    if hop_n == 1:
        return "1 Hop"
    return f"{hop_n} Hops"


def _parse_hop_info(hop: str) -> tuple[int | None, str]:
    """Hop-Anzahl und Verbindungstyp (LoRa / MQTT) aus der Paket-Hop-Zeichenkette."""
    hop_s = (hop or "").strip()
    m = re.search(r"(\d+)\s*Hop", hop_s, re.I)
    hop_n = int(m.group(1)) if m else None
    upper = hop_s.upper()
    if "MQTT" in upper:
        return (hop_n if hop_n is not None else 0), "MQTT"
    if "GATEWAY" in upper or hop_s.startswith("Gateway"):
        return (hop_n if hop_n is not None else 0), "MQTT"
    if hop_s == "Direct" or hop_s.startswith("Direct"):
        return 0, "LoRa"
    if hop_n is not None:
        return hop_n, "LoRa"
    return None, "LoRa"


def bot_place_name() -> str:
    if location_enabled:
        try:
            from modules.locationdata import get_place_name

            return get_place_name(latitudeValue, longitudeValue)
        except Exception:
            pass
    return "Meshhessen"


def format_ping_qsl_response(
    message_from_id,
    deviceID,
    hop: str,
    keyword: str = "QSL",
) -> str:
    """
    QSL-Antwort: LongName [NodeID] KEYWORD @ "Bot-Standort" | N Hops LoRa|MQTT
    """
    long_name = get_name_from_number(message_from_id, "long", deviceID)
    if not long_name or str(long_name).startswith("!"):
        long_name = get_name_from_number(message_from_id, "short", deviceID)
    node_hex = decimal_to_hex(message_from_id)
    place = bot_place_name()
    hop_n, link = _parse_hop_info(hop)
    hop_part = _hop_count_label(hop_n)
    return f'{long_name} [{node_hex}] {keyword} @ "{place}" | {hop_part} {link}'


def get_name_from_number(number, type='long', nodeInt=1):
    interface = globals().get(f'interface{nodeInt}')
    if interface is not None:
        try:
            for node in interface.nodes.values():
                if number == node['num']:
                    user = node.get('user') or {}
                    long_n = user.get('longName', '')
                    short_n = user.get('shortName', '')
                    # opportunistically keep nodeDB warm
                    _ndb.update_node(number,
                                     long_name=long_n or None,
                                     short_name=short_n or None,
                                     public_key=user.get('publicKey') or None)
                    return long_n if type == 'long' else short_n
        except Exception:
            pass

    # interface missing or node not in interface.nodes — try persistent nodeDB
    if type == 'long':
        cached = _ndb.get_node_long_name(number)
    else:
        cached = _ndb.get_node_short_name(number)
    if cached:
        return cached

    return str(decimal_to_hex(number))

def get_num_from_short_name(short_name, nodeInt=1):
    # First, search the specified interface
    interface = globals()[f'interface{nodeInt}']
    logger.debug(f"System: Checking Node Number from Short Name: {short_name} on Device: {nodeInt}")
    for node in interface.nodes.values():
        if short_name == node['user']['shortName'] or str(short_name).lower() == node['user']['shortName'].lower():
            return node['num']

    # If not found, search all other enabled interfaces
    for iface_num in range(1, 10):
        if iface_num == nodeInt:
            continue
        if globals().get(f'interface{iface_num}_enabled'):
            other_interface = globals().get(f'interface{iface_num}')
            for node in other_interface.nodes.values():
                if short_name == node['user']['shortName'] or str(short_name).lower() == node['user']['shortName'].lower():
                    logger.debug(f"System: Found Device:{iface_num} Node:{node['user']['shortName']}")
                    return node['num']

    # !hex node IDs
    if str(short_name).startswith("!"):
        try:
            return int(short_name[1:], 16)
        except Exception:
            pass

    return 0


def _enabled_interface_order(preferred: int = 1):
    """Interface indices to search (preferred first)."""
    order = []
    if globals().get(f"interface{preferred}_enabled"):
        order.append(preferred)
    for i in range(1, 10):
        if i != preferred and globals().get(f"interface{i}_enabled"):
            order.append(i)
    return order or [preferred]


def resolve_mesh_node_target(message, nodeInt=1, default_id=None):
    """
    Parse a node reference from a command message (short name, decimal id, !hex).
    Returns (node_id, error_message). node_id is 0 if unresolved.
    """
    parts = (message or "").strip().split(maxsplit=1)
    token = parts[1].strip() if len(parts) > 1 else ""
    if not token:
        if default_id is not None:
            try:
                return int(default_id), None
            except (TypeError, ValueError):
                return 0, "Ungültige Knoten-ID."
        return 0, "Bitte Kurzname, Dezimal-ID oder !xxxxxxxx angeben."

    if token.startswith("!") and len(token) == 9:
        try:
            return int(token[1:], 16), None
        except ValueError:
            return 0, "Ungültige !hex Node-ID."

    if token.isdigit():
        return int(token), None

    nid = get_num_from_short_name(token, nodeInt)
    if nid:
        return nid, None
    return 0, f"Knoten '{token}' nicht in der NodeDB."


def _ensure_mesh_map_positions_loaded() -> None:
    """If mesh map URL is enabled and we have no snapshot yet, fetch once (uses HTTP cache)."""
    if not globals().get("leaderboard_mesh_map_enabled"):
        return
    if mesh_map_node_positions:
        return
    remote = fetch_leaderboard_mesh_map_nodes_cached()
    if isinstance(remote, dict):
        merge_leaderboard_from_mesh_map_nodes(remote, time.time())


def _parse_altitude_m(value) -> float | None:
    if value is None:
        return None
    try:
        alt = float(value)
    except (TypeError, ValueError):
        return None
    if alt <= 0:
        return None
    return alt


def get_node_altitude_m(nodeID, nodeInt=1) -> float | None:
    """Übertragene Höhe (m) aus NodeDB, positionMetadata oder Mesh-Karte."""
    _ensure_mesh_map_positions_loaded()
    for iface_num in _enabled_interface_order(nodeInt):
        interface = globals().get(f"interface{iface_num}")
        if interface is None or not getattr(interface, "nodes", None):
            continue
        for node in interface.nodes.values():
            if nodeID != node.get("num"):
                continue
            pos = node.get("position")
            if isinstance(pos, dict):
                alt = _parse_altitude_m(pos.get("altitude"))
                if alt is not None:
                    return alt
    meta = positionMetadata.get(nodeID) if isinstance(positionMetadata, dict) else None
    if meta:
        alt = _parse_altitude_m(meta.get("altitude"))
        if alt is not None:
            return alt
    snap = mesh_map_node_positions.get(int(nodeID))
    if snap:
        alt = _parse_altitude_m(snap.get("altitude"))
        if alt is not None:
            return alt
    return None


def format_node_altitude_line(alt_m: float) -> str:
    """Eine Zeile für Mesh-Antworten (!loc, !whereami, …)."""
    if use_metric:
        return f"⛰️{int(round(alt_m))} m MSL"
    return f"⛰️{int(round(alt_m * 3.28084))} ft MSL"


def _apply_mesh_map_position_to_info(info: dict, nodeID: int, round_digits: int) -> None:
    snap = mesh_map_node_positions.get(int(nodeID))
    if snap:
        alt = _parse_altitude_m(snap.get("altitude"))
        if alt is not None and info.get("altitude") is None:
            info["altitude"] = alt
    if info.get("lat") is not None:
        return
    if not snap:
        return
    lat = float(snap["lat"])
    lon = float(snap["lon"])
    if fuzzItAll:
        lat = round(lat, round_digits)
        lon = round(lon, round_digits)
    info["from_mesh_map"] = True
    info["lat"] = lat
    info["lon"] = lon


def get_mesh_node_position_info(nodeID, nodeInt=1, round_digits=2):
    """
    Look up a node across enabled interfaces.
    Returns dict: in_db, from_gps, from_mesh_map, lat, lon, altitude (m|None),
    last_heard (str|None), iface (int|None).
    """
    _ensure_mesh_map_positions_loaded()
    info = {
        "in_db": False,
        "from_gps": False,
        "from_mesh_map": False,
        "lat": None,
        "lon": None,
        "altitude": None,
        "last_heard": None,
        "iface": None,
    }
    for iface_num in _enabled_interface_order(nodeInt):
        interface = globals().get(f"interface{iface_num}")
        if interface is None or not getattr(interface, "nodes", None):
            continue
        for node in interface.nodes.values():
            if nodeID != node.get("num"):
                continue
            info["in_db"] = True
            info["iface"] = iface_num
            lh = node.get("lastHeard") or 0
            if lh:
                try:
                    info["last_heard"] = time.strftime("%m-%d %H:%M", time.localtime(lh))
                except (OSError, OverflowError, TypeError):
                    info["last_heard"] = None
            pos = node.get("position")
            if (
                pos
                and isinstance(pos, dict)
                and pos.get("latitude") is not None
                and pos.get("longitude") is not None
            ):
                try:
                    lat = float(pos["latitude"])
                    lon = float(pos["longitude"])
                    if fuzzItAll:
                        lat = round(lat, round_digits)
                        lon = round(lon, round_digits)
                    info["from_gps"] = True
                    info["lat"] = lat
                    info["lon"] = lon
                    alt = _parse_altitude_m(pos.get("altitude"))
                    if alt is not None:
                        info["altitude"] = alt
                except (TypeError, ValueError) as e:
                    logger.warning(f"System: Error reading position for node {nodeID}: {e}")
            if info.get("altitude") is None:
                meta = positionMetadata.get(nodeID) if isinstance(positionMetadata, dict) else None
                if meta:
                    alt = _parse_altitude_m(meta.get("altitude"))
                    if alt is not None:
                        info["altitude"] = alt
            _apply_mesh_map_position_to_info(info, nodeID, round_digits)
            return info
    _apply_mesh_map_position_to_info(info, nodeID, round_digits)
    if info.get("altitude") is None:
        meta = positionMetadata.get(nodeID) if isinstance(positionMetadata, dict) else None
        if meta:
            alt = _parse_altitude_m(meta.get("altitude"))
            if alt is not None:
                info["altitude"] = alt
    return info

def get_node_list(nodeInt=1):
    interface = globals()[f'interface{nodeInt}']
    # Get a list of nodes on the device
    node_list = ""
    node_list1 = []
    node_list2 = []
    short_node_list = []
    last_heard = 0
    if interface.nodes:
        for node in interface.nodes.values():
            # ignore own
            if all(node['num'] != globals().get(f'myNodeNum{i}') for i in range(1, 10)):
                node_name = get_name_from_number(node['num'], 'short', nodeInt)
                snr = node.get('snr', 0)

                # issue where lastHeard is not always present
                last_heard = node.get('lastHeard', 0)
                
                # make a list of nodes with last heard time and SNR
                item = (node_name, last_heard, snr)
                node_list1.append(item)
    else:
        logger.warning(f"System: No nodes found")
        return ERROR_FETCHING_DATA
    
    try:
        #print (f"Node List: {node_list1[:5]}\n")
        node_list1.sort(key=lambda x: x[1] if x[1] is not None else 0, reverse=True)
        #print (f"Node List: {node_list1[:5]}\n")
        if multiple_interface:
            logger.debug(f"System: FIX ME line 327 Multiple Interface Node List")
            node_list2.sort(key=lambda x: x[1] if x[1] is not None else 0, reverse=True)
    except Exception as e:
        logger.error(f"System: Error sorting node list: {e}")
        logger.debug(f"Node List1: {node_list1[:5]}\n")
        if multiple_interface:
            logger.debug(f"FIX ME MULTI INTERFACE Node List2: {node_list2[:5]}\n")
        node_list = ERROR_FETCHING_DATA

    try:
        # make a nice list for the user
        for x in node_list1[:SITREP_NODE_COUNT]:
            short_node_list.append(f"{x[0]} SNR:{x[2]}")
        for x in node_list2[:SITREP_NODE_COUNT]:
            short_node_list.append(f"{x[0]} SNR:{x[2]}")

        for x in short_node_list:
            if x != "" and x != '\n':
                node_list += x + "\n"
    except Exception as e:
        logger.error(f"System: Error creating node list: {e}")
        node_list = ERROR_FETCHING_DATA
    
    return node_list

def get_node_location(nodeID, nodeInt=1, channel=0, round_digits=2):
    """
    Returns [latitude, longitude] for a node.
    - Always returns a fuzzed (rounded) config location as fallback.
    - returns their actual position if available, else fuzzed config location.
    """
    _ensure_mesh_map_positions_loaded()
    interface = globals()[f'interface{nodeInt}']

    fuzzed_position = [round(latitudeValue, round_digits), round(longitudeValue, round_digits)]
    config_position = [latitudeValue, longitudeValue]

    # Try to find an exact location for the requested node
    if interface.nodes:
        for node in interface.nodes.values():
            if nodeID == node['num']:
                pos = node.get('position')
                if (
                    pos and isinstance(pos, dict)
                    and pos.get('latitude') is not None
                    and pos.get('longitude') is not None
                ):
                    try:
                        # Got a valid position
                        latitude = pos['latitude']
                        longitude = pos['longitude']
                        if fuzzItAll:
                            latitude = round(latitude, round_digits)
                            longitude = round(longitude, round_digits)
                            logger.debug(f"System: Fuzzed location data for {nodeID} is {latitude}, {longitude}")
                        logger.debug(f"System: Location data for {nodeID} is {latitude}, {longitude}")
                        return [latitude, longitude]
                    except Exception as e:
                        logger.warning(f"System: Error processing position for node {nodeID}: {e}")

    snap = mesh_map_node_positions.get(int(nodeID))
    if snap:
        lat = float(snap["lat"])
        lon = float(snap["lon"])
        if fuzzItAll:
            lat = round(lat, round_digits)
            lon = round(lon, round_digits)
        return [lat, lon]

    if fuzz_config_location:
        # Return fuzzed config location if no valid position found
        return fuzzed_position
    else:
        return config_position


def get_node_location_with_source(nodeID, nodeInt=1, round_digits=2):
    """Returns [latitude, longitude, from_gps] for warning/location replies."""
    _ensure_mesh_map_positions_loaded()
    interface = globals()[f'interface{nodeInt}']
    fuzzed_position = [round(latitudeValue, round_digits), round(longitudeValue, round_digits)]
    config_position = [latitudeValue, longitudeValue]

    if interface.nodes:
        for node in interface.nodes.values():
            if nodeID == node['num']:
                pos = node.get('position')
                if (
                    pos and isinstance(pos, dict)
                    and pos.get('latitude') is not None
                    and pos.get('longitude') is not None
                ):
                    try:
                        latitude = pos['latitude']
                        longitude = pos['longitude']
                        if fuzzItAll:
                            latitude = round(latitude, round_digits)
                            longitude = round(longitude, round_digits)
                        return [latitude, longitude, True]
                    except Exception as e:
                        logger.warning(
                            f"System: Error processing position for node {nodeID}: {e}"
                        )

    snap = mesh_map_node_positions.get(int(nodeID))
    if snap:
        lat = float(snap["lat"])
        lon = float(snap["lon"])
        if fuzzItAll:
            lat = round(lat, round_digits)
            lon = round(lon, round_digits)
        return [lat, lon, True]

    if fuzz_config_location:
        return [fuzzed_position[0], fuzzed_position[1], False]
    return [config_position[0], config_position[1], False]

async def get_closest_nodes(nodeInt=1,returnCount=3, channel=publicChannel):
        interface = globals()[f'interface{nodeInt}']
        node_list = []

        if interface.nodes:
            for node in interface.nodes.values():
                if 'position' in node:
                    try:
                        nodeID = node['num']
                        latitude = node['position']['latitude']
                        longitude = node['position']['longitude']

                        #lastheard time in unix time
                        lastheard = node.get('lastHeard', 0)
                        #if last heard is over 24 hours ago, ignore the node
                        if lastheard < (time.time() - 86400):
                            continue

                        # Calculate distance to node from config.ini location
                        distance = round(geopy.distance.geodesic((latitudeValue, longitudeValue), (latitude, longitude)).m, 2)
                        
                        if (distance < sentry_radius):
                            if (nodeID not in my_node_ids) and str(nodeID) not in sentryIgnoreList:
                                node_list.append({'id': nodeID, 'latitude': latitude, 'longitude': longitude, 'distance': distance})
                                
                    except Exception as e:
                        pass
                else:
                    # request location data currently blocking needs to be async
                    reqLocationEnabled = False
                    if reqLocationEnabled:
                        try:
                            logger.debug(f"System: Requesting location data for {node['id']}, lastHeard: {node.get('lastHeard', 'N/A')}")
                            # if not a interface node
                            if node['num'] in my_node_ids:
                                ignore = True
                            else:
                                # one idea is to send a ping to the node to request location data for if or when, ask again later
                                interface.sendPosition(destinationId=node['id'], wantResponse=False, channelIndex=channel)
                                # wayyy too fast async wait
                                
                                # send a traceroute request
                                interface.sendTraceRoute(destinationId=node['id'], channelIndex=channel, wantResponse=False)
                        except Exception as e:
                            logger.error(f"System: Error requesting location data for {node['id']}. Error: {e}")
            # sort by distance closest
            #node_list.sort(key=lambda x: (x['latitude']-latitudeValue)**2 + (x['longitude']-longitudeValue)**2)
            node_list.sort(key=lambda x: x['distance'])
            # return the first 3 closest nodes by default
            return node_list[:returnCount]
        else:
            logger.warning(f"System: No nodes found in closest_nodes on interface {nodeInt}")
            return ERROR_FETCHING_DATA
    
def handleFavoriteNode(nodeInt=1, nodeID=0, aor=False):
    # Add or remove a favorite node for the given interface. aor: True to add, False to remove.
    interface = globals()[f'interface{nodeInt}']
    myNodeNumber = globals().get(f'myNodeNum{nodeInt}')
    try:
        if aor:
            result = interface.getNode(myNodeNumber).setFavorite(nodeID)
            logger.info(f"System: Added {nodeID} to favorites for device {nodeInt}")
        else:
            result = interface.getNode(myNodeNumber).removeFavorite(nodeID)
            logger.info(f"System: Removed {nodeID} from favorites for device {nodeInt}")
        return result
    except Exception as e:
        logger.error(f"System: Error handling favorite node {nodeID} on device {nodeInt}: {e}")
        return None
    
def getFavoritNodes(nodeInt=1):
    interface = globals()[f'interface{nodeInt}']
    myNodeNumber = globals().get(f'myNodeNum{nodeInt}')
    favList = []
    for node in interface.getNode(myNodeNumber).favorites:
        favList.append(node)
    return favList

def handleSentinelIgnore(nodeInt=1, nodeID=0, aor=False):
    #aor is add or remove if True add, if False remove
    if aor:
        sentryIgnoreList.append(str(nodeID))
        logger.info(f"System: Added {nodeID} to sentry ignore list")
    else:
        sentryIgnoreList.remove(str(nodeID))
        logger.info(f"System: Removed {nodeID} from sentry ignore list")

def messageChunker(message):
    message_list = []
    try:
        if len(message) > MESSAGE_CHUNK_SIZE:
            # Split the message into parts by new lines
            parts = message.split('\n')
            for part in parts:
                part = part.strip()
                # remove empty parts
                if not part:
                    continue
                # if part is under the MESSAGE_CHUNK_SIZE, add it to the list
                if len(part) < MESSAGE_CHUNK_SIZE:
                    message_list.append(part)
                else:
                    # split the part into chunks
                    current_chunk = ''
                    sentences = []
                    sentence = ''
                    for char in part:
                        sentence += char
                        # if char in '.!?':
                        #     sentences.append(sentence.strip())
                        #     sentence = ''
                    if sentence:
                        sentences.append(sentence.strip())

                    for sentence in sentences:
                        sentence = sentence.replace('  ', ' ')
                        # remove empty sentences
                        if not sentence:
                            continue
                        # remove junk sentences and append to the previous sentence this may exceed the MESSAGE_CHUNK_SIZE by 3char
                        if len(sentence) < 4:
                            if current_chunk:
                                current_chunk += sentence
                            else:
                                current_chunk = sentence
                            continue

                        # if sentence is too long, split it by words
                        if len(current_chunk) + len(sentence) > MESSAGE_CHUNK_SIZE:
                            if current_chunk:
                                message_list.append(current_chunk)
                            current_chunk = sentence
                        else:
                            if current_chunk:
                                current_chunk += ' ' + sentence
                            else:
                                current_chunk = sentence
                    if current_chunk:
                        message_list.append(current_chunk)

            # Consolidate any adjacent messages that can fit in a single chunk.
            idx = 0
            while idx < len(message_list) - 1:
                if len(message_list[idx]) + len(message_list[idx+1]) < MESSAGE_CHUNK_SIZE:
                    message_list[idx] += '\n' + message_list[idx+1]
                    del message_list[idx+1]
                else:
                    idx += 1

            # Ensure no chunk exceeds MESSAGE_CHUNK_SIZE
            final_message_list = []
            for chunk in message_list:
                while len(chunk) > MESSAGE_CHUNK_SIZE:
                    # Find the last space within the chunk size limit
                    split_index = chunk.rfind(' ', 0, MESSAGE_CHUNK_SIZE)
                    if split_index == -1:
                        split_index = MESSAGE_CHUNK_SIZE
                    final_message_list.append(chunk[:split_index])
                    chunk = chunk[split_index:].strip()
                if chunk:
                    final_message_list.append(chunk)

            # Calculate the total length of the message
            total_length = sum(len(chunk) for chunk in final_message_list)
            num_chunks = len(final_message_list)
            logger.debug(f"System: Splitting #chunks: {num_chunks}, Total length: {total_length}")
            return final_message_list

        return message
    except Exception as e:
        logger.warning(f"System: Exception during message chunking: {e} (message length: {len(message)})")


def dm_chunk_wants_delivery_ack(nodeid, chunk_index, want_ack_all=False, want_ack_on_dm=True):
    """True if this outbound chunk should request a mesh ACK (DM: first chunk only)."""
    if nodeid == 0:
        return bool(want_ack_all)
    return bool(want_ack_on_dm) and chunk_index == 0


def _request_nodeinfo_exchange(dest_node: int, device_id: int) -> None:
    """Send a NODEINFO_APP request to dest_node so its public key reaches meshtasticd's NodeDB."""
    try:
        interface = globals().get(f'interface{device_id}')
        if interface is None:
            return
        # portNum 67 = NODEINFO_APP; wantResponse=True tells the target to reply with its NodeInfo
        interface.sendData(
            b'',
            destinationId=dest_node,
            portNum=67,
            wantAck=False,
            wantResponse=True,
        )
        logger.info(
            f"System: NodeInfo exchange triggered for Node:{dest_node} via Device:{device_id} "
            f"(PKI_SEND_FAIL_PUBLIC_KEY — waiting for key in NodeInfo reply)"
        )
    except Exception as e:
        logger.debug(f"System: NodeInfo exchange request failed for Node:{dest_node}: {e}")


def _log_dm_delivery_result(packet, dest_node, device_id):
    """Log mesh ACK/NAK for a DM we sent with wantAck (via Meshtastic onResponse)."""
    decoded = packet.get('decoded') or {}
    routing = decoded.get('routing') or {}
    error_reason = routing.get('errorReason', routing.get('error_reason', ''))
    request_id = decoded.get('requestId', decoded.get('request_id', packet.get('id')))
    dest_name = get_name_from_number(dest_node, 'long', device_id)
    if _significant_routing_error(error_reason):
        is_pki = str(error_reason).startswith('PKI_')
        try:
            from modules.dm_delivery_stats import record_dm_delivery_outcome

            record_dm_delivery_outcome(
                device_id, dest_node, success=False, is_pki=is_pki
            )
        except Exception as e:
            logger.debug(f"System: dm_delivery_stats record failed: {e}")
        pki_hint = PKI_ROUTING_ERROR_HINTS.get(error_reason, '')
        if is_pki:
            logger.warning(
                f"System: DM delivery failed (PKI) Device:{device_id} To:{dest_name} Node:{dest_node} "
                f"Reason:{error_reason} RequestId:{request_id} Guidance:{pki_hint}"
            )
            if error_reason == 'PKI_SEND_FAIL_PUBLIC_KEY':
                _request_nodeinfo_exchange(dest_node, device_id)
        else:
            logger.warning(
                f"System: DM delivery failed Device:{device_id} To:{dest_name} Node:{dest_node} "
                f"Reason:{error_reason} RequestId:{request_id}"
            )
    else:
        try:
            from modules.dm_delivery_stats import record_dm_delivery_outcome

            record_dm_delivery_outcome(device_id, dest_node, success=True)
        except Exception as e:
            logger.debug(f"System: dm_delivery_stats record failed: {e}")
        logger.info(
            f"System: DM delivery confirmed Device:{device_id} To:{dest_name} Node:{dest_node} "
            f"RequestId:{request_id}"
        )


def _dm_delivery_ack_callback(dest_node, device_id):
    def _on_dm_routing_response(packet):
        _log_dm_delivery_result(packet, dest_node, device_id)
    return _on_dm_routing_response


def send_message(message, ch, nodeid=0, nodeInt=1, bypassChuncking=False, reply_id=None):
    # Send a message to a channel or DM
    interface = globals()[f'interface{nodeInt}']
    # Check if the message is empty
    if message == "" or message is None or len(message) == 0:
        return False

    try:
        def _send_with_reply(**kwargs):
            want_ack = kwargs.pop('wantAck', False)
            on_response = kwargs.pop('onResponse', None)
            on_response_ack_permitted = kwargs.pop('onResponseAckPermitted', False)

            # sendData: threaded replies, and DM delivery ACK callbacks (onResponseAckPermitted).
            if reply_id is not None or on_response is not None:
                text_payload = kwargs.pop('text', '')
                if isinstance(text_payload, str):
                    raw_payload = text_payload.encode('utf-8')
                else:
                    raw_payload = text_payload

                destination_id = kwargs.pop('destinationId', None)
                channel_index = kwargs.pop('channelIndex', ch)
                data_kwargs = {
                    # 1 == TEXT_MESSAGE_APP, required so clients render payload as chat text.
                    'portNum': 1,
                    'channelIndex': channel_index,
                    'wantAck': want_ack,
                }
                if destination_id is not None:
                    data_kwargs['destinationId'] = destination_id
                if on_response is not None:
                    data_kwargs['onResponse'] = on_response
                    data_kwargs['onResponseAckPermitted'] = on_response_ack_permitted
                if reply_id is not None:
                    return interface.sendData(raw_payload, replyId=reply_id, **data_kwargs)
                return interface.sendData(raw_payload, **data_kwargs)
            return interface.sendText(wantAck=want_ack, **kwargs)

        # Force chunking and log if message exceeds maxBuffer
        if len(message.encode('utf-8')) > maxBuffer:
            logger.debug(f"System: Message length {len(message.encode('utf-8'))} exceeds maxBuffer{maxBuffer}, forcing chunking.")
            message_list = messageChunker(message)
        elif not bypassChuncking:
            # Split the message into chunks if it exceeds the MESSAGE_CHUNK_SIZE
            message_list = messageChunker(message)
        else:
            message_list = [message]

        if isinstance(message_list, list):
            num_chunks = len(message_list)
            for idx, m in enumerate(message_list):
                chunk_of = f"{idx + 1}/{num_chunks}"
                chunk_want_ack = dm_chunk_wants_delivery_ack(nodeid, idx, wantAck, wantAckOnDm)
                send_kwargs = {'text': m, 'channelIndex': ch, 'wantAck': chunk_want_ack}
                if nodeid != 0:
                    send_kwargs['destinationId'] = nodeid
                    if chunk_want_ack:
                        send_kwargs['onResponse'] = _dm_delivery_ack_callback(nodeid, nodeInt)
                        send_kwargs['onResponseAckPermitted'] = True
                ack_tag = CustomFormatter.red + "req.ACK " if chunk_want_ack else ""
                if nodeid == 0:
                    logger.info(
                        f"Device:{nodeInt} {format_channel_log(ch, nodeInt)} {ack_tag}"
                        f"Chunker{chunk_of} SendingChannel: {CustomFormatter.white}{m.replace(chr(10), ' ')}"
                    )
                else:
                    logger.info(
                        f"Device:{nodeInt} {ack_tag}Chunker{chunk_of} Sending DM: {CustomFormatter.white}"
                        f"{m.replace(chr(10), ' ')}{CustomFormatter.purple} To: {CustomFormatter.white}"
                        f"{get_name_from_number(nodeid, 'long', nodeInt)}"
                    )
                _send_with_reply(**send_kwargs)

                if (idx + 1) % 4 == 0:
                    time.sleep(responseDelay + 1)
                    if (idx + 1) % 5 == 0:
                        logger.warning(f"System: throttling rate Interface{nodeInt} on {chunk_of}")
                time.sleep(splitDelay)
        else:
            chunk_want_ack = dm_chunk_wants_delivery_ack(nodeid, 0, wantAck, wantAckOnDm)
            send_kwargs = {'text': message, 'channelIndex': ch, 'wantAck': chunk_want_ack}
            if nodeid != 0:
                send_kwargs['destinationId'] = nodeid
                if chunk_want_ack:
                    send_kwargs['onResponse'] = _dm_delivery_ack_callback(nodeid, nodeInt)
                    send_kwargs['onResponseAckPermitted'] = True
            ack_tag = CustomFormatter.red + "req.ACK " if chunk_want_ack else ""
            if nodeid == 0:
                logger.info(
                    f"Device:{nodeInt} {format_channel_log(ch, nodeInt)} {ack_tag}"
                    f"SendingChannel: {CustomFormatter.white}{message.replace(chr(10), ' ')}"
                )
            else:
                logger.info(
                    f"Device:{nodeInt} {ack_tag}Sending DM: {CustomFormatter.white}"
                    f"{message.replace(chr(10), ' ')}{CustomFormatter.purple} To: {CustomFormatter.white}"
                    f"{get_name_from_number(nodeid, 'long', nodeInt)}"
                )
            _send_with_reply(**send_kwargs)
            time.sleep(responseDelay)
        return True
    except Exception as e:
        logger.error(f"System: Exception during send_message: {e} (message length: {len(message)})")
        mark_interface_for_retry(nodeInt, f"send_message failed: {e}")
        return False

def send_raw_bytes(nodeid, raw_bytes, nodeInt=1, channel=0, portnum=256, want_ack=True, reply_id=None):
    # Send raw bytes to a node using the Meshtastic interface.
    interface = globals()[f'interface{nodeInt}']
    try:
        send_kwargs = {
            'destinationId': nodeid,
            'portNum': portnum,
            'channelIndex': channel,
            'wantAck': want_ack,
        }
        if reply_id is not None:
            try:
                interface.sendData(raw_bytes, replyId=reply_id, **send_kwargs)
            except TypeError:
                logger.debug("System: replyId/replyID unsupported for sendData; sending without threaded reply")
                interface.sendData(raw_bytes, **send_kwargs)
        else:
            interface.sendData(raw_bytes, **send_kwargs)
        # Throttle the message sending to prevent spamming the device
        logger.debug(f"System: Sent raw bytes to {nodeid} on portnum {portnum} via Device{nodeInt}")
        time.sleep(responseDelay)
        return True
    except Exception as e:
        logger.error(f"System: Error sending raw bytes to {nodeid} via Device{nodeInt}: {e} bytes: {raw_bytes}")
        return False

def decode_raw_bytes(raw_bytes):
    # Decode raw bytes received from a Meshtastic device.
    try:
        decoded_message = raw_bytes.decode('utf-8', errors='ignore')
        # reminder for a synch word check or crc check if needed later
        logger.debug(f"Decoded raw bytes: {decoded_message}")
        return decoded_message
    except Exception as e:
        logger.debug(f"System: Error decoding raw bytes: {e} bytes: {raw_bytes}")
        return ""

def messageTrap(msg):
    # Check if the message contains a trap word, this is the first filter for listning to messages
    # after this the message is passed to the command_handler in the bot.py which is switch case filter for applying word to function

    # Split Message on assumed words spaces m for m = msg.split(" ")
    # t in trap_list, built by the config and system.py not the user
    message_list=msg.split(" ")
    
    if cmdBang:
        # check for ! at the start of the message to force a command
        if not message_list[0].startswith('!'):
            return False
        else:
            message_list[0] = message_list[0][1:]

    for m in message_list:
        for t in trap_list:
            if not explicitCmd:
                # if word in message is in the trap list, return True
                if t.lower() == m.lower():
                    return True
            else:
                # if the index 0 of the message is a word in the trap list, return True
                if t.lower() == m.lower() and message_list.index(m) == 0:
                    return True
    # if no trap words found, run a search for near misses like ping? or cmd?
    for m in message_list:
        for t in range(len(trap_list)):
            if m.endswith('?') and m[:-1].lower() == trap_list[t]:
                return True
    return False

def stringSafeCheck(s, fromID=0):
    """Disabled: mesh text is not passed to shell; enable_runShellCmd is off by default."""
    return True

def api_throttle(node_id, rxInterface=None, channel=None, apiName=""):
    """
    Throttle API requests from nodes to prevent abuse.
    Returns False if not throttled, or a string message if throttled.
    """
    global apiThrottleList

    current_time = time.time()
    node_id_str = str(node_id)

    if isNodeAdmin(node_id_str):
        return False  # Do not throttle admin nodes
    
    # Find or create the apiThrottleList entry
    node_entry = next((entry for entry in apiThrottleList if entry['node_id'] == node_id_str), None)
    if node_entry:
        # Update interface and channel if provided
        if rxInterface is not None:
            node_entry['rxInterface'] = rxInterface
        if channel is not None:
            node_entry['channel'] = channel
        # Check if the timeframe has expired
        if (current_time - node_entry['lastSeen']) > autoBanTimeframe:
            node_entry['api_throttle_count'] = 1
            node_entry['lastSeen'] = current_time
        else:
            node_entry['api_throttle_count'] += 1
            node_entry['lastSeen'] = current_time
            if node_entry['api_throttle_count'] > apiThrottleValue:
                logger.warning(f"System: Node {node_id_str} throttled on API {apiName} count: {node_entry['api_throttle_count']}")
                if autoBanEnabled:
                    ban_hammer(node_id_str, reason="API Throttle Exceeded")
                return "🚦 Hessenbot ausgelastet — bitte später erneut."
    else:
        # node not found, create a new entry
        entry = {
            'node_id': node_id_str,
            'first_seen': current_time,
            'lastSeen': current_time,
            'api_throttle_count': 1,
            'rxInterface': rxInterface,
            'channel': channel
        }
        apiThrottleList.append(entry)
        node_entry = entry 

    logger.debug(f"System: API Throttle check for Node {node_id} on API {apiName} count: {node_entry['api_throttle_count']}")
    return False  # Not throttled

def ban_hammer(node_id, rxInterface=None, channel=None, reason=""):
    """
    Auto-ban nodes that exceed the message threshold within the timeframe.
    Returns True if the node is (or becomes) banned, False otherwise.
    """
    global autoBanlist, seenNodes, bbs_ban_list

    current_time = time.time()
    node_id_str = str(node_id)

    if isNodeAdmin(node_id_str):
        return False  # Do not ban admin nodes

    # Check if the node is already banned
    if node_id_str in bbs_ban_list or node_id_str in autoBanlist:
        return True  # Node is already banned
    
    # if no reason provided, dont ban just run that last check
    if reason == "":
        return False

    # Find or create the seenNodes entry (patched for missing 'node_id')
    node_entry = next((entry for entry in seenNodes if entry.get('node_id') == node_id_str), None)
    if node_entry:
        # Update interface and channel if provided
        if rxInterface is not None:
            node_entry['rxInterface'] = rxInterface
        if channel is not None:
            node_entry['channel'] = channel
        # Check if the timeframe has expired
        if (current_time - node_entry['lastSeen']) > autoBanTimeframe:
            node_entry['auto_ban_count'] = 1
            node_entry['lastSeen'] = current_time
        else:
            node_entry['auto_ban_count'] += 1
            node_entry['lastSeen'] = current_time
    else:
        # node not found, create a new entry
        entry = {
            'node_id': node_id_str,
            'first_seen': current_time,
            'lastSeen': current_time,
            'auto_ban_count': 3,  # start at 3 to trigger ban faster
            'rxInterface': rxInterface,
            'channel': channel,
            'welcome': False
        }
        seenNodes.append(entry)
        node_entry = entry

    # Check if the node has exceeded the ban threshold
    if node_entry['auto_ban_count'] < autoBanThreshold:
        logger.debug(f"System: Node {node_id_str} auto-ban count: {node_entry['auto_ban_count']}")
        return False  # No ban applied

    # If the node has exceeded the ban threshold within the time window
    autoBanlist.append(node_id_str)
    save_autoBanList()
    logger.info(f"System: Node {node_id_str} exceeded auto-ban threshold with {node_entry['auto_ban_count']} messages")
    if autoBanEnabled:
        logger.warning(f"System: Auto-banned node {node_id_str} Reason: {reason}")
        if node_id_str not in bbs_ban_list:
            bbs_ban_list.append(node_id_str)
            save_bbsBanList()
        return True  # Node is now banned

    return False  # No ban applied


_cmd_rate_tracker: dict = {}  # node_id_str -> list of timestamps

def is_cmd_rate_limited(node_id) -> bool:
    """Returns True and logs a warning if the node is sending commands too fast."""
    if not cmdRateLimitEnabled:
        return False
    if isNodeAdmin(str(node_id)):
        return False

    node_key = str(node_id)
    now = time.time()
    cutoff = now - cmdRateLimitWindow
    timestamps = _cmd_rate_tracker.get(node_key, [])
    # Drop timestamps outside the current window
    timestamps = [t for t in timestamps if t > cutoff]
    timestamps.append(now)
    _cmd_rate_tracker[node_key] = timestamps

    if len(timestamps) > cmdRateLimitMax:
        logger.warning(f"System: Rate limit hit for node {node_key} ({len(timestamps)} cmds in {cmdRateLimitWindow}s)")
        return True
    return False


def bbs_ban_list_file_path():
    from modules.paths import path_in_repo

    return path_in_repo("data/bbs_ban_list.txt")


def save_bbsBanList():
    # save the bbs_ban_list to file (absolute path — unabhängig vom Arbeitsverzeichnis)

    path = bbs_ban_list_file_path()
    ensure_parent_dir(path)
    try:
        with open(path, "w", encoding="utf-8") as f:
            for node in bbs_ban_list:
                if node:
                    f.write(f"{node}\n")
        logger.debug(f"System: BBS ban list saved to {path}")
        return True
    except OSError as e:
        logger.error(
            f"System: Error saving BBS ban list to {path}: {e}. "
            "Prüfe Besitzer/Rechte (z. B. sudo chown -R <bot-user>:<bot-user> data/ oder etc/set-permissions.sh)."
        )
        return False
    except Exception as e:
        logger.error(f"System: Error saving BBS ban list to {path}: {e}")
        return False


def load_bbsBanList():
    global bbs_ban_list
    loaded_list = []
    path = bbs_ban_list_file_path()
    try:
        with open(path, encoding="utf-8") as f:
            loaded_list = [line.strip() for line in f if line.strip()]
        logger.debug(
            f"System: BBS ban list now has {len(loaded_list)} entries loaded from {path}"
        )
    except FileNotFoundError:
        config_val = config['bbs'].get('bbs_ban_list', '')
        if config_val:
            loaded_list = [x.strip() for x in config_val.split(',') if x.strip()]
        logger.debug("System: No BBS ban list file found, loaded from config or started empty")
    except Exception as e:
        logger.error(f"System: Error loading BBS ban list: {e}")

    # Merge loaded_list into bbs_ban_list, only adding new entries
    for node in loaded_list:
        if node not in bbs_ban_list:
            bbs_ban_list.append(node)

def _autoban_file_path():
    from modules.paths import path_in_repo
    return path_in_repo("data/autoban.json")

def save_autoBanList():
    global autoBanlist
    path = _autoban_file_path()
    ensure_parent_dir(path)
    try:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(list(autoBanlist), f)
        logger.debug(f"System: autoBanlist saved ({len(autoBanlist)} entries)")
        return True
    except Exception as e:
        logger.error(f"System: Error saving autoBanlist: {e}")
        return False

def load_autoBanList():
    global autoBanlist
    path = _autoban_file_path()
    try:
        import json
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, list):
            for node in loaded:
                if node and node not in autoBanlist:
                    autoBanlist.append(node)
            logger.debug(f"System: autoBanlist loaded ({len(autoBanlist)} entries)")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"System: Error loading autoBanlist: {e}")


def isNodeAdmin(nodeID):
    # check if the nodeID is in the bbs_admin_list
    if bbs_admin_list != ['']:
        for admin in bbs_admin_list:
            if str(nodeID) == admin:
                return True
    return False

def isNodeBanned(nodeID):
    # check if the nodeID is in the bbs_ban_list
    for banned in bbs_ban_list:
        if str(nodeID) == banned:
            return True
    return False

def handle_bbsban(message, message_from_id, isDM):
    global bbs_ban_list
    msg = ""
    if not isDM:
        return "🤖only available in a Direct Message📵"
    if not isNodeAdmin(message_from_id):
        return NO_ALERTS
    if "?" in message:
        return "Ban or unban a node from posting to the BBS. Example: bannode add 1234567890 or bannode remove 1234567890"

    parts = message.lower().split()
    if len(parts) < 2 or parts[0] != "bannode":
        return "Please specify add, remove, or list. Example: bannode add 1234567890"

    action = parts[1]

    if action == "list":
        load_bbsBanList()  # Always reload from file for latest list
        if bbs_ban_list:
            return "BBS Ban List:\n" + "\n".join(bbs_ban_list)
        else:
            return "The BBS ban list is currently empty."

    if len(parts) < 3:
        return "Please specify add or remove and a node number. Example: bannode add 1234567890"

    node_id = parts[2].strip()
    if not node_id.isdigit():
        return "Invalid node number. Please provide a numeric node ID."

    if action == "add":
        if node_id not in bbs_ban_list:
            bbs_ban_list.append(node_id)
            save_bbsBanList()
            logger.warning(f"System: {message_from_id} added {node_id} to the BBS ban list")
            msg = f"Node {node_id} added to the BBS ban list"
        else:
            msg = f"Node {node_id} is already in the BBS ban list"
    elif action == "remove":
        if node_id in bbs_ban_list:
            bbs_ban_list.remove(node_id)
            save_bbsBanList()
            logger.warning(f"System: {message_from_id} removed {node_id} from the BBS ban list")
            msg = f"Node {node_id} removed from the BBS ban list"
        else:
            msg = f"Node {node_id} is not in the BBS ban list"
    else:
        msg = "Invalid action. Please use 'add', 'remove', or 'list'."

    return msg

def handleMultiPing(nodeID=0, deviceID=1):
    global multiPingList
    if len(multiPingList) > 1:
        mPlCpy = multiPingList.copy()
        for i in range(len(mPlCpy)):
            message_id_from = mPlCpy[i]['message_from_id']
            count = mPlCpy[i]['count']
            type = mPlCpy[i]['type']
            deviceID = mPlCpy[i]['deviceID']
            channel_number = mPlCpy[i]['channel_number']
            start_count = mPlCpy[i]['startCount']

            if count > 1:
                count -= 1
                # update count in the list
                for j in range(len(multiPingList)):
                    if multiPingList[j]['message_from_id'] == message_id_from:
                        multiPingList[j]['count'] = count

                # handle bufferTest
                if type == '🎙TEST':
                    buffer = ''.join(random.choice(['0', '1']) for i in range(maxBuffer))
                    # divide buffer by start_count and get resolution
                    resolution = maxBuffer // start_count
                    slice = resolution * count
                    if slice > maxBuffer:
                        slice = maxBuffer
                    # set the type as a portion of the buffer
                    type = buffer[slice - resolution:]
                    # if exceed the maxBuffer, remove the excess
                    count = len(type + "🔂    ")
                    if count > maxBuffer:
                        type = type[:maxBuffer - count]
                    # final length count of the message for display
                    count = len(type + "🔂    ")
                    if count < 99:
                        count -= 1

                # send the DM
                send_message(f"🔂{count} {type}", channel_number, message_id_from, deviceID, bypassChuncking=True)
                if count < 2:
                    # remove the item from the list
                    for j in range(len(multiPingList)):
                        if multiPingList[j]['message_from_id'] == message_id_from:
                            multiPingList.pop(j)
                            break

# Alert broadcasting initialization
last_alerts = {
    "overdue": {"time": 0, "message": ""},
    "fema": {"time": 0, "message": ""},
    "uk": {"time": 0, "message": ""},
    "de": {"time": 0, "message": ""},
    "wx": {"time": 0, "message": ""},
    "volcano": {"time": 0, "message": ""},
}
def should_send_alert(alert_type, new_message, min_interval=1):
    now = time.time()
    last = last_alerts[alert_type]
    # Only send if enough time has passed AND the message is different
    if (now - last["time"]) > min_interval and new_message != last["message"]:
        last_alerts[alert_type]["time"] = now
        last_alerts[alert_type]["message"] = new_message
        return True
    return False

def handleAlertBroadcast(deviceID=1):
    try:
        overdueAlerts = NO_ALERTS
        clock = datetime.now()

        # Overdue check-in alert
        if checklist_enabled:
            overdueAlerts = format_overdue_alert()
            if overdueAlerts:
                if should_send_alert("overdue", overdueAlerts, min_interval=300): # 5 minutes interval for overdue alerts
                    send_message(overdueAlerts, emergency_responder_alert_channel, 0, emergency_responder_alert_interface)

        if not enableDEalerts or not deAlertAutoBroadcast:
            return False

        # Only allow API call every alert_duration minutes at xx:00, xx:20, xx:40
        if not (clock.minute % alert_duration == 0 and clock.second <= 17):
            return False

        deAlerts = get_nina_alerts()
        alert_types = [("de", deAlerts, True)]

        for alert_type, alert_msg, enabled in alert_types:
            if enabled and alert_msg and NO_ALERTS not in alert_msg and ERROR_FETCHING_DATA not in alert_msg:
                if should_send_alert(alert_type, alert_msg):
                    logger.debug(f"System: Sending {alert_type} alert to emergency responder channel {emergency_responder_alert_channel}")
                    send_message(alert_msg, emergency_responder_alert_channel, 0, emergency_responder_alert_interface)
                    if eAlertBroadcastChannel:
                        for ch in eAlertBroadcastChannel:
                            ch = ch.strip()
                            if ch:
                                logger.debug(f"System: Sending {alert_type} alert to aux channel {ch}")
                                time.sleep(splitDelay)
                                send_message(alert_msg, int(ch), 0, emergency_responder_alert_interface)
    except Exception as e:
        logger.error(f"System: Error in handleAlertBroadcast: {e}")
    return False

def onDisconnect(interface):
    """meshtastic.connection.lost — queue watchdog reconnect (TCP/meshtasticd idle drops)."""
    idx = mesh_interface_index(interface)
    logger.warning(
        f"System: Meshtastic connection lost"
        + (f" (interface{idx})" if idx else "")
        + ", scheduling reconnect..."
    )
    if idx is not None:
        mark_interface_for_retry(idx, "connection.lost")
    try:
        interface.close()
    except Exception as e:
        logger.debug(f"System: onDisconnect close: {e}")

# Telemetry Functions
localTelemetryData = {}
def initialize_telemetryData():
    global localTelemetryData
    localTelemetryData[0] = {f'interface{i}': 0 for i in range(1, 10)}
    localTelemetryData[0].update({f'lastAlert{i}': '' for i in range(1, 10)})
    for i in range(1, 10):
        localTelemetryData[i] = {'numPacketsTx': 0, 'numPacketsRx': 0, 'numOnlineNodes': 0, 'numPacketsTxErr': 0, 'numPacketsRxErr': 0, 'numTotalNodes': 0}

# indented to be called from the main loop
initialize_telemetryData()

def getNodeFirmware(nodeID=0, nodeInt=1):
    interface = globals()[f'interface{nodeInt}']
    # get the firmware version of the node
    # this is a workaround because .localNode.getMetadata spits out a lot of debug info which cant be suppressed
    # Create a StringIO object to capture the 
    output_capture = io.StringIO()
    with contextlib.redirect_stdout(output_capture), contextlib.redirect_stderr(output_capture):
        interface.localNode.getMetadata()
    console_output = output_capture.getvalue()
    if "firmware_version" in console_output:
        fwVer = console_output.split("firmware_version: ")[1].split("\n")[0]
        return fwVer
    return -1

def compileFavoriteList(getInterfaceIDs=True):
    # build a list of favorite nodes to add to the device
    fav_list = []

    if getInterfaceIDs:
        logger.debug(f"System:compileFavoriteList Collecting Nodes for use on roof client_base only")
        # get the node IDs for each interface
        for i in range(1, 10):
            if globals().get(f'interface{i}') and globals().get(f'interface{i}_enabled'):
                myNodeNum = globals().get(f'myNodeNum{i}', 0)
                if myNodeNum != 0:
                    object = {'nodeID': myNodeNum, 'deviceID': i}
                    fav_list.append(object)
                    logger.debug(f"System:compileFavoriteList Added NodeID {myNodeNum} favorite list")

    if not getInterfaceIDs:
        logger.debug(f"System:compileFavoriteList Compiling Favorite Node List for use on bot to save DM keys only")
        if (bbs_admin_list != [0] or favoriteNodeList != ['']) or bbs_link_whitelist != [0]:
            logger.debug(f"System: Collecting Favorite Nodes to add to device(s)")
            # loop through each interface and add the favorite nodes
            for i in range(1, 10):
                if globals().get(f'interface{i}') and globals().get(f'interface{i}_enabled'):
                    for fav in bbs_admin_list + favoriteNodeList + bbs_link_whitelist:
                        if fav != 0 and fav != '' and fav is not None:
                            object = {'nodeID': fav, 'deviceID': i}
                            # check object not already in the list
                            if object not in fav_list:
                                fav_list.append(object)
                                logger.debug(f"System:compileFavoriteList Favorite Node {fav}")
    return fav_list

def displayNodeTelemetry(nodeID=0, rxNode=0, userRequested=False):
    interface = globals()[f'interface{rxNode}']
    myNodeNum = globals().get(f'myNodeNum{rxNode}')
    global localTelemetryData
  
    # throttle the telemetry requests to prevent spamming the device
    if 1 <= rxNode <= 9:
        if time.time() - localTelemetryData[0][f'interface{rxNode}'] < 600 and not userRequested:
            return -1
        localTelemetryData[0][f'interface{rxNode}'] = time.time()

    # some telemetry data is not available in python-meshtastic?
    # bring in values from the last telemetry dump for the node
    numPacketsTx = localTelemetryData[rxNode].get('numPacketsTx', 0)
    numPacketsRx = localTelemetryData[rxNode].get('numPacketsRx', 0)
    numPacketsTxErr = localTelemetryData[rxNode].get('numPacketsTxErr', 0)
    numPacketsRxErr = localTelemetryData[rxNode].get('numPacketsRxErr', 0)
    numTotalNodes = localTelemetryData[rxNode].get('numTotalNodes', 0)
    totalOnlineNodes = localTelemetryData[rxNode].get('numOnlineNodes', 0)
    numRXDupes = localTelemetryData[rxNode].get('numRXDupes', 0)
    numTxRelays = localTelemetryData[rxNode].get('numTxRelays', 0)
    heapFreeBytes = localTelemetryData[rxNode].get('heapFreeBytes', 0)
    heapTotalBytes = localTelemetryData[rxNode].get('heapTotalBytes', 0)
    # get the telemetry data for a node
    chutil = round(interface.nodes.get(decimal_to_hex(myNodeNum), {}).get("deviceMetrics", {}).get("channelUtilization", 0), 1)
    airUtilTx = round(interface.nodes.get(decimal_to_hex(myNodeNum), {}).get("deviceMetrics", {}).get("airUtilTx", 0), 1)
    uptimeSeconds = interface.nodes.get(decimal_to_hex(myNodeNum), {}).get("deviceMetrics", {}).get("uptimeSeconds", 0)
    batteryLevel = interface.nodes.get(decimal_to_hex(myNodeNum), {}).get("deviceMetrics", {}).get("batteryLevel", 0)
    voltage = interface.nodes.get(decimal_to_hex(myNodeNum), {}).get("deviceMetrics", {}).get("voltage", 0)
    #numPacketsRx = interface.nodes.get(decimal_to_hex(myNodeNum), {}).get("localStats", {}).get("numPacketsRx", 0)
    #numPacketsTx = interface.nodes.get(decimal_to_hex(myNodeNum), {}).get("localStats", {}).get("numPacketsTx", 0)
    numTotalNodes = len(interface.nodes) 
    
    dataResponse = f"Telemetry:{rxNode}"

    # packet info telemetry
    dataResponse += f" numPacketsRx:{numPacketsRx} numPacketsRxErr:{numPacketsRxErr} numPacketsTx:{numPacketsTx} numPacketsTxErr:{numPacketsTxErr}"

    # Channel utilization and airUtilTx
    dataResponse += " ChUtil%:" + str(round(chutil, 2)) + " AirTx%:" + str(round(airUtilTx, 2))

    if chutil > 40:
        logger.warning(f"System: High Channel Utilization {chutil}% on Device: {rxNode}")

    if airUtilTx > 25:
        logger.warning(f"System: High Air Utilization {airUtilTx}% on Device: {rxNode}")

    # Number of nodes
    dataResponse += " totalNodes:" + str(numTotalNodes) + " Online:" + str(totalOnlineNodes)

    # Uptime
    uptimeSeconds = getPrettyTime(uptimeSeconds)
    dataResponse += " Uptime:" + str(uptimeSeconds)

    # add battery info to the response
    emji = "🔌" if batteryLevel == 101 else "🪫" if batteryLevel < 10 else "🔋"
    dataResponse += f" Volt:{round(voltage, 1)}"

    if batteryLevel < 25:
        logger.warning(f"System: Low Battery Level: {batteryLevel}{emji} on Device: {rxNode}")
        send_message(f"Low Battery Level: {batteryLevel}{emji} on Device: {rxNode}", {secure_channel}, 0, {secure_interface})
    elif batteryLevel < 10:
        logger.critical(f"System: Critical Battery Level: {batteryLevel}{emji} on Device: {rxNode}")

    # if numRXDupes,numTxRelays,heapFreeBytes,heapTotalBytes are available loge them
    # if numRXDupes != 0:
    #     dataResponse += f" RXDupes:{numRXDupes}"
    #     logger.debug(f"System: Device {rxNode} RX Dupes:{numRXDupes}")
    # if numTxRelays != 0:
    #     dataResponse += f" TxRelays:{numTxRelays}"
    #     logger.debug(f"System: Device {rxNode} TX Relays:{numTxRelays}")
    # if heapFreeBytes != 0 and heapTotalBytes != 0:
    #     logger.debug(f"System: Device {rxNode} Heap Memory Free:{heapFreeBytes} Total:{heapTotalBytes}")
        #dataResponse += f" Heap:{heapFreeBytes}/{heapTotalBytes}"

    return dataResponse

positionMetadata = {}
# Last nodes.json snapshot: node_id -> {lat, lon, updated, shortName?} (degrees WGS84)
mesh_map_node_positions: dict[int, dict] = {}
meshLeaderboard = {}
def initializeMeshLeaderboard():
    global meshLeaderboard
    # Leaderboard for tracking extreme metrics
    meshLeaderboard = {
        'lowestBattery': {'nodeID': None, 'value': 101, 'timestamp': 0},  # 🪫
        'longestUptime': {'nodeID': None, 'value': 0, 'timestamp': 0},    # 🕰️
        'fastestSpeed': {'nodeID': None, 'value': 0, 'timestamp': 0},     # 🚓
        'fastestAirSpeed': {'nodeID': None, 'value': 0, 'timestamp': 0},  # ✈️
        'highestAltitude': {'nodeID': None, 'value': 0, 'timestamp': 0},  # 🚀
        'tallestNode': {'nodeID': None, 'value': 0, 'timestamp': 0},      # 🪜
        'coldestTemp': {'nodeID': None, 'value': 999, 'timestamp': 0},    # 🥶
        'hottestTemp': {'nodeID': None, 'value': -999, 'timestamp': 0},   # 🥵
        'worstAirQuality': {'nodeID': None, 'value': 0, 'timestamp': 0},  # 💨
        'mostTMessages': {'nodeID': None, 'value': 0, 'timestamp': 0},    # 💬
        'mostMessages': {'nodeID': None, 'value': 0, 'timestamp': 0},     # 💬
        'highestDBm': {'nodeID': None, 'value': -999, 'timestamp': 0},    # 📶
        'weakestDBm': {'nodeID': None, 'value': 999, 'timestamp': 0},     # 📶
        'mostReactions': {'nodeID': None, 'value': 0, 'timestamp': 0},    # ❤️
        'mostPaxWiFi': {'nodeID': None, 'value': 0, 'timestamp': 0},      # 👥
        'mostPaxBLE': {'nodeID': None, 'value': 0, 'timestamp': 0},       # 👥
        'adminPackets': [],      # 🚨
        'tunnelPackets': [],     # 🚨
        'audioPackets': [],      # ☎️
        'simulatorPackets': [],  # 🤖
        'emojiCounts': {},       # Track emoji counts per node
        'emojiTypeCounts': {},   # Track emoji type counts
        'nodeMessageCounts': {},  # Track total message counts per node
        'nodeTMessageCounts': {}  # Track total Tmessage counts per node
    }

initializeMeshLeaderboard()

# Known Meshtastic firmware PKI routing errors and practical operator guidance.
PKI_ROUTING_ERROR_HINTS = {
    'PKI_SEND_FAIL_PUBLIC_KEY': 'bot does not have destination public key. or key is missing from the device. Add the destination nodeID to the favorite nodes list, then retry.',
    'PKI_UNKNOWN_PUBKEY': 'Receiver could not decrypt PKI packet due to missing sender public key. Trigger a NodeInfo exchange both directions, then retry.',
    'PKI_FAILED': 'PKI was explicitly requested but send prerequisites were not met. Verify PKI-capable firmware/config, key material, and direct-send destination.',
}

# Protobuf enum „no error“ — ROUTING_APP-Acks, kein Bot-/Mesh-Fehler
_BENIGN_ROUTING_REASONS = frozenset({
    '', '0', 'NONE', 'NO_ERROR', 'ROUTING_ERROR_NONE', 'ROUTING_ERROR_NO_ERROR',
})


def _significant_routing_error(reason) -> bool:
    if reason is None:
        return False
    label = str(reason).strip().upper()
    if label in _BENIGN_ROUTING_REASONS:
        return False
    if label.endswith('_NONE') or label.endswith('.NONE'):
        return False
    return True

# Plausible range for EnvironmentMetrics.temperature (°C); filters wrong units / corrupt values.
_LEADERBOARD_TEMP_MIN_C = -90.0
_LEADERBOARD_TEMP_MAX_C = 70.0


def _ambient_temperature_plausible_celsius(temp: float) -> bool:
    return _LEADERBOARD_TEMP_MIN_C <= temp <= _LEADERBOARD_TEMP_MAX_C


_LEADERBOARD_MESH_MAP_CACHE_SEC = 90.0
_leaderboard_mesh_map_cache: tuple[float, dict | None] = (0.0, None)


def _local_mesh_bot_node_nums() -> set[int]:
    out: set[int] = set()
    for i in range(1, 10):
        if not globals().get(f"interface{i}_enabled"):
            continue
        n = globals().get(f"myNodeNum{i}")
        if n is None:
            continue
        try:
            out.add(int(n))
        except (TypeError, ValueError):
            pass
    return out


def fetch_leaderboard_mesh_map_nodes_cached() -> dict | None:
    """GET leaderboardMeshMapURL; returns dict nodeId(str)->metrics or None. Short-lived cache."""
    global _leaderboard_mesh_map_cache
    if not globals().get("leaderboard_mesh_map_enabled"):
        return None
    url = (globals().get("leaderboard_mesh_map_url") or "").strip()
    if not url:
        return None
    now_t = time.time()
    ts, cached = _leaderboard_mesh_map_cache
    if isinstance(cached, dict) and (now_t - ts) < _LEADERBOARD_MESH_MAP_CACHE_SEC:
        return cached

    timeout = globals().get("urlTimeoutSeconds", 15) or 15
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "HessenBot/leaderboard (mesh-map snapshot)"},
        )
        with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
            raw = resp.read().decode()
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            _leaderboard_mesh_map_cache = (now_t, parsed)
            return parsed
    except Exception as e:
        logger.debug(f"System: leaderboard mesh map JSON fetch/parse failed: {e}")

    _leaderboard_mesh_map_cache = (now_t, None)
    return None


def _lat_lon_degrees_from_map_json(lat_raw, lon_raw) -> tuple[float | None, float | None]:
    """map.meshhessen nodes.json uses lat/lon as 1e7-scaled integers (Meshtastic convention)."""
    if lat_raw is None or lon_raw is None:
        return None, None
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except (TypeError, ValueError):
        return None, None
    if abs(lat) > 90:
        lat /= 1e7
    if abs(lon) > 180:
        lon /= 1e7
    if abs(lat) > 90 or abs(lon) > 180:
        return None, None
    return lat, lon


def merge_leaderboard_from_mesh_map_nodes(data: dict, now: float) -> None:
    """Merge flat Meshtastic map-style nodes dict (e.g. map.meshhessen.de nodes.json).

    Typical fields per node: batteryLevel, uptime, temperature, altitude; latitude/longitude
    update mesh_map_node_positions for !loc / get_node_location fallbacks.

    No SNR / groundSpeed on this feed; those stay from local RX / NodeDB.
    """
    global mesh_map_node_positions
    if not isinstance(data, dict):
        return
    my_nodes = _local_mesh_bot_node_nums()
    rx_fallback = 1

    new_positions: dict[int, dict] = {}

    for key, raw in data.items():
        if not isinstance(raw, dict):
            continue
        try:
            nid = int(str(key))
        except (TypeError, ValueError):
            continue
        if not nid:
            continue

        la, lo = _lat_lon_degrees_from_map_json(
            raw.get("latitude"),
            raw.get("longitude"),
        )
        if la is not None and lo is not None:
            snap: dict = {"lat": la, "lon": lo, "updated": now}
            sn = raw.get("shortName")
            if isinstance(sn, str) and sn.strip():
                snap["shortName"] = sn.strip()
            alt_snap = raw.get("altitude")
            if alt_snap is not None:
                try:
                    snap["altitude"] = float(alt_snap)
                except (TypeError, ValueError):
                    pass
            new_positions[nid] = snap

        bl = raw.get("batteryLevel")
        if bl is not None:
            try:
                battery = float(bl)
                if battery > 0 and battery < float(meshLeaderboard["lowestBattery"]["value"]):
                    meshLeaderboard["lowestBattery"] = {
                        "nodeID": nid,
                        "value": battery,
                        "timestamp": now,
                    }
            except (TypeError, ValueError):
                pass

        if nid not in my_nodes:
            uptime_val = raw.get("uptime")
            if uptime_val is not None:
                try:
                    uptime = float(uptime_val)
                    if uptime > float(meshLeaderboard["longestUptime"]["value"]):
                        meshLeaderboard["longestUptime"] = {
                            "nodeID": nid,
                            "value": uptime,
                            "timestamp": now,
                        }
                except (TypeError, ValueError):
                    pass

        temp_val = raw.get("temperature")
        if temp_val is not None:
            try:
                apply_environment_temperature_to_leaderboard(
                    nid, float(temp_val), rx_node=rx_fallback
                )
            except (TypeError, ValueError):
                pass

        alt = raw.get("altitude")
        if alt is not None:
            try:
                pos = {"altitude": float(alt)}
                apply_leaderboard_altitude_speed_from_position(nid, pos, now)
            except (TypeError, ValueError):
                pass

    mesh_map_node_positions = new_positions


def apply_environment_temperature_to_leaderboard(
    node_id: int, temp: float, rx_node: int = 1
) -> None:
    """Update coldest/hottest records from one environment temperature reading (°C)."""
    global meshLeaderboard
    if not node_id:
        return
    try:
        temp = float(temp)
    except (TypeError, ValueError):
        return
    if not _ambient_temperature_plausible_celsius(temp):
        return
    current_time = time.time()
    try:
        if temp < float(meshLeaderboard['coldestTemp']['value']):
            meshLeaderboard['coldestTemp'] = {
                'nodeID': node_id,
                'value': temp,
                'timestamp': current_time,
            }
            if logMetaStats:
                logger.info(
                    f"System: 🥶 New coldest temp record: {temp}°C from NodeID:{node_id} "
                    f"ShortName:{get_name_from_number(node_id, 'short', rx_node)}"
                )
        if temp > float(meshLeaderboard['hottestTemp']['value']):
            meshLeaderboard['hottestTemp'] = {
                'nodeID': node_id,
                'value': temp,
                'timestamp': current_time,
            }
            if logMetaStats:
                logger.info(
                    f"System: 🥵 New hottest temp record: {temp}°C from NodeID:{node_id} "
                    f"ShortName:{get_name_from_number(node_id, 'short', rx_node)}"
                )
    except Exception as e:
        logger.debug(f"System: leaderboard temperature update error: {e}")


def apply_leaderboard_altitude_speed_from_position(
    node_id: int, position_data: dict, timestamp: float
) -> None:
    """Update tallest / highest altitude / ground & airspeed from a position dict (NodeDB or packet)."""
    global meshLeaderboard
    if not node_id or not isinstance(position_data, dict):
        return
    try:
        if position_data.get("altitude") is None:
            return
        altitude = position_data["altitude"]
        highflying = altitude > highfly_altitude

        if altitude < (highfly_altitude - 100):
            if altitude > meshLeaderboard["tallestNode"]["value"]:
                meshLeaderboard["tallestNode"] = {
                    "nodeID": node_id,
                    "value": altitude,
                    "timestamp": timestamp,
                }
        if highflying:
            if altitude > meshLeaderboard["highestAltitude"]["value"]:
                meshLeaderboard["highestAltitude"] = {
                    "nodeID": node_id,
                    "value": altitude,
                    "timestamp": timestamp,
                }
        if position_data.get("groundSpeed") is not None:
            speed = position_data["groundSpeed"]
            if not highflying and speed > meshLeaderboard["fastestSpeed"]["value"]:
                meshLeaderboard["fastestSpeed"] = {
                    "nodeID": node_id,
                    "value": speed,
                    "timestamp": timestamp,
                }
            elif highflying and speed > meshLeaderboard["fastestAirSpeed"]["value"]:
                meshLeaderboard["fastestAirSpeed"] = {
                    "nodeID": node_id,
                    "value": speed,
                    "timestamp": timestamp,
                }
    except Exception as e:
        logger.debug(f"System: leaderboard position metrics error: {e}")


def apply_environment_iaq_to_leaderboard(
    node_id: int, iaq: float, rx_node: int = 1
) -> None:
    global meshLeaderboard
    if not node_id:
        return
    try:
        iaq = float(iaq)
        if iaq > float(meshLeaderboard["worstAirQuality"]["value"]):
            meshLeaderboard["worstAirQuality"] = {
                "nodeID": node_id,
                "value": iaq,
                "timestamp": time.time(),
            }
            if logMetaStats:
                logger.info(
                    f"System: 💨 New worst air quality record: IAQ {iaq} from NodeID:{node_id} "
                    f"ShortName:{get_name_from_number(node_id, 'short', rx_node)}"
                )
    except (TypeError, ValueError):
        return


def sync_leaderboard_from_nodedb() -> None:
    """Merge NodeDB snapshot into meshLeaderboard (telemetry + last SNR + position).

    Meshtastic merges incoming packets into per-node dicts; this matches the map/explorer
    view and refreshes records that would otherwise stay stuck in leaderboard.pkl.

    Optionally merges a regional map snapshot (leaderboardMeshMapURL), e.g. mesh map JSON,
    into the same scoreboard (temperature, altitude, uptime, battery) without replacing
    local SNR/spikes from your own radios.

    Message-count leaderboards stay packet-driven only (no NodeDB / map snapshot source).
    """
    now = time.time()
    for i in range(1, 10):
        if not globals().get(f"interface{i}_enabled"):
            continue
        iface = globals().get(f"interface{i}")
        if iface is None:
            continue
        myn = globals().get(f"myNodeNum{i}", 777)
        nodes_by_num = getattr(iface, "nodesByNum", None)
        if nodes_by_num:
            node_iter = list(nodes_by_num.values())
        else:
            raw = getattr(iface, "nodes", None) or {}
            node_iter = list(raw.values()) if isinstance(raw, dict) else []

        for node in node_iter:
            if not isinstance(node, dict):
                continue
            num = node.get("num")
            if num is None:
                continue
            try:
                nid = int(num)
            except (TypeError, ValueError):
                continue
            if not nid:
                continue

            # Last heard SNR (same field as Sitrep / admin NodeDB table)
            if nid != myn:
                snr = node.get("snr")
                if snr is not None:
                    try:
                        dbm = float(snr)
                        if dbm > meshLeaderboard["highestDBm"]["value"]:
                            meshLeaderboard["highestDBm"] = {
                                "nodeID": nid,
                                "value": dbm,
                                "timestamp": now,
                            }
                        if dbm < meshLeaderboard["weakestDBm"]["value"]:
                            meshLeaderboard["weakestDBm"] = {
                                "nodeID": nid,
                                "value": dbm,
                                "timestamp": now,
                            }
                    except (TypeError, ValueError):
                        pass

            dm = node.get("deviceMetrics") or node.get("device_metrics")
            if isinstance(dm, dict):
                bl = dm.get("batteryLevel") if dm.get("batteryLevel") is not None else dm.get("battery_level")
                if bl is not None:
                    try:
                        battery = float(bl)
                        if battery > 0 and battery < float(meshLeaderboard["lowestBattery"]["value"]):
                            meshLeaderboard["lowestBattery"] = {
                                "nodeID": nid,
                                "value": battery,
                                "timestamp": now,
                            }
                    except (TypeError, ValueError):
                        pass
                if nid != myn:
                    up = (
                        dm.get("uptimeSeconds")
                        if dm.get("uptimeSeconds") is not None
                        else dm.get("uptime_seconds")
                    )
                    if up is not None:
                        try:
                            uptime = float(up)
                            if uptime > float(meshLeaderboard["longestUptime"]["value"]):
                                meshLeaderboard["longestUptime"] = {
                                    "nodeID": nid,
                                    "value": uptime,
                                    "timestamp": now,
                                }
                        except (TypeError, ValueError):
                            pass

            env = node.get("environmentMetrics") or node.get("environment_metrics")
            if isinstance(env, dict):
                t = env.get("temperature")
                if t is not None:
                    try:
                        apply_environment_temperature_to_leaderboard(nid, float(t), rx_node=i)
                    except (TypeError, ValueError):
                        pass
                iq = env.get("iaq")
                if iq is not None:
                    try:
                        apply_environment_iaq_to_leaderboard(nid, float(iq), rx_node=i)
                    except (TypeError, ValueError):
                        pass

            pos = node.get("position")
            if isinstance(pos, dict):
                apply_leaderboard_altitude_speed_from_position(nid, pos, now)

    remote = fetch_leaderboard_mesh_map_nodes_cached()
    if isinstance(remote, dict):
        merge_leaderboard_from_mesh_map_nodes(remote, now)


def consumeMetadata(packet, rxNode=0, channel=-1):
    global positionMetadata, localTelemetryData, meshLeaderboard
    uptime = battery = temp = iaq = nodeID = 0
    deviceMetrics, envMetrics, localStats = {}, {}, {}

    from modules.mesh_sim_tunnel import unwrap_sim_tunnel_packet

    unwrapped, inner_port = unwrap_sim_tunnel_packet(packet)
    if unwrapped:
        meshLeaderboard["simTunnelUnwrapCount"] = (
            meshLeaderboard.get("simTunnelUnwrapCount", 0) + 1
        )

    # update telemetry data for the device
    try:
        packet_type = ''
        if packet.get('decoded'):
            packet_type = packet['decoded']['portnum']
            nodeID = packet['from']
        
        # if not a bot ID track it
        if nodeID != globals().get(f'myNodeNum{rxNode}') and nodeID != 0:
            # consider Meta for highest and weakest DBm
            if packet.get('rxSnr') is not None:
                dbm = packet['rxSnr']
                if dbm > meshLeaderboard['highestDBm']['value']:
                    meshLeaderboard['highestDBm'] = {'nodeID': nodeID, 'value': dbm, 'timestamp': time.time()}
                if dbm < meshLeaderboard['weakestDBm']['value']:
                    meshLeaderboard['weakestDBm'] = {'nodeID': nodeID, 'value': dbm, 'timestamp': time.time()}

            # Meta for most Messages leaderboard
            if packet_type == 'TEXT_MESSAGE':
                # if packet isnt TO a my_node_id count it
                if packet.get('to') not in my_node_ids:
                    message_count = meshLeaderboard.get('nodeMessageCounts', {})
                    message_count[nodeID] = message_count.get(nodeID, 0) + 1
                    meshLeaderboard['nodeMessageCounts'] = message_count
                    if message_count[nodeID] > meshLeaderboard['mostMessages']['value']:
                        meshLeaderboard['mostMessages'] = {'nodeID': nodeID, 'value': message_count[nodeID], 'timestamp': time.time()}
            else:
                tmessage_count = meshLeaderboard.get('nodeTMessageCounts', {})
                tmessage_count[nodeID] = tmessage_count.get(nodeID, 0) + 1
                meshLeaderboard['nodeTMessageCounts'] = tmessage_count
                if tmessage_count[nodeID] > meshLeaderboard['mostTMessages']['value']:
                    meshLeaderboard['mostTMessages'] = {'nodeID': nodeID, 'value': tmessage_count[nodeID], 'timestamp': time.time()}
        
    except Exception as e:
        logger.debug(f"System: Metadata decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # TELEMETRY packets
    if packet_type == 'TELEMETRY_APP':
        if debugMetadata and 'TELEMETRY_APP' not in metadataFilter:
            print(f"DEBUG TELEMETRY_APP: {packet}\n\n")
        telemetry_packet = packet['decoded']['telemetry']
        # Track device metrics (battery, uptime)
        dm_raw = telemetry_packet.get("deviceMetrics") or telemetry_packet.get(
            "device_metrics"
        )
        if dm_raw and isinstance(dm_raw, dict):
            deviceMetrics = dm_raw
            current_time = time.time()
            # Track lowest battery 🪫
            try:
                bl_raw = deviceMetrics.get("batteryLevel")
                if bl_raw is None:
                    bl_raw = deviceMetrics.get("battery_level")
                if bl_raw is not None:
                    battery = float(bl_raw)
                    if battery > 0 and battery < float(meshLeaderboard['lowestBattery']['value']):
                        meshLeaderboard['lowestBattery'] = {'nodeID': nodeID, 'value': battery, 'timestamp': current_time}
                        if logMetaStats:
                            logger.info(f"System: 🪫 New low battery record: {battery}% from NodeID:{nodeID} ShortName:{get_name_from_number(nodeID, 'short', rxNode)}")
            except Exception as e:
                logger.debug(f"System: TELEMETRY_APP batteryLevel error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

            # Track longest uptime 🕰️
            try:
                # if not a bot ID track it
                if nodeID != globals().get(f'myNodeNum{rxNode}') and nodeID != 0:
                    up_raw = deviceMetrics.get("uptimeSeconds")
                    if up_raw is None:
                        up_raw = deviceMetrics.get("uptime_seconds")
                    if up_raw is not None:
                        uptime = float(up_raw)
                        longest_uptime = float(meshLeaderboard['longestUptime']['value'])
                        if uptime > longest_uptime:
                            meshLeaderboard['longestUptime'] = {'nodeID': nodeID, 'value': uptime, 'timestamp': current_time}
            except Exception as e:
                logger.debug(f"System: TELEMETRY_APP uptimeSeconds error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

        # Track environment metrics (temperature, air quality)
        envMetrics = telemetry_packet.get('environmentMetrics') or telemetry_packet.get(
            'environment_metrics'
        )
        if envMetrics and isinstance(envMetrics, dict):
            current_time = time.time()
            try:
                if envMetrics.get('temperature') is not None and nodeID:
                    temp = float(envMetrics['temperature'])
                    apply_environment_temperature_to_leaderboard(
                        int(nodeID), temp, rx_node=rxNode
                    )
            except Exception as e:
                logger.debug(
                    f"System: TELEMETRY_APP temperature error: Device: {rxNode} Channel: {channel} {e} packet {packet}"
                )

            try:
                if envMetrics.get("iaq") is not None and nodeID:
                    apply_environment_iaq_to_leaderboard(
                        int(nodeID), float(envMetrics["iaq"]), rx_node=rxNode
                    )
            except Exception as e:
                logger.debug(
                    f"System: TELEMETRY_APP iaq error: Device: {rxNode} Channel: {channel} {e} packet {packet}"
                )

        # Update localStats in telemetryData
        if telemetry_packet.get('localStats'):
            localStats = telemetry_packet['localStats']
            try:
                # Only store keys where value is not 0
                filtered_stats = {k: v for k, v in localStats.items() if v != 0}
                localTelemetryData[rxNode].update(filtered_stats)
            except Exception as e:
                logger.debug(f"System: TELEMETRY_APP localStats error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    #POSITION_APP packets
    if packet_type == 'POSITION_APP':
        try:
            if debugMetadata and 'POSITION_APP' not in metadataFilter:
                print(f"DEBUG POSITION_APP: {packet}\n\n")
            position_stats_keys = ['altitude', 'groundSpeed', 'precisionBits']
            position_data = packet['decoded']['position']
            if nodeID not in positionMetadata:
                positionMetadata[nodeID] = {}
            for key in position_stats_keys:
                positionMetadata[nodeID][key] = position_data.get(key, 0)
 
            lb_ts = time.time()
            if position_data.get("altitude") is not None:
                apply_leaderboard_altitude_speed_from_position(
                    nodeID, position_data, lb_ts
                )
                altitude = position_data["altitude"]
                highflying = altitude > highfly_altitude
                if logMetaStats:

                    def _lb_just_updated(key: str) -> bool:
                        r = meshLeaderboard[key]
                        return r.get("nodeID") == nodeID and abs(
                            float(r.get("timestamp", 0)) - lb_ts
                        ) < 0.05

                    if altitude < (highfly_altitude - 100) and _lb_just_updated(
                        "tallestNode"
                    ):
                        logger.info(
                            f"System: 🪜 New tallest node record: {altitude}m from NodeID:{nodeID} "
                            f"ShortName:{get_name_from_number(nodeID, 'short', rxNode)}"
                        )
                    if highflying and _lb_just_updated("highestAltitude"):
                        logger.info(
                            f"System: 🚀 New altitude record: {altitude}m from NodeID:{nodeID} "
                            f"ShortName:{get_name_from_number(nodeID, 'short', rxNode)}"
                        )
                    sp = position_data.get("groundSpeed")
                    if sp is not None:
                        if not highflying and _lb_just_updated("fastestSpeed"):
                            logger.info(
                                f"System: 🚓 New speed record: {sp} km/h from NodeID:{nodeID} "
                                f"ShortName:{get_name_from_number(nodeID, 'short', rxNode)}"
                            )
                        elif highflying and _lb_just_updated("fastestAirSpeed"):
                            logger.info(
                                f"System: ✈️ New air speed record: {sp} km/h from NodeID:{nodeID} "
                                f"ShortName:{get_name_from_number(nodeID, 'short', rxNode)}"
                            )
            # if altitude is over highfly_altitude send a log and message for high-flying nodes and not in highfly_ignoreList
            if position_data.get('altitude', 0) > highfly_altitude and highfly_enabled and str(nodeID) not in highfly_ignoreList and not isNodeBanned(nodeID):
                logger.info(f"System: High Altitude {position_data['altitude']}m on Device: {rxNode} Channel: {channel} NodeID:{nodeID} Lat:{position_data.get('latitude', 0)} Lon:{position_data.get('longitude', 0)}")
                altFeet = round(position_data['altitude'] * 3.28084, 2)
                msg = f"🚀 High Altitude Detected! NodeID:{nodeID} Alt:{altFeet:,.0f}ft/{position_data['altitude']:,.0f}m"
                
                # throttle sending alerts for the same node more than once every 30 minutes
                last_alert_time = positionMetadata[nodeID].get('lastHighFlyAlert', 0)
                current_time = time.time()
                if current_time - last_alert_time < 1800:
                    return False # less than 30 minutes since last alert
                positionMetadata[nodeID]['lastHighFlyAlert'] = current_time
                try:
                    if highfly_check_openskynetwork:
                        if 'latitude' in position_data and 'longitude' in position_data and 'altitude' in position_data:
                            flight_info = get_openskynetwork(
                                position_data.get('latitude', 0),
                                position_data.get('longitude', 0),
                                node_altitude=position_data.get('altitude', 0)
                            )
                            if flight_info and isinstance(flight_info, dict):
                                msg += (
                                    f"\n✈️Detected near:\n"
                                    f"{flight_info.get('callsign', 'N/A')} "
                                    f"Alt:{int(flight_info.get('geo_altitude', 0)) if flight_info.get('geo_altitude') else 'N/A'}m "
                                    f"Vel:{int(flight_info.get('velocity', 0)) if flight_info.get('velocity') else 'N/A'}m/s "
                                    f"Heading:{int(flight_info.get('true_track', 0)) if flight_info.get('true_track') else 'N/A'}°\n"
                                    f"From:{flight_info.get('origin_country', 'N/A')}"
                                )
                    send_message(msg, highfly_channel, 0, highfly_interface)
                except Exception as e:
                    logger.debug(f"System: Highfly: error: {e}")
            # Keep the positionMetadata dictionary at a maximum size
            if len(positionMetadata) > MAX_SEEN_NODES:
                # Remove the oldest entry
                oldest_nodeID = next(iter(positionMetadata))
                del positionMetadata[oldest_nodeID]
            # add a packet count to the positionMetadata for the node
            if 'packetCount' in positionMetadata[nodeID]:
                positionMetadata[nodeID]['packetCount'] += 1
            else:
                positionMetadata[nodeID]['packetCount'] = 1
        except Exception as e:
            logger.debug(f"System: POSITION_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # WAYPOINT_APP packets
    if packet_type == 'WAYPOINT_APP':
        try:
            if debugMetadata and 'WAYPOINT_APP' not in metadataFilter:
                print(f"DEBUG WAYPOINT_APP: {packet}\n\n")
            waypoint_data = packet['decoded']['waypoint']
            id = waypoint_data.get('id', 0)
            latitudeI = waypoint_data.get('latitudeI', 0)
            longitudeI = waypoint_data.get('longitudeI', 0)
            expire = waypoint_data.get('expire', 0)
            if expire == 1:
                expire = "Now"
            elif expire == 0:
                expire = "Never"
            else:
                expire = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expire))
            description = waypoint_data.get('description', '')
            name = waypoint_data.get('name', '')
            if logMetaStats:
                logger.info(f"System: Waypoint from Device: {rxNode} Channel: {channel} NodeID:{nodeID} ID:{id} Lat:{latitudeI/1e7} Lon:{longitudeI/1e7} Expire:{expire} Name:{name} Desc:{description}")
        except Exception as e:
            logger.debug(f"System: WAYPOINT_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # NEIGHBORINFO_APP
    if packet_type == 'NEIGHBORINFO_APP':
        try:
            if debugMetadata and 'NEIGHBORINFO_APP' not in metadataFilter:
                print(f"DEBUG NEIGHBORINFO_APP: {packet}\n\n")
            neighbor_data = packet['decoded']
            neighbor_list = neighbor_data.get('neighbors', [])
            if logMetaStats:
                logger.info(f"System: Neighbor Info from Device: {rxNode} Channel: {channel} NodeID:{nodeID} Neighbors:{len(neighbor_list)}")
        except Exception as e:
            logger.debug(f"System: NEIGHBORINFO_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # TRACEROUTE_APP
    if packet_type == 'TRACEROUTE_APP':
        try:
            if debugMetadata and 'TRACEROUTE_APP' not in metadataFilter:
                print(f"DEBUG TRACEROUTE_APP: {packet}\n\n")
            traceroute_data = packet['decoded']
            # (add any logic here if needed)
        except Exception as e:
            logger.debug(f"System: TRACEROUTE_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # DETECTION_SENSOR_APP
    if packet_type == 'DETECTION_SENSOR_APP':
        try:
            if debugMetadata and 'DETECTION_SENSOR_APP' not in metadataFilter:
                print(f"DEBUG DETECTION_SENSOR_APP: {packet}\n\n")
            detection_data = packet['decoded']
            detction_text = detection_data.get('text', '')
            if detction_text != '':
                if logMetaStats:
                    logger.info(f"System: Detection Sensor Data from Device: {rxNode} Channel: {channel} NodeID:{nodeID} Text:{detction_text}")
                if detctionSensorAlert:
                    send_message(f"🚨Detection Sensor from Device: {rxNode} Channel: {channel} NodeID:{get_name_from_number(nodeID,'long',rxNode)} Alert:{detction_text}", secure_channel, 0, secure_interface)
        except Exception as e:
            logger.debug(f"System: DETECTION_SENSOR_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # PAXCOUNTER_APP
    if packet_type == 'PAXCOUNTER_APP':
        try:
            if debugMetadata and 'PAXCOUNTER_APP' not in metadataFilter:
                print(f"DEBUG PAXCOUNTER_APP: {packet}\n\n")
            paxcounter_data = packet['decoded']['paxcounter']
            wifi_count = paxcounter_data.get('wifi', 0)
            ble_count = paxcounter_data.get('ble', 0)
            uptime = paxcounter_data.get('uptime', 0)
            current_time = time.time()
            # Track most WiFi
            if wifi_count > meshLeaderboard['mostPaxWiFi']['value']:
                meshLeaderboard['mostPaxWiFi'] = {'nodeID': nodeID, 'value': wifi_count, 'timestamp': current_time}
            # Track most BLE
            if ble_count > meshLeaderboard['mostPaxBLE']['value']:
                meshLeaderboard['mostPaxBLE'] = {'nodeID': nodeID, 'value': ble_count, 'timestamp': current_time}
            if logMetaStats:
                logger.info(f"System: Paxcounter Data from Device: {rxNode} Channel: {channel} NodeID:{nodeID} WiFi:{wifi_count} BLE:{ble_count} Uptime:{getPrettyTime(uptime)}")
        except Exception as e:
            logger.debug(f"System: PAXCOUNTER_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")
    
    # REMOTE_HARDWARE_APP
    if packet_type == 'REMOTE_HARDWARE_APP':
        try:
            if debugMetadata and 'REMOTE_HARDWARE_APP' not in metadataFilter:
                print(f"DEBUG REMOTE_HARDWARE_APP: {packet}\n\n")
            remote_hardware_data = packet['decoded']
            hardware_info = remote_hardware_data.get('hardware_info', '')
            if logMetaStats:
                logger.info(f"System: Remote Hardware Data from Device: {rxNode} Channel: {channel} NodeID:{nodeID} Info:{hardware_info}")
        except Exception as e:
            logger.debug(f"System: REMOTE_HARDWARE_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # ADMIN_APP - Track admin packets 🚨
    if packet_type == 'ADMIN_APP':
        try:
            if debugMetadata and 'ADMIN_APP' not in metadataFilter:
                print(f"DEBUG ADMIN_APP: {packet}\n\n")
            # if not a bot ID track it
            if nodeID != globals().get(f'myNodeNum{rxNode}') and nodeID != 0:
                packet_info = {'nodeID': nodeID, 'timestamp': time.time(), 'device': rxNode, 'channel': channel}
                # if not a bot ID track it
                if nodeID != globals().get(f'myNodeNum{rxNode}') and nodeID != 0:
                    meshLeaderboard['adminPackets'].append(packet_info)
                if len(meshLeaderboard['adminPackets']) > 10:
                    meshLeaderboard['adminPackets'].pop(0)
                if logMetaStats:
                    logger.info(f"System: 🚨 Admin packet detected from Device: {rxNode} Channel: {channel} NodeID:{nodeID} ShortName:{get_name_from_number(nodeID, 'short', rxNode)}")
        except Exception as e:
            logger.debug(f"System: ADMIN_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # ROUTING_APP - meta for logs
    if packet_type == 'ROUTING_APP':
        try:
            if debugMetadata and 'ROUTING_APP' not in metadataFilter:
                print(f"DEBUG ROUTING_APP: {packet}\n\n")
            routing_data = packet['decoded']['routing']

            # Meshtastic Python/client can surface this field as errorReason or error_reason.
            error_reason = routing_data.get('errorReason', routing_data.get('error_reason', ''))
            if _significant_routing_error(error_reason):
                requester_node = packet.get('from', nodeID)
                requester_id = packet.get('fromId', '')
                target_node = packet.get('to', 0)
                request_id = packet.get('decoded', {}).get('requestId', packet.get('decoded', {}).get('request_id', 0))
                pki_hint = PKI_ROUTING_ERROR_HINTS.get(error_reason, 'No playbook entry yet. Check node public keys/NodeInfo sync and firmware versions on both peers.')

                # Standardized PKI routing failure log with source/target context for triage.
                if str(error_reason).startswith('PKI_'):
                    logger.warning(
                        f"System: PKI Routing Error Device:{rxNode} Channel:{channel} Reason:{error_reason} "
                        f"RequesterNode:{requester_node} RequesterID:{requester_id} "
                        f"RequesterShort:{get_name_from_number(requester_node, 'short', rxNode)} "
                        f"TargetNode:{target_node} RequestId:{request_id} Guidance:{pki_hint}"
                    )
                elif logMetaStats:
                    logger.info(
                        f"System: ROUTING_APP Error Device:{rxNode} Channel:{channel} Reason:{error_reason} "
                        f"RequesterNode:{requester_node} TargetNode:{target_node} RequestId:{request_id}"
                    )
        except Exception as e:
            logger.debug(f"System: ROUTING_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")
    
    
    # IP_TUNNEL_APP - Track tunneling packets 🚨
    if packet_type == 'IP_TUNNEL_APP':
        try:
            if debugMetadata and 'IP_TUNNEL_APP' not in metadataFilter:
                print(f"DEBUG IP_TUNNEL_APP: {packet}\n\n")
            packet_info = {'nodeID': nodeID, 'timestamp': time.time(), 'device': rxNode, 'channel': channel}
            meshLeaderboard['tunnelPackets'].append(packet_info)
            if len(meshLeaderboard['tunnelPackets']) > 10:
                meshLeaderboard['tunnelPackets'].pop(0)
            if logMetaStats:
                logger.info(f"System: 🚨 IP Tunnel packet detected from Device: {rxNode} Channel: {channel} NodeID:{nodeID} ShortName:{get_name_from_number(nodeID, 'short', rxNode)}")
        except Exception as e:
            logger.debug(f"System: IP_TUNNEL_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # SERIAL_APP

    # STORE_FOWARD_APP

    # RANGE_TEST_APP

    # COMPRESSED_TEXT_APP

    # ATTAK_APP

    # SERIAL_APP

    # NODE_DB_APP

    # RTTTL_APP

    # STORE_AND_FORWARD_APP

    # DEBUG_APP

    # RANGEREPORT_APP

    # CENSUS_APP

    # AUDIO_APP - Track audio/voice packets ☎️
    if packet_type == 'AUDIO_APP':
        try:
            if debugMetadata and 'AUDIO_APP' not in metadataFilter:
                print(f"DEBUG AUDIO_APP: {packet}\n\n")
            packet_info = {'nodeID': nodeID, 'timestamp': time.time(), 'device': rxNode, 'channel': channel}
            meshLeaderboard['audioPackets'].append(packet_info)
            if len(meshLeaderboard['audioPackets']) > 10:
                meshLeaderboard['audioPackets'].pop(0)
            if logMetaStats:
                logger.info(f"System: ☎️ Audio packet detected from Device: {rxNode} Channel: {channel} NodeID:{nodeID} ShortName:{get_name_from_number(nodeID, 'short', rxNode)}")
        except Exception as e:
            logger.debug(f"System: AUDIO_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    # SIMULATOR_APP still present = tunnel envelope could not be unwrapped
    if packet_type == 'SIMULATOR_APP':
        try:
            if debugMetadata and 'SIMULATOR_APP' not in metadataFilter:
                print(f"DEBUG SIMULATOR_APP: {packet}\n\n")
            if logSimulatorPackets:
                logger.debug(
                    f"System: Sim/MQTT tunnel not unwrapped ({inner_port}) "
                    f"Device:{rxNode} Ch:{channel} NodeID:{nodeID} "
                    f"Short:{get_name_from_number(nodeID, 'short', rxNode)}"
                )
        except Exception as e:
            logger.debug(f"System: SIMULATOR_APP decode error: Device: {rxNode} Channel: {channel} {e} packet {packet}")

    return True

def noisyTelemetryCheck():
    global positionMetadata
    if len(positionMetadata) == 0:
        return
    # sort the positionMetadata by packetCount
    sorted_positionMetadata = dict(sorted(positionMetadata.items(), key=lambda item: item[1].get('packetCount', 0), reverse=True))
    top_three = list(sorted_positionMetadata.items())[:3]
    for nodeID, data in top_three:
        if data.get('packetCount', 0) > noisyTelemetryLimit:
            logger.warning(f"System: Noisy Telemetry Detected from NodeID:{nodeID} ShortName:{get_name_from_number(nodeID, 'short', 1)} Packets:{data.get('packetCount', 0)}")
            # reset the packet count for the node
            positionMetadata[nodeID]['packetCount'] = 0

def saveLeaderboard():
    # save the meshLeaderboard to a pickle file
    global meshLeaderboard
    path = _mesh_leaderboard_pkl_path()
    try:
        ensure_parent_dir(path)
        with open(path, "wb") as f:
            pickle.dump(meshLeaderboard, f)
        if logMetaStats:
            logger.debug(f"System: Mesh Leaderboard saved to {path}")
        return True
    except OSError as e:
        logger.warning(
            f"System: Error saving Mesh Leaderboard to {path}: {e}. "
            "Prüfe Schreibrechte auf data/ (z. B. sudo chown -R <bot-user>:<bot-user> data/ oder etc/set-permissions.sh)."
        )
        return False
    except Exception as e:
        logger.warning(f"System: Error saving Mesh Leaderboard to {path}: {e}")
        return False

def loadLeaderboard():
    global meshLeaderboard
    path = _mesh_leaderboard_pkl_path()
    try:
        with open(path, "rb") as f:
            loaded = pickle.load(f)
        # Merge with current default structure to add any new keys
        initializeMeshLeaderboard()  # sets meshLeaderboard to default structure
        for k, v in loaded.items():
            meshLeaderboard[k] = v
        sync_leaderboard_from_nodedb()
        if logMetaStats:
            logger.debug(f"System: Mesh Leaderboard loaded from {path}")
    except FileNotFoundError:
        if logMetaStats:
            logger.debug(f"System: No existing Mesh Leaderboard at {path}, starting fresh")
        initializeMeshLeaderboard()
        sync_leaderboard_from_nodedb()
    except Exception as e:
        logger.warning(f"System: Error loading Mesh Leaderboard: {e}")
        initializeMeshLeaderboard()
        sync_leaderboard_from_nodedb()

def get_mesh_leaderboard(msg, fromID, deviceID):
    """Get formatted leaderboard of extreme mesh metrics"""
    global meshLeaderboard
    result = "📊 Bestenliste 📊\n"

    if "reset" in msg.lower() and str(fromID) in bbs_admin_list:
        initializeMeshLeaderboard()
        return "✅ Bestenliste wurde zurückgesetzt."

    sync_leaderboard_from_nodedb()

    # Lowest battery
    if meshLeaderboard['lowestBattery']['nodeID']:
        nodeID = meshLeaderboard['lowestBattery']['nodeID']
        value = round(meshLeaderboard['lowestBattery']['value'], 1)
        result += f"🪫 Niedrigster Akku: {value}% {get_name_from_number(nodeID, 'short', 1)}\n"
    
    # Longest uptime
    if meshLeaderboard['longestUptime']['nodeID']:
        nodeID = meshLeaderboard['longestUptime']['nodeID']
        value = meshLeaderboard['longestUptime']['value']
        result += f"🕰️ Längste Laufzeit: {getPrettyTime(value)} {get_name_from_number(nodeID, 'short', 1)}\n"
    
    # Fastest speed
    if meshLeaderboard['fastestSpeed']['nodeID']:
        nodeID = meshLeaderboard['fastestSpeed']['nodeID']
        value_kmh = round(meshLeaderboard['fastestSpeed']['value'], 1)
        value_mph = round(value_kmh / 1.60934, 1)
        if use_metric:
            result += f"🚓 Höchstgeschw.: {value_kmh} km/h {get_name_from_number(nodeID, 'short', 1)}\n"
        else:
            result += f"🚓 Höchstgeschw.: {value_mph} mph {get_name_from_number(nodeID, 'short', 1)}\n"

    # Tallest node
    if meshLeaderboard['tallestNode']['nodeID']:
        nodeID = meshLeaderboard['tallestNode']['nodeID']
        value_m = meshLeaderboard['tallestNode']['value']
        value_ft = round(value_m * 3.28084, 0)
        if use_metric:
            result += f"🪜 Höchster Knoten: {int(round(value_m, 0))}m {get_name_from_number(nodeID, 'short', 1)}\n"
        else:
            result += f"🪜 Höchster Knoten: {int(value_ft)}ft {get_name_from_number(nodeID, 'short', 1)}\n"
    
    # Highest altitude
    if meshLeaderboard['highestAltitude']['nodeID']:
        nodeID = meshLeaderboard['highestAltitude']['nodeID']
        value_m = meshLeaderboard['highestAltitude']['value']
        value_ft = round(value_m * 3.28084, 0)
        if use_metric:
            result += f"🚀 Höchste Flughöhe: {int(round(value_m, 0))}m {get_name_from_number(nodeID, 'short', 1)}\n"
        else:
            result += f"🚀 Höchste Flughöhe: {int(value_ft)}ft {get_name_from_number(nodeID, 'short', 1)}\n"

    # Fastest airspeed
    if meshLeaderboard['fastestAirSpeed']['nodeID']:
        nodeID = meshLeaderboard['fastestAirSpeed']['nodeID']
        value_kmh = round(meshLeaderboard['fastestAirSpeed']['value'], 1)
        value_mph = round(value_kmh / 1.60934, 1)
        if use_metric:
            result += f"✈️ Höchste Fluggeschw.: {value_kmh} km/h {get_name_from_number(nodeID, 'short', 1)}\n"
        else:
            result += f"✈️ Höchste Fluggeschw.: {value_mph} mph {get_name_from_number(nodeID, 'short', 1)}\n"
    
    # Coldest temperature
    if meshLeaderboard['coldestTemp']['nodeID']:
        nodeID = meshLeaderboard['coldestTemp']['nodeID']
        value_c = round(meshLeaderboard['coldestTemp']['value'], 1)
        value_f = round((value_c * 9/5) + 32, 1)
        if use_metric:
            result += f"🥶 Kälteste: {value_c}°C {get_name_from_number(nodeID, 'short', 1)}\n"
        else:
            result += f"🥶 Kälteste: {value_f}°F {get_name_from_number(nodeID, 'short', 1)}\n"
    
    # Hottest temperature
    if meshLeaderboard['hottestTemp']['nodeID']:
        nodeID = meshLeaderboard['hottestTemp']['nodeID']
        value_c = round(meshLeaderboard['hottestTemp']['value'], 1)
        value_f = round((value_c * 9/5) + 32, 1)
        if use_metric:
            result += f"🥵 Wärmste: {value_c}°C {get_name_from_number(nodeID, 'short', 1)}\n"
        else:
            result += f"🥵 Wärmste: {value_f}°F {get_name_from_number(nodeID, 'short', 1)}\n"
    
    # Worst air quality
    if meshLeaderboard['worstAirQuality']['nodeID']:
        nodeID = meshLeaderboard['worstAirQuality']['nodeID']
        value = round(meshLeaderboard['worstAirQuality']['value'], 1)
        result += f"💨 Schlechteste Luft: {value} {get_name_from_number(nodeID, 'short', 1)}\n"

    # Weakest RF
    if meshLeaderboard['weakestDBm']['nodeID'] is not None:
        nodeID = meshLeaderboard['weakestDBm']['nodeID']
        value = meshLeaderboard['weakestDBm']['value']
        result += f"📶 Schwächstes RF: {value} dBm {get_name_from_number(nodeID, 'short', 1)}\n"

    # Best RF
    if meshLeaderboard['highestDBm']['nodeID'] is not None:
        nodeID = meshLeaderboard['highestDBm']['nodeID']
        value = meshLeaderboard['highestDBm']['value']
        result += f"📶 Bestes RF: {value} dBm {get_name_from_number(nodeID, 'short', 1)}\n"

    # Most Telemetry Messages
    if 'nodeTMessageCounts' in meshLeaderboard and meshLeaderboard['mostTMessages']['nodeID'] is not None:
        nodeID = meshLeaderboard['mostTMessages']['nodeID']
        value = meshLeaderboard['mostTMessages']['value']
        result += f"📊 Meiste Telemetrie: {value} {get_name_from_number(nodeID, 'short', 1)}\n"

    # Most Emojis
    if meshLeaderboard.get('mostEmojis', {}).get('nodeID') is not None:
        nodeID = meshLeaderboard['mostEmojis']['nodeID']
        value = meshLeaderboard['mostEmojis']['value']
        result += f"🤪 Meiste Emojis: {value} {get_name_from_number(nodeID, 'short', 1)}\n"
    
    # Most Messages
    if 'nodeMessageCounts' in meshLeaderboard and meshLeaderboard['mostMessages']['nodeID'] is not None:
        nodeID = meshLeaderboard['mostMessages']['nodeID']
        value = meshLeaderboard['mostMessages']['value']
        result += f"💬 Meiste Nachrichten: {value} {get_name_from_number(nodeID, 'short', 1)}\n"

    # Most WiFi devices seen
    if meshLeaderboard.get('mostPaxWiFi', {}).get('nodeID'):
        nodeID = meshLeaderboard['mostPaxWiFi']['nodeID']
        value = meshLeaderboard['mostPaxWiFi']['value']
        result += f"📶 PAX Wifi: {value} {get_name_from_number(nodeID, 'short', 1)}\n"

    # Most BLE devices seen
    if meshLeaderboard.get('mostPaxBLE', {}).get('nodeID'):
        nodeID = meshLeaderboard['mostPaxBLE']['nodeID']
        value = meshLeaderboard['mostPaxBLE']['value']
        result += f"📲 PAX BLE: {value} {get_name_from_number(nodeID, 'short', 1)}\n"
    
    # Special packet detections
    if len(meshLeaderboard['adminPackets']) > 0:
        result += f"🚨 Admin-Pakete: {len(meshLeaderboard['adminPackets'])}\n"
    
    if len(meshLeaderboard['tunnelPackets']) > 0:
        result += f"🚨 Tunnel-Pakete: {len(meshLeaderboard['tunnelPackets'])}\n"
    
    if len(meshLeaderboard['audioPackets']) > 0:
        result += f"☎️ Audio-Pakete: {len(meshLeaderboard['audioPackets'])}\n"
    
    unwrap_n = meshLeaderboard.get("simTunnelUnwrapCount", 0)
    if unwrap_n > 0:
        result += f"📡 MQTT/Sim-Tunnel aufgeklappt: {unwrap_n}\n"

    result = result.strip()
    
    if result == "📊 Bestenliste 📊\n":
        result += (
            "Noch keine Rekorde — weiter funken! 📡\n"
            "Firmware 2.7+: „Broadcast Device Metrics“ in der Telemetrie aktivieren."
        )
    
    return result

def get_sysinfo(nodeID=0, deviceID=1):
    # Get the system telemetry data for return on the sysinfo command
    sysinfo = ''
    stats = str(displayNodeTelemetry(nodeID, deviceID, userRequested=True)) + " 🤖👀" + str(len(seenNodes))
    if "numPacketsTx:0" in stats or stats == -1:
        return "Telemetrie wird gesammelt — bitte gleich erneut versuchen ⏳"
    # replace Telemetry with Int in string
    stats = stats.replace("Telemetry", "Int")
    sysinfo += f"📊{stats}"
    return sysinfo

async def handleSignalWatcher():
    from modules.radio import signalWatcher
    from modules.settings import sigWatchBroadcastCh, sigWatchBroadcastInterface, lastHamLibAlert
    # monitor rigctld for signal strength and frequency
    while True:
        msg =  await signalWatcher()
        if msg != ERROR_FETCHING_DATA and msg is not None:
            logger.debug(f"System: Detected Alert from Hamlib {msg}")
            
            # check we are not spammig the channel limit messages to once per minute
            if time.time() - lastHamLibAlert > 60:
                lastHamLibAlert = time.time()
                # if sigWatchBrodcastCh list contains multiple channels, broadcast to all
                if type(sigWatchBroadcastCh) is list:
                    for ch in sigWatchBroadcastCh:
                        if antiSpam and ch != publicChannel:
                            send_message(msg, int(ch), 0, sigWatchBroadcastInterface)
                        else:
                            logger.warning(f"System: antiSpam prevented Alert from Hamlib {msg}")
                else:
                    if antiSpam and sigWatchBroadcastCh != publicChannel:
                        send_message(msg, int(sigWatchBroadcastCh), 0, sigWatchBroadcastInterface)
                    else:
                        logger.warning(f"System: antiSpam prevented Alert from Hamlib {msg}")

        await asyncio.sleep(1)
        pass

async def handleFileWatcher():
    global lastFileAlert
    # monitor the file system for changes
    while True:
        msg =  await watch_file()
        if msg != ERROR_FETCHING_DATA and msg is not None:
            logger.debug(f"System: Detected Alert from FileWatcher on file {file_monitor_file_path}")
            
            # check we are not spammig the channel limit messages to once per minute
            if time.time() - lastFileAlert > 60:
                lastFileAlert = time.time()
                # if fileWatchBroadcastCh list contains multiple channels, broadcast to all
                if type(file_monitor_broadcastCh) is list:
                    for ch in file_monitor_broadcastCh:
                        if antiSpam and int(ch) != publicChannel:
                            send_message(msg, int(ch), 0, 1)
                            if multiple_interface:
                                for i in range(2, 10):
                                    if globals().get(f'interface{i}_enabled'):
                                        send_message(msg, int(ch), 0, i)
                        else:
                            logger.warning(f"System: antiSpam prevented Alert from FileWatcher")
                else:
                    if antiSpam and file_monitor_broadcastCh != publicChannel:
                        send_message(msg, int(file_monitor_broadcastCh), 0, 1)
                        if multiple_interface:
                            for i in range(2, 10):
                                if globals().get(f'interface{i}_enabled'):
                                    send_message(msg, int(file_monitor_broadcastCh), 0, i)
                    else:
                        logger.warning(f"System: antiSpam prevented Alert from FileWatcher")

        await asyncio.sleep(1)
        pass

async def handleWsjtxWatcher():
    # monitor WSJT-X UDP broadcasts for decode messages
    from modules.radio import wsjtxMsgQueue, wsjtxMonitor
    from modules.settings import sigWatchBroadcastCh, sigWatchBroadcastInterface
    
    # Start the WSJT-X monitor task
    monitor_task = asyncio.create_task(wsjtxMonitor())
    
    while True:
        if wsjtxMsgQueue:
            msg = wsjtxMsgQueue.pop(0)
            logger.debug(f"System: Detected message from WSJT-X: {msg}")
            
            # Broadcast to configured channels
            if type(sigWatchBroadcastCh) is list:
                for ch in sigWatchBroadcastCh:
                    if antiSpam and int(ch) != publicChannel:
                        send_message(msg, int(ch), 0, sigWatchBroadcastInterface)
                    else:
                        logger.warning(f"System: antiSpam prevented Alert from WSJT-X")
            else:
                if antiSpam and sigWatchBroadcastCh != publicChannel:
                    send_message(msg, int(sigWatchBroadcastCh), 0, sigWatchBroadcastInterface)
                else:
                    logger.warning(f"System: antiSpam prevented Alert from WSJT-X")
        
        await asyncio.sleep(0.5)

async def handleJs8callWatcher():
    # monitor JS8Call TCP API for messages
    from modules.radio import js8callMsgQueue, js8callMonitor
    from modules.settings import sigWatchBroadcastCh, sigWatchBroadcastInterface
    
    # Start the JS8Call monitor task
    monitor_task = asyncio.create_task(js8callMonitor())
    
    while True:
        if js8callMsgQueue:
            msg = js8callMsgQueue.pop(0)
            logger.debug(f"System: Detected message from JS8Call: {msg}")
            
            # Broadcast to configured channels
            if type(sigWatchBroadcastCh) is list:
                for ch in sigWatchBroadcastCh:
                    if antiSpam and int(ch) != publicChannel:
                        send_message(msg, int(ch), 0, sigWatchBroadcastInterface)
                    else:
                        logger.warning(f"System: antiSpam prevented Alert from JS8Call")
            else:
                if antiSpam and sigWatchBroadcastCh != publicChannel:
                    send_message(msg, int(sigWatchBroadcastCh), 0, sigWatchBroadcastInterface)
                else:
                    logger.warning(f"System: antiSpam prevented Alert from JS8Call")
        
        await asyncio.sleep(0.5)

async def retry_interface(nodeID):
    global retry_int1, retry_int2, retry_int3, retry_int4, retry_int5, retry_int6, retry_int7, retry_int8, retry_int9
    global max_retry_count1, max_retry_count2, max_retry_count3, max_retry_count4, max_retry_count5, max_retry_count6, max_retry_count7, max_retry_count8, max_retry_count9

    if nodeID in _interface_reconnecting:
        return
    _interface_reconnecting.add(nodeID)

    if dont_retry_disconnect:
        logger.critical(f"System: dont_retry_disconnect is set, not retrying interface{nodeID}")
        _interface_reconnecting.discard(nodeID)
        exit_handler()

    globals()[f"retry_int{nodeID}"] = True
    iface = globals().get(f"interface{nodeID}")
    if iface is not None:
        try:
            iface.close()
        except Exception as e:
            logger.error(f"System: closing interface{nodeID}: {e}")
    globals()[f"interface{nodeID}"] = None

    globals()[f"max_retry_count{nodeID}"] -= 1
    remaining = globals()[f"max_retry_count{nodeID}"]
    logger.warning(
        f"System: Reconnecting interface{nodeID} in 15s "
        f"({remaining} attempt(s) left before exit)"
    )
    if remaining <= 0:
        logger.critical(f"System: Max retry count reached for interface{nodeID}")
        _interface_reconnecting.discard(nodeID)
        exit_handler()

    await asyncio.sleep(15)

    try:
        globals()[f"interface{nodeID}"] = open_mesh_interface(nodeID)
        try:
            globals()[f"myNodeNum{nodeID}"] = globals()[f"interface{nodeID}"].getMyNodeInfo()["num"]
        except Exception as e:
            logger.warning(f"System: myNodeNum{nodeID} after reconnect: {e}")
        try:
            refresh_channel_cache()
        except Exception:
            pass
        globals()[f"max_retry_count{nodeID}"] = interface_retry_count
        globals()[f"retry_int{nodeID}"] = False
        host_hint = ""
        if globals().get(f"interface{nodeID}_type") == "tcp":
            h, p = _tcp_host_port_for_interface(nodeID)
            host_hint = f" @ {h}:{p}"
        logger.info(f"System: Interface{nodeID} reconnected{host_hint}")
        _ndb.populate_from_interface(globals().get(f"interface{nodeID}"))
    except Exception as e:
        logger.error(f"System: Error reopening interface{nodeID}: {e}")
        globals()[f"retry_int{nodeID}"] = True
    finally:
        _interface_reconnecting.discard(nodeID)

handleSentinel_spotted = []
handleSentinel_loop = 0
async def handleSentinel(deviceID):
    global handleSentinel_spotted, handleSentinel_loop
    detectedNearby = None
    resolution = "unknown"

    closest_nodes = await get_closest_nodes(deviceID, returnCount=10)
    #logger.debug(f"handleSentinel: closest_nodes={closest_nodes}")

    if not closest_nodes or closest_nodes == ERROR_FETCHING_DATA:
        return

    # Find any watched node inside or outside the zone
    for node in closest_nodes:
        node_id = node['id']
        distance = node['distance']

        if str(node_id) in sentryIgnoreList:
            return
        # Message conditions
        if distance >= sentry_radius and str(node_id) and str(node_id) in sentryWatchList:
            # Outside zone
            detectedNearby = f"{get_name_from_number(node_id, 'long', deviceID)}, {get_name_from_number(node_id, 'short', deviceID)}, {node_id}, {decimal_to_hex(node_id)} at {distance}m (OUTSIDE ZONE)"
        elif distance <= sentry_radius and str(node_id) not in sentryWatchList:
            # Inside the zone
            detectedNearby = f"{get_name_from_number(node_id, 'long', deviceID)}, {get_name_from_number(node_id, 'short', deviceID)}, {node_id}, {decimal_to_hex(node_id)} at {distance}m (INSIDE ZONE)"

    #logger.debug(f"handleSentinel: loop={handleSentinel_loop}/{sentry_holdoff}, detectedNearby={detectedNearby} closest_nodes={closest_nodes}")
    if detectedNearby:
        handleSentinel_loop += 1
        #logger.debug(f"handleSentinel: detectedNearby={detectedNearby}, loop={handleSentinel_loop}/{sentry_holdoff}")
        if handleSentinel_loop >= sentry_holdoff:
            # Get resolution if available
            if positionMetadata and node_id in positionMetadata:
                metadata = positionMetadata[node_id]
                if metadata.get('precisionBits') is not None:
                    resolution = metadata.get('precisionBits')
            # Send message alert
            logger.warning(f"System: {detectedNearby} on Interface{deviceID} Accuracy is {resolution}bits")
            send_message(f"Sentry{deviceID}: {detectedNearby}", secure_channel, 0, secure_interface)
            
            # Send email alerts
            if enableSMTP and email_sentry_alerts:
                for email in sysopEmails:
                    send_email(email, f"Sentry{deviceID}: {detectedNearby}")

            # Execute external script alerts
            if cmdShellSentryAlerts and distance <= sentry_radius:
                # inside zone
                call_external_script('', script=sentryAlertNear)
                logger.info(f"System: Sentry Script Alert {sentryAlertNear} for NodeID:{node_id} on Interface{deviceID}")
            elif cmdShellSentryAlerts and distance >= sentry_radius:
                # outside zone
                call_external_script('', script=sentryAlertFar)
                logger.info(f"System: Sentry Script Alert {sentryAlertFar} for NodeID:{node_id} on Interface{deviceID}")

            handleSentinel_loop = 0 # Loop reset
    else:
        handleSentinel_loop = 0  # Reset if nothing detected

async def process_vox_queue():
    # process the voxMsgQueue
    from modules.settings import sigWatchBroadcastCh, sigWatchBroadcastInterface, voxMsgQueue
    items_to_process = voxMsgQueue[:]
    voxMsgQueue.clear()
    if len(items_to_process) > 0:
        logger.debug(f"System: Processing {len(items_to_process)} items in voxMsgQueue")
        for item in items_to_process:
            message = item
            for channel in sigWatchBroadcastCh:
                if antiSpam and int(channel) != publicChannel:
                    send_message(message, int(channel), 0, sigWatchBroadcastInterface)

async def handleTTS():
    from modules.radio import generate_and_play_tts, available_voices
    from modules.settings import ttsnoWelcome, tts_read_queue
    logger.debug("System: Handle TTS started")
    if not ttsnoWelcome:
        logger.debug("System: Playing TTS welcome message to disable set 'ttsnoWelcome = True' in settings.ini")
        await generate_and_play_tts("Hey its Cheerpy! Thanks for using Meshing-Around on Meshtasstic!", available_voices[0])
    try:
        while True:
            if tts_read_queue:
                tts_read = tts_read_queue.pop(0)
                voice = available_voices[0]
                # ensure the tts_read ends with a punctuation mark
                if not tts_read.endswith(('.', '!', '?')):
                    tts_read += '.'
                try:
                    await generate_and_play_tts(tts_read, voice)
                except Exception as e:
                    logger.error(f"System: TTShandler error: {e}")
            await asyncio.sleep(1)
    except Exception as e:
        logger.critical(f"System: handleTTS crashed: {e}")

async def watchdog():
    global localTelemetryData, retry_int1, retry_int2, retry_int3, retry_int4, retry_int5, retry_int6, retry_int7, retry_int8, retry_int9
    logger.debug("System: Watchdog started")
    wd_last_logged_minute = -1
    while True:
        await asyncio.sleep(20)
        now = datetime.now()

                    
        if now.minute % 20 == 0 and now.minute != wd_last_logged_minute:
            # perform memory cleanup every 10 minutes
            cleanup_memory()
            wd_last_logged_minute = now.minute

        # check all interfaces
        for i in range(1, 10):
            interface = globals().get(f'interface{i}')
            int_enabled = globals().get(f'interface{i}_enabled')
            if not int_enabled:
                continue

            if globals().get(f'retry_int{i}'):
                if i not in _interface_reconnecting:
                    try:
                        await retry_interface(i)
                    except Exception as e:
                        logger.error(f"System: retrying interface{i}: {e}")
                continue

            if interface is not None:
                try:
                    firmware = getNodeFirmware(0, i)
                except Exception as e:
                    logger.error(
                        f"System: interface{i} not responding ({e}), scheduling reconnect"
                    )
                    mark_interface_for_retry(i, "health check failed")
                    continue

                if sentry_enabled:
                    await handleSentinel(i)

                handleMultiPing(0, i)

                if usAlerts or checklist_enabled or (enableDEalerts and deAlertAutoBroadcast):
                    handleAlertBroadcast(i)

                intData = displayNodeTelemetry(0, i)
                if intData != -1 and localTelemetryData[0][f'lastAlert{i}'] != intData:
                    logger.debug(intData + f" Firmware:{firmware}")
                    localTelemetryData[0][f'lastAlert{i}'] = intData
        
        # check for noisy telemetry
        if noisyNodeLogging:
            noisyTelemetryCheck()

        # vox queue processing
        if voxDetectionEnabled:
            await process_vox_queue()
        
        # check the load_bbsdm flag to reload the BBS messages from disk
        if bbs_enabled and bbsAPI_enabled:
            load_bbsdm()
            load_bbsdb()

def saveAllData():
    try:
        # Save BBS data if enabled
        if bbs_enabled:
            save_bbsdb()
            save_bbsdm()
            logger.debug("Persistence: BBS data saved")

        if polls_enabled:
            save_polls()
            logger.debug("Persistence: Polls data saved")

        # Save leaderboard data if enabled
        if logMetaStats:
            sync_leaderboard_from_nodedb()
            if saveLeaderboard():
                logger.debug("Persistence: Leaderboard data saved")

        # Save ban list
        if save_bbsBanList():
            logger.debug("Persistence: Ban list saved")

        # Save auto-ban list
        if save_autoBanList():
            logger.debug("Persistence: Auto-ban list saved")

        # Save persistent node DB (only writes when dirty)
        if _ndb.save_nodedb():
            logger.debug("Persistence: NodeDB saved")

        #logger.info("Persistence: Save completed")
    except Exception as e:
        logger.error(f"Persistence: Save error: {e}")

async def dataPersistenceLoop():
    """Data persistence service loop for periodic data saving"""
    logger.debug("Persistence: Loop started")
    while True:
        await asyncio.sleep(dataPersistence_interval)
        saveAllData()

def exit_handler():
    # Close the interface and save all data
    logger.debug(f"System: Closing Autoresponder")
    try:
        logger.debug(f"System: Closing Interface1")
        interface1.close()
        if multiple_interface:
            for i in range(2, 10):
                if globals().get(f'interface{i}_enabled'):
                    logger.debug(f"System: Closing Interface{i}")
                    globals()[f'interface{i}'].close()
    except Exception as e:
        logger.error(f"System: closing: {e}")

    saveAllData()

    logger.debug(f"System: Exiting")
    asyncLoop.stop()
    asyncLoop.close()
    exit (0)
