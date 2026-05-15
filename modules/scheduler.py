# modules/scheduler.py 2025 meshing-around
# Scheduler module for mesh_bot
import asyncio
import schedule
from datetime import datetime
from modules.log import logger
from modules.system import send_message
from modules.settings import MOTD, schedulerMotd, schedulerMessage, schedulerChannel, schedulerInterface, schedulerValue, schedulerTime, schedulerInterval

async def run_scheduler_loop(interval=1):
    logger.debug(f"System: Scheduler loop started Tasks: {len(schedule.jobs)}, Details:{extract_schedule_fields(schedule.get_jobs())}")
    try:
        last_logged_minute = -1
        while True:
            try:
                # Log scheduled jobs every 20 minutes
                now = datetime.now()
                if now.minute % 20 == 0 and now.minute != last_logged_minute:
                    logger.debug(f"System: Scheduled Tasks {len(schedule.jobs)}, Details:{extract_schedule_fields(schedule.get_jobs())}")
                    last_logged_minute = now.minute
                schedule.run_pending()
            except Exception as e:
                logger.error(f"System: Scheduler loop exception: {e}")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.debug("System: Scheduler loop cancelled, shutting down.")

def safe_int(val, default=0, type=''):
    try:
        return int(val)
    except (ValueError, TypeError):
        if val != '':
            logger.debug(f"System: Scheduler config {type} error '{val}' to int, using default {default}")
        return default

def extract_schedule_fields(jobs):
    """
    Extracts 'Every ... (last run: [...], next run: ...)' from schedule.get_jobs() output without regex.
    """
    jobs_str = str(jobs)
    results = []
    # Split by '), ' to separate jobs, then add ')' back except last
    parts = jobs_str.split('), ')
    for i, part in enumerate(parts):
        if not part.endswith(')'):
            part += ')'
        # Find the start of 'Every'
        start = part.find('Every')
        if start != -1:
            # Find the start of 'do <lambda>()'
            do_idx = part.find('do ')
            if do_idx != -1:
                summary = part[start:do_idx].strip()
                # Find the (last run: ... next run: ...) part
                paren_idx = part.find('(', do_idx)
                if paren_idx != -1:
                    summary += ' ' + part[paren_idx:].strip()
                    while '<function ' in summary:
                        f_start = summary.find('<function ')
                        f_end = summary.find('>', f_start)
                        if f_end == -1:
                            break
                        func_str = summary[f_start+10:f_end]
                        func_name = func_str.split(' ')[0]
                        summary = summary[:f_start] + func_name + summary[f_end+1:]
                    results.append(summary)
    return results

