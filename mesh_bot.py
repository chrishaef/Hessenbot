#!/usr/bin/env python3
# Meshtastic Autoresponder MESH Bot
# K7MHI Kelly Keeton 2025
try:
    from pubsub import pub
except ImportError:
    print(f"Important dependencies are not met, try install.sh\n\n Did you mean to './launch.sh mesh' using a virtual environment.")
    exit(1)

import asyncio
import re
import time # for sleep, get some when you can :)
import random
from datetime import datetime
from modules.log import logger, CustomFormatter, msgLogger, getPrettyTime
import modules.settings as my_settings
from modules.system import *
import modules.nodedb as _ndb

# list of commands to remove from the default list for DM only
restrictedCommands = []
restrictedResponse = ""


def auto_response(message, snr, rssi, hop, pkiStatus, message_from_id, channel_number, deviceID, isDM):
    global cmdHistory
    #Auto response to messages
    message_lower = message.lower()
    bot_response = "🤖I'm sorry, I'm afraid I can't do that."

    # Command List processes system.trap_list. system.messageTrap() sends any commands to here
    default_commands = {
    "ack": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "ask:": lambda: handle_llm(message_from_id, channel_number, deviceID, message, publicChannel),
    "askai": lambda: handle_llm(message_from_id, channel_number, deviceID, message, publicChannel),
    "bannode": lambda: handle_bbsban(message, message_from_id, isDM),
    "bbsack": lambda: bbs_sync_posts(message, message_from_id, deviceID),
    "bbsdelete": lambda: handle_bbsdelete(message, message_from_id),
    "bbshelp": bbs_help,
    "bbsinfo": lambda: get_bbs_stats(),
    "bbslink": lambda: bbs_sync_posts(message, message_from_id, deviceID),
    "bbslist": bbs_list_messages,
    "bbspost": lambda: handle_bbspost(message, message_from_id, deviceID),
    "bbsread": lambda: handle_bbsread(message),
    "approvecl": lambda: handle_checklist(message, message_from_id, deviceID),
    "denycl": lambda: handle_checklist(message, message_from_id, deviceID),
    "checkin": lambda: handle_checklist(message, message_from_id, deviceID),
    "checklist": lambda: handle_checklist(message, message_from_id, deviceID),
    "checkout": lambda: handle_checklist(message, message_from_id, deviceID),
    "clearsms": lambda: handle_sms(message_from_id, message),
    "cmd": lambda: handle_cmd(message, message_from_id, deviceID),
    "cq": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "cqcq": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "cqcqcq": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "dx": lambda: handledxcluster(message, message_from_id, deviceID),
    "echo": lambda: handle_echo(message, message_from_id, deviceID, isDM, channel_number),
    "email:": lambda: handle_email(message_from_id, message),
    "hfcond": hf_band_conditions,
    "history": lambda: handle_history(message, message_from_id, deviceID, isDM),
    "howfar": lambda: handle_howfar(message, message_from_id, deviceID, isDM),
    "howtall": lambda: handle_howtall(message, message_from_id, deviceID, isDM),
    "item": lambda: handle_inventory(message, message_from_id, deviceID),
    "itemadd": lambda: handle_inventory(message, message_from_id, deviceID),
    "itemlist": lambda: handle_inventory(message, message_from_id, deviceID),
    "itemloan": lambda: handle_inventory(message, message_from_id, deviceID),
    "itemremove": lambda: handle_inventory(message, message_from_id, deviceID),
    "itemreset": lambda: handle_inventory(message, message_from_id, deviceID),
    "itemreturn": lambda: handle_inventory(message, message_from_id, deviceID),
    "itemsell": lambda: handle_inventory(message, message_from_id, deviceID),
    "itemstats": lambda: handle_inventory(message, message_from_id, deviceID),
    "cart": lambda: handle_inventory(message, message_from_id, deviceID),
    "cartadd": lambda: handle_inventory(message, message_from_id, deviceID),
    "cartbuy": lambda: handle_inventory(message, message_from_id, deviceID),
    "cartclear": lambda: handle_inventory(message, message_from_id, deviceID),
    "cartlist": lambda: handle_inventory(message, message_from_id, deviceID),
    "cartremove": lambda: handle_inventory(message, message_from_id, deviceID),
    "cartsell": lambda: handle_inventory(message, message_from_id, deviceID),
    "latest": lambda: get_newsAPI(message, message_from_id, deviceID, isDM),
    "leaderboard": lambda: get_mesh_leaderboard(message, message_from_id, deviceID),
    "lheard": lambda: handle_lheard(message, message_from_id, deviceID, isDM),
    "map": lambda: mapHandler(message_from_id, deviceID, channel_number, message, snr, rssi, hop),
    "messages": lambda: handle_messages(message, deviceID, channel_number, msg_history, publicChannel, isDM),
    "moon": lambda: handle_moon(message_from_id, deviceID, channel_number),
    "motd": lambda: handle_motd(message, message_from_id, isDM),
    "ping": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "pinging": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "pong": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "readnews": lambda: handleNews(message_from_id, deviceID, message, isDM),
    "readrss": lambda: get_rss_feed(message),
    "rlist": lambda: handle_repeaterQuery(message_from_id, deviceID, channel_number),
    "satpass": lambda: handle_satpass(message_from_id, deviceID, message),
    "setemail": lambda: handle_email(message_from_id, message),
    "setsms": lambda: handle_sms( message_from_id, message),
    "sitrep": lambda: handle_lheard(message, message_from_id, deviceID, isDM),
    "sms:": lambda: handle_sms(message_from_id, message),
    "solar": lambda: drap_xray_conditions() + "\n" + solar_conditions() + "\n" + get_noaa_scales_summary(),
    "sun": lambda: handle_sun(message_from_id, deviceID, channel_number),
    "sysinfo": lambda: sysinfo(message, message_from_id, deviceID, isDM),
    "test": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "testing": lambda: handle_ping(message_from_id, deviceID, message, hop, snr, rssi, isDM, channel_number),
    "warning": lambda: handle_warning(
        message_from_id, deviceID, channel_number, isDM
    ),
    "dealert": lambda: handle_dealert(message_from_id, deviceID),
    "whereami": lambda: handle_whereami(message_from_id, deviceID, channel_number),
    "loc": lambda: handle_loc(message, message_from_id, deviceID, channel_number),
    "whoami": lambda: handle_whoami(message_from_id, deviceID, hop, snr, rssi, pkiStatus),
    "whois": lambda: handle_whois(message, deviceID, channel_number, message_from_id),
    "wiki": lambda: handle_wiki(message, isDM),
    "wx": lambda: handle_wxc(message_from_id, deviceID),
    "uv": lambda: handle_wx_extra(message_from_id, deviceID, "uv"),
    "regen": lambda: handle_wx_extra(message_from_id, deviceID, "regen"),
    "blitz": lambda: handle_wx_extra(message_from_id, deviceID, "blitz"),
    "metar": lambda: handle_metar(message_from_id, deviceID, message),
    "x:": lambda: handleShellCmd(message, message_from_id, channel_number, isDM, deviceID),
    "📍": lambda: handle_whoami(message_from_id, deviceID, hop, snr, rssi, pkiStatus),
    "🔔": lambda: handle_alertBell(message_from_id, deviceID, message),
    "🐝": lambda: read_file("bee.txt", True),
    # any value from system.py:trap_list_emergency will trigger the emergency function
    "112": lambda: handle_emergency(message_from_id, deviceID, message),
    "911": lambda: handle_emergency(message_from_id, deviceID, message),
    "999": lambda: handle_emergency(message_from_id, deviceID, message),
    "ambulance": lambda: handle_emergency(message_from_id, deviceID, message),
    "emergency": lambda: handle_emergency(message_from_id, deviceID, message),
    "fire": lambda: handle_emergency(message_from_id, deviceID, message),
    "police": lambda: handle_emergency(message_from_id, deviceID, message),
    "rescue": lambda: handle_emergency(message_from_id, deviceID, message),
    }

    if getattr(my_settings, "polls_enabled", False):
        default_commands["poll"] = lambda: handle_poll_command(
            message, message_from_id, isDM
        )

    # set the command handler
    command_handler = default_commands
    cmds = [] # list to hold the commands found in the message
    # check the message for commands words list, processed after system.messageTrap
    for key in command_handler:
        word = message_lower.split(' ')
        if my_settings.cmdBang:
            # strip the !
            if word[0].startswith("!"):
                word[0] = word[0][1:]
        if key in word:
            # append all the commands found in the message to the cmds list
            cmds.append({'cmd': key, 'index': message_lower.index(key)})
        # check for commands with a question mark
        if key + "?" in word:
            # append all the commands found in the message to the cmds list
            cmds.append({'cmd': key, 'index': message_lower.index(key)})

    if len(cmds) > 0:
        # sort the commands by index value
        cmds = sorted(cmds, key=lambda k: k['index'])
    
        # INFO so logs/meshbot.log contains this line when sysloglevel>=INFO (dashboard „Letzte Befehle“).
        logger.info(f"System: Bot detected Commands:{cmds} From: {get_name_from_number(message_from_id)} isDM:{isDM}")
        bot_response = command_handler[cmds[0]['cmd']]()
        if len(cmdHistory) > 50:
            cmdHistory.pop(0)
        cmdHistory.append({'nodeID': message_from_id, 'cmd': cmds[0]['cmd'], 'time': time.time()})
    return bot_response

