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
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

TOKEN = os.getenv("TOKEN")  # حط توكن البوت في متغير البيئة TOKEN
ADMINS = [8145101051]  # استبدل بمعرفات المسؤولين

USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

(
    SELECT_BROADCAST_TYPE,
    STREAM_NAME,
    M3U8_LINK,
    STREAM_KEY,
    ADD_SUBSCRIBE,
) = range(5)

processes = {}
timers = {}


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


def monitor_stream(
    tag, cmd, context: ContextTypes.DEFAULT_TYPE, user_id: int, stream_name: str, is_trial: bool
):
    proc = subprocess.Popen(cmd)
    processes[tag] = proc

    if is_trial:

        def stop_after_timeout():
            if tag in processes:
                proc = processes[tag]
                if proc.poll() is None:
                    proc.terminate()
                    processes.pop(tag, None)
                try:
                    context.bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ انتهت فترة التجربة للبث `{stream_name}`.\nيرجى الاشتراك للاستمرار.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
                timers.pop(tag, None)

        timer = threading.Timer(600, stop_after_timeout)
        timers[tag] = timer
        timer.start()

    proc.wait()
    processes.pop(tag, None)
    if tag in timers:
        timers[tag].cancel()
        timers.pop(tag, None)


def stop_stream_process(tag):
    if tag in timers:
        timers[tag].cancel()
        timers.pop(tag, None)
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        proc.terminate()
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
            "أرسل بيانات الاشتراك بهذا الشكل:\n`user_id | 2025-07-01`\n"
            "أي بمعنى: معرف المستخدم ثم | ثم تاريخ انتهاء الاشتراك (YYYY-MM-DD)",
            parse_mode="Markdown",
        )
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
        except Exception:
            await update.message.reply_text(
                "❌ خطأ في الصيغة، حاول مرة أخرى بالشكل:\n`user_id | 2025-07-01`", parse_mode="Markdown"
            )
        context.user_data["awaiting_subscribe_data"] = False
        return ConversationHandler.END

    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Live FB عادي", callback_data="live_fb"),
                    InlineKeyboardButton("Live FB مع تعديل المصدر", callback_data="live_fb_modified"),
                    InlineKeyboardButton("Live IG", callback_data="live_ig"),
                ],
            ]
        )
        await update.message.reply_text(
            "اختر نوع البث:", reply_markup=keyboard, parse_mode="Markdown"
        )
        return SELECT_BROADCAST_TYPE

    elif text == "⏹ إيقاف البث":
        user_id_str = str(user_id)
        keys_to_stop = [key for key in processes if key.startswith(user_id_str + "_")]
        for key in keys_to_stop:
            stop_stream_process(key)
        await update.message.reply_text("تم إيقاف جميع البثوث الخاصة بك.")
        return ConversationHandler.END

    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    elif text == "🔁 إعادة تشغيل البث":
        user_id_str = str(user_id)
        keys_to_stop = [key for key in processes if key.startswith(user_id_str + "_")]
        for key in keys_to_stop:
            stop_stream_process(key)
        await update.message.reply_text("يرجى إعادة تجهيز البث من جديد.")
        return ConversationHandler.END

    else:
        await update.message.reply_text("اختر أمر من القائمة.")
        return ConversationHandler.END


async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    context.user_data["broadcast_type"] = data
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME


async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_name = update.message.text.strip()
    context.user_data["stream_name"] = stream_name
    await update.message.reply_text("📡 أرسل رابط M3U8 للبث:")
    return M3U8_LINK


async def get_m3u8_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m3u8 = update.message.text.strip()
    context.user_data["m3u8"] = m3u8
    await update.message.reply_text("🔑 أرسل مفتاح البث (Stream Key):")
    return STREAM_KEY


async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_key = update.message.text.strip()
    context.user_data["stream_key"] = stream_key
    user_id = update.effective_user.id
    user_id_str = str(user_id)

    # نبدأ تشغيل البث بعد تجميع البيانات
    broadcast_type = context.user_data.get("broadcast_type")
    stream_name = context.user_data.get("stream_name")
    m3u8 = context.user_data.get("m3u8")
    key = context.user_data.get("stream_key")

    allowed, msg = can_stream(user_id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END

    is_trial = not is_subscribed(user_id)

    tag = f"{user_id_str}_{stream_name.replace(' ', '_')}"
    # إذا بث يعمل سابقاً بنفس الاسم نوقفه
    if tag in processes:
        stop_stream_process(tag)

    # نجهز أمر ffmpeg حسب نوع البث
    # في حالة live_fb_modified نضيف فلتر حماية لتغيير الفيديو
    if broadcast_type == "live_fb":
        # بث فيسبوك عادي
        rtmp_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
        cmd = [
            "ffmpeg",
            "-re",
            "-i",
            m3u8,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-f",
            "flv",
            rtmp_url,
        ]
    elif broadcast_type == "live_fb_modified":
        # بث فيسبوك مع فلتر حماية لتجنب الكوبيرايت
        # تعديل بسيط: تبطئة الفيديو 1.02x + ضوضاء + تعديل ألوان
        rtmp_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
        cmd = [
            "ffmpeg",
            "-re",
            "-i",
            m3u8,
            "-vf",
            "setpts=PTS/1.02,noise=alls=10:allf=t+u,hue=s=0.9",
            "-c:a",
            "aac",
            "-f",
            "flv",
            rtmp_url,
        ]
    elif broadcast_type == "live_ig":
        # بث انستجرام
        rtmp_url = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"
        cmd = [
            "ffmpeg",
            "-re",
            "-i",
            m3u8,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-f",
            "flv",
            rtmp_url,
        ]
    else:
        await update.message.reply_text("خطأ في اختيار نوع البث.")
        return ConversationHandler.END

    # تشغيل البث في Thread
    threading.Thread(target=monitor_stream, args=(tag, cmd, context, user_id, stream_name, is_trial), daemon=True).start()

    # تحديث عدد البثوث المجانية
    if is_trial:
        increment_daily_stream_count(user_id)

    await update.message.reply_text(f"✅ بدأ البث: {stream_name}\nنوع البث: {broadcast_type.replace('_', ' ')}")
    return ConversationHandler.END


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],
        states={
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_m3u8_link)],
            STREAM_KEY: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_key)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    print("بوت يعمل...")
    app.run_polling()


if __name__ == "__main__":
    main()