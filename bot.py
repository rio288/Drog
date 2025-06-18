import os
import json
import threading
import subprocess
import time
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

TOKEN = os.getenv("TOKEN")
ADMINS = [8145101051]
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

# Conversation states
SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)

# FFmpeg processes tracking
stream_sessions = {}

def load_json(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_admin(user_id): return user_id in ADMINS

def is_subscribed(user_id):
    users = load_json(USERS_FILE)
    expires = users.get(str(user_id), {}).get("expires")
    try:
        return datetime.fromisoformat(expires) > datetime.now()
    except:
        return False

def can_stream(user_id):
    if is_subscribed(user_id): return True, ""
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    usage = user.get("daily_stream_count", 0)
    last_date = datetime.fromisoformat(user.get("daily_stream_date", "")) if user.get("daily_stream_date") else None
    if not last_date or last_date.date() < datetime.now().date():
        usage = 0
    if usage >= 1:
        return False, "❌ وصلت الحد المجاني اليومي."
    return True, ""

def increment_daily_stream_count(user_id):
    users = load_json(USERS_FILE)
    user = users.get(str(user_id), {})
    now = datetime.now()
    if user.get("daily_stream_date") != now.date().isoformat():
        user["daily_stream_count"] = 1
        user["daily_stream_date"] = now.date().isoformat()
    else:
        user["daily_stream_count"] = user.get("daily_stream_count", 0) + 1
    users[str(user_id)] = user
    save_json(USERS_FILE, users)

def build_ffmpeg_cmd(link, output, is_pro, use_filter, is_ig):
    vf = ["scale=1920:-2"] if is_pro else ["scale=854:-2"]
    af = []
    if use_filter or is_pro:
        vf += ["eq=contrast=1.05:brightness=0.02:saturation=1.02", "drawbox=x=0:y=0:w=iw:h=60:color=black@0.3:t=fill"]
        af += ["atempo=1.03", "asetrate=44100*0.98"]

    vf_str = ",".join(vf) if vf else "null"
    af_str = ",".join(af) if af else "anull"

    cmd = [
        "ffmpeg", "-re", "-i", link,
        "-vf", vf_str,
        "-c:v", "libx264", "-preset", "veryfast", "-maxrate", "2500k",
        "-bufsize", "5120k", "-g", "50", "-r", "25", "-pix_fmt", "yuv420p",
        "-af", af_str,
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-f", "flv", output
    ]

    if is_ig:
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,{vf_str}",
            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "1800k", "-maxrate", "2000k", "-bufsize", "3000k",
            "-af", af_str,
            "-c:a", "aac", "-b:a", "128k", "-f", "flv", "-rtbufsize", "1500M", output
        ]

    return cmd

def monitor_audio(tag, cmd, chat_id, context):
    while True:
        process = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        stream_sessions[tag] = {"process": process, "cmd": cmd, "chat_id": chat_id}
        last_audio = True

        def check_audio():
            while True:
                probe = subprocess.run([
                    "ffprobe", "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=avg_frame_rate",
                    "-of", "default=noprint_wrappers=1:nokey=1", cmd[3]
                ], capture_output=True, text=True)
                if "-inf" in probe.stdout or probe.returncode != 0:
                    process.terminate()
                    context.application.create_task(
                        context.bot.send_message(chat_id=chat_id, text="🔇 تم اكتشاف انقطاع الصوت، إعادة تشغيل البث...")
                    )
                    break
                time.sleep(60)

        checker_thread = threading.Thread(target=check_audio, daemon=True)
        checker_thread.start()
        process.wait()
        stream_sessions.pop(tag, None)
        break

def stop_stream(tag):
    if tag in stream_sessions:
        process = stream_sessions[tag]["process"]
        if process and process.poll() is None:
            process.terminate()
        stream_sessions.pop(tag, None)

# ==== Telegram Handlers ====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    buttons = [["🎬 تجهيز البث", "⏹ إيقاف البث"], ["🔁 إعادة التشغيل", "📞 دعم"]]
    if is_admin(user.id): buttons.append(["➕ إضافة اشتراك"])
    await update.message.reply_text(
        f"مرحباً {user.first_name}\nمعرفك: `{user.id}`\nالحالة: {'✅ مشترك' if is_subscribed(user.id) else '❌ غير مشترك'}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "➕ إضافة اشتراك" and is_admin(user_id):
        context.user_data["awaiting_subscribe_data"] = True
        await update.message.reply_text("أرسل: user_id | 2025-07-01")
        return ADD_SUBSCRIBE

    if context.user_data.get("awaiting_subscribe_data"):
        try:
            uid, date = [x.strip() for x in text.split("|")]
            datetime.fromisoformat(date)
            users = load_json(USERS_FILE)
            users[uid] = {"expires": date}
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"تم تفعيل الاشتراك لـ {uid} حتى {date}")
        except:
            await update.message.reply_text("❌ صيغة غير صحيحة.")
        context.user_data["awaiting_subscribe_data"] = False
        return ConversationHandler.END

    if text == "🎬 تجهيز البث":
        allowed, msg = can_stream(user_id)
        if not allowed:
            await update.message.reply_text(msg)
            return ConversationHandler.END
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Facebook", callback_data="fb"),
             InlineKeyboardButton("Instagram", callback_data="ig")],
            [InlineKeyboardButton("تفعيل الحماية", callback_data="use_filter")]
        ])
        await update.message.reply_text("اختر المنصة أو تفعيل الحماية:", reply_markup=keyboard)
        return SELECT_BROADCAST_TYPE

    if text == "⏹ إيقاف البث":
        stop_stream(str(user_id))
        await update.message.reply_text("تم إيقاف البث.")
        return ConversationHandler.END

    if text == "🔁 إعادة التشغيل":
        stop_stream(str(user_id))
        await update.message.reply_text("تمت إعادة التشغيل. أعد تجهيز البث.")
        return ConversationHandler.END

    if text == "📞 دعم":
        await update.message.reply_text("للتواصل: @premuimuser12")
        return ConversationHandler.END

    await update.message.reply_text("اختر خيار من القائمة.")
    return ConversationHandler.END

async def select_broadcast_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    if data == "use_filter":
        context.user_data["use_filter"] = True
        await query.message.reply_text("✅ تم تفعيل الحماية. الآن اختر نوع البث:")
        return SELECT_BROADCAST_TYPE
    context.user_data["broadcast_type"] = data
    await query.message.reply_text("🎥 أرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text
    await update.message.reply_text("🔗 أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ يجب أن ينتهي الرابط بـ .m3u8")
        return ConversationHandler.END
    context.user_data["m3u8"] = link
    await update.message.reply_text("🔑 أرسل مفتاح البث:")
    return STREAM_KEY

async def get_stream_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    data = context.user_data
    user_id = update.effective_user.id
    is_pro = is_subscribed(user_id)
    use_filter = data.get("use_filter", False)
    is_ig = data["broadcast_type"] == "ig"

    output = (
        f"rtmps://live-upload.instagram.com:443/rtmp/{key}" if is_ig else
        f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    )
    cmd = build_ffmpeg_cmd(data["m3u8"], output, is_pro, use_filter, is_ig)

    await update.message.reply_text("🚀 بدء البث...")
    increment_daily_stream_count(user_id)

    threading.Thread(target=monitor_audio, args=(str(user_id), cmd, update.effective_chat.id, context), daemon=True).start()

    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            STREAM_NAME: [MessageHandler(filters.TEXT, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT, get_stream_key)],
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT, handle_message)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("✅ البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()