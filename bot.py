import os
import json
import threading
import subprocess
from datetime import datetime, timedelta
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
import asyncio

# إعدادات عامة
TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"  # ضع توكن بوتك هنا
ADMINS = [8145101051]  # IDs الأدمن
USERS_FILE = "data/users.json"
ADMIN_CHAT_ID = -1001234567890  # ID مجموعة الإدارة

os.makedirs("data", exist_ok=True)

# حالات ConversationHandler
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY = range(4)

processes = {}

FREE_STREAM_LIMIT_SECONDS = 1800  # 30 دقيقة يوميًا للمجانيين

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
    except Exception:
        return False

def can_stream(user_id):
    if is_subscribed(user_id):
        return True, ""
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    last_date_str = user.get("daily_stream_date")
    last_date = datetime.fromisoformat(last_date_str) if last_date_str else None
    now = datetime.now()
    if not last_date or last_date.date() < now.date():
        user["daily_stream_seconds"] = 0
        user["daily_stream_date"] = now.isoformat()
        users[str(user_id)] = user
        save_json(USERS_FILE, users)
    used_seconds = user.get("daily_stream_seconds", 0)
    if used_seconds >= FREE_STREAM_LIMIT_SECONDS:
        return False, "❌ وصلت لحد البث المجاني اليومي (30 دقيقة). اشترك للبث أكثر."
    return True, ""

def increment_stream_time(user_id, seconds):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    now = datetime.now()
    last_date_str = user.get("daily_stream_date")
    last_date = datetime.fromisoformat(last_date_str) if last_date_str else None
    if not last_date or last_date.date() < now.date():
        user["daily_stream_seconds"] = seconds
        user["daily_stream_date"] = now.isoformat()
    else:
        user["daily_stream_seconds"] = user.get("daily_stream_seconds", 0) + seconds
    users[str(user_id)] = user
    save_json(USERS_FILE, users)

def monitor_stream(tag, cmd, user_id):
    try:
        proc = subprocess.Popen(cmd)
        processes[tag] = proc
        start_time = datetime.now()
        proc.wait()
        end_time = datetime.now()
        if not is_subscribed(int(user_id)):
            elapsed = (end_time - start_time).total_seconds()
            increment_stream_time(int(user_id), int(elapsed))
    except Exception as e:
        print(f"Error in monitor_stream for {tag}: {e}")
    finally:
        processes.pop(tag, None)

def stop_stream_process(tag):
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
        processes.pop(tag, None)

# أوامر البوت

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    users = load_json(USERS_FILE)
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
    keyboard = ReplyKeyboardMarkup(
        [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def support_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📞 للتواصل مع الدعم، يرجى مراسلة @@premuimuser12")

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
        # جودة المشترك: 720p 2500k
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-c:v", "libx264", "-preset", "veryfast",
            "-maxrate", "2500k", "-bufsize", "5120k",
            "-g", "50", "-r", "25", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-f", "flv", output
        ]
    else:
        # جودة مجاني: عدة جودات لإنستغرام - 480p، 360p، 240p، 144p
        if broadcast_type == "live_ig":
            # بث متعدد جودات لإنستغرام (متبسط - بث واحد 360p فقط)
            cmd = [
                "ffmpeg", "-re", "-i", link,
                "-vf", "scale=640:360",
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-b:v", "600k", "-maxrate", "700k", "-bufsize", "1200k",
                "-c:a", "aac", "-b:a", "128k", "-f", "flv", "-rtbufsize", "1500M",
                output
            ]
        else:
            # بث مجاني فيسبوك 480p
            cmd = [
                "ffmpeg", "-re", "-i", link,
                "-vf", "scale=854:480",
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-b:v", "1000k", "-maxrate", "1200k", "-bufsize", "1500k",
                "-c:a", "aac", "-b:a", "128k", "-f", "flv", "-rtbufsize", "1500M",
                output
            ]

    tag = f"{user_id}_{name}_{broadcast_type}"
    stop_stream_process(tag)  # إيقاف أي بث سابق بنفس الوسم
    threading.Thread(target=monitor_stream, args=(tag, cmd, user_id), daemon=True).start()

    await update.message.reply_text("✅ تم بدء البث بنجاح.")

    return ConversationHandler.END

async def stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stopped = False
    for tag in list(processes.keys()):
        if tag.startswith(user_id):
            stop_stream_process(tag)
            stopped = True
    if stopped:
        await update.message.reply_text("⏹ تم إيقاف البث.")
    else:
        await update.message.reply_text("❌ لا يوجد بث نشط لإيقافه.")

async def restart_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    stopped = False
    for tag in list(processes.keys()):
        if tag.startswith(user_id):
            stop_stream_process(tag)
            stopped = True
    if stopped:
        await update.message.reply_text("♻️ تم إيقاف البث، ابدأ بث جديد باستخدام 🎬 تجهيز البث.")
    else:
        await update.message.reply_text("❌ لا يوجد بث نشط لإعادة تشغيله.")

# إدارة المشتركين

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ أنت لست أدمن.")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("الاستخدام: /addsub <user_id> <مدة_بالأيام>")
        return
    try:
        user_id = str(int(args[0]))
        days = int(args[1])
        users = load_json(USERS_FILE)
        expires = datetime.now() + timedelta(days=days)
        users[user_id] = users.get(user_id, {})
        users[user_id]["expires"] = expires.isoformat()
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تمت إضافة اشتراك للمستخدم {user_id} لمدة {days} يومًا.")
    except Exception:
        await update.message.reply_text("❌ خطأ في الإدخال.")

async def del_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ أنت لست أدمن.")
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("الاستخدام: /delsub <user_id>")
        return
    try:
        user_id = str(int(args[0]))
        users = load_json(USERS_FILE)
        if user_id in users:
            users[user_id].pop("expires", None)
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"✅ تم حذف اشتراك المستخدم {user_id}.")
        else:
            await update.message.reply_text("❌ المستخدم غير موجود.")
    except Exception:
        await update.message.reply_text("❌ خطأ في الإدخال.")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ أمر غير معروف.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎬 تجهيز البث":
        return await start_prepare(update, context)
    elif text == "⏹ إيقاف البث":
        return await stop_stream(update, context)
    elif text == "🔁 إعادة تشغيل البث":
        return await restart_stream(update, context)
    elif text == "📞 تواصل مع الدعم":
        return await support_contact(update, context)
    else:
        await update.message.reply_text("❌ استخدم الأزرار المتاحة فقط.")

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(🎬 تجهيز البث)$"), start_prepare)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("stop", stop_stream))
    application.add_handler(CommandHandler("restart", restart_stream))
    application.add_handler(CommandHandler("addsub", add_subscriber))
    application.add_handler(CommandHandler("delsub", del_subscriber))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()