def handle_cmd(message, message_from_id, deviceID):
    # why CMD? its just a command list. a terminal would normally use "Help"
    # I didnt want to invoke the word "help" in Meshtastic due to its possible emergency use
    if " " in message and message.split(" ")[1] in trap_list:
        return "🤖 Befehle einfach direkt im Chat senden (ohne cmd davor)."
    return help_message

def handle_ping(message_from_id, deviceID,  message, hop, snr, rssi, isDM, channel_number):
    global multiPing
    if  "?" in message and isDM:
        pingHelp = (
            "🤖 Hessenbot · Ping-Hilfe:\n"
            "🏓 ping / pong / test — QSL: Name [ID] @ Ort | Hops LoRa/MQTT\n"
            "🏓 ping <Zahl> — mehrere Pings per DM.\n"
            "🏓 ping @Knoten — Ping als BBS-DM."
        )
        return pingHelp

    msg_lower = message.lower()
    words = msg_lower.split()
    msg = ""
    type = ""
    rich_ping = True

    if "test" in msg_lower or "testing" in msg_lower:
        msg = format_ping_qsl_response(message_from_id, deviceID, hop, "QSL")
        type = "🎙TEST"
    elif "pong" in words:
        msg = format_ping_qsl_response(message_from_id, deviceID, hop, "QSL")
        type = "🏓PONG"
    elif "ping" in msg_lower or "pinging" in msg_lower:
        msg = format_ping_qsl_response(message_from_id, deviceID, hop, "QSL")
        type = "🏓PING"
    elif "ack" in msg_lower:
        msg = format_ping_qsl_response(message_from_id, deviceID, hop, "ACK")
        type = "✋ACK"
    elif "cqcq" in msg_lower or "cq" in words or "cqcqcq" in msg_lower:
        msg = format_ping_qsl_response(message_from_id, deviceID, hop, "QSL")
        type = "CQ"
    else:
        msg = format_ping_qsl_response(message_from_id, deviceID, hop, "QSL")
        type = "QSL"
        rich_ping = True

    if "@" in message:
        msg = msg + " @" + message.split("@")[1]
        type = type + " @" + message.split("@")[1]

        # check for ping to @nodeID and allow BBS DM
        toNode = message.split("@")[1].strip().split(" ")[0]
        # validate toNode is shortname
        if len(toNode) <= 4:
            toNode = get_num_from_short_name(toNode, deviceID)
            if toNode and isinstance(toNode, int) and toNode != 0:
                if my_settings.bbs_enabled:
                    msg_result = None
                    logger.debug(f"System: Sending ping as BBS DM to @{toNode} from {get_name_from_number(message_from_id, 'short', deviceID)}")
                    msg_result = bbs_post_dm(toNode, "Ping von Hessenbot (Meshhessen)!", message_from_id)
                    # exit the function
                    return msg_result if msg_result else logger.warning(f"System: ping @nodeID detected but no BBS to send with, enable BBS in settings.ini")

    elif "#" in message:
        msg = msg + " #" + message.split("#")[1]
        type = type + " #" + message.split("#")[1]

    # check for multi ping request
    if " " in message:
        # if stop multi ping
        if "stop" in message.lower():
            for i in range(0, len(multiPingList)):
                if multiPingList[i].get('message_from_id') == message_from_id:
                    multiPingList.pop(i)
                    msg = "🛑 Auto-Ping gestoppt"

        # if 3 or more entries (2 or more active), throttle the multi-ping for congestion
        if len(multiPingList) > 2:
            msg = "🚫⛔️ Auto-Ping: Hessenbot ausgelastet. ⏳ Bitte später."
            pingCount = -1
        else:
            # set inital pingCount
            try:
                pingCount = int(message.split(" ")[1])
                if pingCount == 123 or pingCount == 1234:
                    pingCount =  1
                elif not my_settings.autoPingInChannel and not isDM:
                    # no autoping in channels
                    pingCount = 1

                if pingCount > 51 and pingCount <= 101:
                    pingCount = 50
                if pingCount > 800:
                    ban_hammer(message_from_id, deviceID, reason="Excessive auto-ping request")
                    return "🚫⛔️ Auto-Ping abgelehnt."
            except ValueError:
                pingCount = -1
    
        if pingCount > 1:
            multiPingList.append({'message_from_id': message_from_id, 'count': pingCount + 1, 'type': type, 'deviceID': deviceID, 'channel_number': channel_number, 'startCount': pingCount})
            logger.info(f"System: Starting auto-ping of type {type} for {pingCount} pings to {get_name_from_number(message_from_id, 'short', deviceID)}")
            if type == "🎙TEST":
                msg = f"🛜 Puffertest: ~{int(maxBuffer // pingCount)} Zeichen/Teil, max {maxBuffer} in {pingCount} Nachrichten"
            else:
                msg = f"🚦 Starte {pingCount} Auto-Pings"

    # Kanal: @ nur wenn Name noch nicht in der Antwort steht (altes Kurzformat)
    if not my_settings.useDMForResponse and not isDM and not rich_ping:
        msg = "@" + get_name_from_number(message_from_id, "short", deviceID) + " " + msg

    return msg

def handle_alertBell(message_from_id, deviceID, message):
    msg = ["the only prescription is more 🐮🔔🐄🛎️", "what this 🤖 needs is more 🐮🔔🐄🛎️", "🎤ring my bell🛎️🔔🎶"]
    return random.choice(msg)

def handle_emergency(message_from_id, deviceID, message):
    myNodeNum = globals().get(f'myNodeNum{deviceID}', 777)
    # if user in bbs_ban_list return
    if str(message_from_id) in my_settings.bbs_ban_list:
        # silent discard
        hammer_value = ban_hammer(message_from_id, deviceID, reason="Emergency Alert from banned node")
        logger.warning(f"System: {message_from_id} on spam list, no emergency responder alert sent. Ban hammer value: {hammer_value}")
        return ''
    # trgger alert to emergency_responder_alert_channel
    if message_from_id != 0:
        nodeLocation = get_node_location(message_from_id, deviceID)
        # if default location is returned set to Unknown
        if nodeLocation[0] == my_settings.latitudeValue and nodeLocation[1] == my_settings.longitudeValue:
            nodeLocation = ["?", "?"]
        nodeInfo = (
            f"{get_name_from_number(message_from_id, 'short', deviceID)} "
            f"via {get_name_from_number(myNodeNum, 'short', deviceID)} "
            f"GPS {nodeLocation[0]}, {nodeLocation[1]}"
        )
        msg = f"🔔🚨 Möglicher Notruf (Hessenbot/Meshhessen): {nodeInfo}"
        # alert the emergency_responder_alert_channel
        send_message(msg, my_settings.emergency_responder_alert_channel, 0, my_settings.emergency_responder_alert_interface)
        logger.warning(f"System: {message_from_id} Emergency Assistance Requested in {message}")
        # send the message out via email/sms
        if my_settings.enableSMTP:
            for user in my_settings.sysopEmails:
                send_email(user, f"Emergency Assistance Requested by {nodeInfo} in {message}", message_from_id)
        return my_settings.EMERGENCY_RESPONSE

def handle_motd(message, message_from_id, isDM):
    msg = my_settings.MOTD
    isAdmin = isNodeAdmin(message_from_id)
    if  "?" in message:
        msg = "Tagesnachricht (MOTD). Admin: motd $ Dein Text"
    elif "$" in message and isAdmin:
        my_settings.MOTD = message.split("$")[1]
        my_settings.MOTD = my_settings.MOTD.rstrip()
        logger.debug(f"System: {message_from_id} temporarly changed my_settings.MOTD: {my_settings.MOTD}")
        msg = "MOTD geändert: " + my_settings.MOTD
    return msg

