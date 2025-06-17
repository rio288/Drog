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

# -------- إعدادات أساسية -------------
TOKEN = os.getenv("TOKEN")  # ضع توكن بوتك في متغير البيئة TOKEN
ADMINS = [8145101051]       # أضف أيادٍ إدارية
DATA_FILE = "users_data.json"

# تحميل البيانات أو إنشاؤها
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {
        "users": {},        # هيكل المستخدمين
        "streams": {},      # هيكل البثوث {user_id: {stream_name: process_info}}
    }

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# -------- ثوابت وحالات -----------
(
    CHOOSING_BROADCAST_TYPE,
    ENTER_M3U8,
    ENTER_STREAM_KEY,
    ENTER_STREAM_NAME,
) = range(4)

# -------- مساعدات الاشتراك وحالة المستخدم -------------

def is_subscribed(user_id: int) -> bool:
    user = data["users"].get(str(user_id), {})
    sub_until = user.get("sub_until")
    if sub_until:
        return datetime.strptime(sub_until, "%Y-%m-%d") >= datetime.now()
    return False

def increment_daily_stream_count(user_id: int):
    user = data["users"].setdefault(str(user_id), {})
    today_str = datetime.now().strftime("%Y-%m-%d")
    if user.get("last_stream_date") != today_str:
        user["daily_stream_count"] = 0
        user["last_stream_date"] = today_str
    user["daily_stream_count"] = user.get("daily_stream_count", 0) + 1
    save_data()

def get_daily_stream_count(user_id: int) -> int:
    user = data["users"].get(str(user_id), {})
    today_str = datetime.now().strftime("%Y-%m-%d")
    if user.get("last_stream_date") != today_str:
        return 0
    return user.get("daily_stream_count", 0)

# -------- دالة تشغيل المونيتور لمراقبة ffmpeg -------------

def monitor_stream(tag: str, cmd: list):
    # تشغيل ffmpeg كعملية خارجية
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # تخزين العملية في data للبث المعني
    user_id, stream_name = tag.split(":", 1)
    if str(user_id) not in data["streams"]:
        data["streams"][str(user_id)] = {}
    data["streams"][str(user_id)][stream_name] = process
    save_data()

    # انتظر انتهاء البث
    process.wait()

    # عند الانتهاء أو التوقف، نحذف من data
    data["streams"][str(user_id)].pop(stream_name, None)
    if not data["streams"][str(user_id)]:
        data["streams"].pop(str(user_id))
    save_data()

# -------- أوامر بوت التيليغرام -------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "مرحبًا بك في بوت البث المباشر!\n\n"
        "يمكنك تشغيل بث مباشر عبر Facebook أو Instagram.\n"
        "للبدء، اكتب /stream\n"
        "لإدارة الاشتراك اكتب /subscribe\n"
        "لإيقاف بث معين اكتب /stop\n"
    )
    await update.message.reply_text(text)

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = data["users"].setdefault(str(user_id), {})
    # مثال: تمديد الاشتراك لمدة 7 أيام من اليوم
    user["sub_until"] = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    save_data()
    await update.message.reply_text("🎉 تم تفعيل الاشتراك لمدة 7 أيام!")

