import os
import json
import threading
import subprocess
import time
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

TOKEN = os.getenv("TOKEN")  # ضع توكن البوت في متغير البيئة TOKEN
ADMINS = [8145101051]  # استبدل بمعرفات المسؤولين
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

SELECT_BROADCAST_TYPE, STREAM_NAME, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(5)

processes = {}  # تخزين عمليات ffmpeg { user_id : Popen }
last_cmds = {}  # تخزين آخر أوامر ffmpeg لكل مستخدم { user_id : [cmd] }

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
    last_cmds.pop(tag, None)  # احذف آخر أمر عند انتهاء البث

def stop_stream_process(tag):
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(tag, None)
        last_cmds.pop(tag, None)

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

    if text == "🔁 إعادة تشغيل البث":
        tag = str(user_id)
        if tag not in last_cmds:
            await update.message.reply_text("⚠️ لا يوجد بث جاري لإعادة تشغيله.")
            return ConversationHandler.END

        # إيقاف البث الحالي قبل إعادة تشغيله فوراً
        stop_stream_process(tag)
        await update.message.reply_text("⏹ تم إيقاف البث الحالي، جاري إعادة التشغيل...")

        # نعيد تشغيل نفس الأمر
        cmd = last_cmds[tag]
        threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()
        await update.message.reply_text("✅ تم إعادة تشغيل البث 🔁")
        return ConversationHandler.END

    # باقي الكود مثل إضافة مفتاح اشتراك وتجهيز البث وإيقاف البث وغيرها
    # ...

    # عند تجهيز البث:
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
                InlineKeyboardButton("protected", callback_data="use_filter")
            ]
        ])
        await update.message.reply_text(
            "اختر نوع البث أو اختر *protected* لتفعيل الفلاتر:", 
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
            "الآن اختر نوع البث:",
            parse_mode="Markdown"
        )
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

    # إعداد فلاتر الفيديو والصوت بناء على الحماية أو الاشتراك المميز
    if use_filter or is_pro:
        vf_filters = [
            "eq=contrast=1.05:brightness=0.02:saturation=1.02",
            "drawbox=x=0:y=0:w=iw:h=60:color=black@0.3:t=fill"
        ]
        af_filters = [
            "atempo=1.03",
            "asetrate=44100*0.98"
        ]
    else:
        vf_filters = []
        af_filters = []

    vf = ",".join(vf_filters) if vf_filters else None
    af = ",".join(af_filters) if af_filters else None

    # دعم جودة 1080p إذا كان مشترك مميز
    if is_pro:
        # 1080p مع حماية
        vf_cmd = f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
        if vf:
            vf_cmd += "," + vf
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", vf_cmd,
            "-c:v", "libx264", "-preset", "veryfast", "-maxrate", "3500k",
            "-bufsize", "7000k", "-g", "50", "-r", "25", "-pix_fmt", "yuv420p",
            "-af", af if af else "anull",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-f", "flv", output
        ]
    else:
        # جودة أقل للمستخدم العادي 720p
        vf_cmd = f"scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
        if vf:
            vf_cmd += "," + vf
        cmd = [
            "ffmpeg", "-re", "-i", link,
            "-vf", vf_cmd,
            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "1800k",
            "-maxrate", "2000k", "-bufsize", "3000k",
            "-af", af if af else "anull",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "flv", output
        ]

    await update.message.reply_text("جاري بدء البث...")

    increment_daily_stream_count(user_id)

    tag = str(user_id)
    last_cmds[tag] = cmd  # تخزين آخر أمر للبث

    # إيقاف أي بث سابق إذا كان موجوداً
    stop_stream_process(tag)

    threading.Thread(target=monitor_stream, args=(tag, cmd), daemon=True).start()

    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
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
    app.add_handler(conv_handler)

    print("البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()