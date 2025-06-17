import os
import json
import subprocess
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TOKEN")  # ضع توكن البوت في متغير البيئة TOKEN
ADMINS = [8145101051]  # استبدل بمعرفات المسؤولين
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)

processes = {}  # لتخزين عمليات ffmpeg


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


def monitor_stream(tag, cmd):
    os.makedirs("logs", exist_ok=True)
    with open(f"logs/{tag}.log", "w") as logfile:
        proc = subprocess.Popen(cmd, stdout=logfile, stderr=logfile)
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
    expire = users.get(str(user.id), {}).get("expires", "غير محدد")
    status = f"مشترك حتى {expire}" if is_subscribed(user.id) else "غير مشترك ❌"

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
            parse_mode="Markdown"
        )
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
            [
                InlineKeyboardButton("تفعيل حماية الكوبيرايت", callback_data="use_filter")
            ]
        ])
        await update.message.reply_text(
            "اختر نوع البث أو اختر *تفعيل حماية الكوبيرايت* لتفعيل الفلاتر:", 
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return SELECT_BROADCAST_TYPE

    elif text == "⏹ إيقاف البث":
        if str(user_id) in processes:
            stop_stream_process(str(user_id))
            await update.message.reply_text("تم إيقاف البث.")
        else:
            await update.message.reply_text("لا يوجد بث قيد التشغيل حالياً.")
        return ConversationHandler.END

    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    elif text == "🔁 إعادة تشغيل البث":
        if str(user_id) in processes:
            stop_stream_process(str(user_id))
        await update.message.reply_text("يرجى إعادة تجهيز البث من جديد.")
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
        await query.message.reply_text(
            "✅ تم تفعيل *الحماية من الكوبيرايت*\n"
            "سيتم تطبيق التعديلات تلقائيًا.\n"
            "الآن اختر نوع البث:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Live FB", callback_data="live_fb"),
                    InlineKeyboardButton("Live IG", callback_data="live_ig")
                ]
            ])
        )
        return SELECT_BROADCAST_TYPE

    if data in ("live_fb", "live_ig"):
        context.user_data["broadcast_type"] = data
        await query.message.reply_text("🎥 أرسل اسم البث:")
        return STREAM_NAME

    await query.message.reply_text("❌ اختيار غير صالح.")
    return ConversationHandler.END


async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK


async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح. يجب أن ينتهي بـ .m3u8")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY


async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    broadcast_type = context.user_data.get("broadcast_type")
    user_id = update.effective_user.id
    m3u8_link = context.user_data.get("m3u8")
    use_filter = context.user_data.get("use_filter", False)
    is_pro = is_subscribed(user_id)

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

    # بناء فلترات الفيديو
    video_filters = [
        "format=yuv420p",
        "eq=brightness=0.02:saturation=1.4",
        "noise=alls=20:allf=t+u",
        "boxblur=2:1",
        "scale='if(gte(t,5),1280,960)':'if(gte(t,5),720,540)'",
        "tblend=all_mode=difference",
        "fps=29.97"
    ]

    # بناء فلترات الصوت
    audio_filters = [
        "aecho=0.8:0.9:1000:0.3",
        "asetrate=44100*0.97",
        "atempo=1.03",
        "highpass=f=200",
        "lowpass=f=3000"
    ]

    # إذا المستخدم مش مشترك وطلب الحماية، طبق الفلاتر، أو لو مش مشترك، ما تسمح إلا ببث واحد يومي
    if use_filter or is_pro:
        vf_filter = ",".join(video_filters)
        af_filter = ",".join(audio_filters)
    else:
        vf_filter = None
        af_filter = None

    # بناء أمر ffmpeg
    cmd = [
        "ffmpeg",
        "-re",
        "-i", m3u8_link,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-maxrate", "3000k",
        "-bufsize", "6000k",
        "-pix_fmt", "yuv420p",
        "-g", "50",
        "-c:a", "aac",
        "-b:a", "160k",
        "-ar", "44100",
        "-f", "flv"
    ]

    if vf_filter:
        cmd.extend(["-vf", vf_filter])
    if af_filter:
        cmd.extend(["-af", af_filter])

    cmd.append(output)

    # إيقاف بث سابق إن وجد
    if str(user_id) in processes:
        stop_stream_process(str(user_id))

    increment_daily_stream_count(user_id)
    await update.message.reply_text(f"⏳ بدأ البث...\n\n{cmd}")

    # تشغيل البث في عملية منفصلة بدون انتظار
    import threading
    threading.Thread(target=monitor_stream, args=(str(user_id), cmd), daemon=True).start()

    await update.message.reply_text("✅ تم تشغيل البث. لإيقاف البث اضغط ⏹ إيقاف البث من القائمة.")
    return ConversationHandler.END


async def add_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "|" not in text:
        await update.message.reply_text("❌ الصيغة غير صحيحة. استخدم: user_id | 2025-07-01")
        return ConversationHandler.END
    user_id_str, date_str = [x.strip() for x in text.split("|", 1)]
    try:
        user_id = int(user_id_str)
        expire_date = datetime.fromisoformat(date_str)
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في الصيغة: {e}")
        return ConversationHandler.END

    users = load_json(USERS_FILE)
    users[str(user_id)] = {
        "expires": expire_date.isoformat(),
        "daily_stream_count": 0,
        "daily_stream_date": None
    }
    save_json(USERS_FILE, users)
    await update.message.reply_text(f"✅ تم إضافة اشتراك للمستخدم {user_id} حتى {expire_date.date()}")
    return ConversationHandler.END


def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subscribe)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    application.run_polling()


if __name__ == "__main__":
    main()