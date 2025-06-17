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

TOKEN = os.getenv("TOKEN")  # ضع توكن البوت هنا أو في متغير البيئة
ADMINS = [8145101051]  # استبدل بمعرفات المسؤولين
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# حالات الـ ConversationHandler
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

def monitor_stream(tag, cmd, context: ContextTypes.DEFAULT_TYPE, user_id: int, stream_name: str, is_trial: bool):
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
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                timers.pop(tag, None)

        timer = threading.Timer(600, stop_after_timeout)  # 10 دقائق تجربة مجانية
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
            ],
            [
                InlineKeyboardButton("🛡️ حماية ضد كوبيرايت", callback_data="use_filter")
            ]
        ])
        await update.message.reply_text(
            "اختر نوع البث أو اختر الحماية ضد كوبيرايت 🛡️:", 
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

    if data == "use_filter":
        if not is_subscribed(user_id):
            await query.message.reply_text("❌ أنت غير مشترك مميز، يرجى الاشتراك للوصول لهذه الخاصية.")
            return ConversationHandler.END
        context.user_data["use_filter"] = True
        await query.message.reply_text(
            "✅ تم تفعيل *الحماية من الكوبيرايت*\n"
            "سيتم تطبيق التعديلات التالية تلقائيًا:\n"
            "- تبطئة الفيديو 2%\n"
            "- تحسين الألوان\n"
            "- تمويه خفيف\n"
            "- ضوضاء للحماية\n\n"
            "الآن اختر نوع البث:",
            parse_mode="Markdown"
        )
        return SELECT_BROADCAST_TYPE

    context.user_data["broadcast_type"] = data
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_name = update.message.text.strip()
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    # تحقق من وجود بث بنفس الاسم نشط
    existing_tags = [key for key in processes if key.startswith(user_id_str + "_")]
    if f"{user_id_str}_{stream_name}" in existing_tags:
        await update.message.reply_text("❌ لديك بث بنفس الاسم يعمل حالياً، يرجى اختيار اسم آخر.")
        return STREAM_NAME

    context.user_data["stream_name"] = stream_name
    await update.message.reply_text("🔗 أرسل رابط M3U8 الخاص بالبث:")
    return M3U8_LINK

async def get_m3u8_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.startswith("http"):
        await update.message.reply_text("❌ الرابط غير صحيح، أرسل رابط يبدأ بـ http أو https.")
        return M3U8_LINK
    context.user_data["m3u8_link"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث (Stream Key):")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_key = update.message.text.strip()
    context.user_data["stream_key"] = stream_key

    user_id = update.effective_user.id
    user_id_str = str(user_id)
    stream_name = context.user_data.get("stream_name")
    m3u8_link = context.user_data.get("m3u8_link")
    broadcast_type = context.user_data.get("broadcast_type")
    use_filter = context.user_data.get("use_filter", False)

    tag = f"{user_id_str}_{stream_name}"
    if tag in processes:
        await update.message.reply_text("❌ هناك بث نشط بنفس الاسم. يرجى إيقافه أولاً.")
        return ConversationHandler.END

    # بناء أمر ffmpeg مع الحماية ضد كوبيرايت إذا تم التفعيل
    filter_complex = ""
    if use_filter:
        filter_complex = (
            "-filter_complex "
            "\"[0:v]setpts=1.02*PTS,eq=contrast=1.2:brightness=0.05:saturation=1.3,boxblur=2:1,noise=alls=20:allf=t+u[v]\" "
            "-map \"[v]\" -map 0:a?"
        )
    else:
        filter_complex = ""

    if broadcast_type == "live_fb":
        url = f"rtmp://live-api-s.facebook.com:80/rtmp/{stream_key}"
    elif broadcast_type == "live_ig":
        url = f"rtmp://live-upload.instagram.com:80/rtmp/{stream_key}"
    else:
        await update.message.reply_text("❌ خطأ في اختيار نوع البث.")
        return ConversationHandler.END

    # بناء أمر ffmpeg
    cmd = [
        "ffmpeg",
        "-re",
        "-i",
        m3u8_link,
    ]

    if use_filter:
        # نستخدم الفلاتر للحماية
        cmd += [
            "-filter_complex",
            "[0:v]setpts=1.02*PTS,eq=contrast=1.2:brightness=0.05:saturation=1.3,boxblur=2:1,noise=alls=20:allf=t+u[v]",
            "-map",
            "[v]",
            "-map",
            "0:a?",
        ]

    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-f",
        "flv",
        url,
    ]

    is_trial = not is_subscribed(user_id)
    allowed, msg = can_stream(user_id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END

    increment_daily_stream_count(user_id)
    await update.message.reply_text(f"🚀 بدء البث `{stream_name}` إلى {broadcast_type.replace('_', ' ').upper()}", parse_mode="Markdown")

    thread = threading.Thread(target=monitor_stream, args=(tag, cmd, context, user_id, stream_name, is_trial))
    thread.start()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],
        states={
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],

            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],

            STREAM_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_name)],

            M3U8_LINK: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_m3u8_link)],

            STREAM_KEY: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()