def handle_echo(message, message_from_id, deviceID, isDM, channel_number):
    # Check if user is admin
    isAdmin = isNodeAdmin(message_from_id)

    # Admin extended syntax: echo <string> c=<channel> d=<device>
    if isAdmin and message.strip().lower().startswith("echo ") and not message.strip().endswith("?"):
        msg_to_echo = message.split(" ", 1)[1]
        target_channel = channel_number
        target_device = deviceID

        # Split into words to find c= and d=, but preserve spaces in message
        words = msg_to_echo.split()
        new_words = []
        for w in words:
            if w.startswith("c=") and w[2:].isdigit():
                target_channel = int(w[2:])
            elif w.startswith("d=") and w[2:].isdigit():
                target_device = int(w[2:])
            else:
                new_words.append(w)
        msg_to_echo = " ".join(new_words).strip()
        # Replace motd/MOTD with the current MOTD from settings
        msg_to_echo = " ".join(my_settings.MOTD if w.lower() == "motd" else w for w in msg_to_echo.split())
        # Replace welcome! with the current welcome_message from settings
        msg_to_echo = " ".join(my_settings.welcome_message if w.lower() == "welcome!" else w for w in msg_to_echo.split())

        # Send echo to specified channel/device
        logger.debug(f"System: Admin Echo to channel {target_channel} device {target_device} message: {msg_to_echo}")
        time.sleep(splitDelay) # throttle for 2x send
        send_message(msg_to_echo, target_channel, 0, target_device)
        time.sleep(splitDelay) # throttle for 2x send
        return f"🐬 Echo an Kanal {target_channel}, Gerät {target_device}"

    # dev echoBinary off
    echoBinary = False
    if echoBinary:
        try:
            port_num = 256
            synch_word = b"echo:"
            parts = message.split("echo ", 1)
            if len(parts) > 1 and parts[1].strip() != "":
                msg_to_echo = parts[1]
                raw_bytes = synch_word + msg_to_echo.encode('utf-8')
                send_raw_bytes(message_from_id, raw_bytes, nodeInt=deviceID, channel=channel_number, portnum=port_num)
                return f"Sent binary echo message to {message_from_id} to {port_num} on channel {channel_number} device {deviceID}"
        except Exception as e:
            logger.error(f"System: Echo Exception {e}")

    if "?" in message:
        isAdmin = isNodeAdmin(message_from_id)
        if isAdmin:
            return (
                "Admin: echo <Text> c=<Kanal> d=<Gerät>\n"
                "Beispiel: echo Hallo Welt c=1 d=2"
            )
        return "Gibt deinen Text zurück. Beispiel: echo Hallo Welt"

    # process normal echo back to user
    elif message.strip().lower().startswith("echo "):
        parts = message.split("echo ", 1)
        if len(parts) > 1 and parts[1].strip() != "":
            echo_msg = parts[1]
            if channel_number != my_settings.echoChannel and not isDM:
                echo_msg = "@" + get_name_from_number(message_from_id, 'short', deviceID) + " " + echo_msg
            return echo_msg
        else:
            return "Bitte Text angeben. Beispiel: echo Hallo Welt"
    return "🐬echo.."

def handle_dealert(message_from_id, deviceID):
    if my_settings.enableDEalerts:
        return get_nina_alerts()
    return "🤖NINA/Warnung Bund ist in der Konfiguration deaktiviert."

def handle_wxc(message_from_id, deviceID, days=None, vox=False):
    from modules.wx_meteo import format_wx_info_header, get_wx_meteo

    location = get_node_location(message_from_id, deviceID)
    unit = 1 if my_settings.use_metric else 0
    report = get_wx_meteo(str(location[0]), str(location[1]), unit)
    if not report or report == ERROR_FETCHING_DATA:
        return report
    header = format_wx_info_header(location[0], location[1])
    return f"{header}\n{report}"


def handle_wx_extra(message_from_id, deviceID, cmd: str):
    if not my_settings.location_enabled:
        return "Standortmodul aus ([location] enabled = False)."
    if not getattr(my_settings, "use_meteo_wxApi", False):
        return "Open-Meteo (!wx) ist in der Konfiguration deaktiviert."
    if not getattr(my_settings, "wx_extra_commands", True):
        return f"🤖 !{cmd} ist in der Konfiguration deaktiviert (wxExtraCommands)."
    from modules.wx_extra import get_blitz, get_regen, get_uv

    location = get_node_location(message_from_id, deviceID)
    lat, lon = str(location[0]), str(location[1])
    if cmd == "uv":
        return get_uv(lat, lon)
    if cmd == "regen":
        return get_regen(lat, lon)
    if cmd == "blitz":
        return get_blitz(lat, lon)
    return "Unbekannter Wetter-Befehl."


def handle_metar(message_from_id, deviceID, message=""):
    if not my_settings.location_enabled:
        return "Standortmodul aus ([location] enabled = False)."
    if not getattr(my_settings, "metar_enabled", True):
        return "🤖 METAR (!metar) ist in der Konfiguration deaktiviert."
    from modules.metar import (
        get_metar,
        get_metar_by_icao,
        get_metar_decode_help,
        parse_metar_icao_from_message,
    )

    if "?" in (message or ""):
        return get_metar_decode_help()

    icao = parse_metar_icao_from_message(message or "")
    if icao:
        return get_metar_by_icao(icao)

    location = get_node_location(message_from_id, deviceID)
    return get_metar(str(location[0]), str(location[1]))


def handle_warning(message_from_id, deviceID, channel_number, isDM):
    if not my_settings.enableDEalerts:
        return "🤖NINA/Warnung Bund ist in der Konfiguration deaktiviert."
    lat, lon, from_gps = get_node_location_with_source(message_from_id, deviceID)
    parts = build_warning_messages(lat, lon, from_gps, include_detail=isDM or my_settings.useDMForResponse)
    if not parts:
        return WARNING_NONE_MSG
    dest = message_from_id if my_settings.useDMForResponse or isDM else 0
    for extra in parts[1:]:
        time.sleep(my_settings.splitDelay)
        send_message(extra, channel_number, dest, deviceID)
    return parts[0]

def handle_emergency_alerts(message, message_from_id, deviceID):
    if my_settings.enableDEalerts:
        return get_nina_alerts()
    return "NINA/Warnung-Bund (DE) nicht aktiv."

def handle_checklist(message, message_from_id, deviceID):
    name = get_name_from_number(message_from_id, 'short', deviceID)
    location = get_node_location(message_from_id, deviceID)
    return process_checklist_command(message_from_id, message, name, location)

def handle_inventory(message, message_from_id, deviceID):
    name = get_name_from_number(message_from_id, 'short', deviceID)
    return process_inventory_command(message_from_id, message, name)

def handle_bbspost(message, message_from_id, deviceID):
    if "$" in message and not "example:" in message:
        subject = message.split("$")[1].split("#")[0]
        subject = subject.rstrip()
        if "#" in message:
            body = message.split("#", 1)[1]
            body = body.rstrip()
            logger.info(f"System: BBS Post: {subject} Body: {body}")
            return bbs_post_message(subject, body, message_from_id)
        elif not "example:" in message:
            return "Beispiel: bbspost $Betreff #✉️Nachricht"
    elif "@" in message and not "example:" in message:
        toNode = message.split("@")[1].split("#")[0]
        toNode = toNode.rstrip()
        if toNode.startswith("!") and len(toNode) == 9:
            # mesh !hex
            try:
                toNode = int(toNode.strip("!"),16)
            except ValueError as e:
                toNode = 0
        elif toNode.isalpha() or not toNode.isnumeric() or len(toNode) < 5:
            # try short name
            toNode = get_num_from_short_name(toNode, deviceID)

        if "#" in message:
            if toNode == 0:
                return "Knoten nicht gefunden: " + message.split("@")[1].split("#")[0]
            body = message.split("#", 1)[1]
            body = body.rstrip()
            logger.info(f"System: BBS Post DM to: {toNode} Body: {body}")
            return bbs_post_dm(toNode, body, message_from_id)
        else:
            return "Beispiel: bbspost @Kurzname/!hex #✉️Nachricht"
    elif not "example:" in message:
        return "Beispiel: bbspost $Betreff #✉️Text oder bbspost @Knoten #✉️Text"

def handle_bbsread(message):
    if "#" in message and not "example:" in message:
        messageID = int(message.split("#")[1])
        return bbs_read_message(messageID)
    elif not "example:" in message:
        return "Bitte Nummer: bbsread #14"

def handle_bbsdelete(message, message_from_id):
    if "#" in message and not "example:" in message:
        messageID = int(message.split("#")[1])
        return bbs_delete_message(messageID, message_from_id)
    elif not "example:" in message:
        return "Bitte Nummer: bbsdelete #14"

def handle_messages(message, deviceID, channel_number, msg_history, publicChannel, isDM):
    msg_ch = int(getattr(my_settings, "messages_channel", 1))
    msg_limit = int(getattr(my_settings, "messages_limit", 5))
    ch_label = format_channel_label(msg_ch, deviceID)

    if "?" in message and isDM:
        return (
            f"{message.split('?')[0]}? — letzte {msg_limit} Nachrichten von Kanal {msg_ch} "
            f"({ch_label}), ohne Bot-Befehle."
        )

    filtered_msgs = [
        msgH
        for msgH in msg_history
        if msgH[4] == deviceID and int(msgH[2]) == msg_ch
    ]
    filtered_msgs = filtered_msgs[-msg_limit:][::-1]
    if my_settings.reverseSF:
        filtered_msgs = filtered_msgs[::-1]

    response = ""
    header = f"📨 {ch_label} (letzte {msg_limit}):\n"
    for msgH in filtered_msgs:
        new_line = f"\n{msgH[0]}: {msgH[1]}"
        test_response = response + new_line
        if len(test_response.encode("utf-8")) > maxBuffer:
            msg_text = msgH[1]
            truncated = False
            trunc_marker = "..."
            while (
                len(msg_text) > 0
                and len(
                    (response + f"\n{msgH[0]}: {msg_text}{trunc_marker}").encode("utf-8")
                )
                > maxBuffer
            ):
                msg_text = msg_text[:-1]
                truncated = True
            if len(msg_text) > 10:
                if truncated:
                    response += f"\n{msgH[0]}: {msg_text}{trunc_marker}"
                else:
                    response += f"\n{msgH[0]}: {msg_text}"
                break
            continue
        response += new_line

    if len(response) > 0:
        return header + response
    return f"Keine 📭 Nachrichten auf {ch_label} im Verlauf"

