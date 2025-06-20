import os
import json
import threading
import subprocess
from datetime import datetime
from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes, CallbackQueryHandler
)

# ========================
# === إعدادات أساسية ===
# ========================

TOKEN = os.getenv("TOKEN")  # ضع توكن بوتك هنا أو في متغير البيئة
ADMINS = [8145101051]       # معرفات المشرفين المصرح لهم
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# --- مراحل المحادثة ---
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)

# --- تخزين عمليات البث لكل مستخدم (user_id: process) ---
processes = {}

# ==============================
# === دوال مساعدة للعمل مع JSON ===
# ==============================

def load_json(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ======================
# === تحقق من صلاحيات المستخدم ===
# ======================

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

def is_subscribed(user_id: int) -> bool:
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    expires = user.get("expires")
    if not expires:
        return False
    try:
        return datetime.fromisoformat(expires) > datetime.now()
    except Exception:
        return False

# =============================
# === إدارة حدود البث المجانية ===
# =============================

def can_stream(user_id: int) -> (bool, str):
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

def increment_daily_stream_count(user_id: int):
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

# ===================
# === إدارة البث (FFMPEG) ===
# ===================

def monitor_stream(user_tag: str, cmd: list):
    """تشغيل ffmpeg ومراقبة العملية"""
    proc = subprocess.Popen(cmd)
    processes[user_tag] = proc
    proc.wait()
    processes.pop(user_tag, None)

def stop_stream_process(user_tag: str):
    """إيقاف بث ffmpeg للمستخدم"""
    proc = processes.get(user_tag)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(user_tag, None)

# ======================
# === دوال التفاعل مع المستخدم ===
# ======================

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

    welcome_text = (
        f"مرحباً بك، {user.full_name}!\n"
        f"معرفك: `{user.id}`\n"
        f"حالة الاشتراك: {status}\n\n"
        "اختر أحد الخيارات من القائمة:"
    )
    await update.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    # -- إضافة مفتاح اشتراك (للادمن فقط) --
    if text == "➕ إضافة مفتاح اشتراك" and is_admin(user_id):
        await update.message.reply_text(
            "أرسل بيانات الاشتراك بهذا الشكل:\n`user_id | 2025-07-01`",
            parse_mode="Markdown"
        )
        context.user_data["awaiting_subscribe_data"] = True
        return ADD_SUBSCRIBE

    # -- استقبال بيانات الاشتراك وتخزينها --
    if context.user_data.get("awaiting_subscribe_data"):
        try:
            user_str, expire_str = map(str.strip, text.split("|"))
            datetime.fromisoformat(expire_str)  # تحقق من صحة التاريخ
            users = load_json(USERS_FILE)
            user_data = users.get(user_str, {})
            user_data["expires"] = expire_str
            users[user_str] = user_data
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"✅ تم تحديث اشتراك المستخدم {user_str} حتى {expire_str}")
        except Exception:
            await update.message.reply_text(
                "❌ خطأ في الصيغة. يرجى إرسال البيانات بالشكل:\n`user_id | 2025-07-01`",
                parse_mode="Markdown"
            )
        context.user_data["awaiting_subscribe_data"] = False
        return ConversationHandler.END

    # -- أوامر البث --
    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Live Facebook", callback_data="live_fb"),
             InlineKeyboardButton("Live Instagram", callback_data="live_ig")],
            [InlineKeyboardButton("تفعيل حماية الكوبيرايت", callback_data="use_filter")]
        ])
        await update.message.reply_text(
            "اختر نوع البث أو تفعيل الحماية من الكوبيرايت:",
            reply_markup=keyboard
        )
        return SELECT_BROADCAST_TYPE

    elif text == "⏹ إيقاف البث":
        if str(user_id) in processes:
            stop_stream_process(str(user_id))
            await update.message.reply_text("✅ تم إيقاف البث.")
        else:
            await update.message.reply_text("لا يوجد بث قيد التشغيل.")
        return ConversationHandler.END

    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    elif text == "🔁 إعادة تشغيل البث":
        if str(user_id) in processes:
            stop_stream_process(str(user_id))
        await update.message.reply_text("✅ يرجى تجهيز البث من جديد.")
        return ConversationHandler.END

    else:
        await update.message.reply_text("❌ يرجى اختيار أمر من القائمة.")
        return ConversationHandler.END

