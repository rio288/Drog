import os
import json
import threading
import subprocess
from datetime import datetime, timedelta
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

TOKEN = os.getenv("TOKEN")  # ضع توكن البوت في متغير البيئة TOKEN
ADMINS = [8145101051]  # استبدل بمعرفات الأدمن
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# مراحل الـ ConversationHandler
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
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    if is_subscribed(user_id):
        return True, ""

    daily_seconds = user.get("daily_stream_seconds", 0)
    last_date_str = user.get("daily_stream_date")
    last_date = datetime.fromisoformat(last_date_str) if last_date_str else None
    now = datetime.now()

    if not last_date or last_date.date() < now.date():
        daily_seconds = 0  # إعادة تعيين كل يوم

    if daily_seconds >= 1800:  # 30 دقيقة = 1800 ثانية
        return False, "❌ وصلت الحد المجاني اليومي للبث (30 دقيقة). يرجى الاشتراك."

    return True, ""

def increment_daily_stream_time(user_id, seconds):
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
    proc = subprocess.Popen(cmd)
    processes[tag] = proc
    try:
        while proc.poll() is None:
            threading.Event().wait(5)
            increment_daily_stream_time(user_id, 5)
    except Exception:
        pass
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
        ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"],
    ]
    if is_admin(user.id):
        buttons.append(["➕ إضافة مشترك"])

    keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    text = (
        f"مرحباً!\nمعرفك: `{user.id}`\n"
        f"الاسم: {user.full_name}\n"
        f"الحالة: {status}\n\n"
        "اختر من القائمة:\n🎬 تجهيز البث\n⏹ إيقاف البث\n🔁 إعادة تشغيل البث\n📞 تواصل مع الدعم"
    )
    if is_admin(user.id):
        text += "\n➕ إضافة مشترك (خاص بالمسؤولين)"

    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "➕ إضافة مشترك":
        if not is_admin(user_id):
            await update.message.reply_text("❌ هذا الخيار خاص بالمسؤولين فقط.")
            return ConversationHandler.END
        await update.message.reply_text(
            "أرسل معرف المستخدم وعدد الأيام مفصولين بمسافة.\nمثال:\n`123456789 30`",
            parse_mode="Markdown",
        )
        return ADD_SUBSCRIBER

    elif text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Live FB", callback_data="live_fb"),
                    InlineKeyboardButton("Live IG", callback_data="live_ig"),
                ],
                [InlineKeyboardButton("Safeguard", callback_data="use_filter")],
            ]
        )
        await update.message.reply_text(
            "اختر نوع البث أو اختر *Filter* لتفعيل الحماية:",
            reply_markup=keyboard,
            parse_mode="Markdown",
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
            "سيتم تطبيق الحماية تلقائيًا أثناء البث.\n\n"
            "الآن اختر نوع البث:",
            parse_mode="Markdown",
        )
        return SELECT_BROADCAST_TYPE

    context.user_data["broadcast_type"] = data
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8 (ينتهي بـ .m3u8):")
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
    link = context.user_data.get("m3u8")
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

    # إعداد فلاتر الفيديو والصوت للحماية (تُطبق فقط عند تفعيل Filter أو للمشتركين)
    if use_filter or is_pro:
        vf_filters = ["setpts=PTS/1.02", "boxblur=2:1", "eq=brightness=0.06:saturation=1.2"]
        af_filters = ["asetrate=44100*1.1", "atempo=0.91"]
    else:
        vf_filters = []
        af_filters = []

    vf = ",".join(vf_filters) if vf_filters else "null"
    af = ",".join(af_filters) if af_filters else "anull"

    # جودة البث (720p لدعم الحد الأدنى)
    scale_filter = "scale=w=1280:h=720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"

    cmd = [
        "ffmpeg",
        "-re",
        "-i",
        link,
        "-vf",
        f"{scale_filter},{vf}" if vf_filters else scale_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-maxrate",
        "2500k",
        "-bufsize",
        "5120k",
        "-g",
        "50",
        "-r",
        "25",
        "-pix_fmt",
        "yuv420p",
        "-af",
        af,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-f",
        "flv",
        output,
    ]

    # تشغيل ffmpeg في Thread
    tag = str(user_id)
    if tag in processes:
        stop_stream_process(tag)
    threading.Thread(target=monitor_stream, args=(tag, cmd, user_id), daemon=True).start()

    await update.message.reply_text(
        "✅ تم بدء البث.\n"
        "اضغط ⏹ لإيقاف البث متى شئت."
    )
    return ConversationHandler.END

async def add_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        user_id_str, days_str = text.split()
        user_id = int(user_id_str)
        days = int(days_str)
        if days <= 0:
            raise ValueError()
    except:
        await update.message.reply_text(
            "❌ الخطأ في التنسيق.\n"
            "أرسل: معرف_المستخدم عدد_الأيام\n"
            "مثال:\n`123456789 30`",
            parse_mode="Markdown",
        )
        return ADD_SUBSCRIBER

    users = load_json(USERS_FILE)
    now = datetime.now()
    new_expire = now + timedelta(days=days)

    if str(user_id) in users:
        old_exp = users[str(user_id)].get("expires")
        if old_exp:
            old_exp_date = datetime.fromisoformat(old_exp)
            if old_exp_date > now:
                new_expire = old_exp_date + timedelta(days=days)

    users[str(user_id)] = {
        "expires": new_expire.isoformat(),
        "daily_stream_seconds": 0,
        "daily_stream_date": now.isoformat(),
    }
    save_json(USERS_FILE, users)
    await update.message.reply_text(
        f"✅ تم إضافة/تحديث الاشتراك للمستخدم `{user_id}` لمدة {days} يوم.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & (~filters.COMMAND), get_stream_key)],
            ADD_SUBSCRIBER: [MessageHandler(filters.TEXT & (~filters.COMMAND), add_subscriber)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("البوت شغال...")
    app.run_polling()

if __name__ == "__main__":
    main()