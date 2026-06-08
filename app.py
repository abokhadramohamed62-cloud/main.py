import os
import sqlite3
import threading
from datetime import datetime
from flask import Flask, request, jsonify
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ========== الإعدادات ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_توكن_البوت_هنا")
ADMIN_ID = 868999453
CHANNELS = ["@Crypto_Dragon13"]
REWARD_PER_REFERRAL = 0.03
MIN_WITHDRAW = 0.15
CURRENCY = "TON"
CF_SECRET = os.getenv("CF_SECRET", "0x4AAAAAADg_QwNGvi2wp0eo")
VERIFY_URL = "https://abokhadramohamed62-cloud.github.io"

# ========== Flask السيرفر ==========
flask_app = Flask(__name__)

@flask_app.route('/verify-cf', methods=['POST'])
def verify_cf():
    data = request.json
    token = data.get('token')
    user_id = data.get('user_id')
    if not token or not user_id:
        return jsonify({'success': False})
    response = requests.post(
        'https://challenges.cloudflare.com/turnstile/v0/siteverify',
        data={'secret': CF_SECRET, 'response': token}
    )
    result = response.json()
    if result.get('success'):
        set_cf_verified(int(user_id))
        return jsonify({'success': True})
    return jsonify({'success': False})

@flask_app.route('/')
def home():
    return 'OK'

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))

# ========== قاعدة البيانات ==========
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
        verified INTEGER DEFAULT 0,
        cf_verified INTEGER DEFAULT 0
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
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id, username, referred_by, joined_at, verified, cf_verified) VALUES (?,?,?,?,0,0)",
                  (user_id, username, referred_by, datetime.now().isoformat()))
        conn.commit()
    conn.close()

def set_cf_verified(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET cf_verified=1 WHERE user_id=?", (user_id,))
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
            c.execute("SELECT user_id FROM users WHERE user_id=?", (referred_by,))
            if c.fetchone():
                c.execute("UPDATE users SET balance=balance+?, referrals=referrals+1 WHERE user_id=?",
                          (REWARD_PER_REFERRAL, referred_by))
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

def add_withdrawal(user_id, amount, wallet):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO withdrawals (user_id, amount, wallet, requested_at) VALUES (?,?,?,?)",
              (user_id, amount, wallet, datetime.now().isoformat()))
    c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

# ========== التحقق من الاشتراك ==========
async def check_subscriptions(user_id, context):
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except:
            return False
    return True

# ========== لوحة المفاتيح ==========
def reply_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔗 رابط الإحالة"), KeyboardButton("💰 رصيدي")],
        [KeyboardButton("👥 إحالاتي"), KeyboardButton("💵 سحب")],
        [KeyboardButton("📋 شروط الاشتراك")]
    ], resize_keyboard=True)

def subscription_keyboard():
    buttons = [[InlineKeyboardButton(f"📢 اشترك في {ch}", url=f"https://t.me/{ch.lstrip('@')}")] for ch in CHANNELS]
    buttons.append([InlineKeyboardButton("✅ تحققت من اشتراكي", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

def verify_keyboard(user_id):
    url = f"{VERIFY_URL}?user_id={user_id}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛡️ فتح صفحة التحقق", web_app=WebAppInfo(url=url))
    ]])

