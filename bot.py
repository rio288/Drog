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

TOKEN = os.getenv("TOKEN")  # ضع توكن بوتك هنا في متغير البيئة
ADMINS = [8145101051]  # استبدل بمعرفات الأدمن
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# حالات الحوار
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)

# تخزين العمليات الجارية
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

def monitor_stream(tag, cmd, context: ContextTypes.DEFAULT_TYPE, user_id: int, stream_name: str, is_trial: bool):
    proc = subprocess.Popen(cmd)
    processes[tag] = proc

    # مؤقت إيقاف البث التجريبي بعد 10 دقائق
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
                        parse_mode="Markdown"
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
            parse_mode="Markdown"
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
            await update.message.reply_text("❌ خطأ في الصيغة، حاول مرة أخرى بالشكل:\n`user_id | 2025-07-01`", parse_mode="Markdown")
        context.user_data["awaiting_subscribe_data"] = False
        return ConversationHandler.END

    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Live FB", callback_data="live_fb"),
                InlineKeyboardButton("Live IG", callback_data="live_ig")
            ]
        ])
        await update.message.reply_text(
            "اختر نوع البث:", 
            reply_markup=keyboard,
            parse_mode="Markdown"
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

    if data not in ("live_fb", "live_ig"):
        await query.message.reply_text("خطأ في اختيار نوع البث.")
        return ConversationHandler.END

    context.user_data["broadcast_type"] = data
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_name = update.message.text.strip()
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    existing_tags = [key for key in processes if key.startswith(user_id_str + "_")]
    for tag in existing_tags:
        if tag == f"{user_id_str}_{stream_name}":
            await update.message.reply_text("❌ لديك بث بالفعل بنفس الاسم، اختر اسم آخر.")
            return STREAM_NAME
    context.user_data["stream_name"] = stream_name
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح. يجب أن ينتهي بـ .m3u8")
        return M3U8_LINK
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    broadcast_type = context.user_data.get("broadcast_type")
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    link = context.user_data.get("m3u8")
    stream_name = context.user_data.get("stream_name")

    # تحقق من صحة المفتاح حسب نوع البث
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

    # هل المستخدم مشترك؟
    is_pro = is_subscribed(user_id)

    # تحقق إن المستخدم غير مشترك هل استهلك البث المجاني اليومي؟
    if not is_pro:
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END
        increment_daily_stream_count(user_id)

    # دالة تكوين أمر ffmpeg مع تحسينات صوت فقط
    cmd = [
        "ffmpeg",
        "-i", link,
        "-vf", "null",  # بدون تعديل فيديو
        "-af", "asetrate=44100*1.02,atempo=0.96,highpass=f=200,lowpass=f=3000,volume=0.95",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-max_muxing_queue_size", "1024",
        "-c:a", "aac",
        "-b:a", "128k",
        "-f", "flv",
        output
    ]

    tag = f"{user_id_str}_{stream_name}"

    # إيقاف أي بث بنفس الاسم موجود سابقاً
    stop_stream_process(tag)

    await update.message.reply_text(
        f"🔴 بدء البث: {stream_name}\n"
        f"نوع البث: {'Facebook Live' if broadcast_type == 'live_fb' else 'Instagram Live'}\n"
        f"فترة البث المجاني: 10 دقائق (للمستخدمين غير المشتركين)\n"
        f"اضغط ⏹ لإيقاف البث متى شئت."
    )

    # تشغيل ffmpeg في خيط منفصل (streaming)
    threading.Thread(
        target=monitor_stream,
        args=(tag, cmd, context, user_id, stream_name, not is_pro),
        daemon=True
    ).start()

    return ConversationHandler.END

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()