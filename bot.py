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

TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
LAST_STREAMS_FILE = "data/last_streams.json"
os.makedirs("data", exist_ok=True)

SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)

processes = {}

def load_json(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return {}

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

def monitor_stream(tag, cmd, user_id, is_pro):
    proc = subprocess.Popen(cmd)
    processes[tag] = proc

    if not is_pro:
        def stop_later():
            proc.terminate()
            processes.pop(tag, None)

        threading.Timer(600, stop_later).start()

    proc.wait()
    processes.pop(tag, None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"

    buttons = [
        ["🎬 تجهيز البث", "⏹ إيقاف البث"],
        ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"],
    ]
    if is_admin(user.id):
        buttons.append(["➕ إضافة مفتاح اشتراك"])

    keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    text = (
        f"مرحباً!\nمعرفك: `{user.id}`\n"
        f"الاسم: {user.full_name}\n"
        f"الحالة: {status}\n\n"
        "اختر من القائمة:\n🎬 تجهيز البث\n⏹ إيقاف البث\n🔁 إعادة تشغيل البث\n📞 تواصل مع الدعم"
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "➕ إضافة مفتاح اشتراك" and is_admin(user_id):
        await update.message.reply_text(
            "أرسل بيانات الاشتراك بهذا الشكل:\n`user_id | 2025-07-01`",
            parse_mode="Markdown")
        context.user_data["awaiting_subscribe_data"] = True
        return ADD_SUBSCRIBE

    if context.user_data.get("awaiting_subscribe_data"):
        try:
            data = text.split("|")
            target_user_id = data[0].strip()
            expire_date = data[1].strip()
            datetime.fromisoformat(expire_date)
            users = load_json(USERS_FILE)
            user = users.get(target_user_id, {})
            user["expires"] = expire_date
            users[target_user_id] = user
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"✅ تم تحديث اشتراك المستخدم {target_user_id} حتى {expire_date}")
        except:
            await update.message.reply_text("❌ خطأ في الصيغة، حاول مرة أخرى")
        context.user_data["awaiting_subscribe_data"] = False
        return ConversationHandler.END

    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Live FB", callback_data="live_fb"),
             InlineKeyboardButton("Live IG", callback_data="live_ig")],
            [InlineKeyboardButton("protected", callback_data="use_filter")]
        ])
        await update.message.reply_text("اختر نوع البث أو *protected* للحماية:", reply_markup=keyboard, parse_mode="Markdown")
        return SELECT_BROADCAST_TYPE

    elif text == "⏹ إيقاف البث":
        proc = processes.get(str(user_id))
        if proc and proc.poll() is None:
            proc.terminate()
            processes.pop(str(user_id), None)
            await update.message.reply_text("✅ تم إيقاف البث.")
        else:
            await update.message.reply_text("❌ لا يوجد بث نشط.")
        return ConversationHandler.END

    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    elif text == "🔁 إعادة تشغيل البث":
        data = load_json(LAST_STREAMS_FILE).get(str(user_id))
        if not data:
            await update.message.reply_text("❌ لا يوجد بث سابق لإعادة تشغيله.")
            return ConversationHandler.END

        await update.message.reply_text("🔁 جاري إعادة تشغيل البث بدون انقطاع...")

        increment_daily_stream_count(user_id)

        # تشغيل البث الجديد
        threading.Thread(
            target=monitor_stream,
            args=(str(user_id), data["cmd"], user_id, is_subscribed(user_id)),
            daemon=True
        ).start()

        # إيقاف القديم بعد مهلة 10 ثواني
        def delayed_termination():
            old_proc = processes.get(str(user_id))
            if old_proc and old_proc.poll() is None:
                try:
                    old_proc.terminate()
                except:
                    pass
                processes.pop(str(user_id), None)

        threading.Timer(10, delayed_termination).start()
        return ConversationHandler.END

    else:
        await update.message.reply_text("اختر أمر من القائمة.")
        return ConversationHandler.END

async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "use_filter":
        context.user_data["use_filter"] = True
        await query.message.reply_text("✅ تم تفعيل الحماية من الكوبيرايت. الآن اختر نوع البث:")
        return SELECT_BROADCAST_TYPE

    context.user_data["broadcast_type"] = data
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
    user_id = update.effective_user.id
    link = context.user_data.get("m3u8")
    use_filter = context.user_data.get("use_filter", False)
    is_pro = is_subscribed(user_id)
    broadcast_type = context.user_data.get("broadcast_type")

    if broadcast_type == "live_fb":
        if not key.startswith("FB-"):
            await update.message.reply_text("❌ مفتاح غير صالح. يجب أن يبدأ بـ FB-")
            return ConversationHandler.END
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    elif broadcast_type == "live_ig":
        output = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"
    else:
        await update.message.reply_text("❌ نوع البث غير معروف.")
        return ConversationHandler.END

    vf = "eq=contrast=1.05:brightness=0.02:saturation=1.02,drawbox=x=0:y=0:w=iw:h=60:color=black@0.1:t=fill" if (use_filter or is_pro) else "null"
    af = "atempo=1.03,asetrate=44100*0.98" if (use_filter or is_pro) else "anull"

    if is_pro:
        cmd = ["ffmpeg", "-re", "-i", link, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-maxrate", "4500k",
               "-bufsize", "6000k", "-g", "50", "-r", "30", "-pix_fmt", "yuv420p",
               "-af", af, "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
               "-f", "flv", output]
    else:
        cmd = ["ffmpeg", "-re", "-i", link, "-vf", f"scale=720:-2,{vf}", "-c:v", "libx264", "-preset", "veryfast",
               "-b:v", "1500k", "-maxrate", "1800k", "-bufsize", "3000k", "-af", af, "-c:a", "aac", "-b:a", "96k",
               "-f", "flv", output]

    await update.message.reply_text("🚀 بدء البث الآن...")
    increment_daily_stream_count(user_id)
    tag = str(user_id)
    save_json(LAST_STREAMS_FILE, {**load_json(LAST_STREAMS_FILE), tag: {"cmd": cmd}})
    threading.Thread(target=monitor_stream, args=(tag, cmd, user_id, is_pro), daemon=True).start()
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    print("✅ البوت يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()