def handle_sun(message_from_id, deviceID, channel_number, vox=False):
    if vox:
        # return a default message if vox is enabled
        return get_sun(str(my_settings.latitudeValue), str(my_settings.longitudeValue))
    location = get_node_location(message_from_id, deviceID, channel_number)
    return get_sun(str(location[0]), str(location[1]))

def handle_satpass(message_from_id, deviceID, message):
    if "?" in message:
        return (
            "satpass [NORAD] — nächster sichtbarer Überflug (n2yo). "
            "Ohne Nummer: erster Eintrag aus satList in config.ini. "
            "Beispiel ISS: satpass 25544"
        )
    norad = None
    for part in message.replace("!", " ").split():
        if part.isdigit():
            norad = part
            break
    if norad is None:
        sat_list = getattr(my_settings, "satListConfig", ["25544"])
        norad = (sat_list[0] if sat_list else "25544").strip()
    location = get_node_location(message_from_id, deviceID)
    return getNextSatellitePass(norad, location[0], location[1])

def sysinfo(message, message_from_id, deviceID, isDM):
    if "?" in message:
        return "sysinfo — System- und Telemetrie-Infos von Hessenbot."
    else:
        if enable_runShellCmd and file_monitor_enabled:
            # get the system information from the shell script
            # this is an example of how to run a shell script and return the data
            shellData = call_external_script('', "script/sysEnv.sh")
            # check if the script returned data
            if shellData == "" or shellData == None:
                # no data returned from the script
                shellData = "Shell-Skript lieferte keine Daten"
            # if not an admin remove any line in the shellData that had 'IP:' in it
            if (str(message_from_id) not in bbs_admin_list) or (not isDM):
                shell_lines = shellData.splitlines()
                filtered_lines = [line for line in shell_lines if 'IP:' not in line]
                shellData = "\n".join(filtered_lines)
            return get_sysinfo(message_from_id, deviceID) + "\n" + shellData.rstrip()
        else:
            return get_sysinfo(message_from_id, deviceID)

def handle_lheard(message, nodeid, deviceID, isDM):
    if  "?" in message and isDM:
        return f"{message.split('?')[0]} — zuletzt gehörte Knoten im Mesh."

    # display last heard nodes add to response
    bot_response = "Zuletzt gehört\n"
    bot_response += str(get_node_list(1))

    # show last users of the bot with the cmdHistory list
    history = handle_history(message, nodeid, deviceID, isDM, lheard=True)
    if history:
        bot_response += f'Zuletzt aktiv\n{history}'
    else:
        # trim the last \n
        bot_response = bot_response[:-1]

    # get count of nodes heard
    bot_response += f"\n👀 Im Mesh: {len(seenNodes)}"

    # bot_response += getNodeTelemetry(deviceID)
    return bot_response

def handle_history(message, nodeid, deviceID, isDM, lheard=False):
    global cmdHistory, lheardCmdIgnoreNode, bbs_admin_list
    msg = ""
    buffer = []

    if  "?" in message and isDM:
        return f"{message.split('?')[0]} — letzte Befehle an Hessenbot."

    # show the last commands from the user to the bot
    if not lheard:
        for i in range(len(cmdHistory)):
            cmdTime = round((time.time() - cmdHistory[i]['time']) / 600) * 5
            prettyTime = getPrettyTime(cmdTime)

            # history display output
            if str(nodeid) in bbs_admin_list and cmdHistory[i]['nodeID'] not in lheardCmdIgnoreNode:
                buffer.append((get_name_from_number(cmdHistory[i]['nodeID'], 'short', deviceID), cmdHistory[i]['cmd'], prettyTime))
            elif cmdHistory[i]['nodeID'] == nodeid and cmdHistory[i]['nodeID'] not in lheardCmdIgnoreNode:
                buffer.append((get_name_from_number(nodeid, 'short', deviceID), cmdHistory[i]['cmd'], prettyTime))
        # message for output of the last commands
        buffer.reverse()
        # only return the last 4 commands
        if len(buffer) > 4:
            buffer = buffer[-4:]
        # create the message from the buffer list
        for i in range(0, len(buffer)):
            msg += f"{buffer[i][0]}: {buffer[i][1]} :{buffer[i][2]} her"
            if i < len(buffer) - 1:
                msg += "\n" # add a new line if not the last line
    else:
        # sort the cmdHistory list by time, return the username and time into a new list which used for display
        for i in range(len(cmdHistory)):
            cmdTime = round((time.time() - cmdHistory[i]['time']) / 600) * 5
            prettyTime = getPrettyTime(cmdTime)

            if cmdHistory[i]['nodeID'] not in lheardCmdIgnoreNode:
                # add line to a new list for display
                nodeName = get_name_from_number(cmdHistory[i]['nodeID'], 'short', deviceID)
                if not any(d[0] == nodeName for d in buffer):
                    buffer.append((nodeName, prettyTime))
                else:
                    # update the time for the node in the buffer for the latest time in cmdHistory
                    for j in range(len(buffer)):
                        if buffer[j][0] == nodeName:
                            buffer[j] = (nodeName, prettyTime)

        # create the message from the buffer list
        buffer.reverse() # reverse the list to show the latest first
        for i in range(0, len(buffer)):
            msg += f"{buffer[i][0]}, {buffer[i][1]} her"
            if i < len(buffer) - 1:
                msg += "\n" # add a new line if not the last line
            if i > 3:
                break # only return the last 4 nodes
    return msg

def handle_whereami(message_from_id, deviceID, channel_number):
    location = get_node_location(message_from_id, deviceID, channel_number)
    # check api_throttle
    check_throttle = api_throttle(message_from_id, deviceID, apiName='whereami')
    if check_throttle:
        return check_throttle
    msg = where_am_i(str(location[0]), str(location[1]))
    alt = get_node_altitude_m(message_from_id, deviceID)
    if alt is not None:
        msg += f"\n{format_node_altitude_line(alt)}"
    return msg


def handle_howfar(message, message_from_id, deviceID, isDM):
    if "?" in message:
        return (
            "!howfar — zurückgelegte Strecke seit dem letzten Aufruf. "
            "!howfar reset setzt den Startpunkt zurück."
        )
    if not my_settings.location_enabled:
        return "Standortmodul aus ([location] enabled = False)."
    check_throttle = api_throttle(message_from_id, deviceID, apiName="howfar")
    if check_throttle:
        return check_throttle
    location = get_node_location(message_from_id, deviceID)
    reset = "reset" in message.lower()
    return distance(location[0], location[1], message_from_id, reset=reset)


def handle_howtall(message, message_from_id, deviceID, isDM):
    if "?" in message:
        return (
            "!howtall <Schatten> — Höhe per Sonnenwinkel, "
            "z. B. !howtall 2 (Schattenlänge in m oder ft)."
        )
    if not my_settings.solar_conditions_enabled:
        return "Sonnen-Befehle aus (spaceWeather = False in config)."
    check_throttle = api_throttle(message_from_id, deviceID, apiName="howtall")
    if check_throttle:
        return check_throttle
    location = get_node_location(message_from_id, deviceID)
    shadow = None
    parts = message.replace("!", " ").split()
    for i, part in enumerate(parts):
        if part.lower().startswith("howtall"):
            if i + 1 < len(parts):
                try:
                    shadow = float(parts[i + 1].replace(",", "."))
                except ValueError:
                    pass
            break
    if shadow is None:
        for part in parts:
            pl = part.lower()
            if pl in ("howtall", "howtall?"):
                continue
            try:
                shadow = float(part.replace(",", "."))
                break
            except ValueError:
                continue
    if shadow is None:
        return "Bitte Schattenlänge angeben, z. B. !howtall 2"
    return measureHeight(location[0], location[1], shadow)