async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "use_filter":
        context.user_data["use_filter"] = True
        await query.message.reply_text(
            "✅ تم تفعيل حماية الكوبيرايت.\n"
            "- قتل الخورزميات بنسبة 100%\n"
            "- إخفاء روبوتات\n"
            "- تتبع لمنع الكشف\n\n"
            "الآن اختر نوع البث:"
        )
        return SELECT_BROADCAST_TYPE

    if data in ["live_fb", "live_ig"]:
        context.user_data["broadcast_type"] = data
        await query.message.reply_text("🔤 أرسل اسم البث:")
        return STREAM_NAME

    await query.message.reply_text("❌ خطأ في اختيار نوع البث.")
    return ConversationHandler.END

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8 (يجب أن ينتهي بـ .m3u8):")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط غير صالح، يجب أن ينتهي بـ .m3u8")
        return M3U8_LINK
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    user_id = update.effective_user.id
    broadcast_type = context.user_data.get("broadcast_type")
    link = context.user_data.get("m3u8")
    use_filter = context.user_data.get("use_filter", False)
    is_pro = is_subscribed(user_id)

    # تحديد عنوان الخروج حسب نوع البث
    if broadcast_type == "live_fb":
        if not key.startswith("FB-"):
            await update.message.reply_text("❌ مفتاح البث فيسبوك يجب أن يبدأ بـ 'FB-'")
            return ConversationHandler.END
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    elif broadcast_type == "live_ig":
        output = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"
    else:
        await update.message.reply_text("❌ خطأ في اختيار نوع البث.")
        return ConversationHandler.END

    # إعداد الفلاتر (حماية الكوبيرايت)
    vf_filters = []
    af_filters = []
    if use_filter or is_pro:
        vf_filters.extend(["setpts=PTS/1.02", "boxblur=2:1"])
        af_filters.extend(["asetrate=44100*1.1", "atempo=1.03"])

    vf = ",".join(vf_filters) if vf_filters else "null"
    af = ",".join(af_filters) if af_filters else "anull"

    # إعدادات جودة البث
    # البرو (المشتركين) يحصلون على 1080p بجودة عالية
    if is_pro:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", f"scale=1920:1080,{vf}",
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", "3000k", "-maxrate", "3500k", "-bufsize", "7000k",
            "-g", "50", "-r", "30", "-pix_fmt", "yuv420p",
            "-af", af,
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-f", "flv", output
        ]
    else:
        # للمستخدمين المجانيين جودة أقل 720p أو 480p حسب نوع البث
        if broadcast_type == "live_ig":
            cmd = [
                "ffmpeg", "-re", "-i", link,
                "-vf", f"scale=720:1280,{vf}",
                "-c:v", "libx264", "-preset", "veryfast",
                "-b:v", "1800k", "-maxrate", "2000k", "-bufsize", "3000k",
                "-af", af,
                "-c:a", "aac", "-b:a", "128k", "-f", "flv", output
            ]
        else:
            cmd = [
                "ffmpeg", "-re", "-i", link,
                "-vf", f"scale=854:-2,{vf}",
                "-c:v", "libx264", "-preset", "veryfast",
                "-b:v", "1000k", "-maxrate", "1200k", "-bufsize", "2000k",
                "-af", af,
                "-c:a", "aac", "-b:a", "96k", "-f", "flv", output
            ]

    await update.message.reply_text("🔄 جاري بدء البث...")

    increment_daily_stream_count(user_id)

    tag = str(user_id)
    # تشغيل ffmpeg في Thread منفصل حتى لا يحجب البوت
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    return ConversationHandler.END

# --- معالجة طلب إضافة اشتراك ---
async def add_subscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_subscribe_data"] = True
    return ConversationHandler.END

# ======================
# === نقطة البداية ===
# ======================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subscribe_handler)],
        },
        fallbacks=[],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("البوت يعمل...")

    app.run_polling()

if __name__ == "__main__":
    main()