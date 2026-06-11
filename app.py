import os
import sqlite3
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_توكن_البوت_هنا")
ADMIN_ID = 868999453
CHANNELS = ["@Crypto_Dragon13", "@KingsCrypto770", "@hazarcrypto", "@Crypto_Kings5", "@hh6442"]
REWARD_PER_REFERRAL = 0.015
MIN_WITHDRAW = 0.15
CURRENCY = "TON"
CF_SECRET = os.getenv("CF_SECRET", "0x4AAAAAADg_QzpMFMb68n4OPqIkwhs1gEI")
VERIFY_URL = "https://abokhadramohamed62-cloud.github.io"
PAYMENT_PROOF_CHANNEL = "https://t.me/Crypto_Dragon14"

flask_app = Flask(__name__)
CORS(flask_app)
bot_app = None

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
        cf_verified INTEGER DEFAULT 0,
        ip_address TEXT DEFAULT NULL,
        banned INTEGER DEFAULT 0
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
        c.execute("INSERT INTO users (user_id, username, referred_by, joined_at, verified, cf_verified, banned) VALUES (?,?,?,?,0,0,0)",
                  (user_id, username, referred_by, datetime.now().isoformat()))
        conn.commit()
    conn.close()

def set_cf_verified(user_id, ip=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET cf_verified=1, ip_address=? WHERE user_id=?", (ip, user_id))
    conn.commit()
    conn.close()

def is_ip_registered(ip):
    if not ip:
        return False
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE ip_address=? AND cf_verified=1", (ip,))
    row = c.fetchone()
    conn.close()
    return row is not None

def is_banned(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row and row[0] == 1

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

def is_fully_verified(user_id):
    """تحقق ان المستخدم عمل التحقق من IP والاشتراك في القنوات"""
    user = get_user(user_id)
    if not user:
        return False
    return user[7] == 1 and user[6] >= 1

async def notify_referrer(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT referred_by, verified FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    referred_by = row[0]
    already_verified = row[1]
    if already_verified == 1 or not referred_by or referred_by == user_id:
        return False
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (referred_by,))
    if c.fetchone():
        c.execute("UPDATE users SET balance=balance+?, referrals=referrals+1 WHERE user_id=?",
                  (REWARD_PER_REFERRAL, referred_by))
        c.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        try:
            await bot_app.bot.send_message(
                referred_by,
                f"🎉 انضم شخص جديد عبر رابطك!\n💰 حصلت على +{REWARD_PER_REFERRAL} {CURRENCY}"
            )
        except Exception as e:
            logger.error(f"خطأ في إرسال المكافأة: {e}")
        return True
    conn.close()
    return False

# ========== Flask ==========
@flask_app.route('/verify-cf', methods=['POST'])
def verify_cf():
    try:
        data = request.json
        token = data.get('token')
        user_id = data.get('user_id')
        referred_by = data.get('referred_by')

        if not token or not user_id:
            return jsonify({'success': False, 'reason': 'missing_data'})

        if referred_by and str(referred_by) == str(user_id):
            return jsonify({'success': False, 'reason': 'self_referral'})

        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        if is_ip_registered(ip):
            conn = sqlite3.connect("bot.db")
            c = conn.cursor()
            c.execute("UPDATE users SET banned=1 WHERE user_id=?", (int(user_id),))
            conn.commit()
            conn.close()
            return jsonify({'success': False, 'reason': 'ip_exists'})

        try:
            response = requests.post(
                'https://challenges.cloudflare.com/turnstile/v0/siteverify',
                data={'secret': CF_SECRET, 'response': token},
                timeout=10
            )
            result = response.json()
        except requests.exceptions.Timeout:
            return jsonify({'success': False, 'reason': 'cf_timeout'})
        except Exception as e:
            logger.error(f"Cloudflare error: {e}")
            return jsonify({'success': False, 'reason': 'cf_error'})

        if result.get('success'):
            conn = sqlite3.connect("bot.db")
            c = conn.cursor()
            ref = int(referred_by) if referred_by and str(referred_by).isdigit() and str(referred_by) != str(user_id) else None
            c.execute("SELECT user_id FROM users WHERE user_id=?", (int(user_id),))
            if not c.fetchone():
                c.execute("INSERT INTO users (user_id, username, referred_by, joined_at, verified, cf_verified, banned) VALUES (?,?,?,?,0,1,0)",
                          (int(user_id), None, ref, datetime.now().isoformat()))
            else:
                c.execute("UPDATE users SET cf_verified=1, referred_by=COALESCE(referred_by, ?) WHERE user_id=?",
                          (ref, int(user_id)))
            conn.commit()
            conn.close()
            set_cf_verified(int(user_id), ip)

            # بعد التحقق من IP ابعت رسالة الاشتراك الاجباري تلقائياً
            if bot_app:
                import asyncio
                buttons = [[InlineKeyboardButton(f"📢 اشترك في {ch}", url=f"https://t.me/{ch.lstrip('@')}")] for ch in CHANNELS]
                buttons.append([InlineKeyboardButton("✅ تحققت من اشتراكي", callback_data="check_sub")])
                keyboard = InlineKeyboardMarkup(buttons)
                asyncio.run_coroutine_threadsafe(
                    bot_app.bot.send_message(
                        int(user_id),
                        "✅ تم التحقق من جهازك!\n\n"
                        "⚠️ الخطوة الأخيرة: اشترك في القنوات التالية:",
                        reply_markup=keyboard
                    ),
                    bot_app.update_queue._loop if hasattr(bot_app, 'update_queue') else asyncio.get_event_loop()
                )
            return jsonify({'success': True})

        return jsonify({'success': False, 'reason': 'cf_failed'})

    except Exception as e:
        logger.error(f"خطأ في verify_cf: {e}")
        return jsonify({'success': False, 'reason': 'server_error'})

@flask_app.route('/')
def home():
    return 'OK'

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))

