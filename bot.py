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

TOKEN = os.getenv("TOKEN")  # ضع توكن بوتك هنا أو استخدم متغير بيئة
ADMINS = [8145101051]       # ضع ايدي الأدمن هنا
USERS_FILE = "data/users.json"
ADMIN_CHAT_ID = -1001234567890  # شات ادمن أو قناة للإشعارات

os.makedirs("data", exist_ok=True)

STREAM_NAME, M3U8_LINK, FB_KEY, PLATFORM, ADD_SUB = range(5)
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    users = load_json(USERS_FILE)
    user_data = users.get(str(user.id), {})

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
        "➕ إضافة مشترك (للمشرفين فقط)\n"
        "📞 تواصل مع الدعم"
    )

    keyboard_buttons = [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث"]]

    if is_admin(user.id):
        keyboard_buttons.append(["➕ إضافة مشترك"])

    keyboard_buttons.append(["📞 تواصل مع الدعم"])

    keyboard = ReplyKeyboardMarkup(
        keyboard_buttons,
        resize_keyboard=True,
    )
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
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return FB_KEY

async def get_fb_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    platform = context.user_data.get("platform")
    # تحقق مفتاح فيسبوك فقط، الإنستاغرام يقبل أي مفتاح
    if platform == "facebook" and not key.startswith("FB-"):
        await update.message.reply_text("❌ مفتاح غير صالح لمنصة فيسبوك، يجب أن يبدأ بـ FB-")
        return ConversationHandler.END

    user_id = str(update.effective_user.id)
    name = context.user_data["stream_name"]
    link = context.user_data["m3u8"]

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

    tag = f"{user_id}_{name}"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    if not is_subscribed(update.effective_user.id):
        increment_daily_stream_count(user_id)

    users = load_json(USERS_FILE)
    user = users.get(user_id, {})
    user["last_stream"] = datetime.now().isoformat()
    user["last_stream_info"] = {"m3u8": link, "key": key, "name": name, "platform": platform}
    users[user_id] = user
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم بدء البث!\n📛 الاسم: {name}\n🖥️ منصة البث: {platform}")

    if not is_subscribed(update.effective_user.id):
        def stop_and_notify():
            stop_stream_process(tag)
            asyncio.run_coroutine_threadsafe(
                update.message.reply_text(
                    "⏰ انتهى وقت البث المجاني (30 دقيقة). يرجى الاشتراك لمواصلة البث."
                ),
                context.application.loop
            )
            asyncio.run_coroutine_threadsafe(
                context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"📢 المستخدم @{update.effective_user.username or update.effective_user.id} انتهى بثه المجاني."
                ),
                context.application.loop
            )

        timer = threading.Timer(1800, stop_and_notify)
        timer.daemon = True
        timer.start()

    return ConversationHandler.END

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    tags = [tag for tag in processes if tag.startswith(user_id)]
    stopped = 0
    for tag in tags:
        stop_stream_process(tag)
        stopped += 1
    await update.message.reply_text(f"⏹ تم إيقاف {stopped} بث(ات)." if stopped else "❌ لا يوجد بث نشط.")

async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users = load_json(USERS_FILE)
    user = users.get(user_id)
    if not user or "last_stream_info" not in user:
        await update.message.reply_text("❌ لا يوجد بث سابق لإعادة تشغيله.")
        return ConversationHandler.END
    context.user_data.update(user["last_stream_info"])
    platform = context.user_data.get("platform")
    await update.message.reply_text(f"🔑 أرسل مفتاح البث الجديد (يبدأ بـ {'FB-' if platform=='facebook' else ''}):")
    return FB_KEY

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎬 تجهيز البث":
        return await start_prepare(update, context)
    elif text == "⏹ إيقاف البث":
        return await stop_stream(update, context)
    elif text == "🔁 إعادة تشغيل البث":
        return await restart_stream(update, context)
    elif text == "➕ إضافة مشترك":
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("❌ هذا الأمر مخصص فقط للمشرفين.")
            return ConversationHandler.END
        await update.message.reply_text("أرسل: USER_ID DAYS\nمثال:\n8145101051 30")
        return ADD_SUB
    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("📞 للتواصل مع الدعم:\n@SupportUsername أو أرسل رسالة هنا.")
    else:
        await update.message.reply_text("❓ الرجاء اختيار خيار من القائمة.")

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        user_id, days = text.split()
        days = int(days)
        users = load_json(USERS_FILE)
        expires = datetime.now() + timedelta(days=days)
        users[user_id] = users.get(user_id, {})
        users[user_id]["expires"] = expires.isoformat()
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تم الاشتراك للمستخدم {user_id} لمدة {days} يوم.")
        try:
            await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك. استمتع بالخدمة!")
        except:
            pass
    except:
        await update.message.reply_text("❌ الخطأ في الصيغة. أرسل: USER_ID DAYS\nمثال:\n8145101051 30")
    return ConversationHandler.END

async def platform_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # مجرد تحويل منصة للبث من أزرار إنلاين
    return await platform_chosen(update, context)

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],
        states={
            PLATFORM: [CallbackQueryHandler(platform_callback, pattern="^platform_")],
            STREAM_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_fb_key)],
            ADD_SUB: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_subscriber)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()