def handle_loc(message, message_from_id, deviceID, channel_number):
    """Show last known position of a mesh node from NodeDB or mesh map snapshot."""
    if "?" in message:
        return (
            "!loc — Position aus NodeDB oder Mesh-Karte (nodes.json), inkl. Höhe wenn "
            "übertragen. !loc = du, !loc <Kurzname>, !loc 1234567890, !loc !a1b2c3d4"
        )
    if not my_settings.location_enabled:
        return "Standortmodul aus ([location] enabled = False)."

    node_id, err = resolve_mesh_node_target(message, deviceID, default_id=message_from_id)
    if err:
        return err

    info = get_mesh_node_position_info(node_id, deviceID)
    short = get_name_from_number(node_id, "short", deviceID)
    hex_id = decimal_to_hex(node_id)

    has_pos = info["from_gps"] or info.get("from_mesh_map")
    if not info["in_db"] and not has_pos:
        return f"{short} {hex_id}: nicht in NodeDB, keine Koordinaten in der Mesh-Karte."

    if not has_pos:
        return f"{short} {hex_id}: keine Koordinaten (NodeDB ohne GPS, keine Mesh-Karte)."

    lat, lon = info["lat"], info["lon"]
    if info["from_gps"]:
        src = "GPS"
    elif info.get("from_mesh_map"):
        src = "Mesh-Karte"
    else:
        src = "?"
    lines = [f"{short} {hex_id}", f"{lat},{lon} {src}"]
    if info.get("altitude") is not None:
        lines.append(format_node_altitude_line(info["altitude"]))
    try:
        import maidenhead as mh

        lines.append(mh.to_maiden(lat, lon)[:10])
    except Exception:
        pass
    if info.get("last_heard"):
        lines.append(f"👀{info['last_heard']}")
    if info.get("iface") and info["iface"] != deviceID:
        lines.append(f"IF{info['iface']}")

    msg = "\n".join(lines)
    if len(msg) > my_settings.MESSAGE_CHUNK_SIZE:
        msg = msg[: my_settings.MESSAGE_CHUNK_SIZE - 1] + "…"
    return msg


def handle_repeaterQuery(message_from_id, deviceID, channel_number):
    location = get_node_location(message_from_id, deviceID, channel_number)
    # check api_throttle
    check_throttle = api_throttle(message_from_id, deviceID, apiName='repeaterQuery')
    if check_throttle:
        return check_throttle
    if repeater_lookup == "rbook":
        return getRepeaterBook(str(location[0]), str(location[1]))
    elif repeater_lookup == "artsci":
        return getArtSciRepeaters(str(location[0]), str(location[1]))
    else:
        return "Repeater-Suche ist nicht aktiviert."

def handle_moon(message_from_id, deviceID, channel_number, vox=False):
    if vox:
        return get_moon(str(my_settings.latitudeValue), str(my_settings.longitudeValue))
    location = get_node_location(message_from_id, deviceID, channel_number)
    return get_moon(str(location[0]), str(location[1]))

def handle_whoami(message_from_id, deviceID, hop, snr, rssi, pkiStatus):
    try:
        loc = []
        msg = (
            f"Du bist {message_from_id} — "
            f"{get_name_from_number(message_from_id, 'long', deviceID)}, "
            f"{get_name_from_number(message_from_id, 'short', deviceID)}, "
            f"{decimal_to_hex(message_from_id)}\n"
        )
        msg += f"Signal RSSI {rssi}, SNR {snr}, Route: {hop}"
        if pkiStatus[1] != 'ABC':
            msg += f"\nPKI {pkiStatus[0]} pubKey: {pkiStatus[1]}"

        loc = get_node_location(message_from_id, deviceID)
        if loc != [my_settings.latitudeValue, my_settings.longitudeValue]:
            msg += f"\nPosition: {loc[0]}, {loc[1]}"

            if positionMetadata and message_from_id in positionMetadata:
                metadata = positionMetadata[message_from_id]
                msg += (
                    f" Höhe:{metadata.get('altitude')} "
                    f"Geschw:{metadata.get('groundSpeed')} "
                    f"Präz:{metadata.get('precisionBits')}"
                )
    except Exception as e:
        logger.error(f"System: Error in whoami: {e}")
        msg = "Fehler bei whoami"
    return msg

def handle_whois(message, deviceID, channel_number, message_from_id):
    #return data on a node name or number
    if  "?" in message:
        return f"{message.split('?')[0]} — Infos zu einem Mesh-Knoten."
    else:
        # get the nodeID from the message
        msg = ''
        node = ''
        # find the requested node in db
        if " " in message:
            node = message.split(" ")[1]
        if node.startswith("!") and len(node) == 9:
            # mesh !hex
            try:
                node = int(node.strip("!"),16)
            except ValueError as e:
                node = 0
        elif node.isalpha() or not node.isnumeric():
            # try short name
            node = get_num_from_short_name(node, deviceID)

        # get details on the node
        for i in range(len(seenNodes)):
            if seenNodes[i]['nodeID'] == int(node):
                msg = f"Knoten {seenNodes[i]['nodeID']}: {get_name_from_number(seenNodes[i]['nodeID'], 'long', deviceID)}\n"
                msg += f"Zuletzt 👀: {time.ctime(seenNodes[i]['lastSeen'])} "
                break

        if msg == '':
            msg = "Gültige Knoten-ID, !hex oder Kurzname angeben"
        else:
            # if the user is an admin show the channel and interface and location
            if str(message_from_id) in bbs_admin_list:
                location = get_node_location(seenNodes[i]['nodeID'], deviceID, channel_number)
                msg += f"Ch: {seenNodes[i]['channel']}, Int: {seenNodes[i]['rxInterface']}"
                msg += f"Lat: {location[0]}, Lon: {location[1]}\n"
                if location != [my_settings.latitudeValue, my_settings.longitudeValue]:
                    msg += f"Loc: {where_am_i(str(location[0]), str(location[1]))}"
        return msg