def setup_scheduler(
    schedulerMotd, MOTD, schedulerMessage, schedulerChannel, schedulerInterface,
    schedulerValue, schedulerTime, schedulerInterval):
    try:
        # Methods imported from mesh_bot for scheduling tasks
        from mesh_bot import (
            welcome_message,
            handle_wxc,
            handle_moon,
            handle_sun,
            handle_satpass,
            handleNews,
            sysinfo,
        )
        from modules.rss import get_rss_feed
    except ImportError as e:
        logger.warning(f"Some mesh_bot schedule features are unavailable by option disable in config.ini: {e} comment out the use of these methods in your custom_scheduler.py")
    
    # Setup the scheduler based on configuration
    schedulerValue = schedulerValue.lower().strip()
    schedulerTime = schedulerTime.strip()
    schedulerInterval = schedulerInterval.strip()
    schedulerChannel = safe_int(schedulerChannel, 0, type="channel")
    schedulerInterface = safe_int(schedulerInterface, 1, type="interface")
    schedulerIntervalInt = safe_int(schedulerInterval, 5, type="interval")

    try:
        scheduler_message = MOTD if schedulerMotd else schedulerMessage

        def send_sched_msg():
            send_message(scheduler_message, schedulerChannel, 0, schedulerInterface)

        # Basic Scheduler Options
        basicOptions = ['day', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'hour', 'min']
        effective_interval = schedulerIntervalInt
        if any(option in schedulerValue for option in basicOptions):
            if schedulerValue == 'day':
                day_interval = safe_int(schedulerInterval, 1, type="interval")
                if day_interval < 1:
                    logger.debug(f"System: Scheduler config interval '{schedulerInterval}' invalid for day schedule, using default 1")
                    day_interval = 1
                effective_interval = day_interval
                if schedulerTime:
                    # Specific time at a daily or multi-day interval
                    if day_interval == 1:
                        schedule.every().day.at(schedulerTime).do(send_sched_msg)
                    else:
                        schedule.every(day_interval).days.at(schedulerTime).do(send_sched_msg)
                else:
                    # Every N days
                    schedule.every(day_interval).days.do(send_sched_msg)
            elif 'mon' in schedulerValue and schedulerTime:
                schedule.every().monday.at(schedulerTime).do(send_sched_msg)
            elif 'tue' in schedulerValue and schedulerTime:
                schedule.every().tuesday.at(schedulerTime).do(send_sched_msg)
            elif 'wed' in schedulerValue and schedulerTime:
                schedule.every().wednesday.at(schedulerTime).do(send_sched_msg)
            elif 'thu' in schedulerValue and schedulerTime:
                schedule.every().thursday.at(schedulerTime).do(send_sched_msg)
            elif 'fri' in schedulerValue and schedulerTime:
                schedule.every().friday.at(schedulerTime).do(send_sched_msg)
            elif 'sat' in schedulerValue and schedulerTime:
                schedule.every().saturday.at(schedulerTime).do(send_sched_msg)
            elif 'sun' in schedulerValue and schedulerTime:
                schedule.every().sunday.at(schedulerTime).do(send_sched_msg)
            elif 'hour' in schedulerValue:
                schedule.every(schedulerIntervalInt).hours.do(send_sched_msg)
            elif 'min' in schedulerValue:
                schedule.every(schedulerIntervalInt).minutes.do(send_sched_msg)
            logger.debug(f"System: Starting the basic scheduler to send '{scheduler_message}' on schedule '{schedulerValue}' every {effective_interval} interval at time '{schedulerTime}' on Device:{schedulerInterface} Channel:{schedulerChannel}")
        elif 'link' in schedulerValue:
            schedule.every(schedulerIntervalInt).hours.do(
                lambda: send_message("bbslink MeshBot looking for peers", schedulerChannel, 0, schedulerInterface)
            )
            logger.debug(f"System: Starting the link scheduler to send link messages every {schedulerIntervalInt} hours on Device:{schedulerInterface} Channel:{schedulerChannel}")
        elif 'weather' in schedulerValue:
            schedule.every().day.at(schedulerTime).do(
                lambda: send_message(handle_wxc(0, schedulerInterface, 'wx', days=1), schedulerChannel, 0, schedulerInterface)
            )
            logger.debug(f"System: Starting the weather scheduler to send weather updates every {schedulerIntervalInt} hours on Device:{schedulerInterface} Channel:{schedulerChannel}")
        elif 'news' in schedulerValue:
            schedule.every(schedulerIntervalInt).hours.do(
                lambda: send_message(handleNews(0, schedulerInterface, 'readnews', False), schedulerChannel, 0, schedulerInterface)
            )
            logger.debug(f"System: Starting the news scheduler to send news updates every {schedulerIntervalInt} hours on Device:{schedulerInterface} Channel:{schedulerChannel}")
        elif 'readrss' in schedulerValue:
            schedule.every(schedulerIntervalInt).hours.do(
                lambda: send_message(get_rss_feed(''), schedulerChannel, 0, schedulerInterface)
            )
            logger.debug(f"System: Starting the RSS scheduler to send RSS feeds every {schedulerIntervalInt} hours on Device:{schedulerInterface} Channel:{schedulerChannel}")
        elif 'sysinfo' in schedulerValue:
            schedule.every(schedulerIntervalInt).hours.do(
                lambda: send_message(sysinfo('', 0, schedulerInterface, False), schedulerChannel, 0, schedulerInterface)
            )
            logger.debug(f"System: Starting the sysinfo scheduler to send system information every {schedulerIntervalInt} hours on Device:{schedulerInterface} Channel:{schedulerChannel}")
        elif 'solar' in schedulerValue:
            schedule.every().day.at(schedulerTime).do(
                lambda: send_message(handle_sun(0, schedulerInterface, schedulerChannel), schedulerChannel, 0, schedulerInterface)
            )
            logger.debug(f"System: Starting the scheduler to send solar information at {schedulerTime} on Device:{schedulerInterface} Channel:{schedulerChannel}")
        elif 'custom' in schedulerValue:
            try:
                from modules.custom_scheduler import setup_custom_schedules # type: ignore
                setup_custom_schedules(
                    send_message, welcome_message, handle_wxc, MOTD,
                    schedulerChannel, schedulerInterface)
                logger.debug(f"System: Starting the custom_scheduler.py ")
                schedule.every().monday.at("12:00").do(
                    lambda: logger.info("System: Scheduled Broadcast Enabled Reminder")
                )
            except Exception as e:
                logger.warning("Custom scheduler file not found or failed to import. cp etc/custom_scheduler.template modules/custom_scheduler.py")
    except Exception as e:
        logger.error(f"System: Scheduler Error {e}")
    return True


