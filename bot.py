import os
import json
import threading
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

TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
DATA_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# تعريف حالات المحادثة
SELECT_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE, STOP_STREAM_NAME = range(6)

processes = {}  # مفتاح = "user_id|stream_name" => قيمة = عملية ffmpeg

def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_admin(user_id):
    return user_id in ADMINS

def is_subscribed(user_id):
    data = load_data()
    user = data.get(str(user_id), {})
    expires = user.get("expires")
    if not expires:
        return False
    try:
        return datetime.fromisoformat(expires) > datetime.now()
    except:
        return False

def trial_time_left(user_id, stream_name):
    data = load_data()
    user = data.get(str(user_id), {})
    trials = user.get("trials", {})
    key = stream_name.lower()
    start_time_str = trials.get(key)
    if not start_time_str:
        return 600  # 10 دقائق
    start_time = datetime.fromisoformat(start_time_str)
    elapsed = (datetime.now() - start_time).total_seconds()
    left = 600 - elapsed
    return max(0, left)

def start_trial(user_id, stream_name):
    data = load_data()
    user = data.get(str(user_id), {})
    trials = user.get("trials", {})
    key = stream_name.lower()
    trials[key] = datetime.now().isoformat()
    user["trials"] = trials
    data[str(user_id)] = user
    save_data(data)

def can_stream(user_id, stream_name):
    if is_subscribed(user_id):
        return True, ""
    left = trial_time_left(user_id, stream_name)
    if left <= 0:
        return False, "⏰ انتهت فترة التجربة المجانية (10 دقائق) لهذا البث.\nيرجى الاشتراك للبث بشكل مستمر."
    return True, f"⏳ لديك {int(left // 60)} دقائق و {int(left % 60)} ثانية متبقية في فترة التجربة."

def stop_stream(user_id, stream_name):
    key = f"{user_id}|{stream_name.lower()}"
    proc = processes.get(key)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(key, None)
        return True
    return False

def run_stream(user_id, stream_name, m3u8, stream_key, broadcast_type, use_filter, is_pro):
    # إعداد رابط البث حسب نوع البث
    if broadcast_type == "live_fb":
        output_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{stream_key}"
    elif broadcast_type == "live_ig":
        output_url = f"rtmps://live-upload.instagram.com:443/rtmp/{stream_key}"
    else:
        return None

    # فلاتر الحماية (خفيفة) مع جودة 1080p
    vf_filters = [
        "scale=1920:1080",
        "setpts=PTS*1.01",
        "eq=contrast=1.05:brightness=0.02:saturation=1.1",
        "boxblur=1:1",
        "noise=alls=5:allf=t+u"
    ]
    af_filters = ["asetrate=44100*1.01", "atempo=0.99"]

    vf = ",".join(vf_filters) if (use_filter or is_pro) else "scale=1920:1080"
    af = ",".join(af_filters) if (use_filter or is_pro) else "anull"

    cmd = [
        "ffmpeg", "-re", "-i", m3u8,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast",
        "-maxrate", "3500k", "-bufsize", "7000k",
        "-g", "50", "-r", "25", "-pix_fmt", "yuv420p",
        "-af", af,
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-f", "flv",
        output_url
    ]

    key = f"{user_id}|{stream_name.lower()}"
    proc = subprocess.Popen(cmd)
    processes[key] = proc
    if not is_pro:
        start_trial(user_id, stream_name)
    proc.wait()
    processes.pop(key, None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"
    buttons = [
        ["🎬 تجهيز البث", "⏹ إيقاف بث"],
        ["📞 تواصل مع الدعم"],
    ]
    if is_admin(user.id):
        buttons.append(["➕ إضافة اشتراك"])
    keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    text = (
        f"مرحباً {user.full_name}!\n"
        f"معرفك: `{user.id}`\n"
        f"الحالة: {status}\n\n"
        "اختر من القائمة:"
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "➕ إضافة اشتراك" and is_admin(user_id):
        await update.message.reply_text(
            "أرسل بيانات الاشتراك بالشكل:\n`user_id | 2025-07-01`",
            parse_mode="Markdown"
        )
        context.user_data["awaiting_subscribe_data"] = True
        return ADD_SUBSCRIBE

    if context.user_data.get("awaiting_subscribe_data"):
        try:
            parts = text.split("|")
            target_id = parts[0].strip()
            expire_date = parts[1].strip()
            datetime.fromisoformat(expire_date)
            data = load_data()
            user = data.get(target_id, {})
            user["expires"] = expire_date
            data[target_id] = user
            save_data(data)
            await update.message.reply_text(f"✅ تم تحديث اشتراك المستخدم {target_id} حتى {expire_date}")
        except:
            await update.message.reply_text("❌ الصيغة خاطئة! استخدم: `user_id | 2025-07-01`", parse_mode="Markdown")
        context.user_data["awaiting_subscribe_data"] = False
        return ConversationHandler.END

    if text == "🎬 تجهيز البث":
        await update.message.reply_text(
            "اختر نوع البث:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Live Facebook", callback_data="live_fb"),
                 InlineKeyboardButton("Live Instagram", callback_data="live_ig")],
                [InlineKeyboardButton("تفعيل حماية (للمشتركين فقط)", callback_data="use_filter")]
            ])
        )
        return SELECT_TYPE

    if text == "⏹ إيقاف بث":
        await update.message.reply_text("أرسل اسم البث الذي تريد إيقافه:")
        return STOP_STREAM_NAME

    if text == "📞 تواصل مع الدعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    await update.message.reply_text("اختر أمر من القائمة.")
    return ConversationHandler.END

