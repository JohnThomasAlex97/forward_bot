import os
import re
import json
import time
import requests
import threading
from flask import Flask
from urllib.parse import urlparse

from dotenv import load_dotenv  # ✅ for .env support
load_dotenv()  # ✅ loads values from .env if running locally

from telegram import Update, MessageEntity
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# ---------- Config ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]  # no default!
SOURCE_GROUP_ID = int(os.environ.get("SOURCE_GROUP_ID", "-4873981826"))
REGISTRATION_KEY = os.environ.get("REGISTRATION_KEY")  # set this!
RENDER_URL = os.environ.get("RENDER_URL")  # e.g., https://your-app.onrender.com

GROUPS_FILE = "groups.json"
FILE_LOCK = threading.Lock()

# If you can, migrate to a persistent store. This file may reset on redeploys!
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

# --------- Threat intel (basic) ---------
SCAM_PATTERNS = [
    r"free\s*eth",
    r"air\s*drop|airdrop",
    r"claim\s*(your|eth|now)",
    r"instant\s*rewards?",
    r"limited\s*time\s*offer",
    r"connect\s*(your\s*)?wallet",
    r"verify\s*(and|to)\s*(claim|receive)",
    r"drip|faucet",
]

# Common shady TLDs used in phishing (extend as needed)
SUSPICIOUS_TLDS = {
    "xyz", "top", "gift", "icu", "cn", "click", "link", "rest", "monster",
    "live", "fit", "best", "cam", "work", "surf", "ru", "zip"
}

# Blocklist domains (case-insensitive, no scheme)
DOMAIN_BLOCKLIST = {
    "freeether.net",  # example from your report
    # add more if you see them in the wild
}

# Optional allowlist: if non-empty, only forward URLs whose registrable domain is here.
# Keep empty to allow most and rely on blocklist/patterns.
DOMAIN_ALLOWLIST = set()


def _registrable(domain: str) -> str:
    """
    Best-effort to reduce 'sub.example.com' -> 'example.com'.
    Not perfect without tldextract, but fine for quick filtering.
    """
    parts = domain.lower().split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain.lower()


def extract_domains_from_message(update: Update):
    """
    Extract domains from text/captions and URL/TEXT_LINK entities.
    """
    msg = update.effective_message
    text = msg.text or msg.caption or ""
    domains = set()

    # From URL/TEXT_LINK entities
    if msg.entities:
        for ent in msg.entities:
            if ent.type == MessageEntity.URL:
                url = text[ent.offset: ent.offset + ent.length]
                try:
                    parsed = urlparse(url if url.startswith(("http://", "https://")) else f"http://{url}")
                    if parsed.hostname:
                        domains.add(_registrable(parsed.hostname))
                except Exception:
                    pass
            elif ent.type == MessageEntity.TEXT_LINK and ent.url:
                try:
                    parsed = urlparse(ent.url)
                    if parsed.hostname:
                        domains.add(_registrable(parsed.hostname))
                except Exception:
                    pass

    # Fallback: very simple URL finder in raw text (in case entities missing)
    for m in re.finditer(r"(https?://[^\s]+|[\w.-]+\.[a-z]{2,})", text, flags=re.I):
        candidate = m.group(0)
        try:
            parsed = urlparse(candidate if candidate.startswith(("http://", "https://")) else f"http://{candidate}")
            if parsed.hostname:
                domains.add(_registrable(parsed.hostname))
        except Exception:
            pass

    return domains


def looks_suspicious(update: Update) -> bool:
    msg = update.effective_message
    text = (msg.text or msg.caption or "").lower()

    # 1) Keyword heuristics
    for pat in SCAM_PATTERNS:
        if re.search(pat, text, flags=re.I):
            return True

    # 2) Domain checks
    domains = extract_domains_from_message(update)
    if not domains:
        return False  # nothing to judge

    # Allowlist enforcement (if configured)
    if DOMAIN_ALLOWLIST and any(d not in DOMAIN_ALLOWLIST for d in domains):
        return True

    for d in domains:
        if d in DOMAIN_BLOCKLIST:
            return True
        tld = d.split(".")[-1]
        if tld in SUSPICIOUS_TLDS:
            return True

    return False

# ---------- Flask (keep-alive) ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Telegram bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    if not RENDER_URL:
        return
    while True:
        try:
            requests.get(RENDER_URL, timeout=10)
            print("🔁 Self-ping successful")
        except Exception as e:
            print(f"⚠️ Self-ping failed: {e}")
        time.sleep(300)

# ---------- Handlers ----------
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only works in group/supergroup and only by an admin, with the correct key.
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text("Use /register from a group where I’ve been added.")
        return

    if not REGISTRATION_KEY:
        await update.message.reply_text("Registration key not configured. Contact the bot owner.")
        return

    # Expect: /register <KEY>
    parts = (update.message.text or "").split(maxsplit=1)
    if len(parts) != 2 or parts[1].strip() != REGISTRATION_KEY:
        await update.message.reply_text("Registration key is missing or invalid.")
        return

    # Check user is admin in this group
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("Only group admins can register this group.")
            return
    except Exception:
        await update.message.reply_text("Couldn’t verify admin status. Try again later.")
        return

    groups = load_groups()
    if chat.id not in groups:
        groups.append(chat.id)
        save_groups(groups)
        await update.message.reply_text("✅ Group registered for forwarding.")
    else:
        await update.message.reply_text("⚠️ Group is already registered.")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # For safety: only allow the bot owner to list (set your Telegram user ID as OWNER_ID if you want)
    owner_id = os.environ.get("OWNER_ID")
    if not owner_id or str(update.effective_user.id) != str(owner_id):
        await update.message.reply_text("Not authorized.")
        return
    groups = load_groups()
    if not groups:
        await update.message.reply_text("No registered groups.")
        return
    await update.message.reply_text("Registered groups:\n" + "\n".join(map(str, groups)))

async def forward_from_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only process messages that originate from the source group
    if update.effective_chat.id != SOURCE_GROUP_ID:
        return

    # Block scams before forwarding
    if looks_suspicious(update):
        print("🚫 Blocked suspicious message from source; not forwarding.")
        # Optional: if bot is admin in source, delete it
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id,
                                             message_id=update.effective_message.message_id)
            print("🧹 Deleted scam in source group.")
        except Exception as e:
            print(f"⚠️ Couldn’t delete in source: {e}")
        return

    groups = load_groups()
    for gid in groups:
        try:
            await context.bot.forward_message(
                chat_id=gid,
                from_chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id
            )
        except Exception as e:
            print(f"❌ Failed to forward to {gid}: {e}")

# Optional: delete scams in any group the bot is in (requires admin rights in that group)
async def clean_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if looks_suspicious(update):
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id,
                                             message_id=update.effective_message.message_id)
            print(f"🧹 Deleted scam in {update.effective_chat.id}")
        except Exception as e:
            print(f"⚠️ Failed to delete scam in {update.effective_chat.id}: {e}")

def main():
    # Start Flask + Keep-alive threads
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()

    app_bot = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app_bot.add_handler(CommandHandler("register", register))
    app_bot.add_handler(CommandHandler("listgroups", list_groups))

    # Clean scams in any chat (optional)
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, clean_incoming))

    # Forward only from source (after cleaning)
    app_bot.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, forward_from_source))

    print("🤖 Secure forwarder running…")
    app_bot.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