# ========== الأوامر ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = int(args[0]) if args and args[0].isdigit() else None
    existing = get_user(user.id)

    if not existing:
        add_user(user.id, user.username or user.first_name, referred_by)

    user_data = get_user(user.id)

    # أول حاجة: التحقق من Cloudflare
    if not user_data or user_data[7] == 0:
        await update.message.reply_text(
            "🛡️ **التحقق الأمني مطلوب**\n\n"
            "لمنع التسجيل المتعدد، نحتاج للتحقق من جهازك.\n"
            "⏱️ صلاحية الرابط: 5 دقائق\n\n"
            "👇 اضغط على الزر أدناه للتحقق:",
            parse_mode="Markdown",
            reply_markup=verify_keyboard(user.id)
        )
        return

    # ثاني حاجة: التحقق من الاشتراك
    subscribed = await check_subscriptions(user.id, context)
    if not subscribed:
        await update.message.reply_text(
            "👋 مرحباً بك!\n\n⚠️ يجب الاشتراك في القنوات التالية أولاً:",
            reply_markup=subscription_keyboard()
        )
        return

    # إضافة المكافأة بعد التأكد من الاتنين
    if user_data and user_data[6] == 0:
        referred_by_id = verify_user(user.id)
        if referred_by_id:
            try:
                await context.bot.send_message(
                    referred_by_id,
                    f"🎉 انضم شخص جديد عبر رابطك!\n💰 حصلت على +{REWARD_PER_REFERRAL} {CURRENCY}"
                )
            except:
                pass

    await update.message.reply_text(
        f"👋 أهلاً {user.first_name}!\n\n"
        f"🤖 بوت الإحالات\n"
        f"💰 اربح {REWARD_PER_REFERRAL} {CURRENCY} لكل صديق تدعوه!\n"
        f"📌 الحد الأدنى للسحب: {MIN_WITHDRAW} {CURRENCY}",
        reply_markup=reply_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "check_sub":
        user_data = get_user(user.id)
        if not user_data or user_data[7] == 0:
            await query.edit_message_text(
                "❌ يجب إتمام التحقق الأمني أولاً!",
                reply_markup=verify_keyboard(user.id)
            )
            return
        subscribed = await check_subscriptions(user.id, context)
        if subscribed:
            referred_by_id = verify_user(user.id)
            if referred_by_id:
                try:
                    await context.bot.send_message(
                        referred_by_id,
                        f"🎉 انضم شخص جديد عبر رابطك!\n💰 حصلت على +{REWARD_PER_REFERRAL} {CURRENCY}"
                    )
                except:
                    pass
            await query.edit_message_text(f"✅ تم التحقق! أهلاً {user.first_name}")
            await context.bot.send_message(
                user.id,
                f"👋 أهلاً {user.first_name}!\n\n"
                f"🤖 بوت الإحالات\n"
                f"💰 اربح {REWARD_PER_REFERRAL} {CURRENCY} لكل صديق تدعوه!\n"
                f"📌 الحد الأدنى للسحب: {MIN_WITHDRAW} {CURRENCY}",
                reply_markup=reply_keyboard()
            )
        else:
            await query.edit_message_text(
                "❌ لم تشترك في جميع القنوات!\nاشترك ثم اضغط تحققت.",
                reply_markup=subscription_keyboard()
            )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if context.user_data.get("awaiting_wallet"):
        wallet = text.strip()
        amount = context.user_data["withdraw_amount"]
        add_withdrawal(user.id, amount, wallet)
        conn = sqlite3.connect("bot.db")
        withdrawal_id = conn.execute(
            "SELECT id FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 1", (user.id,)
        ).fetchone()[0]
        conn.close()
        context.user_data.pop("awaiting_wallet", None)
        context.user_data.pop("withdraw_amount", None)
        await update.message.reply_text(
            "✅ تم تقديم طلب السحب وسيتم مراجعته من قبل الإدارة.",
            reply_markup=reply_keyboard()
        )
        username = f"@{user.username}" if user.username else user.first_name
        await context.bot.send_message(
            ADMIN_ID,
            f"💵 طلب سحب جديد!\n\n"
            f"👤 المستخدم: {username} ({user.id})\n"
            f"💰 المبلغ: {amount} {CURRENCY}\n"
            f"🏦 محفظة TON:\n`{wallet}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ موافقة", callback_data=f"approve_{withdrawal_id}_{user.id}")
            ]])
        )
        return

    if text == "💰 رصيدي":
        balance, refs = get_balance(user.id)
        await update.message.reply_text(
            f"💰 رصيدك الحالي: {round(balance, 3)} {CURRENCY}\n👥 عدد إحالاتك: {refs}",
            reply_markup=reply_keyboard()
        )
    elif text == "🔗 رابط الإحالة":
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={user.id}"
        await update.message.reply_text(
            f"🔗 رابط إحالتك:\n\n`{link}`\n\nاربح {REWARD_PER_REFERRAL} {CURRENCY} لكل شخص يشترك!",
            parse_mode="Markdown", reply_markup=reply_keyboard()
        )
    elif text == "👥 إحالاتي":
        balance, refs = get_balance(user.id)
        await update.message.reply_text(
            f"👥 عدد إحالاتك: {refs}\n💰 إجمالي أرباحك: {round(refs * REWARD_PER_REFERRAL, 3)} {CURRENCY}",
            reply_markup=reply_keyboard()
        )
    elif text == "💵 سحب":
        balance, _ = get_balance(user.id)
        if round(balance, 3) < MIN_WITHDRAW:
            await update.message.reply_text(
                f"❌ رصيدك {round(balance, 3)} {CURRENCY} أقل من الحد الأدنى ({MIN_WITHDRAW} {CURRENCY})\n"
                f"تحتاج {round(MIN_WITHDRAW - balance, 3)} {CURRENCY} إضافية.",
                reply_markup=reply_keyboard()
            )
        else:
            context.user_data["awaiting_wallet"] = True
            context.user_data["withdraw_amount"] = round(balance, 3)
            await update.message.reply_text(
                f"💵 رصيدك المتاح: {round(balance, 3)} {CURRENCY}\n\n📩 أرسل عنوان محفظة TON:"
            )
    elif text == "📋 شروط الاشتراك":
        await update.message.reply_text(
            "📋 شروط الاشتراك:\n\n"
            f"• تحصل على {REWARD_PER_REFERRAL} {CURRENCY} لكل صديق\n"
            f"• الحد الأدنى للسحب: {MIN_WITHDRAW} {CURRENCY}\n"
            "• يجب اشتراك الصديق في القنوات\n"
            "• السحب عبر محفظة TON فقط\n"
            "• طلبات السحب تُراجع خلال 24 ساعة",
            reply_markup=reply_keyboard()
        )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    pending = c.fetchone()[0]
    conn.close()
    await update.message.reply_text(
        f"📊 إحصائيات البوت:\n\n"
        f"👥 إجمالي المستخدمين: {total_users}\n"
        f"⏳ طلبات سحب معلقة: {pending}"
    )

# ========== التشغيل ==========
def main():
    init_db()
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("✅ البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