def handle_boot(mesh=True):
    try:
        print (CustomFormatter.bold_white + f"\nMeshtastic Autoresponder Bot CTL+C to exit\n" + CustomFormatter.reset)
        if mesh:
            
            for i in range(1, 10):
                if globals().get(f'interface{i}_enabled', False):
                    myNodeNum = globals().get(f'myNodeNum{i}', 0)
                    logger.info(f"System: Autoresponder Started for Device{i} {get_name_from_number(myNodeNum, 'long', i)},"
                                f"{get_name_from_number(myNodeNum, 'short', i)}. NodeID: {myNodeNum}, {decimal_to_hex(myNodeNum)}")
                    
            if llm_enabled:
                msg = f"System: LLM Enabled"
                llmLoad = llm_query(" ", init=True)
                if "trouble" not in llmLoad:
                    if my_settings.llmReplyToNonCommands:
                        msg += " | Reply to DM's Enabled"
                    if my_settings.llmUseWikiContext:
                        wiki_source = "Kiwixpedia" if my_settings.use_kiwix_server else "Wikipedia"
                        msg += f" | {wiki_source} Context Enabled"
                    if my_settings.useOpenWebUI:
                        msg += " | OpenWebUI API Enabled"
                    else:
                        msg += f" | Ollama API Model {my_settings.llmModel} loaded. Use {'RAW' if my_settings.rawLLMQuery else 'SYSTEM'} prompt mode."
                    logger.debug(msg)
                else:
                    logger.debug(f"System: Bad response from LLM: {llmLoad}")

            if my_settings.bbs_enabled:
                logger.debug(f"System: BBS Enabled, {bbsdb} has {len(bbs_messages)} messages. Direct Mail Messages waiting: {(len(bbs_dm) - 1)}")
                if my_settings.bbs_link_enabled:
                    if len(bbs_link_whitelist) > 0:
                        logger.debug(f"System: BBS Link Enabled with {len(bbs_link_whitelist)} peers")
                    else:
                        logger.debug(f"System: BBS Link Enabled allowing all")
            
            if my_settings.solar_conditions_enabled:
                logger.debug("System: Celestial Telemetry Enabled")

            if my_settings.meshagesTTS:
                logger.debug("System: Meshages TTS Text-to-Speech Enabled")
            
            if my_settings.location_enabled:
                if my_settings.use_meteo_wxApi:
                    logger.debug("System: Location Telemetry Enabled using Open-Meteo API")
                else:
                    logger.debug("System: Location Telemetry Enabled using NOAA API")
                    
            if my_settings.wikipedia_enabled:
                if my_settings.use_kiwix_server:
                    logger.debug(f"System: Wikipedia search Enabled using Kiwix server at {my_settings.kiwix_url}")
                else:
                    logger.debug("System: Wikipedia search Enabled")
            
            if my_settings.rssEnable:
                logger.debug(f"System: RSS Feed Reader Enabled for feeds: {my_settings.rssFeedNames}")
            if my_settings.enable_headlines:
                logger.debug("System: News Headlines Enabled from NewsAPI.org")
            
            if my_settings.radio_detection_enabled:
                logger.debug(f"System: Radio Detection Enabled using rigctld at {my_settings.rigControlServerAddress} broadcasting to channels: {my_settings.sigWatchBroadcastCh}")
            
            if my_settings.file_monitor_enabled:
                logger.warning(f"System: File Monitor Enabled for {my_settings.file_monitor_file_path}, broadcasting to channels: {my_settings.file_monitor_broadcastCh}")
            if my_settings.enable_runShellCmd:
                logger.debug("System: Shell Command monitor enabled")
                if my_settings.allowXcmd:
                    logger.warning("System: File Monitor shell XCMD Enabled")
            if my_settings.read_news_enabled:
                logger.debug(f"System: File Monitor News Reader Enabled for {my_settings.news_file_path}")
            if my_settings.bee_enabled:
                logger.debug("System: File Monitor Bee Monitor Enabled for 🐝bee.txt")
            if my_settings.enableDEalerts:
                logger.debug(f"System: NINA Alerts Enabled with counties {my_settings.myRegionalKeysDE}")
            if my_settings.enableDEalerts:
                logger.debug(f"System: NINA Alerts Enabled with counties {my_settings.myRegionalKeysDE}")
            if my_settings.emergency_responder_enabled:
                logger.debug(f"System: Emergency Responder Enabled on channels {my_settings.emergency_responder_alert_channel}")
            
            if my_settings.qrz_hello_enabled:
                if my_settings.train_qrz:
                    logger.debug("System: QRZ Welcome/Hello Enabled with training mode")
                else:
                    logger.debug("System: QRZ Welcome/Hello Enabled")

            if my_settings.enableSMTP:
                if my_settings.enableImap:
                    logger.debug("System: SMTP Email Alerting Enabled using IMAP")
                else:
                    logger.warning("System: SMTP Email Alerting Enabled")

        # Default Options
        if my_settings.useDMForResponse:
            logger.debug("System: Respond by DM only")

        if my_settings.autoBanEnabled:
            logger.debug(f"System: Auto-Ban Enabled for {my_settings.autoBanThreshold} messages in {my_settings.autoBanTimeframe} seconds")
            load_bbsBanList()
            load_autoBanList()
        _ndb.load_nodedb()

        if my_settings.log_messages_to_file:
            logger.debug("System: Logging Messages to disk")
        if my_settings.syslog_to_file:
            logger.debug("System: Logging System Logs to disk")

        if my_settings.motd_enabled:
            logger.debug(f"System: MOTD Enabled using {my_settings.MOTD} scheduler:{my_settings.schedulerMotd}")
        
        if my_settings.sentry_enabled:
            logger.debug(f"System: Sentry Mode Enabled {my_settings.sentry_radius}m radius reporting to channel:{my_settings.secure_channel} requestLOC:{reqLocationEnabled}")
            if my_settings.sentryIgnoreList:
                logger.debug(f"System: Sentry BlockList Enabled for nodes: {my_settings.sentryIgnoreList}")
            if my_settings.sentryWatchList:
                logger.debug(f"System: Sentry WatchList Enabled for nodes: {my_settings.sentryWatchList}")

        if my_settings.highfly_enabled:
            logger.debug(f"System: HighFly Enabled using {my_settings.highfly_altitude}m limit reporting to channel:{my_settings.highfly_channel}")
        
        if my_settings.store_forward_enabled:
            logger.debug(
                f"System: S&F(!messages) Kanal {my_settings.messages_channel}, "
                f"limit {my_settings.messages_limit}, reverse:{my_settings.reverseSF}"
            )
        
        if my_settings.enableEcho:
            logger.debug("System: Echo command Enabled")
        
        if my_settings.repeater_enabled and multiple_interface:
            logger.debug(f"System: Repeater Enabled for Channels: {my_settings.repeater_channels}")
        
        if my_settings.checklist_enabled:
            logger.debug("System: CheckList Module Enabled")
        if my_settings.inventory_enabled:
            logger.debug("System: Inventory Module Enabled")
        if my_settings.ignoreChannels:
            logger.debug(f"System: Ignoring Channels: {my_settings.ignoreChannels}")
        
        if my_settings.noisyNodeLogging:
            logger.debug("System: Noisy Node Logging Enabled")
        
        if my_settings.logMetaStats:
            logger.debug("System: Logging Metadata Stats Enabled, leaderboard")
        
        if my_settings.scheduler_enabled:
            logger.debug(f"System: Scheduler Enabled. Default Device:{my_settings.schedulerInterface} Channel:{my_settings.schedulerChannel}")

    except Exception as e:
        logger.error(f"System: Error during boot: {e}")