async def stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Facebook", "Instagram"], ["إلغاء"]]
    await update.message.reply_text(
        "اختر نوع البث:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return CHOOSING_BROADCAST_TYPE

async def choose_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.lower()
    if choice == "facebook":
        context.user_data["broadcast_type"] = "live_fb"
    elif choice == "instagram":
        context.user_data["broadcast_type"] = "live_ig"
    else:
        await update.message.reply_text("تم الإلغاء.")
        return ConversationHandler.END

    await update.message.reply_text("أرسل لي رابط m3u8 للبث (رابط الميديا):")
    return ENTER_M3U8

async def enter_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.startswith("http"):
        await update.message.reply_text("❌ الرابط غير صالح، حاول مرة أخرى.")
        return ENTER_M3U8
    context.user_data["m3u8"] = link
    await update.message.reply_text("أرسل لي مفتاح البث (Stream Key):")
    return ENTER_STREAM_KEY

async def enter_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    # تأكد من صلاحية المفتاح في حالة Facebook
    if context.user_data.get("broadcast_type") == "live_fb" and not key.startswith("FB-"):
        await update.message.reply_text("❌ مفتاح Facebook يجب أن يبدأ بـ FB-")
        return ENTER_STREAM_KEY

    context.user_data["stream_key"] = key
    await update.message.reply_text("أرسل اسم مميز للبث (مثلا: بث العائلة):")
    return ENTER_STREAM_NAME

async def enter_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_name = update.message.text.strip()
    user_id = update.effective_user.id

    # تحقق وجود نفس اسم البث
    if str(user_id) in data["streams"] and stream_name in data["streams"][str(user_id)]:
        await update.message.reply_text("❌ لديك بث بنفس الاسم شغّال، يرجى اختيار اسم آخر.")
        return ENTER_STREAM_NAME

    # تحقق من فترة التجربة لغير المشتركين (10 دقائق)
    if not is_subscribed(user_id):
        daily_count = get_daily_stream_count(user_id)
        if daily_count >= 1:
            await update.message.reply_text(
                "⏳ انتهت فترة التجربة اليومية. لتشغيل بث إضافي، يرجى الاشتراك."
            )
            return ConversationHandler.END

    context.user_data["stream_name"] = stream_name

    # ابدأ البث بفلاتر حماية متقدمة للمشتركين أو بدون فلتر للغير مشتركين
    is_pro = is_subscribed(user_id)
    use_filter = is_pro  # أو اضبط حسب رغبتك

    # إعداد رابط البث حسب المنصة
    broadcast_type = context.user_data["broadcast_type"]
    link = context.user_data["m3u8"]
    key = context.user_data["stream_key"]

    if broadcast_type == "live_fb":
        rtmp_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    else:  # live_ig
        rtmp_url = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"

    # إعداد فلاتر الحماية المتقدمة
    if use_filter:
        vf_filters = [
            "setpts=PTS/1.01",
            "boxblur=1:1",
            "eq=contrast=1.05:brightness=0.02:saturation=1.1",
            "noise=alls=5:allf=t+u"
        ]
        af_filters = [
            "asetrate=44100*1.02",
            "atempo=0.98",
            "acompressor=threshold=0.5:ratio=2:attack=200:release=1000",
            "volume=1.05",
            "aecho=0.8:0.88:60:0.4"
        ]
    else:
        vf_filters = []
        af_filters = []

    vf = ",".join(vf_filters) if vf_filters else None
    af = ",".join(af_filters) if af_filters else None

    # جودة الفيديو حسب الاشتراك (مثال)
    if is_pro:
        video_scale = "1920:1080"  # 1080p
        maxrate = "4000k"
        bufsize = "8000k"
    else:
        video_scale = "640:360"  # 360p للغير مشتركين
        maxrate = "1000k"
        bufsize = "2000k"

    cmd = [
        "ffmpeg", "-re", "-i", link,
    ]

    if vf:
        cmd += ["-vf", vf + f",scale={video_scale}"]
    else:
        cmd += ["-vf", f"scale={video_scale}"]

    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-maxrate", maxrate,
        "-bufsize", bufsize,
        "-g", "50",
        "-r", "25",
        "-pix_fmt", "yuv420p",
    ]

    if af:
        cmd += ["-af", af]

    cmd += [
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",
        "-f", "flv",
        rtmp_url
    ]

    # بدء البث في Thread
    tag = f"{user_id}:{stream_name}"
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    increment_daily_stream_count(user_id)

    await update.message.reply_text(f"✅ بدأ البث: {stream_name}\n\nيمكنك إيقافه بكتابة /stop")

    return ConversationHandler.END

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    streams = data["streams"].get(str(user_id), {})
    if not streams:
        await update.message.reply_text("ليس لديك بث مباشر شغّال.")
        return

    keyboard = [
        [InlineKeyboardButton(name, callback_data=name)]
        for name in streams.keys()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر البث الذي تريد إيقافه:", reply_markup=reply_markup)

async def stop_stream_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    stream_name = query.data

    streams = data["streams"].get(str(user_id), {})
    process = streams.get(stream_name)
    if process:
        process.terminate()
        await query.edit_message_text(f"✅ تم إيقاف البث: {stream_name}")
    else:
        await query.edit_message_text("❌ حدث خطأ، لم يتم العثور على البث.")

# ------------- بناء تطبيق التيليغرام -------------

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("stream", stream)],
        states={
            CHOOSING_BROADCAST_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_broadcast_type)],
            ENTER_M3U8: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_m3u8)],
            ENTER_STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_stream_key)],
            ENTER_STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_stream_name)],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CallbackQueryHandler(stop_stream_callback))
    application.add_handler(conv_handler)

    print("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
