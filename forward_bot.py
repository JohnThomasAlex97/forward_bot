import os
import re
import json
import time
import threading
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# ---------- Load Env ----------
load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
SOURCE_GROUP_ID = int(os.environ.get("SOURCE_GROUP_ID", "-4873981826"))
REGISTRATION_KEY = os.environ.get("REGISTRATION_KEY")
RENDER_URL = os.environ.get("RENDER_URL")
LOCAL_TEST = os.environ.get("LOCAL_TEST", "false").lower() == "true"

GROUPS_FILE = "groups.json"
FILE_LOCK = threading.Lock()

# ---------- Helpers ----------
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

def save_blocked_message(update: Update):
    text = update.effective_message.text or update.effective_message.caption or ""
    with open("blocked_messages.txt", "a", encoding="utf-8") as f:
        f.write(text.strip() + "\n---\n")

# ---------- Scam Filter ----------
SCAM_PATTERNS = [
    r"free\s*eth", r"air\s*drop", r"claim\s*(your|eth|now)", r"bonus\s*code",
    r"promo\s*code", r"no\s*verification", r"instant\s*win", r"casino",
    r"bet\s*now", r"jetacas", r"crypto\s*wallet", r"send\s*btc",
    r"\.eth\b", r"\.casino\b", r"\.crypto\b", r"no\s*id\s*required",
    r"click\s*here", r"play\s*now", r"register\s*now", r"http[s]?://[^ ]*"
]

def looks_suspicious(update: Update) -> bool:
    text = (update.effective_message.text or update.effective_message.caption or "").lower()
    for pat in SCAM_PATTERNS:
        if re.search(pat, text, flags=re.I):
            return True
    return False

# ---------- Handlers ----------
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text("Use /register from a group where I’ve been added.")
        return

    parts = (update.message.text or "").split(maxsplit=1)
    if len(parts) != 2 or parts[1].strip() != REGISTRATION_KEY:
        await update.message.reply_text("Registration key is missing or invalid.")
        return

    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("Only group admins can register this group.")
        return

    groups = load_groups()
    if chat.id not in groups:
        groups.append(chat.id)
        save_groups(groups)
        await update.message.reply_text("✅ Group registered for forwarding.")
    else:
        await update.message.reply_text("⚠️ Group is already registered.")

async def forward_from_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Message received from {update.effective_chat.id}, text={update.effective_message.text}")

    if update.effective_chat.id != SOURCE_GROUP_ID:
        print("DEBUG: This message is NOT from the source group. Ignoring.")
        return

    if looks_suspicious(update):
        save_blocked_message(update)
        print("🚫 Blocked suspicious message (scam filter).")
        return

    groups = load_groups()
    if not groups:
        print("DEBUG: No groups registered for forwarding.")
        return

    for gid in groups:
        try:
            await context.bot.forward_message(
                chat_id=gid,
                from_chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id
            )
            print(f"✅ Forwarded message to group {gid}")
        except Exception as e:
            print(f"❌ Failed to forward to {gid}: {e}")

# ---------- Main ----------
def main():
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("register", register))
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, forward_from_source))

    print("🤖 Bot is running…")

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
