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
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

TOKEN = os.getenv("TOKEN")  # ضع توكن بوتك في متغير البيئة TOKEN
ADMINS = [8145101051]       # عدل حسب معرفات المسؤولين لديك
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# مراحل المحادثة
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)

processes = {}  # تخزين عمليات ffmpeg

# تحميل و حفظ بيانات المستخدمين
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

# تحقق اذا مستخدم ادمن
def is_admin(user_id):
    return user_id in ADMINS

# تحقق الاشتراك
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

# تحقق اذا يمكنه بدء بث (يومياً مجاني 1)
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

# تحديث عدد البث اليومي
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

# بدء عملية البث (ffmpeg)
def start_stream_process(tag, cmd):
    proc = subprocess.Popen(cmd)
    processes[tag] = proc
    proc.wait()
    processes.pop(tag, None)

# إيقاف البث
def stop_stream_process(tag):
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(tag, None)

# أمر /start
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

# معالجة الرسائل
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
        except:
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
                InlineKeyboardButton("Protected (تفعيل حماية ضد الكوبيرايت)", callback_data="use_filter")
            ]
        ])
        await update.message.reply_text(
            "اختر نوع البث أو اختر *Protected* لتفعيل الفلاتر:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return SELECT_BROADCAST_TYPE

    elif text == "⏹ إيقاف البث":
        tag = str(user_id)
        if tag in processes:
            stop_stream_process(tag)
            await update.message.reply_text("تم إيقاف البث.")
        else:
            await update.message.reply_text("لا يوجد بث قيد التشغيل حالياً.")
        return ConversationHandler.END

    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    elif text == "🔁 إعادة تشغيل البث":
        tag = str(user_id)
        if tag in processes:
            stop_stream_process(tag)
        await update.message.reply_text("يرجى إعادة تجهيز البث من جديد.")
        return ConversationHandler.END

    else:
        await update.message.reply_text("اختر أمر من القائمة.")
        return ConversationHandler.END

# اختيار نوع البث
async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "use_filter":
        context.user_data["use_filter"] = True
        await query.message.reply_text(
            "✅ تم تفعيل *الحماية من الكوبيرايت*.\n"
            "اختر منصة الدي تريد ابث عليها\n"
            "الآن اختر نوع البث:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Live FB", callback_data="live_fb")],
                [InlineKeyboardButton("Live IG", callback_data="live_ig")]
            ]),
            parse_mode="Markdown"
        )
        return SELECT_BROADCAST_TYPE

    context.user_data["broadcast_type"] = data
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

# استقبال اسم البث
async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK

# استقبال رابط M3U8
async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح. يجب أن ينتهي بـ .m3u8")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

# استقبال مفتاح البث وتشغيل ffmpeg
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

    # فلتر الفيديو والصوت مع تأخير تقريبي 5 ثواني للحماية من الكوبيرايت
    # ضبط setpts لتعديل توقيت الفيديو
    # ضبط asetrate و atempo لتعديل سرعة الصوت وتقليل التأخير الصوتي

    vf_filters = []
    af_filters = []

    if use_filter or is_pro:
        # نضيف تأخير 5 ثواني للفيديو (تقريباً)
        # setpts=PTS+5/TB تأخير 5 ثواني
        vf_filters.append("setpts=PTS+5/TB")
        # تأثير طفيف لتشويش لمنع الكوبيرايت
        vf_filters.append("boxblur=2:1")

        # الصوت: ضبط معدل العينة والسرعة لضبط التأخير وصوت طبيعي
        af_filters.append("adelay=5000|5000")  # تأخير صوت 5 ثواني
        af_filters.append("atempo=1.0")        # سرعة الصوت طبيعية

    vf = ",".join(vf_filters) if vf_filters else "null"
    af = ",".join(af_filters) if af_filters else "anull"

    cmd = [
        "ffmpeg",
        "-re",
        "-i", link,
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-maxrate", "2500k",
        "-bufsize", "12000k",  # زيادة البفر لزيادة الاستقرار والتأخير
        "-g", "50",
        "-c:a", "aac",
        "-b:a", "128k",
        "-f", "flv",
        output,
    ]

    tag = str(user_id)
    # إذا كان هناك بث سابق، أوقفه أولاً
    if tag in processes:
        stop_stream_process(tag)

    increment_daily_stream_count(user_id)

    await update.message.reply_text("⏳ يتم تشغيل البث الآن ... انتظر ثواني ...")

    # تشغيل ffmpeg في Thread منفصل حتى لا يعلق البوت
    thread = subprocess.Popen(cmd)
    processes[tag] = thread

    await update.message.reply_text("✅ تم تشغيل البث بنجاح!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("بوت يعمل ...")
    app.run_polling()

if __name__ == "__main__":
    main()