import json
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

BOT_TOKEN = '7784625461:AAEzgCgFh-ZGpJzehQ8ZVcWwlEIOq-Cbc_w'
SOURCE_GROUP_ID = -4873981826  # Replace with your source group ID
GROUPS_FILE = 'groups.json'

def load_groups():
    try:
        with open(GROUPS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_groups(groups):
    with open(GROUPS_FILE, 'w') as f:
        json.dump(groups, f)

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

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("register", register))
    app.add_handler(MessageHandler(filters.ALL, forward_from_source))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
