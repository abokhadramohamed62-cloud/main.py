import os
import asyncio
import sqlite3
import threading
from datetime import datetime
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_توكن_البوت_هنا")
ADMIN_ID = 868999453
PAYMENT_CHANNEL = "@Crypto_Fox13"
CHANNELS = ["@penguin_110", "@Crypto_Dragon13"]
REWARD_PER_REFERRAL = 2000
MIN_WITHDRAW = 10000
CURRENCY = "SHIB"

# ---------------- FLASK ----------------
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "SHIB Bot Running Successfully ✅"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        referred_by INTEGER DEFAULT NULL,
        joined_at TEXT,
        verified INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        wallet TEXT,
        status TEXT DEFAULT 'pending',
        requested_at TEXT
    )''')

    conn.commit()
    conn.close()

# ---------------- USERS ----------------
def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def add_user(user_id, username, referred_by=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = c.fetchone()

    if not exists:
        c.execute(
            "INSERT INTO users (user_id, username, referred_by, joined_at, verified) VALUES (?,?,?,?,0)",
            (user_id, username, referred_by, datetime.now().isoformat())
        )
        conn.commit()

    conn.close()

def verify_user(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("SELECT verified, referred_by FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()

    if row and row[0] == 0:
        c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
        referred_by = row[1]

        if referred_by and referred_by != user_id:
            c.execute(
                "UPDATE users SET balance=balance+?, referrals=referrals+1 WHERE user_id=?",
                (REWARD_PER_REFERRAL, referred_by)
            )

        conn.commit()
        conn.close()
        return referred_by

    conn.close()
    return None

def get_balance(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT balance, referrals FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row if row else (0, 0)

# ---------------- WITHDRAWALS ----------------
def add_withdrawal(user_id, amount, wallet):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute(
        "INSERT INTO withdrawals (user_id, amount, wallet, requested_at) VALUES (?,?,?,?)",
        (user_id, amount, wallet, datetime.now().isoformat())
    )

    c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id))

    conn.commit()
    conn.close()

def get_withdrawal(withdrawal_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM withdrawals WHERE id=?", (withdrawal_id,))
    row = c.fetchone()
    conn.close()
    return row

def approve_withdrawal(withdrawal_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (withdrawal_id,))
    conn.commit()
    conn.close()

# ---------------- CHECK SUB ----------------
async def check_subscriptions(user_id, context):
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except:
            return False
    return True

# ---------------- KEYBOARDS ----------------
def reply_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔗 رابط الإحالة"), KeyboardButton("💰 رصيدي")],
        [KeyboardButton("👥 إحالاتي"), KeyboardButton("💵 سحب")],
        [KeyboardButton("📢 قناة إثبات الدفع")]
    ], resize_keyboard=True)

def subscription_keyboard():
    buttons = [[InlineKeyboardButton(f"📢 اشترك في {ch}", url=f"https://t.me/{ch.lstrip('@')}")] for ch in CHANNELS]
    buttons.append([InlineKeyboardButton("✅ تحققت من اشتراكي", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = int(args[0]) if args and args[0].isdigit() else None

    if not get_user(user.id):
        add_user(user.id, user.username or user.first_name, referred_by)

    if not await check_subscriptions(user.id, context):
        await update.message.reply_text(
            "👋 يجب الاشتراك أولاً:",
            reply_markup=subscription_keyboard()
        )
        return

    user_data = get_user(user.id)

    if user_data and user_data[6] == 0:
        referred_by_id = verify_user(user.id)
        if referred_by_id:
            try:
                await context.bot.send_message(
                    referred_by_id,
                    f"🎉 انضم شخص جديد عبر رابطك!\n💰 +{REWARD_PER_REFERRAL} {CURRENCY}"
                )
            except:
                pass

    await update.message.reply_text(
        f"👋 أهلاً {user.first_name}\n💰 اربح {REWARD_PER_REFERRAL} {CURRENCY}",
        reply_markup=reply_keyboard()
    )

# ---------------- CALLBACKS ----------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    if query.data == "check_sub":
        if await check_subscriptions(user.id, context):
            referred_by_id = verify_user(user.id)

            if referred_by_id:
                try:
                    await context.bot.send_message(
                        referred_by_id,
                        f"🎉 إحالة جديدة +{REWARD_PER_REFERRAL} {CURRENCY}"
                    )
                except:
                    pass

            await query.edit_message_text("✅ تم التحقق")
        else:
            await query.edit_message_text("❌ اشترك أولاً")

    elif query.data.startswith("approve_"):
        if user.id != ADMIN_ID:
            return

        parts = query.data.split("_")
        withdrawal_id = int(parts[1])
        target_user_id = int(parts[2])

        withdrawal = get_withdrawal(withdrawal_id)

        if not withdrawal or withdrawal[4] == "approved":
            await query.answer("تمت الموافقة مسبقاً!", show_alert=True)
            return

        approve_withdrawal(withdrawal_id)

        await context.bot.send_message(
            PAYMENT_CHANNEL,
            f"✅ تم الدفع\n💰 {withdrawal[2]} {CURRENCY}\n🏦 `{withdrawal[3]}`",
            parse_mode="Markdown"
        )

        try:
            await context.bot.send_message(
                target_user_id,
                f"✅ تم الدفع {withdrawal[2]} {CURRENCY}"
            )
        except:
            pass

        await query.answer("تمت الموافقة", show_alert=True)

# ---------------- MESSAGE HANDLER ----------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if context.user_data.get("awaiting_wallet"):
        wallet = text.strip()

        if not wallet.isdigit():
            await update.message.reply_text("❌ Binance ID غير صحيح")
            return

        amount = context.user_data["withdraw_amount"]
        add_withdrawal(user.id, amount, wallet)

        context.user_data.clear()

        await update.message.reply_text("✅ تم إرسال طلب السحب")

        return

    if text == "💰 رصيدي":
        balance, refs = get_balance(user.id)
        await update.message.reply_text(f"{balance} {CURRENCY} | إحالات: {refs}")

    elif text == "🔗 رابط الإحالة":
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={user.id}"
        await update.message.reply_text(link)

    elif text == "💵 سحب":
        balance, _ = get_balance(user.id)

        if balance < MIN_WITHDRAW:
            await update.message.reply_text("❌ رصيد غير كافي")
        else:
            context.user_data["awaiting_wallet"] = True
            context.user_data["withdraw_amount"] = balance
            await update.message.reply_text("📩 أرسل Binance ID")

# ---------------- ADMIN ----------------
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    pending = c.fetchone()[0]

    conn.close()

    await update.message.reply_text(
        f"👥 Users: {users}\n⏳ Pending: {pending}"
    )

# ---------------- MAIN ----------------
def main():
    init_db()

    threading.Thread(target=run_web, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("✅ البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
