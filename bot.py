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
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)
processes = {}

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
    user_id = update.effective_user.id
    if str(user_id) not in load_json(USERS_FILE):
        users = load_json(USERS_FILE)
        users[str(user_id)] = {}
        save_json(USERS_FILE, users)
    await update.message.reply_text("👋 أهلاً بك! لاستخدام البوت، أرسل /stream للبدء أو /subscribe للاشتراك.")
    
async def stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    can, reason = can_stream(update.effective_user.id)
    if not can:
        await update.message.reply_text(reason)
        return ConversationHandler.END

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎥 Facebook", callback_data="facebook")],
        [InlineKeyboardButton("📷 Instagram", callback_data="instagram")]
    ])
    await update.message.reply_text("اختر نوع البث:", reply_markup=reply_markup)
    return SELECT_BROADCAST_TYPE

async def select_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["type"] = query.data
    await query.message.reply_text("📛 أرسل اسم للجلسة:")
    return STREAM_NAME

async def set_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["session_name"] = update.message.text.strip()
    await update.message.reply_text("🎞️ أرسل رابط M3U8:")
    return M3U8_LINK

async def set_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["m3u8"] = update.message.text.strip()
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

async def set_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_key"] = update.message.text.strip()
    session_name = context.user_data["session_name"]
    m3u8 = context.user_data["m3u8"]
    stream_key = context.user_data["stream_key"]
    platform = context.user_data["type"]

    rtmp_url = f"rtmp://live-api-s.facebook.com:80/rtmp/{stream_key}" if platform == "facebook" else f"rtmp://live-upload.instagram.com:80/rtmp/{stream_key}"

    video_filters = (
        "format=yuv420p,"
        "eq=brightness=0.02:saturation=1.4,"
        "noise=alls=20:allf=t+u,"
        "boxblur=2:1,"
        "scale='if(gte(t,5),1280,960)':'if(gte(t,5),720,540)',"
        "tblend=all_mode=difference,"
        "fps=29.97"
    )
    audio_filters = (
        "aecho=0.8:0.9:1000:0.3,"
        "asetrate=42777,"
        "atempo=1.03,"
        "highpass=f=200,"
        "lowpass=f=3000"
    )

    ffmpeg_cmd = [
        "ffmpeg",
        "-re", "-i", m3u8,
        "-vf", video_filters,
        "-af", audio_filters,
        "-c:v", "libx264", "-preset", "veryfast", "-maxrate", "3000k", "-bufsize", "6000k",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "flv", rtmp_url
    ]

    await update.message.reply_text("🚀 بدء البث...")

    tag = f"{update.effective_user.id}_{session_name}"
    threading.Thread(target=monitor_stream, args=(tag, ffmpeg_cmd), daemon=True).start()

    increment_daily_stream_count(update.effective_user.id)
    return ConversationHandler.END

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    for tag in list(processes.keys()):
        if str(user_id) in tag:
            stop_stream_process(tag)
            await update.message.reply_text("⛔ تم إيقاف البث.")
            return
    await update.message.reply_text("❌ لا يوجد بث نشط حاليًا.")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_json(USERS_FILE)
    user_id = str(update.effective_user.id)
    users[user_id] = {
        "expires": (datetime.now().replace(hour=23, minute=59) + timedelta(days=1)).isoformat(),
        "daily_stream_count": 0,
        "daily_stream_date": datetime.now().isoformat()
    }
    save_json(USERS_FILE, users)
    await update.message.reply_text("✅ تم تفعيل الاشتراك ليوم واحد.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("stream", stream)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast)],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_stream_key)],
        },
        fallbacks=[CommandHandler("cancel", start)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("subscribe", subscribe))

    app.run_polling()

if __name__ == "__main__":
    main()