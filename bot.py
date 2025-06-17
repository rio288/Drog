import os
import json
import threading
import subprocess
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, CallbackQueryHandler, filters
)

# إعدادات البوت
TOKEN = os.getenv("TOKEN")  # ضع توكن البوت في متغير البيئة TOKEN
ADMINS = [8145101051]  # ضع معرفات الأدمن هنا
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# حالات المحادثة
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK = range(3)

# لتخزين عمليات البث والمهام المؤقتة
processes = {}
timers = {}

# دوال مساعدة لتحميل وحفظ البيانات
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

def stop_stream_process(tag):
    if tag in timers:
        timers[tag].cancel()
        timers.pop(tag)
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(tag)

def build_ffmpeg_command(m3u8_url, rtmp_url, stream_key, use_filter):
    # نص شفاف جداً يغطي الشاشة (شفافية 0.01)
    watermark_filter = (
        "drawtext=text='1234567890':fontcolor=white@0.01:fontsize=72:x=w*t/6:y=h/2:box=0"
    )

    if use_filter:
        filter_complex = (
            f"setpts=PTS/0.98,eq=contrast=1.2:brightness=0.05,"
            f"gblur=sigma=1,noise=alls=10:allf=t+u,{watermark_filter}"
        )
    else:
        filter_complex = watermark_filter

    cmd = [
        "ffmpeg", "-re", "-i", m3u8_url,
        "-vf", filter_complex,
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "2500k",
        "-c:a", "aac", "-b:a", "128k", "-f", "flv",
        f"{rtmp_url}/{stream_key}"
    ]
    return cmd

# أوامر البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"
    buttons = [
        ["🎬 تجهيز البث", "⏹ إيقاف البث"],
        ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"]
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
            parse_mode="Markdown"
        )
        context.user_data["awaiting_subscribe_data"] = True
        return ConversationHandler.END

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
            [InlineKeyboardButton("Live Facebook", callback_data="live_fb"),
             InlineKeyboardButton("Live Instagram", callback_data="live_ig")],
            [InlineKeyboardButton("حماية كوبيرايت (للمشتركين فقط)", callback_data="use_filter")]
        ])
        await update.message.reply_text(
            "اختر نوع البث أو الحماية:",
            reply_markup=keyboard
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
        await query.message.reply_text("✅ تم تفعيل حماية الكوبيرايت.\nالآن أرسل اسم البث:")
        return STREAM_NAME

    if data in ("live_fb", "live_ig"):
        context.user_data["broadcast_type"] = data
        context.user_data["use_filter"] = False
        await query.message.reply_text("🎥 أرسل اسم البث:")
        return STREAM_NAME

    await query.message.reply_text("خطأ في الاختيار.")
    return ConversationHandler.END

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

async def get_m3u8_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m3u8_url = update.message.text.strip()
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    stream_name = context.user_data.get("stream_name")
    broadcast_type = context.user_data.get("broadcast_type")
    use_filter = context.user_data.get("use_filter", False)

    # التحقق من صلاحية البث
    allowed, msg = can_stream(user_id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END

    tag = f"{user_id_str}_{stream_name}"
    if tag in processes:
        await update.message.reply_text("❌ لديك بث شغال بنفس الاسم.")
        return ConversationHandler.END

    # تعيين روابط البث ومفاتيحها
    if broadcast_type == "live_fb":
        stream_key = f"{stream_name}_fb_key"
        rtmp_url = "rtmp://live.facebook.com/live"
    else:
        stream_key = f"{stream_name}_ig_key"
        rtmp_url = "rtmp://live.instagram.com/live"

    cmd = build_ffmpeg_command(m3u8_url, rtmp_url, stream_key, use_filter)

    proc = subprocess.Popen(cmd)
    processes[tag] = proc

    if not is_subscribed(user_id):
        increment_daily_stream_count(user_id)

        # مؤقت لإيقاف البث بعد 10 دقائق للمجانيين
        def stop_after_10min():
            if tag in processes:
                p = processes[tag]
                if p.poll() is None:
                    p.terminate()
                    processes.pop(tag, None)
                try:
                    context.bot.send_message(chat_id=user_id,
                        text=f"⏰ انتهت فترة التجربة للبث `{stream_name}`.\nيرجى الاشتراك للاستمرار.",
                        parse_mode="Markdown"
                    )
                except:
                    pass
                timers.pop(tag, None)

        timer = threading.Timer(600, stop_after_10min)
        timers[tag] = timer
        timer.start()

    await update.message.reply_text(f"✅ بدأ البث `{stream_name}` بنجاح.")
    return ConversationHandler.END

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    keys_to_stop = [key for key in processes if key.startswith(user_id_str + "_")]
    for key in keys_to_stop:
        stop_stream_process(key)
    await update.message.reply_text("تم إيقاف جميع البثوث الخاصة بك.")

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8_link)],
        },
        fallbacks=[CommandHandler("stop", stop_command)],
        allow_reentry=True
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("stop", stop_command))

    print("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()