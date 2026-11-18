import logging
import os
from datetime import date, timedelta
from html import escape

import httpx
from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP = "БИФ-24-01"
API = "https://raspisanie.rusoil.net/origins"
DAY_NAMES = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}
DAY_ALIASES = {
    "1": 1, "пн": 1, "понедельник": 1,
    "2": 2, "вт": 2, "вторник": 2,
    "3": 3, "ср": 3, "среда": 3,
    "4": 4, "чт": 4, "четверг": 4,
    "5": 5, "пт": 5, "пятница": 5,
    "6": 6, "сб": 6, "суббота": 6,
    "7": 7, "вс": 7, "воскресенье": 7,
}
MONTH_NAMES = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_json(path: str, payload: dict | None = None):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{API}/{path}", json=payload)
        response.raise_for_status()
        return response.json()


async def current_week() -> tuple[int, int]:
    result = await post_json("get_now")
    now = result.get("now") or []
    if not now:
        raise RuntimeError("Сайт не вернул номер текущей учебной недели")
    return int(now[0]["NUMWEEK"]), int(now[0]["DAYWEEK"])


async def fetch_schedule(week: int) -> list[dict]:
    result = await post_json(
        "get_rasp_student",
        {"gruppa": GROUP, "beginweek": week, "endweek": week},
    )
    if isinstance(result, dict):
        error = result.get("error", {}).get("comment", "Неизвестная ошибка сайта")
        raise RuntimeError(error)
    if not isinstance(result, list):
        raise RuntimeError("Сайт вернул расписание в неизвестном формате")
    return result


def selected_subgroup(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("subgroup", "all")


def subgroup_label(value: str) -> str:
    return {"all": "все подгруппы", "1": "1-я подгруппа", "2": "2-я подгруппа"}[value]


def filter_subgroup(rows: list[dict], value: str) -> list[dict]:
    if value == "all":
        return rows
    # Общие занятия (PODGRUPPA пустая) остаются видны обеим подгруппам.
    return [row for row in rows if str(row.get("PODGRUPPA") or "") in ("", value)]


def format_lesson(row: dict) -> str:
    start = str(row.get("START_TIME", ""))[:5]
    end = str(row.get("END_TIME", ""))[:5]
    title = escape(str(row.get("NDISC") or "Занятие без названия"))
    kind = escape(str(row.get("NVIDZANAT") or ""))
    teacher = escape(str(row.get("TEACHER_NAME", "")).strip())
    auditorium = escape(str(row.get("AUD", "")).strip())
    subgroup = row.get("PODGRUPPA")

    lines = [f"<b>🔔 {row.get('PARA', '?')} пара · {start}–{end}</b>", f"📘 {title}"]
    if kind:
        lines.append(f"🧪 {kind}")
    if subgroup:
        lines.append(f"👥 Подгруппа {subgroup}")
    if teacher:
        lines.append(f"👨‍🏫 {teacher}")
    if auditorium:
        if auditorium.lower() == "-on-line":
            lines.append("🌐 Онлайн")
        else:
            building = row.get("KORPUS")
            location = f"корпус {building} · " if building else ""
            lines.append(f"📍 {location}ауд. {auditorium}")
    return "\n".join(lines)


def menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    subgroup = selected_subgroup(context)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Сегодня", callback_data="view:today"),
                InlineKeyboardButton("Завтра", callback_data="view:tomorrow"),
            ],
            [
                InlineKeyboardButton("Эта неделя", callback_data="view:week"),
                InlineKeyboardButton("Следующая", callback_data="view:nextweek"),
            ],
            [
                InlineKeyboardButton(
                    ("✓ " if subgroup == value else "") + label,
                    callback_data=f"subgroup:{value}",
                )
                for value, label in (("all", "Все"), ("1", "Подгруппа 1"), ("2", "Подгруппа 2"))
            ],
        ]
    )


def subgroup_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    value = selected_subgroup(context)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(("✓ " if value == choice else "") + label, callback_data=f"subgroup:{choice}")
            for choice, label in (("all", "Все"), ("1", "Подгруппа 1"), ("2", "Подгруппа 2"))
        ]
    ])


def date_for_day(current_day: int, day: int, week_offset: int = 0) -> date:
    monday = date.today() - timedelta(days=current_day - 1)
    return monday + timedelta(days=week_offset * 7 + day - 1)


def date_label(current_day: int, day: int, week_offset: int = 0) -> str:
    scheduled_date = date_for_day(current_day, day, week_offset)
    return f"{DAY_NAMES.get(day, f'День {day}').upper()} · {scheduled_date.day} {MONTH_NAMES[scheduled_date.month - 1]}"