# ========== لوحة المفاتيح ==========
def reply_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔗 رابط الإحالة"), KeyboardButton("💰 رصيدي")],
        [KeyboardButton("👥 إحالاتي"), KeyboardButton("💵 سحب")],
        [KeyboardButton("📸 قناة إثبات الدفع")]
    ], resize_keyboard=True)

def subscription_keyboard():
    buttons = [[InlineKeyboardButton(f"📢 اشترك في {ch}", url=f"https://t.me/{ch.lstrip('@')}")] for ch in CHANNELS]
    buttons.append([InlineKeyboardButton("✅ تحققت من اشتراكي", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

def verify_keyboard(user_id, referred_by=None):
    url = f"{VERIFY_URL}?user_id={user_id}"
    if referred_by and referred_by != user_id:
        url += f"&referred_by={referred_by}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛡️ فتح صفحة التحقق", url=url)
    ]])

async def check_subscriptions(user_id, context):
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logger.error(f"خطأ في فحص الاشتراك: {e}")
            return False
    return True

# ========== الأوامر ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = int(args[0]) if args and args[0].isdigit() else None

    if referred_by and referred_by == user.id:
        referred_by = None

    existing = get_user(user.id)
    if not existing:
        add_user(user.id, user.username or user.first_name, referred_by)
    elif referred_by and existing[4] is None:
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referred_by, user.id))
        conn.commit()
        conn.close()

    if is_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام البوت.")
        return

    user_data = get_user(user.id)

    # المرحلة 1: التحقق من IP
    if not user_data or user_data[7] == 0:
        await update.message.reply_text(
            "🛡️ *التحقق الأمني مطلوب*\n\n"
            "لمنع التسجيل المتعدد، نحتاج للتحقق من جهازك.\n\n"
            "👇 اضغط على الزر أدناه للتحقق:",
            parse_mode="Markdown",
            reply_markup=verify_keyboard(user.id, referred_by)
        )
        return

    # المرحلة 2: الاشتراك الاجباري
    subscribed = await check_subscriptions(user.id, context)
    if not subscribed:
        await update.message.reply_text(
            "⚠️ يجب الاشتراك في القنوات التالية للمتابعة:",
            reply_markup=subscription_keyboard()
        )
        return

    # المرحلة 3: إضافة المكافأة وفتح البوت
    if user_data and user_data[6] == 0:
        await notify_referrer(user.id)

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

    if is_banned(user.id):
        await query.edit_message_text("🚫 تم حظرك من استخدام البوت.")
        return

    if query.data == "check_sub":
        user_data = get_user(user.id)

        # تأكد من التحقق من IP أولاً
        if not user_data or user_data[7] == 0:
            await query.edit_message_text(
                "❌ يجب إتمام التحقق الأمني أولاً!",
                reply_markup=verify_keyboard(user.id)
            )
            return

        subscribed = await check_subscriptions(user.id, context)
        if subscribed:
            await notify_referrer(user.id)
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

    elif query.data.startswith("approve_"):
        if user.id != ADMIN_ID:
            return
        parts = query.data.split("_")
        withdrawal_id = int(parts[1])
        target_user_id = int(parts[2])
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("SELECT * FROM withdrawals WHERE id=?", (withdrawal_id,))
        withdrawal = c.fetchone()
        if withdrawal and withdrawal[4] != 'approved':
            c.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (withdrawal_id,))
            conn.commit()
            # جيب اسم المستخدم
            try:
                target_user = await context.bot.get_chat(target_user_id)
                username = f"@{target_user.username}" if target_user.username else target_user.first_name
            except:
                username = str(target_user_id)
            # انشر في قناة إثبات الدفع تلقائياً
            try:
                await context.bot.send_message(
                    "@Crypto_Dragon14",
                    f"✅ تم الدفع!\n\n"
                    f"👤 المستخدم: {username}\n"
                    f"💰 المبلغ: {withdrawal[2]} {CURRENCY}\n"
                    f"🏦 المحفظة: `{withdrawal[3]}`",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"خطأ في النشر في القناة: {e}")
        conn.close()
        await query.edit_message_text(f"✅ تم الموافقة ونشر إثبات الدفع #{withdrawal_id}")
        try:
            await context.bot.send_message(
                target_user_id,
                "✅ تم الموافقة على طلب السحب!\n💰 تفقد قناة إثبات الدفع:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📸 قناة إثبات الدفع", url="https://t.me/Crypto_Dragon14")
                ]])
            )
        except Exception as e:
            logger.error(f"خطأ في إرسال رسالة الموافقة: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if is_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام البوت.")
        return

    # تأكد من اكتمال التحقق قبل أي عملية
    user_data = get_user(user.id)
    if not user_data or user_data[7] == 0:
        await update.message.reply_text(
            "🛡️ يجب إتمام التحقق الأمني أولاً:",
            reply_markup=verify_keyboard(user.id)
        )
        return

    subscribed = await check_subscriptions(user.id, context)
    if not subscribed:
        await update.message.reply_text(
            "⚠️ يجب الاشتراك في القنوات للمتابعة:",
            reply_markup=subscription_keyboard()
        )
        return

    if context.user_data.get("awaiting_wallet"):
        wallet = text.strip()
        if len(wallet) < 10:
            await update.message.reply_text("❌ عنوان المحفظة غير صحيح، أرسل عنوان TON صحيح:")
            return
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
                f"💵 رصيدك المتاح: {round(balance, 3)} {CURRENCY}\n\n"
                f"📩 أرسل عنوان TON Wallet الخاص بك:"
            )
    elif text == "📸 قناة إثبات الدفع":
        await update.message.reply_text(
            "📸 قناة إثبات الدفع:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 فتح القناة", url=PAYMENT_PROOF_CHANNEL)
            ]])
        )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned=1")
    banned_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    pending = c.fetchone()[0]
    conn.close()
    await update.message.reply_text(
        f"📊 إحصائيات البوت:\n\n"
        f"👥 إجمالي المستخدمين: {total_users}\n"
        f"🚫 محظورين: {banned_users}\n"
        f"⏳ طلبات سحب معلقة: {pending}"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("استخدم: /broadcast رسالتك")
        return
    message = " ".join(context.args)
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE banned=0")
    users = c.fetchall()
    conn.close()
    success = 0
    failed = 0
    for u in users:
        try:
            await context.bot.send_message(u[0], f"📢 رسالة من الإدارة:\n\n{message}")
            success += 1
        except:
            failed += 1
    await update.message.reply_text(f"✅ نجح: {success}\n❌ فشل: {failed}")

def main():
    global bot_app
    init_db()
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("stats", admin_stats))
    bot_app.add_handler(CommandHandler("broadcast", broadcast))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("✅ البوت يعمل...")
    bot_app.run_polling()

if __name__ == "__main__":
    main()
