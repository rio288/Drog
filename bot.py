import os
import json
import threading
import subprocess
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

TOKEN = os.getenv("TOKEN")  # ضع توكن بوت تيليجرام في متغير البيئة TOKEN
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
ADMIN_CHAT_ID = -1001234567890  # استبدلها بمعرف قناة أو شات الدعم

os.makedirs("data", exist_ok=True)

SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY = range(4)
processes = {}

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
    return expires and datetime.fromisoformat(expires) > datetime.now()

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
        return False, "❌ وصلت للحد المجاني اليومي، اشترك للبث أكثر."
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username or "لا يوجد"
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"

    buttons = [
        ["🎬 تجهيز البث", "⏹ إيقاف البث"],
        ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"],
    ]

    if is_admin(user.id):
        buttons.append(["➕ إضافة مشترك"])

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

async def contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_text = (
        "📞 تواصل مع الدعم:\n"
        "Telegram: @@premuimuser12\n"
        "https://t.me/strpro339\n"
        "أو أرسل رسالتك هنا وسأرد عليك بأقرب وقت."
    )
    await update.message.reply_text(support_text)

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

    if is_subscribed(update.effective_user.id):
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-c:v", "libx264", "-preset", "veryfast", "-maxrate", "2500k",
            "-bufsize", "5120k", "-g", "50", "-r", "25", "-pix_fmt", "yuv420p",
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
                "-c:a", "aac", "-b:a", "128k", "-f", "flv", "-rtbufsize", "1500M",
                output
            ]
        else:
            cmd = [
                "ffmpeg", "-re", "-i", link,
                "-vf", "scale=854:480",
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-b:v", "1000k", "-maxrate", "1200k", "-bufsize", "1500k",
                "-c:a", "aac", "-b:a", "128k", "-f", "flv", "-rtbufsize", "1500M",
                output
            ]

    tag = f"{user_id}_{name}_{broadcast_type}"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(user_id)

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
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"📡 المستخدم {user_id} بدأ بث {broadcast_type} باسم {name}")
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

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ هذه الخاصية خاصة بالأدمن فقط.")
        return

    if len(context.args) != 2:
        await update.message.reply_text("استخدم: /addsub <user_id> <days>")
        return

    try:
        target_id = context.args[0]
        days = int(context.args[1])
    except Exception:
        await update.message.reply_text("❌ تأكد من كتابة المعرف وعدد الأيام بشكل صحيح.")
        return

    users = load_json(USERS_FILE)
    user = users.get(target_id, {})
    expire_date = datetime.now() + timedelta(days=days)
    user["expires"] = expire_date.isoformat()
    users[target_id] = user
    save_json(USERS_FILE, users)
    await update.message.reply_text(f"✅ تم إضافة اشتراك لـ {target_id} لمدة {days} أيام.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🎬 تجهيز البث":
        return await start_prepare(update, context)
    elif text == "⏹ إيقاف البث":
        return await stop_stream(update, context)
    elif text == "🔁 إعادة تشغيل البث":
        return await restart_stream(update, context)
    elif text == "📞 تواصل مع الدعم":
        return await contact_support(update, context)
    elif text == "➕ إضافة مشترك" and is_admin(user_id):
        await update.message.reply_text("لاستخدام إضافة مشترك اكتب:\n/addsub <user_id> <عدد الأيام>")
    else:
        await update.message.reply_text("❌ أمر غير معروف، الرجاء استخدام الأزرار.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("🎬 تجهيز البث"), start_prepare)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addsub", add_subscriber))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()