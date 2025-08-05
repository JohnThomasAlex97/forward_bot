import os
import re
import json
import time
import requests
import threading
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# ---------- Load .env ----------
load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
SOURCE_GROUP_ID = int(os.environ.get("SOURCE_GROUP_ID", "-1001234567890"))
REGISTRATION_KEY = os.environ.get("REGISTRATION_KEY", "secretkey")
RENDER_URL = os.environ.get("RENDER_URL")  # used for webhook or keepalive
LOCAL_TEST = os.environ.get("LOCAL_TEST", "false").lower() == "true"

GROUPS_FILE = "groups.json"
FILE_LOCK = threading.Lock()

# ---------- Group Handling ----------
def load_groups():
    with FILE_LOCK:
        try:
            with open(GROUPS_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return []

def save_groups(groups):
    with FILE_LOCK:
        with open(GROUPS_FILE, "w") as f:
            json.dump(groups, f)

# ---------- AI-Based Scam Filter ----------
def is_scam_message(text: str) -> bool:
    """
    Placeholder AI check.
    In production, integrate with real HuggingFace model/API.
    """
    SCAM_KEYWORDS = [
        "airdrop", "bonus", "casino", "claim now", "promo code", "connect wallet",
        "fast money", "verify to get", "click below", "no KYC", "instant reward",
        "crypto giveaway", "telegram bot earn"
    ]
    lowered = text.lower()
    return any(word in lowered for word in SCAM_KEYWORDS)

def is_safe(update: Update) -> bool:
    text = (update.effective_message.text or update.effective_message.caption or "")
    return not is_scam_message(text)

# ---------- /register Handler ----------
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text("Use /register from a group.")
        return

    parts = (update.message.text or "").split(maxsplit=1)
    if len(parts) != 2 or parts[1].strip() != REGISTRATION_KEY:
        await update.message.reply_text("Invalid or missing registration key.")
        return

    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("Only admins can register.")
        return

    groups = load_groups()
    if chat.id not in groups:
        groups.append(chat.id)
        save_groups(groups)
        await update.message.reply_text("✅ Group registered.")
    else:
        await update.message.reply_text("⚠️ Group already registered.")

# ---------- Forward Handler ----------
async def forward_from_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != SOURCE_GROUP_ID:
        return  # Ignore non-source messages

    if not is_safe(update):
        print("🚫 Scam blocked.")
        return

    groups = load_groups()
    for gid in groups:
        try:
            await context.bot.forward_message(
                chat_id=gid,
                from_chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id
            )
            print(f"✅ Forwarded to {gid}")
        except Exception as e:
            print(f"❌ Error forwarding to {gid}: {e}")

# ---------- Keep Alive Ping ----------
def keep_alive():
    if not RENDER_URL:
        return
    while True:
        try:
            requests.get(RENDER_URL, timeout=10)
            print("🔁 Self-ping OK")
        except Exception as e:
            print(f"⚠️ Self-ping failed: {e}")
        time.sleep(300)

# ---------- Main ----------
def main():
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("register", register))
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, forward_from_source))

    print("🤖 Bot running securely...")

    # Start keepalive
    threading.Thread(target=keep_alive, daemon=True).start()

    if LOCAL_TEST:
        app_bot.run_polling(allowed_updates=Update.ALL_TYPES)
    else:
        app_bot.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 10000)),
            webhook_url=RENDER_URL,
            allowed_updates=Update.ALL_TYPES
        )

if __name__ == "__main__":
    main()
