import os
import json
import threading
import subprocess
from datetime import datetime, timedelta
from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, CallbackQueryHandler, filters
)

# ====== الإعدادات ======
TOKEN = os.getenv("TOKEN")  # ضع توكن بوت تيليجرام في متغير البيئة TOKEN
ADMINS = [8145101051]  # معرفات المسؤولين
ADMIN_CHAT_ID = -1001234567890  # معرف الشات الإداري (قناة أو مجموعة)
USERS_FILE = "data/users.json"

os.makedirs("data", exist_ok=True)

# ====== مراحل الحوار ======
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY = range(4)
ADD_USER_ID, ADD_DAYS = range(4, 6)

processes = {}  # لتخزين عمليات البث

# ====== وظائف مساعدة ======
def load_json(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_admin(user_id):
    return user_id in ADMINS

def is_subscribed(user_id):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    expires = user.get("expires")
    if not expires:
        return False
    try:
        return datetime.fromisoformat(expires) > datetime.now()
    except:
        return False

def can_stream(user_id):
    if is_subscribed(user_id):
        return True, ""
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    usage = user.get("daily_stream_count", 0)
    last_date_str = user.get("daily_stream_date")
    last_date = datetime.fromisoformat(last_date_str) if last_date_str else None
    now = datetime.now()
    if not last_date or last_date.date() < now.date():
        usage = 0
    if usage >= 1:
        return False, "❌ وصلت الحد المجاني اليومي. يرجى الاشتراك للبث أكثر."
    return True, ""

def increment_daily_stream_count(user_id):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    now = datetime.now()
    last_date_str = user.get("daily_stream_date")
    last_date = datetime.fromisoformat(last_date_str) if last_date_str else None
    if not last_date or last_date.date() < now.date():
        user["daily_stream_count"] = 1
        user["daily_stream_date"] = now.isoformat()
    else:
        user["daily_stream_count"] = user.get("daily_stream_count", 0) + 1
    users[str(user_id)] = user
    save_json(USERS_FILE, users)

def monitor_stream(tag, cmd):
    proc = subprocess.Popen(cmd)
    processes[tag] = proc
    proc.wait()
    processes.pop(tag, None)

def stop_stream_process(tag):
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(tag, None)

def is_instagram(broadcast_type):
    return broadcast_type == "live_ig"

# ====== أوامر البوت ======

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username or "لا يوجد"
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"

    buttons = [
        ["🎬 تجهيز البث", "⏹ إيقاف البث"],
        ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"],
    ]

    keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    text = (
        f"مرحباً!\n"
        f"معرفك: `{user.id}`\n"
        f"اسم المستخدم: @{username}\n"
        f"الاسم: {full_name}\n"
        f"الحالة: {status}\n\n"
        f"اختر من القائمة:\n\n"
        "🎬 تجهيز البث\n"
        "⏹ إيقاف البث\n"
        "🔁 إعادة تشغيل البث\n"
        "📞 تواصل مع الدعم"
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

    if is_admin(user.id):
        inline_buttons = [[InlineKeyboardButton("➕ إضافة مشترك", callback_data="add_subscriber")]]
        await update.message.reply_text("⚙️ خيارات الإدارة:", reply_markup=InlineKeyboardMarkup(inline_buttons))

# تواصل الدعم
async def contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_text = (
        "📞 تواصل مع الدعم:\n"
        "Telegram: @@premuimuser12\n"
        "https://t.me/strpro339\n"
        "أو أرسل رسالتك هنا وسأرد عليك."
    )
    await update.message.reply_text(support_text)

# بدء تجهيز البث
async def start_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Live FB", callback_data="live_fb"),
                InlineKeyboardButton("Live IG", callback_data="live_ig"),
            ]
        ]
    )
    await update.message.reply_text("اختر نوع البث:", reply_markup=keyboard)
    return SELECT_BROADCAST_TYPE