def onReceive(packet, interface):
    global seenNodes, msg_history, cmdHistory
    # Priocess the incoming packet, handles the responses to the packet with auto_response()
    # Sends the packet to the correct handler for processing

    if not isinstance(packet, dict):
        logger.warning(f"System: Ignoring malformed packet type: {type(packet).__name__}")
        return

    decoded = packet.get('decoded')
    if not isinstance(decoded, dict):
        decoded = {}

    from modules.mesh_sim_tunnel import unwrap_sim_tunnel_packet
    from modules.packet_dedup import should_drop_duplicate_packet

    unwrap_sim_tunnel_packet(packet)
    if should_drop_duplicate_packet(packet):
        return
    decoded = packet.get('decoded') or {}

    # Intercept NodeInfo packets to build our own unlimited persistent NodeDB,
    # independent of the hardware device's ~250-node flash limit.
    portnum = decoded.get('portnum', '')
    if portnum == 'NODEINFO_APP':
        sender = packet.get('from')
        user = decoded.get('user') or {}
        if sender and (user.get('longName') or user.get('shortName') or user.get('publicKey')):
            _ndb.update_node(
                sender,
                long_name=user.get('longName') or None,
                short_name=user.get('shortName') or None,
                public_key=user.get('publicKey') or None,
            )

    # extract interface details from inbound packet
    rxType = type(interface).__name__

    # Values assinged to the packet
    packet_id = None
    rxNode = message_from_id = snr = rssi = hop = hop_away = channel_number = hop_start = hop_count = hop_limit = 0
    pkiStatus = (False, 'ABC')
    rxNodeHostName = None
    replyIDset = None
    emojiSeen = False
    simulator_flag = False
    isDM = False
    channel_name = "unknown"
    session_passkey = None
    playingGame = False

    if my_settings.DEBUGpacket:
        # Debug print the interface object
        for item in interface.__dict__.items(): intDebug = f"{item}\n"
        logger.debug(f"System: Packet Received on {rxType} Interface\n {intDebug} \n END of interface \n")
        # Debug print the packet for debugging
        logger.debug(f"Packet Received\n {packet} \n END of packet \n")

    # determine the rxNode based on the interface type
    if rxType == 'TCPInterface':
        rxHost = interface.__dict__.get('hostname', 'unknown')
        rxNodeHostName = interface.__dict__.get('ip', None)
        rxNode = next(
            (i for i in range(1, 10)
            if multiple_interface and rxHost and
            globals().get(f'hostname{i}', '').split(':', 1)[0] in rxHost and
            globals().get(f'interface{i}_type', '') == 'tcp'),None)

    if rxType == 'SerialInterface':
        rxInterface = interface.__dict__.get('devPath', 'unknown')
        rxNode = next(
            (i for i in range(1, 10)
            if globals().get(f'port{i}', '') in rxInterface),None)

    if rxType == 'BLEInterface':
        rxNode = next(
            (i for i in range(1, 10)
            if globals().get(f'interface{i}_type', '') == 'ble'),0)
        
    if rxNode is None:
        # default to interface 1 ## FIXME needs better like a default interface setting or hash lookup
        if decoded.get('portnum') in ['ADMIN_APP', 'SIMULATOR_APP']:
            session_passkey = decoded.get('admin', {}).get('sessionPasskey', None)
        rxNode = 1

    # check if the packet has a channel flag use it ## FIXME needs to be channel hash lookup
    if packet.get('channel'):
        channel_number = packet.get('channel')
        channel_name = "unknown"
        try:
            res = resolve_channel_name(channel_number, rxNode, interface)
            if res:
                try:
                    channel_name, _ = res
                except Exception:
                    channel_name = "unknown"
            else:
                # Search all interfaces for this channel
                cache = build_channel_cache()
                found_on_other = None
                for device in cache:
                    for chan_name, info in device.get("channels", {}).items():
                        if str(info.get('number')) == str(channel_number) or str(info.get('hash')) == str(channel_number):
                            found_on_other = device.get("interface_id")
                            found_chan_name = chan_name
                            break
                    if found_on_other:
                        break
                if found_on_other and found_on_other != rxNode:
                    logger.debug(
                        f"System: Received Packet on Channel:{channel_number} ({found_chan_name}) on Interface:{rxNode}, but this channel is configured on Interface:{found_on_other}"
                    )
        except Exception as e:
            logger.debug(f"System: channel resolution error: {e}")
    
        #debug channel info
        # if "unknown" in str(channel_name):
        #     logger.debug(f"System: Received Packet on Channel:{channel_number} on Interface:{rxNode}")
        # else:
        #     logger.debug(f"System: Received Packet on Channel:{channel_number} Name:{channel_name} on Interface:{rxNode}")

    # check if the packet has a simulator flag
    simulator_flag = decoded.get('simulator', False)
    if isinstance(simulator_flag, dict):
        # assume Software Simulator
        simulator_flag = True

    # set the message_from_id
    message_from_id = packet.get('from')
    if message_from_id is None:
        logger.warning(f"System: Ignoring packet missing 'from' field on Device:{rxNode}")
        return

    # if message_from_id is not in the seenNodes list add it
    if not any(node.get('nodeID') == message_from_id for node in seenNodes):
        seenNodes.append({'nodeID': message_from_id, 'rxInterface': rxNode, 'channel': channel_number, 'welcome': False, 'first_seen': time.time(), 'lastSeen': time.time()})
        if len(seenNodes) > MAX_SEEN_NODES:
            seenNodes = seenNodes[-MAX_SEEN_NODES:]
    else:
        # update lastSeen time
        for node in seenNodes:
            if node.get('nodeID') == message_from_id:
                node['lastSeen'] = time.time()
                break
    # BBS DM MAIL CHECKER
    if bbs_enabled and decoded:
        msg = bbs_check_dm(message_from_id)
        if msg:
            logger.info(
                f"System: BBS DM Delivery: from={msg[2]} to={message_from_id}"
            )
            logger.debug(
                f"System: BBS DM Delivery body for {get_name_from_number(message_from_id, 'long', rxNode)}: {msg[1]}"
            )
            message = "Mail: " + msg[1] + "  From: " + get_name_from_number(msg[2], 'long', rxNode)
            bbs_delete_dm(msg[0], msg[1])
            send_message(message, channel_number, message_from_id, rxNode)

    # CHECK with ban_hammer() if the node is banned
    if str(message_from_id) in my_settings.bbs_ban_list or str(message_from_id) in my_settings.autoBanlist:
        logger.warning(f"System: Banned Node {message_from_id} tried to send a message. Ignored. Try adding to node firmware-blocklist")
        return

    # handle TEXT_MESSAGE_APP
    try:
        if decoded.get('portnum') == 'TEXT_MESSAGE_APP':
            message_bytes = decoded.get('payload', b'')
            if isinstance(message_bytes, bytes):
                message_string = message_bytes.decode('utf-8', errors='replace')
            elif isinstance(message_bytes, str):
                message_string = message_bytes
            else:
                logger.warning(f"System: Ignoring TEXT_MESSAGE_APP with invalid payload type: {type(message_bytes).__name__}")
                return
            message_log_string = message_string.replace('\r', ' ').replace('\n', ' ')
            via_mqtt = decoded.get('viaMqtt', False)
            transport_mechanism = (
                packet.get('transport_mechanism')
                or packet.get('transportMechanism')
                or decoded.get('transport_mechanism')
                or decoded.get('transportMechanism')
                or 'unknown'
            )
            rx_time = decoded.get('rxTime', time.time())

            # check if the packet is from us (ignore echo of our own replies; e.g. !metar → "METAR …" retriggers trap)
            _my_nodes = [
                n for n in (
                    myNodeNum1, myNodeNum2, myNodeNum3, myNodeNum4,
                    myNodeNum5, myNodeNum6, myNodeNum7, myNodeNum8, myNodeNum9,
                )
                if n
            ]
            if message_from_id in _my_nodes:
                logger.warning(
                    f"System: Packet from self {message_from_id} loop or traffic replay detected"
                )
                return

            # get the signal strength and snr if available
            if packet.get('rxSnr') or packet.get('rxRssi'):
                snr = packet.get('rxSnr', 0)
                rssi = packet.get('rxRssi', 0)

            # check if the packet has a publicKey flag use it; persist in nodeDB
            if packet.get('publicKey'):
                pk = packet.get('publicKey', 'ABC')
                pkiStatus = packet.get('pkiEncrypted', False), pk
                _ndb.update_node(message_from_id, public_key=pk)
            else:
                # fall back to previously cached public key for this node
                cached_pk = _ndb.get_node_pubkey(message_from_id)
                if cached_pk:
                    pkiStatus = (False, cached_pk)
            
            # Use packet id for threaded replies;
            packet_id = packet.get('id', None)

            # existing reply - unused for tracking
            replyIDSet = packet.get('replyIDSet', None)
            
            # check if the packet has emoji flag set it // currently unused in the code
            if packet.get('emoji'):
                emojiSeen = packet.get('emoji', False)

            # check if the packet has a hop count flag use it
            if packet.get('hopsAway'):
                hop_away = packet.get('hopsAway', 0)

            if packet.get('hopStart'):
                hop_start = packet.get('hopStart', 0)

            if packet.get('hopLimit'):
                hop_limit = packet.get('hopLimit', 0)
            
            # calculate hop count
            hop = ""
            if hop_limit > 0 and hop_start >= hop_limit:
                hop_count = hop_away + (hop_start - hop_limit)
            elif hop_limit > 0 and hop_start < hop_limit:
                hop_count = hop_away + (hop_limit - hop_start)
            else:
                hop_count = hop_away

            transport_label = None
            if via_mqtt or "mqtt" in str(transport_mechanism).lower():
                transport_label = "MQTT"
                via_mqtt = True
            elif "udp" in str(transport_mechanism).lower():
                transport_label = "Gateway"

            if (
                hop_start == hop_limit
                and "lora" in str(transport_mechanism).lower()
                and (snr != 0 or rssi != 0)
                and hop_count == 0
            ):
                hop = "Direct"
            elif transport_label == "MQTT":
                hop = "MQTT" if hop_count == 0 else f"{hop_count} Hops MQTT"
            elif transport_label == "Gateway":
                hop = "Gateway" if hop_count == 0 else f"{hop_count} Hops Gateway"
            elif hop_count > 0:
                hop = f"{hop_count} Hop" if hop_count == 1 else f"{hop_count} Hops"
            else:
                hop = ""

            # Add relay node info if present
            if packet.get('relayNode') is not None:
                relay_val = packet['relayNode']
                last_byte = relay_val & 0xFF
                if last_byte == 0x00:
                    hex_val = 'OldFW'
                else:
                    hex_val = f"{last_byte:02X}"
                hop += f" Relay:{hex_val}"

            if enableHopLogs:
                logger.debug(f"System: Packet HopDebugger: hop_away:{hop_away} hop_limit:{hop_limit} hop_start:{hop_start} calculated_hop_count:{hop_count} final_hop_value:{hop} via_mqtt:{via_mqtt} transport_mechanism:{transport_mechanism} Hostname:{rxNodeHostName}")

            if help_message in message_string or welcome_message in message_string or "CMD?:" in message_string:
                # ignore help and welcome messages
                logger.warning(f"Got Own Welcome/Help header. From: {get_name_from_number(message_from_id, 'long', rxNode)}")
                return
        
            # If the packet is a DM (Direct Message) respond to it, otherwise validate its a message for us on the channel
            if packet.get('to') in [myNodeNum1, myNodeNum2, myNodeNum3, myNodeNum4, myNodeNum5, myNodeNum6, myNodeNum7, myNodeNum8, myNodeNum9]:
                # message is DM to us
                isDM = True
                # check if the message contains a trap word, DMs are always responded to
                if (messageTrap(message_string) and not llm_enabled) or messageTrap(message_string.split()[0]):
                    # log the message to stdout
                    logger.info(f"Device:{rxNode} {format_channel_log(channel_number, rxNode)} " + CustomFormatter.green + f"Received DM: " + CustomFormatter.white + f"{message_log_string} " + CustomFormatter.purple +\
                                "From: " + CustomFormatter.white + f"{get_name_from_number(message_from_id, 'long', rxNode)}")
                    # rate limit check
                    if is_cmd_rate_limited(message_from_id):
                        send_message("⏱️ Bitte etwas langsamer.", channel_number, message_from_id, rxNode)
                    else:
                        # respond with DM
                        send_message(auto_response(message_string, snr, rssi, hop, pkiStatus, message_from_id, channel_number, rxNode, isDM), channel_number, message_from_id, rxNode)
                else:
                    if llm_enabled and my_settings.llmReplyToNonCommands:
                        llm = handle_llm(message_from_id, channel_number, rxNode, message_string, publicChannel)
                        send_message(llm, channel_number, message_from_id, rxNode)
                    else:
                        logger.warning(f"Device:{rxNode} Ignoring DM: {message_log_string} From: {get_name_from_number(message_from_id, 'long', rxNode)}")
                        if not any(node['nodeID'] == message_from_id and node['welcome'] == True for node in seenNodes):
                            send_message(welcome_message, channel_number, message_from_id, rxNode)
                            for node in seenNodes:
                                if node['nodeID'] == message_from_id:
                                    node['welcome'] = True
                        else:
                            send_message(help_message, channel_number, message_from_id, rxNode)
                    
                    # add message to tts queue
                    if meshagesTTS:
                        # add to the tts_read_queue
                        readMe = f"DM from {get_name_from_number(message_from_id, 'short', rxNode)}: {message_string}"
                        tts_read_queue.append(readMe)
                        
                    # log the message to the message log
                    if log_messages_to_file:
                        msgLogger.info(f"Device:{rxNode} {format_channel_log(channel_number, rxNode)} | {get_name_from_number(message_from_id, 'long', rxNode)} | DM | " + message_log_string)
            else:
                # message is on a channel
                if messageTrap(message_string):
                    # message is for us to respond to, or is it...
                    if my_settings.ignoreDefaultChannel and channel_number == my_settings.publicChannel:
                        logger.debug(f"System: Ignoring CMD:{message_log_string} From: {get_name_from_number(message_from_id, 'short', rxNode)} Default Channel:{channel_number}")
                    elif str(message_from_id) in my_settings.bbs_ban_list:
                        logger.debug(f"System: Ignoring CMD:{message_log_string} From: {get_name_from_number(message_from_id, 'short', rxNode)} Cantankerous Node")
                    elif str(channel_number) in my_settings.ignoreChannels:
                        logger.debug(f"System: Ignoring CMD:{message_log_string} From: {get_name_from_number(message_from_id, 'short', rxNode)} Ignored Channel:{channel_number}")
                    elif my_settings.cmdBang and not message_string.startswith("!"):
                        logger.debug(f"System: Ignoring CMD:{message_log_string} From: {get_name_from_number(message_from_id, 'short', rxNode)} Didnt sound like they meant it")
                    else:
                        # message is for bot to respond to, seriously this time..
                        logger.info(f"Device:{rxNode} {format_channel_log(channel_number, rxNode)} " + CustomFormatter.green + "ReceivedChannel: " + CustomFormatter.white + f"{message_log_string} " + CustomFormatter.purple +\
                                    "From: " + CustomFormatter.white + f"{get_name_from_number(message_from_id, 'long', rxNode)}")
                        # rate limit check
                        if is_cmd_rate_limited(message_from_id):
                            send_message("⏱️ Bitte etwas langsamer.", channel_number, message_from_id, rxNode)
                        elif my_settings.useDMForResponse:
                            # respond to channel message via direct message
                            send_message(auto_response(message_string, snr, rssi, hop, pkiStatus, message_from_id, channel_number, rxNode, isDM), channel_number, message_from_id, rxNode, reply_id=packet_id)
                        else:
                            # or respond to channel message on the channel itself
                            if channel_number == my_settings.publicChannel and my_settings.antiSpam:
                                # warning user spamming default channel
                                logger.warning(f"System: AntiSpam protection, sending DM to: {get_name_from_number(message_from_id, 'long', rxNode)}")
                            
                                # respond to channel message via direct message
                                send_message(auto_response(message_string, snr, rssi, hop, pkiStatus, message_from_id, channel_number, rxNode, isDM), channel_number, message_from_id, rxNode, reply_id=packet_id)
                            else:
                                # respond to channel message on the channel itself
                                send_message(auto_response(message_string, snr, rssi, hop, pkiStatus, message_from_id, channel_number, rxNode, isDM), channel_number, 0, rxNode, reply_id=packet_id)

                else:
                    # message is not for us to respond to
                    # ignore the message but add it to the message history list
                    if my_settings.zuluTime:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S%p")

                    # trim the history list if it exceeds max_history
                    if len(msg_history) >= my_settings.MAX_MSG_HISTORY:
                        # Always keep only the most recent MAX_MSG_HISTORY entries
                        msg_history = msg_history[-my_settings.MAX_MSG_HISTORY:]

                    # Store-forward buffer nur für den !messages-Kanal (z. B. 1 Meshhessen)
                    if int(channel_number) == int(getattr(my_settings, "messages_channel", 1)):
                        msg_history.append(
                            (
                                get_name_from_number(message_from_id, "long", rxNode),
                                message_string,
                                channel_number,
                                timestamp,
                                rxNode,
                            )
                        )

                    # print the message to the log and sdout
                    logger.info(f"Device:{rxNode} {format_channel_log(channel_number, rxNode)} " + CustomFormatter.green + "Ignoring Message:" + CustomFormatter.white +\
                                f" {message_log_string} " + CustomFormatter.purple + "From:" + CustomFormatter.white + f" {get_name_from_number(message_from_id)}")
                    if my_settings.log_messages_to_file:
                        msgLogger.info(f"Device:{rxNode} {format_channel_log(channel_number, rxNode)} | {get_name_from_number(message_from_id, 'long', rxNode)} | " + message_log_string)

                    # repeat the message on the other device
                    if my_settings.repeater_enabled and my_settings.multiple_interface:
                        # wait a responseDelay to avoid message collision from lora-ack.
                        time.sleep(my_settings.responseDelay)
                        if len(message_string) > (3 * my_settings.MESSAGE_CHUNK_SIZE):
                            logger.warning(f"System: Not repeating message, exceeds size limit ({len(message_string)} > {3 * MESSAGE_CHUNK_SIZE})")
                        else:
                            rMsg = (f"{message_string} From:{get_name_from_number(message_from_id, 'short', rxNode)}")
                            # if channel found in the repeater list repeat the message
                            if str(channel_number) in my_settings.repeater_channels:
                                for i in range(1, 10):
                                    if globals().get(f'interface{i}_enabled', False) and i != rxNode:
                                        logger.debug(f"Repeating message on Device{i} Channel:{channel_number}")
                                        send_message(rMsg, channel_number, 0, i)
                                        time.sleep(my_settings.responseDelay)
                    
                    # if QRZ enabled check if we have said hello
                    if my_settings.qrz_hello_enabled:
                        if never_seen_before(message_from_id):
                            name = get_name_from_number(message_from_id, 'short', rxNode)
                            if isinstance(name, str) and name.startswith("!") and len(name) == 9:
                                # we didnt get a info packet yet so wait and ingore this go around
                                logger.debug(f"System: QRZ Hello ignored, no info packet yet")
                            else:
                                # add to qrz_hello list
                                hello(message_from_id, name)
                                # send a hello message as a DM
                                if not my_settings.train_qrz:
                                    send_message(f"Hallo {name} {qrz_hello_string}", channel_number, message_from_id, rxNode, reply_id=packet_id)

                    # add message to tts queue
                    if my_settings.meshagesTTS and channel_number == my_settings.ttsChannels:
                        # add to the tts_read_queue
                        readMe = f"DM from {get_name_from_number(message_from_id, 'short', rxNode)}: {message_string}"
                        tts_read_queue.append(readMe)
        else:
            # Evaluate non TEXT_MESSAGE_APP packets
            consumeMetadata(packet, rxNode, channel_number)
    except Exception as e:
        logger.exception(f"System: Error processing packet: {e} Device:{rxNode}")
        logger.debug(f"System: Error Packet = {packet}")