def register_recurring_broadcast(
    *,
    mode: str,
    interval: str,
    sched_time: str,
    interface: int,
    channel: int,
    job_fn,
    log_label: str,
) -> None:
    """Register one timed send job (day/hour/min/weekdays). job_fn is called with no arguments."""
    mode = (mode or "day").lower().strip()
    sched_time = (sched_time or "").strip()
    interval_int = safe_int(interval, 1, type="interval")
    if interval_int < 1:
        interval_int = 1
    interface = safe_int(interface, 1, type="interface")
    channel = safe_int(channel, 0, type="channel")

    if mode == "day":
        if sched_time:
            if interval_int == 1:
                schedule.every().day.at(sched_time).do(job_fn)
            else:
                schedule.every(interval_int).days.at(sched_time).do(job_fn)
        else:
            schedule.every(interval_int).days.do(job_fn)
    elif mode == "mon" and sched_time:
        schedule.every().monday.at(sched_time).do(job_fn)
    elif mode == "tue" and sched_time:
        schedule.every().tuesday.at(sched_time).do(job_fn)
    elif mode == "wed" and sched_time:
        schedule.every().wednesday.at(sched_time).do(job_fn)
    elif mode == "thu" and sched_time:
        schedule.every().thursday.at(sched_time).do(job_fn)
    elif mode == "fri" and sched_time:
        schedule.every().friday.at(sched_time).do(job_fn)
    elif mode == "sat" and sched_time:
        schedule.every().saturday.at(sched_time).do(job_fn)
    elif mode == "sun" and sched_time:
        schedule.every().sunday.at(sched_time).do(job_fn)
    elif mode == "hour":
        schedule.every(interval_int).hours.do(job_fn)
    elif mode == "min":
        schedule.every(interval_int).minutes.do(job_fn)
    else:
        logger.warning(
            f"System: {log_label} — ungültiger Modus '{mode}' oder fehlende Uhrzeit; Job nicht registriert"
        )
        return
    logger.debug(
        f"System: {log_label} — mode={mode} interval={interval_int} time={sched_time!r} "
        f"IF={interface} CH={channel}"
    )


def setup_motd_broadcast() -> None:
    import modules.settings as st

    if not st.motd_broadcast_enabled:
        return

    def _send():
        send_message(st.MOTD, st.motd_broadcast_channel, 0, st.motd_broadcast_interface)

    register_recurring_broadcast(
        mode=st.motd_broadcast_mode,
        interval=st.motd_broadcast_interval,
        sched_time=st.motd_broadcast_time,
        interface=st.motd_broadcast_interface,
        channel=st.motd_broadcast_channel,
        job_fn=_send,
        log_label="MOTD broadcast",
    )


def setup_news_broadcast() -> None:
    import modules.settings as st

    if not st.news_broadcast_enabled:
        return
    try:
        from mesh_bot import handleNews
    except ImportError as e:
        logger.warning(f"System: News broadcast disabled — handleNews unavailable: {e}")
        return

    iface = st.news_broadcast_interface
    ch = st.news_broadcast_channel

    def _send():
        send_message(handleNews(0, iface, "readnews", False), ch, 0, iface)

    register_recurring_broadcast(
        mode=st.news_broadcast_mode,
        interval=st.news_broadcast_interval,
        sched_time=st.news_broadcast_time,
        interface=iface,
        channel=ch,
        job_fn=_send,
        log_label="News broadcast",
    )


def setup_all_scheduled_jobs(
    schedulerMotd,
    MOTD,
    schedulerMessage,
    schedulerChannel,
    schedulerInterface,
    schedulerValue,
    schedulerTime,
    schedulerInterval,
) -> None:
    """Register main [scheduler] job plus MOTD/News broadcast jobs."""
    import modules.settings as st

    if st.scheduler_enabled:
        setup_scheduler(
            schedulerMotd,
            MOTD,
            schedulerMessage,
            schedulerChannel,
            schedulerInterface,
            schedulerValue,
            schedulerTime,
            schedulerInterval,
        )
    setup_motd_broadcast()
    setup_news_broadcast()


def scheduler_loop_needed() -> bool:
    import modules.settings as st

    return bool(
        st.scheduler_enabled
        or st.motd_broadcast_enabled
        or st.news_broadcast_enabled
    )