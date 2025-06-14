import os
import json
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

TOKEN = os.getenv("TOKEN")  # حط التوكن هنا أو في متغير بيئة
ADMINS = [8145101051]       # عدل رقم الأدمن هنا
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBER = range(5)
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
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"

    buttons = [
        ["🎬 تجهيز البث", "⏹ إيقاف البث"],
        ["🔁 إعادة تشغيل البث"],
        ["📞 تواصل مع الدعم"],
    ]

    if is_admin(user.id):
        buttons.append(["📊 تحليلات المشتركين", "➕ إضافة مشترك"])

    keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    text = (
        f"مرحباً!\nمعرفك: `{user.id}`\n"
        f"الاسم: {user.full_name}\n"
        f"الحالة: {status}\n\n"
        "اختر من القائمة:\n🎬 تجهيز البث\n⏹ إيقاف البث\n🔁 إعادة تشغيل البث\n📞 تواصل مع الدعم"
    )

    if is_admin(user.id):
        text += "\n📊 تحليلات المشتركين (للمسؤولين فقط)\n➕ إضافة مشترك (للمسؤولين فقط)"

    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Live FB عادي", callback_data="live_fb_no"),
             InlineKeyboardButton("Live FB محمي", callback_data="live_fb_yes")],
            [InlineKeyboardButton("Live IG عادي", callback_data="live_ig_no"),
             InlineKeyboardButton("Live IG محمي", callback_data="live_ig_yes")]
        ])
        await update.message.reply_text("اختر نوع البث:", reply_markup=keyboard)
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

    elif text == "📊 تحليلات المشتركين":
        if not is_admin(user_id):
            await update.message.reply_text("❌ هذا الأمر مخصص للمسؤولين فقط.")
            return ConversationHandler.END

        users = load_json(USERS_FILE)
        total_users = len(users)
        active_subs = sum(1 for u in users.values() if u.get("expires") and datetime.fromisoformat(u["expires"]) > datetime.now())
        today = datetime.now().date()
        daily_active = sum(1 for u in users.values() if u.get("daily_stream_date") and datetime.fromisoformat(u["daily_stream_date"]).date() == today)

        text = (
            f"📊 **تحليلات المشتركين:**\n\n"
            f"👥 إجمالي المستخدمين: {total_users}\n"
            f"✅ المشتركين النشطين: {active_subs}\n"
            f"🎬 المستخدمين اليوميين للبث: {daily_active}\n"
        )

        await update.message.reply_text(text, parse_mode="Markdown")
        return ConversationHandler.END

    elif text == "➕ إضافة مشترك":
        if not is_admin(user_id):
            await update.message.reply_text("❌ هذا الأمر مخصص للمسؤولين فقط.")
            return ConversationHandler.END
        await update.message.reply_text("📥 أرسل معرف المستخدم (ID) الذي تريد إضافته كمشترك (الاشتراك 7 أيام).")
        return ADD_SUBSCRIBER

    else:
        await update.message.reply_text("اختر أمر من القائمة.")
        return ConversationHandler.END

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ هذا الأمر مخصص للمسؤولين فقط.")
        return ConversationHandler.END

    if not text.isdigit():
        await update.message.reply_text("❌ يجب أن يكون المعرف رقماً فقط.")
        return ADD_SUBSCRIBER

    new_user_id = text
    users = load_json(USERS_FILE)

    expire_date = datetime.now() + timedelta(days=7)
    users[new_user_id] = {
        "expires": expire_date.isoformat(),
        "daily_stream_count": 0,
        "daily_stream_date": None
    }
    save_json(USERS_FILE, users)

    await update.message.reply_text(f"✅ تم إضافة المستخدم `{new_user_id}` كمشترك لمدة 7 أيام.", parse_mode="Markdown")

    return ConversationHandler.END

async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    context.user_data["broadcast_type"] = data

    await query.message.reply_text("✏️ الآن أرسل اسم البث (مثلاً: بث تجريبي).")
    return STREAM_NAME

async def stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ اسم البث لا يمكن أن يكون فارغاً.")
        return STREAM_NAME
    context.user_data["stream_name"] = name
    await update.message.reply_text("📡 أرسل رابط M3U8 للبث (مثلاً من سيرفر).")
    return M3U8_LINK

async def m3u8_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.startswith("http"):
        await update.message.reply_text("❌ رابط غير صالح.")
        return M3U8_LINK
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث (Stream Key).")
    return STREAM_KEY

async def stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    if not key:
        await update.message.reply_text("❌ مفتاح البث لا يمكن أن يكون فارغاً.")
        return STREAM_KEY

    context.user_data["stream_key"] = key

    user_id = update.effective_user.id
    broadcast_type = context.user_data.get("broadcast_type")
    m3u8_link = context.user_data.get("m3u8")
    stream_key = key

    # تحقق من صلاحية البث
    allowed, msg = can_stream(user_id)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END

    # أمر ffmpeg مع حماية الكوبيرايت للبث المحمي
    if broadcast_type == "live_fb_yes" or broadcast_type == "live_ig_yes":
        # حماية متقدمة بفلاتر صوت وفيديو معقدة
        ffmpeg_command = [
            "ffmpeg", "-i", m3u8_link,
            "-vf", ("hue=h=45:s=0.65,eq=contrast=1.3:brightness=0.08:saturation=0.7,"
                    "noise=alls=15:allf=t+u,format=yuv420p,rotate=PI/180*2*mod(t\\,360),"
                    "tblend=all_mode=difference,unsharp=5:5:0.8"),
            "-af", "asetrate=44100*1.05,atempo=0.95,aphaser,aresample=44100,volume=1.05,adelay=10|10",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv",
        ]
        if broadcast_type == "live_fb_yes":
            ffmpeg_command.append(f"rtmp://live-api.facebook.com/rtmp/{stream_key}")
        else:
            ffmpeg_command.append(f"rtmp://live-api.instagram.com/rtmp/{stream_key}")
    else:
        # بث عادي بدون حماية
        ffmpeg_command = [
            "ffmpeg", "-i", m3u8_link,
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "flv",
        ]
        if broadcast_type == "live_fb_no":
            ffmpeg_command.append(f"rtmp://live-api.facebook.com/rtmp/{stream_key}")
        else:
            ffmpeg_command.append(f"rtmp://live-api.instagram.com/rtmp/{stream_key}")

    increment_daily_stream_count(user_id)
    await update.message.reply_text("🔴 تم بدء البث، الرجاء الانتظار قليلاً...")
    # تشغيل ffmpeg في Thread منفصل
    threading.Thread(target=monitor_stream, args=(str(user_id), ffmpeg_command)).start()

    return ConversationHandler.END

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & (~filters.COMMAND), m3u8_link)],
            STREAM_KEY: [MessageHandler(filters.TEXT & (~filters.COMMAND), stream_key)],
            ADD_SUBSCRIBER: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_subscriber)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    print("بوت تيليجرام يعمل الآن...")
    application.run_polling()


if __name__ == "__main__":
    main()