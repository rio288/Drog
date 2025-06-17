import os
import json
import threading
import subprocess
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, CallbackQueryHandler, filters
)

TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)
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
    buttons = [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة تشغيل البث", "📞 تواصل مع الدعم"]]
    if is_admin(user.id):
        buttons.append(["➕ إضافة مفتاح اشتراك"])
    keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text(
        f"مرحباً!\nمعرفك: `{user.id}`\nالاسم: {user.full_name}\nالحالة: {status}\n\n"
        "اختر من القائمة:", reply_markup=keyboard, parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    if text == "➕ إضافة مفتاح اشتراك" and is_admin(user_id):
        await update.message.reply_text(
            "أرسل بهذا الشكل:\n`user_id | 2025-07-01`", parse_mode="Markdown"
        )
        context.user_data["awaiting_subscribe_data"] = True
        return ADD_SUBSCRIBE
    if context.user_data.get("awaiting_subscribe_data"):
        try:
            uid, date = map(str.strip, text.split("|"))
            datetime.fromisoformat(date)
            users = load_json(USERS_FILE)
            users[uid] = {"expires": date}
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"✅ تم اشتراك {uid} حتى {date}")
        except:
            await update.message.reply_text("❌ صيغة خاطئة. استخدم `user_id | 2025-07-01`", parse_mode="Markdown")
        context.user_data["awaiting_subscribe_data"] = False
        return ConversationHandler.END
    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Live FB", callback_data="live_fb"),
             InlineKeyboardButton("Live IG", callback_data="live_ig")],
            [InlineKeyboardButton("protected", callback_data="use_filter")]
        ])
        await update.message.reply_text("اختر نوع البث أو اضغط *protected* لتفعيل الحماية:", reply_markup=kb, parse_mode="Markdown")
        return SELECT_BROADCAST_TYPE
    if text == "⏹ إيقاف البث":
        if str(user_id) in processes:
            stop_stream_process(str(user_id))
            await update.message.reply_text("✅ تم إيقاف البث.")
        else:
            await update.message.reply_text("❌ لا يوجد بث نشط.")
    elif text == "🔁 إعادة تشغيل البث":
        if str(user_id) in processes:
            stop_stream_process(str(user_id))
        await update.message.reply_text("تم توقيف البث، أعد التجهيز.")
    elif text == "📞 تواصل مع الدعم":
        await update.message.reply_text("راسلنا: @premuimuser12")
    else:
        await update.message.reply_text("❗ اختر من الأوامر.")
    return ConversationHandler.END

async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "use_filter":
        context.user_data["use_filter"] = True
        await query.message.reply_text("✅ تم تفعيل الحماية.\nاختر نوع البث:")
        return SELECT_BROADCAST_TYPE
    context.user_data["broadcast_type"] = data
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ رابط غير صحيح.")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    user_id = update.effective_user.id
    broadcast_type = context.user_data.get("broadcast_type")
    link = context.user_data.get("m3u8")
    is_pro = is_subscribed(user_id)
    use_filter = context.user_data.get("use_filter", False)

    if broadcast_type == "live_fb":
        if not key.startswith("FB-"):
            await update.message.reply_text("❌ مفتاح Facebook غير صالح.")
            return ConversationHandler.END
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    elif broadcast_type == "live_ig":
        output = f"rtmps://live-upload.instagram.com:443/rtmp/{key}"
    else:
        await update.message.reply_text("❌ نوع بث غير معروف.")
        return ConversationHandler.END

    # فلترة الفيديو والصوت للحماية
    if use_filter or is_pro:
        vf_filters = ["setpts=PTS/1.03", "eq=contrast=1.05:brightness=0.02", "boxblur=2:1"]
        af_filters = ["asetrate=44100*1.06", "atempo=0.94", "aecho=0.5:0.5:300:0.1"]
    else:
        vf_filters = []
        af_filters = []

    vf = ",".join(vf_filters) if vf_filters else "null"
    af = ",".join(af_filters) if af_filters else "anull"

    if is_pro:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", f"scale=1920:-2,{vf}",
            "-c:v", "libx264", "-preset", "veryfast", "-maxrate", "3000k", "-bufsize", "6000k",
            "-g", "50", "-r", "25", "-pix_fmt", "yuv420p",
            "-af", af, "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-f", "flv", output
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", f"scale=1280:-2,{vf}",
            "-c:v", "libx264", "-preset", "veryfast", "-maxrate", "1500k", "-bufsize", "2500k",
            "-af", af, "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "2",
            "-f", "flv", output
        ]

    await update.message.reply_text("✅ جاري بدء البث...")
    increment_daily_stream_count(user_id)
    tag = str(user_id)
    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        },
        fallbacks=[],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    print("✅ البوت جاهز...")
    app.run_polling()

if __name__ == "__main__":
    main()