async def show_schedule(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    view: str,
    chosen_day: int | None = None,
) -> None:
    target = update.effective_message
    try:
        week, today = await current_week()
        week_offset = 1 if view == "nextweek" or (view == "tomorrow" and today == 7) else 0
        schedule_week = week + week_offset
        if view == "today":
            chosen_day = today
        elif view == "tomorrow":
            chosen_day = today + 1 if today < 7 else 1
        rows = filter_subgroup(await fetch_schedule(schedule_week), selected_subgroup(context))
    except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        logger.exception("Не удалось получить расписание")
        await target.reply_text(f"Не получилось загрузить расписание: {exc}")
        return

    if chosen_day is not None:
        days = [chosen_day]
        if view == "today":
            heading = f"📅 Сегодня · {date_label(today, chosen_day)}"
        elif view == "tomorrow":
            heading = f"📅 Завтра · {date_label(today, chosen_day, week_offset)}"
        else:
            heading = f"📅 {date_label(today, chosen_day, week_offset)}"
    else:
        days = sorted({int(row["DAYWEEK"]) for row in rows if row.get("DAYWEEK") is not None})
        heading = f"📚 {'Следующая неделя' if view == 'nextweek' else 'Эта неделя'} · неделя {schedule_week}"

    await target.reply_text(
        f"<b>{heading}</b>\n🎓 {GROUP} · {subgroup_label(selected_subgroup(context))}",
        parse_mode="HTML",
    )

    sent_any = False
    for day in days:
        lessons = [row for row in rows if int(row.get("DAYWEEK", 0)) == day]
        lessons.sort(key=lambda row: (row.get("START_TIME", ""), str(row.get("PODGRUPPA", ""))))
        if not lessons:
            continue
        sent_any = True
        body = "\n\n".join(format_lesson(row) for row in lessons)
        day_heading = date_label(today, day, week_offset)
        await target.reply_text(f"<b>{day_heading}</b>\n\n{body}", parse_mode="HTML")

    if not sent_any:
        label = DAY_NAMES.get(chosen_day, "этого дня") if chosen_day is not None else "этой недели"
        await target.reply_text(f"Пар на {label} нет.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"👋 Привет! Я бот расписания группы <b>{GROUP}</b>.\n\n"
        "Каждый раз загружаю актуальные данные с сайта.\n"
        "Команды: /today, /tomorrow, /thisweek, /nextweek, /day, /subgroup\n\n"
        "Выбери расписание или подгруппу:",
        parse_mode="HTML",
        reply_markup=menu(context),
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_schedule(update, context, "today")


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_schedule(update, context, "week")


async def next_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_schedule(update, context, "nextweek")


async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_schedule(update, context, "tomorrow")


async def choose_subgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"Сейчас выбрано: {subgroup_label(selected_subgroup(context))}. Выбери подгруппу:",
        reply_markup=subgroup_menu(context),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "<b>Команды бота</b>\n\n"
        "/start — главное меню\n"
        "/today — расписание на сегодня\n"
        "/tomorrow — расписание на завтра\n"
        "/thisweek — расписание на эту неделю\n"
        "/nextweek — расписание на следующую неделю\n"
        "/day 1 — выбранный день (1 — понедельник, 7 — воскресенье)\n"
        "/subgroup — выбрать подгруппу\n"
        "/help — эта подсказка",
        parse_mode="HTML",
    )


async def day_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Напиши номер или название дня, например: /day 1 или /day пятница")
        return
    day = DAY_ALIASES.get(" ".join(context.args).strip().lower())
    if day is None:
        await update.effective_message.reply_text("Укажи день от 1 до 7: /day 1 — понедельник, /day 7 — воскресенье.")
        return
    await show_schedule(update, context, "day", chosen_day=day)


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, value = query.data.split(":", 1)
    if action == "subgroup":
        context.user_data["subgroup"] = value
        await query.edit_message_reply_markup(reply_markup=menu(context))
    elif action == "view":
        await show_schedule(update, context, "week" if value == "week" else value)


async def register_commands(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("today", "Пары на сегодня"),
        BotCommand("tomorrow", "Пары на завтра"),
        BotCommand("thisweek", "Расписание на эту неделю"),
        BotCommand("nextweek", "Расписание на следующую неделю"),
        BotCommand("day", "Пары в выбранный день: /day 1"),
        BotCommand("subgroup", "Выбрать подгруппу"),
        BotCommand("help", "Список команд"),
    ])


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN. Скопируй .env.example в .env и добавь токен бота.")

    application = Application.builder().token(BOT_TOKEN).post_init(register_commands).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("today", today))
    application.add_handler(CommandHandler(["thisweek", "week"], week))
    application.add_handler(CommandHandler("tomorrow", tomorrow))
    application.add_handler(CommandHandler("nextweek", next_week))
    application.add_handler(CommandHandler("day", day_command))
    application.add_handler(CommandHandler("subgroup", choose_subgroup))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(buttons))
    logger.info("Бот запускается для группы %s", GROUP)
    application.run_polling()


if __name__ == "__main__":
    main()