async def start_rx():
    # Start the receive subscriber using pubsub via meshtastic library
    pub.subscribe(onReceive, 'meshtastic.receive')
    pub.subscribe(onDisconnect, 'meshtastic.connection.lost')
    logger.debug("System: RX Subscriber started")
    # here we go loopty loo
    while True:
        await asyncio.sleep(0.5)
        pass

loadLeaderboard()

async def main():
    tasks = []
    
    try:
        handle_boot()
        if my_settings.web_admin_enabled:
            from modules.admin_web import start_admin_web_background
            start_admin_web_background()
        # Create core tasks
        tasks.append(asyncio.create_task(start_rx(), name="mesh_rx"))
        tasks.append(asyncio.create_task(watchdog(), name="watchdog"))

        # Add optional tasks
        if my_settings.dataPersistence_enabled:
            tasks.append(asyncio.create_task(dataPersistenceLoop(), name="data_persistence"))

        if my_settings.file_monitor_enabled:
            tasks.append(asyncio.create_task(handleFileWatcher(), name="file_monitor"))
        
        if my_settings.radio_detection_enabled:
            tasks.append(asyncio.create_task(handleSignalWatcher(), name="hamlib"))

        if my_settings.voxDetectionEnabled:
            from modules.radio import voxMonitor
            tasks.append(asyncio.create_task(voxMonitor(), name="vox_detection"))

        if my_settings.meshagesTTS:
            tasks.append(asyncio.create_task(handleTTS(), name="tts_handler"))
        
        if my_settings.wsjtx_detection_enabled:
            tasks.append(asyncio.create_task(handleWsjtxWatcher(), name="wsjtx_monitor"))
        
        if my_settings.js8call_detection_enabled:
            tasks.append(asyncio.create_task(handleJs8callWatcher(), name="js8call_monitor"))

        from modules.scheduler import run_scheduler_loop, scheduler_loop_needed, setup_all_scheduled_jobs
        if scheduler_loop_needed():
            setup_all_scheduled_jobs(
                schedulerMotd,
                MOTD,
                schedulerMessage,
                schedulerChannel,
                schedulerInterface,
                schedulerValue,
                schedulerTime,
                schedulerInterval,
            )
            tasks.append(asyncio.create_task(run_scheduler_loop(), name="scheduler"))
        
        logger.debug(f"System: Starting {len(tasks)} async tasks")
        
        # Wait for all tasks with proper exception handling
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check for exceptions in results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Task {tasks[i].get_name()} failed with: {result}")
        
    except Exception as e:
        logger.error(f"Main loop error: {e}")
    finally:
        # Cleanup tasks
        logger.debug("System: Cleaning up async tasks")
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.debug(f"Task {task.get_name()} cancelled successfully")
                except Exception as e:
                    logger.warning(f"Error cancelling task {task.get_name()}: {e}")

    await asyncio.sleep(0.01)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        exit_handler()
    except SystemExit:
        pass
# EOF
