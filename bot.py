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
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TOKEN")  # ضع توكن البوت في متغير البيئة TOKEN
ADMINS = [8145101051]  # استبدل بمعرفات المسؤولين
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE = os.path.join(DATA_DIR, "users.json")
SUBS_FILE = os.path.join(DATA_DIR, "subscriptions.json")

# حالات الحوار
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE, ADD_SUBSCRIBE_DAYS = range(6)

processes = {}  # تخزين عمليات البث: user_id -> subprocess.Popen

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

def stop_stream_process(user_id):
    proc = processes.get(str(user_id))
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(str(user_id), None)

def build_ffmpeg_cmd(m3u8, stream_key, quality, use_filter):
    # إعداد جودة البث
    if quality == "1080p":
        scale = "1920:1080"
        video_bitrate = "4500k"
    elif quality == "720p":
        scale = "1280:720"
        video_bitrate = "2500k"
    elif quality == "480p":
        scale = "854:480"
        video_bitrate = "1000k"
    else:
        scale = "1280:720"
        video_bitrate = "2500k"
    
    filter_str = f"-vf scale={scale}"
    if use_filter:
        filter_str += ",eq=contrast=1.2:brightness=0.05"  # مثال فلتر بسيط للحماية

    cmd = [
        "ffmpeg",
        "-re",
        "-i", m3u8,
        "-c:v", "libx264",
        "-b:v", video_bitrate,
        "-preset", "veryfast",
        "-maxrate", video_bitrate,
        "-bufsize", "2M",
        "-g", "50",
        "-c:a", "aac",
        "-b:a", "128k",
        "-vf", filter_str,
        "-f", "flv",
        stream_key
    ]
    return cmd

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

    # إضافة مفتاح الاشتراك - البداية
    if text == "➕ إضافة مفتاح اشتراك":
        if not is_admin(user_id):
            await update.message.reply_text("❌ أنت لست مسؤولاً.")
            return ConversationHandler.END
        await update.message.reply_text("يرجى إرسال مفتاح الاشتراك الجديد:")
        return ADD_SUBSCRIBE

    # أوامر بث وإيقاف وإعادة التشغيل والتواصل
    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Live Facebook", callback_data="live_fb"),
                InlineKeyboardButton("Live Instagram", callback_data="live_ig")
            ],
            [
                InlineKeyboardButton("تمكين فلتر الحماية", callback_data="use_filter_off"),
                InlineKeyboardButton("تعطيل فلتر الحماية", callback_data="use_filter_on"),
            ],
            [
                InlineKeyboardButton("1080p", callback_data="quality_1080p"),
                InlineKeyboardButton("720p", callback_data="quality_720p"),
                InlineKeyboardButton("480p", callback_data="quality_480p"),
            ],
        ])
        context.user_data["use_filter"] = False
        context.user_data["quality"] = "720p"
        await update.message.reply_text(
            "اختر نوع البث (Facebook أو Instagram)، ثم اختر جودة البث، ويمكنك تمكين أو تعطيل فلتر الحماية:",
            reply_markup=keyboard,
        )
        return SELECT_BROADCAST_TYPE

    elif text == "⏹ إيقاف البث":
        stop_stream_process(user_id)
        await update.message.reply_text("تم إيقاف البث.")
        return ConversationHandler.END

    elif text == "🔁 إعادة تشغيل البث":
        if str(user_id) not in context.user_data.get("last_stream_cmd", {}):
            await update.message.reply_text("❌ لم يتم تجهيز بث سابق لإعادة التشغيل.")
            return ConversationHandler.END
        # أوقف العملية القديمة إذا تعمل
        stop_stream_process(user_id)
        # أعد تشغيل البث بنفس الأمر السابق
        last_cmd = context.user_data["last_stream_cmd"][str(user_id)]
        proc = subprocess.Popen(last_cmd)
        processes[str(user_id)] = proc
        await update.message.reply_text("✅ تم إعادة تشغيل البث.")
        return ConversationHandler.END

    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    else:
        await update.message.reply_text("اختر أمر من القائمة.")
        return ConversationHandler.END

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # ضبط نوع البث
    if data in ("live_fb", "live_ig"):
        context.user_data["broadcast_type"] = data
        await query.message.reply_text("أرسل اسم البث (Stream Name):")
        return STREAM_NAME

    # تفعيل أو تعطيل الفلتر
    if data == "use_filter_on":
        context.user_data["use_filter"] = True
        await query.message.reply_text("✅ تم تفعيل فلتر الحماية.")
        return SELECT_BROADCAST_TYPE
    if data == "use_filter_off":
        context.user_data["use_filter"] = False
        await query.message.reply_text("❌ تم تعطيل فلتر الحماية.")
        return SELECT_BROADCAST_TYPE

    # اختيار الجودة
    if data.startswith("quality_"):
        q = data.split("_")[1]
        context.user_data["quality"] = q
        await query.message.reply_text(f"✅ تم اختيار جودة البث: {q}")
        return SELECT_BROADCAST_TYPE

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
    await update.message.reply_text("🔑 أرسل رابط أو مفتاح البث (Stream Key) كاملاً:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_key = update.message.text.strip()
    user_id = update.effective_user.id
    broadcast_type = context.user_data.get("broadcast_type")
    m3u8 = context.user_data.get("m3u8")
    use_filter = context.user_data.get("use_filter", False)
    quality = context.user_data.get("quality", "720p")

    # تأكيد بيانات
    await update.message.reply_text(
        f"جاري بدء البث...\nنوع البث: {broadcast_type}\nالجودة: {quality}\nالفلتر: {'مفعل' if use_filter else 'غير مفعل'}"
    )

    # بناء أمر ffmpeg
    cmd = build_ffmpeg_cmd(m3u8, stream_key, quality, use_filter)

    # إيقاف البث السابق إن وجد
    stop_stream_process(user_id)

    # بدء البث الجديد
    proc = subprocess.Popen(cmd)
    processes[str(user_id)] = proc

    # حفظ آخر أمر بث
    if "last_stream_cmd" not in context.user_data:
        context.user_data["last_stream_cmd"] = {}
    context.user_data["last_stream_cmd"][str(user_id)] = cmd

    # تحديث عدد مرات البث اليومي
    increment_daily_stream_count(user_id)

    await update.message.reply_text("✅ تم بدء البث بنجاح!")
    return ConversationHandler.END

async def add_subscribe_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # هذه الوظيفة للتعامل مع حالة إضافة مفتاح الاشتراك
    # سيتم إدارتها ضمن ConversationHandler
    pass  # التعامل في handle_message

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_subscribe_key)],
            ADD_SUBSCRIBE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_subscribe_days)],
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(callback_query_handler)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("Bot started...")
    app.run_polling()

# وظائف خاصة باضافة مفتاح الاشتراك:
async def handle_add_subscribe_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    context.user_data["new_sub_key"] = key
    await update.message.reply_text("يرجى إرسال عدد الأيام لهذا المفتاح:")
    return ADD_SUBSCRIBE_DAYS

async def handle_add_subscribe_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح لعدد الأيام.")
        return ADD_SUBSCRIBE_DAYS

    key = context.user_data.get("new_sub_key")
    if not key:
        await update.message.reply_text("❌ حدث خطأ. يرجى المحاولة مجدداً.")
        return ConversationHandler.END

    subs = load_json(SUBS_FILE)
    subs[key] = days
    save_json(SUBS_FILE, subs)

    await update.message.reply_text(f"✅ تم إضافة مفتاح الاشتراك '{key}' لمدة {days} يوم.")
    context.user_data.pop("new_sub_key", None)
    return ConversationHandler.END

if __name__ == "__main__":
    main()