import os
import json
import threading
import subprocess
from datetime import datetime
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]  # عدل حسب معرفك

USERS_FILE = "data/users.json"
STATE_FILE = "data/stream_state.json"
os.makedirs("data", exist_ok=True)

# حالات المحادثة
(
    SELECT_BROADCAST_TYPE,
    STREAM_NAME,
    M3U8_LINK,
    STREAM_KEY,
    ADD_SUBSCRIBE,
) = range(5)

processes = {}

def load_json(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
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
    last_time_str = user.get("last_stream_time")
    now = datetime.now()
    if not last_time_str:
        return True, ""
    last_time = datetime.fromisoformat(last_time_str)
    if last_time.date() < now.date():
        return True, ""
    duration = user.get("duration_minutes", 0)
    if duration >= 10:
        return False, "❌ لقد استهلكت 10 دقائق المجانية لهذا اليوم."
    return True, ""

def increment_usage(user_id, minutes):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    now = datetime.now()
    last_time_str = user.get("last_stream_time")
    last_time = datetime.fromisoformat(last_time_str) if last_time_str else None
    if not last_time or last_time.date() < now.date():
        user["duration_minutes"] = minutes
    else:
        user["duration_minutes"] = user.get("duration_minutes", 0) + minutes
    user["last_stream_time"] = now.isoformat()
    users[str(user_id)] = user
    save_json(USERS_FILE, users)

def monitor_stream(tag, cmd, user_id, is_pro):
    start_time = datetime.now()
    proc = subprocess.Popen(cmd)
    processes[tag] = proc
    save_json(STATE_FILE, {"user_id": user_id, "cmd": cmd})
    proc.wait()
    processes.pop(tag, None)
    # تحديث الاستخدام بعد انتهاء البث للمشتركين المجانيين فقط
    if not is_pro:
        elapsed = (datetime.now() - start_time).total_seconds() / 60
        increment_usage(user_id, int(elapsed))
    if os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except:
            pass

def stop_stream_process(tag):
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        processes.pop(tag, None)
    if os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"
    keyboard = [
        ["🎬 تجهيز البث", "⏹ إيقاف البث"],
        ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"]
    ]
    if is_admin(user.id):
        keyboard.append(["➕ إضافة مفتاح اشتراك"])
    await update.message.reply_text(
        f"مرحباً!\nمعرفك: `{user.id}`\nالاسم: {user.full_name}\nالحالة: {status}\n\n"
        "اختر من القائمة:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "➕ إضافة مفتاح اشتراك" and is_admin(user_id):
        await update.message.reply_text("أرسل بالشكل: `user_id | YYYY-MM-DD`", parse_mode="Markdown")
        return ADD_SUBSCRIBE

    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Live FB", callback_data="live_fb"),
                InlineKeyboardButton("Live IG", callback_data="live_ig")
            ],
            [InlineKeyboardButton("تفعيل الحماية (Protected)", callback_data="use_filter")]
        ])
        await update.message.reply_text(
            "اختر نوع البث أو *تفعيل الحماية* لتفعيل الفلاتر:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return SELECT_BROADCAST_TYPE

    elif text == "⏹ إيقاف البث":
        stop_stream_process(str(user_id))
        await update.message.reply_text("✅ تم إيقاف البث.")
        return ConversationHandler.END

    elif text == "🔁 إعادة تشغيل البث":
        state = load_json(STATE_FILE)
        if str(user_id) != str(state.get("user_id")):
            await update.message.reply_text("❌ لا يوجد بث سابق لإعادة تشغيله.")
            return ConversationHandler.END
        stop_stream_process(str(user_id))
        threading.Thread(target=monitor_stream, args=(str(user_id), state["cmd"], user_id, is_subscribed(user_id)), daemon=True).start()
        await update.message.reply_text("🔁 تم إعادة تشغيل البث بنجاح.")
        return ConversationHandler.END

    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    else:
        await update.message.reply_text("❗ اختر أمراً من القائمة.")
        return ConversationHandler.END

async def add_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        uid, date = map(str.strip, text.split("|"))
        datetime.fromisoformat(date)
        users = load_json(USERS_FILE)
        users[uid] = {"expires": date}
        save_json(USERS_FILE, users)
        await update.message.reply_text(f"✅ تم تحديث اشتراك المستخدم {uid} حتى {date}")
    except Exception:
        await update.message.reply_text("❌ خطأ في الصيغة. أرسل: `user_id | YYYY-MM-DD`", parse_mode="Markdown")
    return ConversationHandler.END

async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "use_filter":
        context.user_data["use_filter"] = True
        await query.message.reply_text("✅ تم تفعيل الحماية، اختر نوع البث:")
        return SELECT_BROADCAST_TYPE
    if query.data in ("live_fb", "live_ig"):
        context.user_data["broadcast_type"] = query.data
        await query.message.reply_text("🎥 أرسل اسم البث:")
        return STREAM_NAME
    await query.message.reply_text("❌ اختيار غير معروف.")
    return ConversationHandler.END

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
    m3u8 = context.user_data.get("m3u8")
    use_filter = context.user_data.get("use_filter", False)
    is_pro = is_subscribed(user_id)
    broadcast_type = context.user_data.get("broadcast_type")

    if broadcast_type == "live_fb":
        if not key.startswith("FB-"):
            await update.message.reply_text("❌ مفتاح فيسبوك غير صالح. يجب أن يبدأ بـ `FB-`")
            return ConversationHandler.END
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    elif broadcast_type == "live_ig":
        output = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"
    else:
        await update.message.reply_text("❌ خطأ في نوع البث.")
        return ConversationHandler.END

    # جودة الفيديو حسب الاشتراك
    if is_pro:
        scale_filter = "scale=1920:1080"  # 1080p
        maxrate = "5000k"
        bufsize = "10000k"
    else:
        scale_filter = "scale=854:480"  # 480p
        maxrate = "2500k"
        bufsize = "5120k"

    vf = scale_filter
    af = "anull"
    if use_filter or is_pro:
        vf = (
            f"hue=s=0.9,eq=contrast=1.05:brightness=0.02:saturation=1.02,"
            f"drawbox=x=0:y=0:w=iw:h=60:color=black@0.5:t=fill,"
            f"{vf}"
        )
        af = "asetrate=44100*0.8,atempo=1.25,asetrate=44100"

    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", m3u8,
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-maxrate", maxrate,
        "-bufsize", bufsize,
        "-c:a", "aac",
        "-b:a", "128k",
        "-f", "flv",
        output,
    ]

    # إيقاف أي بث سابق للمستخدم
    stop_stream_process(str(user_id))
    threading.Thread(
        target=monitor_stream,
        args=(str(user_id), ffmpeg_cmd, user_id, is_pro),
        daemon=True,
    ).start()

    await update.message.reply_text(
        f"✅ تم بدء البث على {broadcast_type.upper()} بجودة {'1080p' if is_pro else '480p'}"
    )
    return ConversationHandler.END

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],
        states={
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_subscribe)],
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_key)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == "__main__":
    main()