async def select_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "use_filter":
        if not is_subscribed(user_id):
            await query.message.reply_text("❌ فقط المشتركين يمكنهم تفعيل الحماية.")
            return ConversationHandler.END
        context.user_data["use_filter"] = True
        await query.message.reply_text("✅ تم تفعيل الحماية. الآن اختر نوع البث:")
        return SELECT_TYPE

    context.user_data["broadcast_type"] = data
    await query.message.reply_text("أرسل اسم البث (معرف مميز):")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_name = update.message.text.strip()
    context.user_data["stream_name"] = stream_name
    await update.message.reply_text("أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط يجب أن ينتهي بـ .m3u8")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("أرسل مفتاح البث:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    user_id = update.effective_user.id
    broadcast_type = context.user_data.get("broadcast_type")
    stream_name = context.user_data.get("stream_name")
    m3u8 = context.user_data.get("m3u8")
    use_filter = context.user_data.get("use_filter", False)
    pro = is_subscribed(user_id)

    if broadcast_type == "live_fb":
        if not key.startswith("FB-"):
            await update.message.reply_text("❌ مفتاح بث Facebook يجب أن يبدأ بـ FB-")
            return ConversationHandler.END
    elif broadcast_type == "live_ig":
        pass  # لا تحقق خاص لـ IG
    else:
        await update.message.reply_text("❌ نوع بث غير صحيح.")
        return ConversationHandler.END

    allowed, msg = can_stream(user_id, stream_name)
    if not allowed:
        await update.message.reply_text(msg)
        return ConversationHandler.END
    elif msg:
        await update.message.reply_text(msg)

    await update.message.reply_text("يتم الآن بدء البث...")

    stop_stream(user_id, stream_name)

    threading.Thread(
        target=run_stream,
        args=(user_id, stream_name, m3u8, key, broadcast_type, use_filter, pro),
        daemon=True
    ).start()

    return ConversationHandler.END

async def stop_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stream_name = update.message.text.strip()
    user_id = update.effective_user.id

    stopped = stop_stream(user_id, stream_name)
    if stopped:
        await update.message.reply_text(f"تم إيقاف البث '{stream_name}'.")
    else:
        await update.message.reply_text(f"لا يوجد بث باسم '{stream_name}' قيد التشغيل.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SELECT_TYPE: [CallbackQueryHandler(select_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            STOP_STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, stop_stream_name)],
        },
        fallbacks=[],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
