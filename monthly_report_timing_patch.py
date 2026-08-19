from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import monthly_social_runtime as runtime


_PATCHED = False


def _target_report_date(now):
    # Normal path: 19:00 MSK on the last calendar day of the month.
    # February is automatic: 28 or 29 depending on the year.
    if runtime.is_last_calendar_day(now.date()) and now.hour >= 19:
        return now.date()

    # Catch-up path: if Railway was down at 19:00, the first scheduler tick on
    # day 1 may still publish the previous month exactly once.
    if now.day == 1:
        return now.date() - timedelta(days=1)

    return None


async def _run_monthly_report_if_due(application) -> None:
    bot_module = runtime._find_bot_module()
    if bot_module is None:
        return

    now = bot_module.current_msk_datetime()
    target_date = _target_report_date(now)
    if target_date is None:
        return

    target_month = runtime.month_key(target_date)
    chat_ids = await asyncio.to_thread(runtime._known_chat_ids_sync, bot_module)
    for chat_id in chat_ids:
        if await asyncio.to_thread(
            runtime._report_already_sent_sync,
            bot_module,
            chat_id,
            target_month,
        ):
            continue

        stats = await asyncio.to_thread(
            runtime._monthly_stats_sync,
            bot_module,
            chat_id,
            target_date,
        )
        text = runtime.format_monthly_report(stats, target_date)
        try:
            await application.bot.send_message(chat_id=chat_id, text=text)
        except Exception as error:
            logging.warning("Monthly chat report failed chat=%s: %s", chat_id, error)
            continue

        await asyncio.to_thread(
            runtime._mark_report_sent_sync,
            bot_module,
            chat_id,
            target_month,
        )


def install() -> None:
    global _PATCHED
    if _PATCHED:
        return
    runtime.run_monthly_report_if_due = _run_monthly_report_if_due
    _PATCHED = True


install()
