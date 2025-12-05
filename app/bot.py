from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import (
    AIORateLimiter,
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .agents import AGENT_PROFILES, run_agent
from .config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("doctorai.bot")

WEB_APP_URL = os.getenv("WEB_APP_URL", "http://localhost:8000")
DEFAULT_AGENT = settings.default_agent or "dermatologist"


def format_reply(payload: Dict) -> str:
    v = payload.get("verification") or payload.get("verified") or {}
    followups = v.get("followups") or []
    diffs = v.get("differentials") or []
    parts = [
        f"*Likely:* {v.get('provisional_diagnosis', 'unclear')}",
        f"*Confidence:* {v.get('confidence', '—')}",
        f"*Answer:* {v.get('answer', '—')}",
        f"*Plan:* {v.get('plan', '—')}",
        f"*Triage:* {v.get('triage', '—')}",
    ]
    if diffs:
        parts.append("*Alternatives:* " + "; ".join(diffs[:3]))
    if followups:
        parts.append("*Follow-ups:* " + " | ".join(followups[:5]))
    risk = v.get("risk_flags")
    if risk:
        parts.append(f"*Risk flags:* {risk}")
    parts.append("_Not medical advice. See a clinician if symptoms worsen or you feel unwell._")
    return "\n".join(parts)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("Open DoctorAI", web_app=WebAppInfo(url=WEB_APP_URL))]]
    agent = context.user_data.get("agent", DEFAULT_AGENT)
    await update.message.reply_text(
        f"Hi! I am DoctorAI.\nDefault mode: {agent}.\nSend a photo + description, "
        "or tap to open the mini-app UI.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def set_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /mode <dermatologist|therapist>")
        return
    agent = context.args[0].lower()
    if agent not in AGENT_PROFILES:
        await update.message.reply_text("Unknown agent. Use dermatologist or therapist.")
        return
    context.user_data["agent"] = agent
    await update.message.reply_text(f"Mode set to {agent}.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not settings.openai_api_key:
        await update.message.reply_text("Server missing OPENAI_API_KEY. Please retry later.")
        return

    text = update.message.text or update.message.caption or ""
    if not text.strip() and not update.message.photo:
        await update.message.reply_text("Send a short description, optionally with a photo.")
        return

    image_bytes: Optional[bytes] = None
    filename: Optional[str] = None
    if update.message.photo:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        image_bytes = await file.download_as_bytearray()
        filename = f"{file.file_unique_id}.jpg"

    agent = context.user_data.get("agent", DEFAULT_AGENT)
    history: List[Dict[str, str]] = context.user_data.get("history", [])
    history = history[-6:]

    try:
        result = await run_agent(
            question=text or "Photo attached",
            agent_key=agent,
            image_bytes=image_bytes,
            image_filename=filename,
            history=history,
        )
    except Exception as exc:  # pragma: no cover - network/model failures
        logger.exception("agent error: %s", exc)
        await update.message.reply_text("Sorry, I could not process that right now.")
        return

    reply_text = format_reply(result)
    await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply_text})
    context.user_data["history"] = history[-8:]


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    app = (
        Application.builder()
        .token(token)
        .rate_limiter(AIORateLimiter())
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mode", set_agent))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT, handle_message))

    await app.initialize()
    await app.start()
    logger.info("DoctorAI bot started with web app URL %s", WEB_APP_URL)
    await app.updater.start_polling()
    await app.updater.idle()


if __name__ == "__main__":
    asyncio.run(main())
