import os
import json
import threading
import subprocess
import random
import string
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

TOKEN = os.getenv("TOKEN")  # ضع التوكن في متغير البيئة TOKEN
ADMINS = [8145101051]  # استبدل بمعرفات المسؤولين
USERS_FILE = "data/users.json"
os.makedirs("data", exist_ok=True)

SELECT_BROADCAST_TYPE, M3U8_LINK, STREAM_KEY, ADD_SUBSCRIBE = range(4)

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

def generate_filter_params():
    tempo = round(random.uniform(0.95, 1.05), 2)
    pitch_rate = round(random.uniform(0.9, 1.1), 2)
    brightness = round(random.uniform(0.0, 0.1), 2)
    contrast = round(random.uniform(1.0, 1.2), 2)
    vf_filters = [f"eq=contrast={contrast}:brightness={brightness}", "format=yuv420p"]
    af_filters = [f"asetrate=44100*{pitch_rate}", "aresample=44100", f"atempo={tempo}", "highpass=f=200", "lowpass=f=3000"]
    return ",".join(vf_filters), ",".join(af_filters)

def monitor_stream(tag, base_cmd):
    global processes
    while True:
        if tag not in processes:
            break

        vf, af = generate_filter_params()

        cmd_filtered = []
        skip_next = False
        for part in base_cmd:
            if skip_next:
                skip_next = False
                continue
            if part in ("-vf", "-af"):
                skip_next = True
                continue
            cmd_filtered.append(part)

        cmd_filtered += ["-vf", vf, "-af", af]

        print(f"تشغيل بث جديد مع فلاتر: vf={vf}, af={af}")

        proc = subprocess.Popen(cmd_filtered)
        processes[tag] = proc

        for _ in range(60):
            if tag not in processes:
                proc.terminate()
                return
            if proc.poll() is not None:
                processes.pop(tag, None)
                return
            time.sleep(1)

        proc.terminate()
        proc.wait()
        processes.pop(tag, None)

def stop_stream_process(tag):
    proc = processes.get(tag)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(tag, None)

def random_stream_name(length=8):
    letters_and_digits = string.ascii_letters + string.digits
    return ''.join(random.choice(letters_and_digits) for _ in range(length))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    status = "مشترك ✅" if is_subscribed(user.id) else "غير مشترك ❌"
    
    buttons = [
        ["🎬 تجهيز البث", "⏹ إيقاف البث"],
        ["📞 تواصل مع الدعم"],
    ]
    
    if is_admin(user.id):
        buttons.append(["➕ إضافة مفتاح اشتراك"])
    
    keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    
    text = (
        f"مرحباً!\nمعرفك: `{user.id}`\n"
        f"الاسم: {user.full_name}\n"
        f"الحالة: {status}\n\n"
        "اختر من القائمة:\n🎬 تجهيز البث\n⏹ إيقاف البث\n📞 تواصل مع الدعم"
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

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
        except Exception:
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
        if str(user_id) in processes:
            stop_stream_process(str(user_id))
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
            "سيتم تطبيق الفلاتر تلقائيًا.\n"
            "الآن اختر نوع البث:",
            parse_mode="Markdown"
        )
        return SELECT_BROADCAST_TYPE

    context.user_data["broadcast_type"] = data
    # حذف طلب اسم البث نهائياً
    await query.message.reply_text("🔗 أرسل رابط M3U8:")
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
    context.user_data["stream_key"] = key

    user_id = update.effective_user.id
    use_filter = context.user_data.get("use_filter", False)
    broadcast_type = context.user_data.get("broadcast_type")
    m3u8 = context.user_data.get("m3u8")
    stream_key = key

    stream_name = random_stream_name()

    if broadcast_type == "live_fb":
        url = f"rtmp://live-api-s.facebook.com:80/rtmp/{stream_key}"
    elif broadcast_type == "live_ig":
        url = f"rtmp://live-upload.instagram.com:80/rtmp/{stream_key}"
    else:
        await update.message.reply_text("خطأ في اختيار نوع البث.")
        return ConversationHandler.END

    ffmpeg_cmd = [
        "ffmpeg", "-re",
        "-i", m3u8,
        "-c:v", "copy",
        "-c:a", "aac",
        "-f", "flv",
        url
    ]

    if use_filter:
        await update.message.reply_text("⏳ يتم تجهيز البث مع تفعيل الحماية...")
        increment_daily_stream_count(user_id)

        def run_monitor():
            processes[str(user_id)] = True
            monitor_stream(str(user_id), ffmpeg_cmd)

        threading.Thread(target=run_monitor, daemon=True).start()
        await update.message.reply_text(f"✅ تم بدء البث مع حماية الكوبيرايت. اسم البث: {stream_name}")
    else:
        if str(user_id) in processes:
            stop_stream_process(str(user_id))
        proc = subprocess.Popen(ffmpeg_cmd)
        processes[str(user_id)] = proc
        increment_daily_stream_count(user_id)
        await update.message.reply_text(f"✅ تم بدء البث بدون حماية. اسم البث: {stream_name}")

    return ConversationHandler.END

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            ADD_SUBSCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            SELECT_BROADCAST_TYPE: [CallbackQueryHandler(select_broadcast_type)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            STREAM_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_key)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    print("بوت تيليجرام يعمل ...")
    application.run_polling()

if __name__ == "__main__":
    main()