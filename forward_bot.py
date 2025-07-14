
import json
import os
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "7784625461:AAEzgCgFh-ZGpJzehQ8ZVcWwlEIOq-Cbc_w")
SOURCE_GROUP_ID = -4873981826
GROUPS_FILE = 'groups.json'

# ----- Flask Setup (for Render) -----
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))  # ✅ Use Render-assigned port
    app.run(host='0.0.0.0', port=port)

# ----- Group Management -----
def load_groups():
    try:
        with open(GROUPS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_groups(groups):
    with open(GROUPS_FILE, 'w') as f:
        json.dump(groups, f)

# ----- Bot Handlers -----
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    groups = load_groups()
    if group_id not in groups:
        groups.append(group_id)
        save_groups(groups)
        await update.message.reply_text("✅ Group registered for forwarding.")
    else:
        await update.message.reply_text("⚠️ Group is already registered.")

async def forward_from_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == SOURCE_GROUP_ID:
        groups = load_groups()
        for group_id in groups:
            try:
                await context.bot.forward_message(
                    chat_id=group_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
            except Exception as e:
                print(f"❌ Failed to forward to {group_id}: {e}")

# ----- Main -----
def main():
    # Start Flask server in a thread
    Thread(target=run_flask).start()

    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("register", register))
    bot_app.add_handler(MessageHandler(filters.ALL, forward_from_source))

    print("🤖 Bot is running...")
    bot_app.run_polling()

if __name__ == '__main__':
    main()