async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["broadcast_type"] = query.data
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح.")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    broadcast_type = context.user_data.get("broadcast_type")
    user_id = str(update.effective_user.id)
    name = context.user_data.get("stream_name")
    link = context.user_data.get("m3u8")

    if broadcast_type == "live_fb":
        if not key.startswith("FB-"):
            await update.message.reply_text("❌ مفتاح غير صالح. يجب أن يبدأ بـ FB-")
            return ConversationHandler.END
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"

    elif broadcast_type == "live_ig":
        output = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"
    else:
        await update.message.reply_text("❌ خطأ في اختيار نوع البث.")
        return ConversationHandler.END

    # إعداد أمر ffmpeg مع تعديل الصوت لتفادي حقوق النشر (asetrate)
    if is_subscribed(update.effective_user.id):
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-c:v", "libx264", "-preset", "veryfast", "-maxrate", "2500k",
            "-bufsize", "5120k", "-g", "50", "-r", "25", "-pix_fmt", "yuv420p",
            "-af", "asetrate=44100*0.9,aresample=44100",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-f", "flv", output
        ]
    else:
        if is_instagram(broadcast_type):
            cmd = [
                "ffmpeg", "-re", "-i", link,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-b:v", "1800k", "-maxrate", "2000k", "-bufsize", "3000k",
                "-af", "asetrate=44100*0.9,aresample=44100",
                "-c:a", "aac", "-b:a", "128k", "-f", "flv", "-rtbufsize", "1500M",
                output
            ]
        else:
            cmd = [
                "ffmpeg", "-re", "-i", link,
                "-vf", "scale=854:480",
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-b:v", "1000k", "-maxrate", "1200k", "-bufsize", "1500k",
                "-af", "asetrate=44100*0.9,aresample=44100",
                "-c:a", "aac", "-b:a", "128k", "-f", "flv", "-rtbufsize", "1500M",
                output
            ]

    tag = f"{user_id}_{name}_{broadcast_type}"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(update.effective_user.id)

    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    user["last_stream"] = {
        "name": name,
        "link": link,
        "key": key,
        "broadcast_type": broadcast_type,
        "started_at": datetime.now().isoformat()
    }
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text("✅ تم بدء البث بنجاح!")
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID,
                                       text=f"📡 المستخدم {user_id} بدأ بث {broadcast_type} باسم {name}")
    except:
        pass

    return ConversationHandler.END

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    last_stream = user.get("last_stream")
    if not last_stream:
        await update.message.reply_text("❌ لا يوجد بث جاري للإيقاف.")
        return

    tag = f"{user_id}_{last_stream['name']}_{last_stream['broadcast_type']}"
    stop_stream_process(tag)
    await update.message.reply_text("⏹ تم إيقاف البث بنجاح.")

async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    last_stream = user.get("last_stream")
    if not last_stream:
        await update.message.reply_text("❌ لا يوجد بث لإعادة تشغيله.")
        return

    context.user_data["broadcast_type"] = last_stream["broadcast_type"]
    context.user_data["stream_name"] = last_stream["name"]
    context.user_data["m3u8"] = last_stream["link"]
    update.message.text = last_stream["key"]
    await get_stream_key(update, context)

# إضافة مشترك - خطوات
async def add_subscriber_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🆔 أرسل معرف المستخدم الذي تريد إضافته:")
    return ADD_USER_ID

async def add_subscriber_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.text.strip()
    if not user_id.isdigit():
        await update.message.reply_text("❌ المعرف يجب أن يكون رقمًا. أرسل معرف صحيح:")
        return ADD_USER_ID
    context.user_data["new_sub_user_id"] = user_id
    await update.message.reply_text("📅 أرسل عدد الأيام للاشتراك (مثلاً 30):")
    return ADD_DAYS

async def add_subscriber_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = update.message.text.strip()
    if not days.isdigit() or int(days) <= 0:
        await update.message.reply_text("❌ أدخل عدد أيام صالح (رقم موجب):")
        return ADD_DAYS
    days = int(days)

    users = load_json(USERS_FILE)
    user_id = context.user_data["new_sub_user_id"]

    expire_date = datetime.now() + timedelta(days=days)
    user = users.get(user_id, {})
    current_expire_str = user.get("expires")
    if current_expire_str:
        try:
            current_expire = datetime.fromisoformat(current_expire_str)
            if current_expire > datetime.now():
                expire_date = current_expire + timedelta(days=days)
        except:
            pass

    user["expires"] = expire_date.isoformat()
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم إضافة الاشتراك للمستخدم {user_id} لعدد {days} يومًا.")

    try:
        await context.bot.send_message(chat_id=int(user_id), text="🎉 تم تفعيل اشتراكك في البث المباشر!")
    except:
        pass

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ أمر غير معروف، الرجاء استخدام الأزرار أو الأوامر المتاحة.")

# ====== ربط الأوامر والبدء ======

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Start command
    app.add_handler(CommandHandler("start", start))

    # Contact support
    app.add_handler(MessageHandler(filters.Regex("^(📞 تواصل مع الدعم)$"), contact_support))

    # Prepare broadcast conversation
    conv_prepare = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 تجهيز البث$"), start_prepare)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_prepare)

    # Stop stream
    app.add_handler(MessageHandler(filters.Regex("^⏹ إيقاف البث$"), stop_stream))

    # Restart stream
    app.add_handler(MessageHandler(filters.Regex("^🔁 إعادة تشغيل البث$"), restart_stream))

    # Admin add subscriber conversation
    conv_add_sub = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_subscriber_start, pattern="add_subscriber")],
        states={
            ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subscriber_user_id)],
            ADD_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subscriber_days)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_add_sub)

    # Unknown commands handler
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()