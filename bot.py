import os
import json
import threading
import subprocess
from datetime import datetime, timedelta
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
import asyncio

# --- الإعدادات ---
TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]  # عدل معرفات الأدمن هنا
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# --- حالات المحادثة ---
STREAM_NAME, M3U8_LINK, FB_KEY, PLATFORM, ADD_SUB_USER, ADD_SUB_DAYS = range(6)

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
        return False, "❌ وصلت الحد المجاني اليومي، يرجى الاشتراك للبث أكثر."
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

# ---- أوامر البوت ----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username or "لا يوجد"
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"

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

    keyboard_buttons = [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"]]

    if is_admin(user.id):
        keyboard_buttons.insert(0, ["➕ إضافة مشترك"])

    keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def start_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, msg = can_stream(update.effective_user.id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("فيسبوك", callback_data="platform_facebook"),
            InlineKeyboardButton("إنستاغرام", callback_data="platform_instagram"),
        ]
    ])
    await update.message.reply_text("اختر منصة البث:", reply_markup=keyboard)
    return PLATFORM

async def platform_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    platform = query.data.split("_")[1]
    context.user_data["platform"] = platform
    await query.edit_message_text(f"تم اختيار: {platform}\nالآن أرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح، يجب أن ينتهي بـ .m3u8")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث (رابط إنستاغرام الكامل أو مفتاح فيسبوك):")
    return FB_KEY

async def get_fb_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    platform = context.user_data.get("platform")
    if platform == "facebook" and not key.startswith("FB-"):
        await update.message.reply_text("❌ مفتاح غير صالح لمنصة فيسبوك، يجب أن يبدأ بـ FB-")
        return ConversationHandler.END
    if platform == "instagram" and not any(x in key for x in ["?", "=", "&"]):
        await update.message.reply_text(
            "❌ مفتاح إنستاغرام غير صالح. الرجاء لصق المفتاح كاملاً كما هو من تطبيق إنستاغرام، ويجب أن يحتوي على الرموز `?` و `=` و `&`."
        )
        return ConversationHandler.END

    user_id = str(update.effective_user.id)
    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]

    # إعداد رابط البث النهائي
    if platform == "facebook":
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    else:
        output = f"rtmp://live-upload.instagram.com:80/rtmp/{key}"

    # اختيار إعداد الجودة
    if is_subscribed(update.effective_user.id):
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4500k", "-maxrate", "5000k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=854:480",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "1000k", "-maxrate", "1200k", "-bufsize", "1500k",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]

    tag = f"{user_id}_{name}"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(update.effective_user.id)

    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    user["last_stream"] = datetime.now().isoformat()
    user["last_stream_info"] = {"m3u8": link, "key": key, "name": name, "platform": platform}
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم بدء البث!\n📛 الاسم: {name}\n🖥️ منصة البث: {platform}")
    return ConversationHandler.END

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    last_info = user.get("last_stream_info")
    if not last_info:
        await update.message.reply_text("❌ لا يوجد بث يعمل حالياً.")
        return
    tag = f"{user_id}_{last_info['name']}"
    stop_stream_process(tag)
    await update.message.reply_text("⏹ تم إيقاف البث.")

async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    last_info = user.get("last_stream_info")
    if not last_info:
        await update.message.reply_text("❌ لا يوجد بث سابق لإعادة التشغيل.")
        return

    # أوقف القديم
    tag = f"{user_id}_{last_info['name']}"
    stop_stream_process(tag)

    # أعد تشغيل
    link = last_info["m3u8"]
    key = last_info["key"]
    name = last_info["name"]
    platform = last_info["platform"]
    if platform == "facebook":
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    else:
        output = f"rtmp://live-upload.instagram.com:80/rtmp/{key}"

    if is_subscribed(update.effective_user.id):
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4500k", "-maxrate", "5000k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", "scale=854:480",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "1000k", "-maxrate", "1200k", "-bufsize", "1500k",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "flv", "-rtbufsize", "1500M",
            output
        ]

    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()
    await update.message.reply_text(f"🔄 تم إعادة تشغيل البث: {name}")

# --- إضافة مشترك بواسطة الأدمن ---

async def add_sub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ أنت لست أدمن.")
        return ConversationHandler.END
    await update.message.reply_text("📥 أرسل معرف (ID) المستخدم الذي تريد إضافته كمشترك:")
    return ADD_SUB_USER

async def add_sub_user_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id_str = update.message.text.strip()
    if not user_id_str.isdigit():
        await update.message.reply_text("❌ المعرف يجب أن يكون رقم فقط.")
        return ConversationHandler.END
    context.user_data["new_sub_user"] = user_id_str
    await update.message.reply_text("📅 أرسل عدد أيام الاشتراك (مثلاً: 30):")
    return ADD_SUB_DAYS

async def add_sub_days_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days_str = update.message.text.strip()
    if not days_str.isdigit():
        await update.message.reply_text("❌ يجب إدخال رقم صحيح للأيام.")
        return ConversationHandler.END
    days = int(days_str)
    new_user_id = context.user_data["new_sub_user"]
    users = load_json(USERS_FILE)
    expire_date = datetime.now() + timedelta(days=days)
    if new_user_id in users and users[new_user_id].get("expires"):
        current_expire = datetime.fromisoformat(users[new_user_id]["expires"])
        if current_expire > datetime.now():
            expire_date = current_expire + timedelta(days=days)
    users[new_user_id] = users.get(new_user_id, {})
    users[new_user_id]["expires"] = expire_date.isoformat()
    save_json(USERS_FILE, users)
    await update.message.reply_text(f"✅ تم إضافة المستخدم {new_user_id} كمشترك لمدة {days} يوم.")
    return ConversationHandler.END

# --- الرد على أزرار تواصل الدعم ---

async def support_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 تواصل مع الدعم:\n"
        "• حساب تيليجرام الدعم: @YourSupportUsername\n"
        "• البريد الإلكتروني: support@example.com"
    )

# --- التعامل مع نصوص الأزرار ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎬 تجهيز البث":
        return await start_prepare(update, context)
    elif text == "⏹ إيقاف البث":
        return await stop_stream(update, context)
    elif text == "🔁 إعادة تشغيل البث":
        return await restart_stream(update, context)
    elif text == "📞 تواصل مع الدعم":
        return await support_contact(update, context)
    elif text == "➕ إضافة مشترك" and is_admin(update.effective_user.id):
        return await add_sub_start(update, context)
    else:
        await update.message.reply_text("❓ الرجاء استخدام الأزرار الموجودة.")
        return

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(🎬 تجهيز البث)$"), start_prepare)],
        states={
            PLATFORM: [CallbackQueryHandler(platform_chosen, pattern="^platform_")],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fb_key)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    add_sub_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(➕ إضافة مشترك)$"), add_sub_start)],
        states={
            ADD_SUB_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sub_user_received)],
            ADD_SUB_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sub_days_received)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(add_sub_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("بوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()