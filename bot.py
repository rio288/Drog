import os
import json
import subprocess
from datetime import datetime, timedelta
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
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
import re

# ====== الإعدادات =======
TOKEN = os.getenv("TOKEN")  # ضع توكن البوت في متغير بيئة
ADMINS = [8145101051]       # ضع معرفات الآدمن هنا
USERS_FILE = "data/users.json"

os.makedirs("data", exist_ok=True)

# ===== حالات الحوار =====
(
    PLATFORM, STREAM_NAME, M3U8_LINK, FB_KEY,
    ADD_SUB_USER_ID, ADD_SUB_DAYS
) = range(6)

processes = {}

# ===== دوال مساعدة لقراءة وحفظ بيانات المستخدمين =====
def load_users():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            json.dump({}, f)
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ===== تحقق صلاحية الآدمن =====
def is_admin(user_id):
    return user_id in ADMINS

# ===== تحقق الاشتراك =====
def is_subscribed(user_id):
    users = load_users()
    user = users.get(str(user_id), {})
    expires = user.get("expires")
    if expires:
        expire_date = datetime.fromisoformat(expires)
        return expire_date > datetime.now()
    return False

# ===== زيادة عداد البث المجاني اليومي =====
def can_stream(user_id):
    users = load_users()
    user = users.get(str(user_id), {})
    usage = user.get("daily_stream_count", 0)
    last_date_str = user.get("daily_stream_date")
    now = datetime.now()
    if last_date_str:
        last_date = datetime.fromisoformat(last_date_str)
        if last_date.date() < now.date():
            usage = 0  # يوم جديد
    if usage >= 1 and not is_subscribed(user_id):
        return False
    return True

def increment_stream_count(user_id):
    users = load_users()
    user = users.get(str(user_id), {})
    now = datetime.now()
    last_date_str = user.get("daily_stream_date")
    if last_date_str:
        last_date = datetime.fromisoformat(last_date_str)
        if last_date.date() < now.date():
            user["daily_stream_count"] = 1
        else:
            user["daily_stream_count"] = user.get("daily_stream_count", 0) + 1
    else:
        user["daily_stream_count"] = 1
    user["daily_stream_date"] = now.isoformat()
    users[str(user_id)] = user
    save_users(users)

# ===== تشغيل البث =====
def start_stream(user_id, platform, stream_name, m3u8_link, fb_key):
    stop_stream(user_id)  # إيقاف أي بث شغال

    if platform == "facebook":
        output = f"rtmps://live-api-s.facebook.com:443/rtmp/{fb_key}"
    else:  # instagram
        output = f"rtmp://live-upload.instagram.com:80/rtmp/{fb_key}"

    # إعداد ffmpeg حسب الاشتراك
    if is_subscribed(user_id):
        cmd = [
            "ffmpeg", "-re", "-i", m3u8_link,
            "-vf", "scale=1920:1080",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "4500k", "-maxrate", "5000k", "-bufsize", "6000k",
            "-c:a", "aac", "-b:a", "160k",
            "-f", "flv", output
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", m3u8_link,
            "-vf", "scale=1280:720",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", "2500k", "-maxrate", "2800k", "-bufsize", "3000k",
            "-c:a", "aac", "-b:a", "96k",
            "-f", "flv", output
        ]

    proc = subprocess.Popen(cmd)
    processes[user_id] = proc

# ===== إيقاف البث =====
def stop_stream(user_id):
    proc = processes.get(user_id)
    if proc and proc.poll() is None:
        proc.terminate()
        processes.pop(user_id, None)

# ===== بدء الأمر /start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"مرحباً بك {user.first_name}!\n"
        f"معرفك: `{user.id}`\n"
        f"الحالة: {'مشترك ✅' if is_subscribed(user.id) else 'غير مشترك ❌'}\n\n"
        "اختر من القائمة:\n"
        "🎬 تجهيز البث\n"
        "⏹ إيقاف البث\n"
        "🔁 إعادة تشغيل البث\n"
        "📥 تحميل ملف IPTV"
    )
    buttons = [
        ["🎬 تجهيز البث", "⏹ إيقاف البث"],
        ["🔁 إعادة تشغيل البث", "📥 تحميل ملف IPTV"],
    ]
    if is_admin(user.id):
        buttons.append(["➕ إضافة مشترك"])
    keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

# ===== التعامل مع الرسائل الرئيسية =====
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🎬 تجهيز البث":
        if not can_stream(user_id):
            await update.message.reply_text("❌ وصلت الحد اليومي للبث المجاني، اشترك للبث أكثر.")
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("فيسبوك", callback_data="platform_facebook"),
             InlineKeyboardButton("إنستاغرام", callback_data="platform_instagram")]
        ])
        await update.message.reply_text("اختر منصة البث:", reply_markup=keyboard)
        return PLATFORM

    elif text == "⏹ إيقاف البث":
        stop_stream(user_id)
        await update.message.reply_text("🛑 تم إيقاف البث الخاص بك.")
    elif text == "🔁 إعادة تشغيل البث":
        # تحتاج حفظ بيانات البث السابق لوضع إعادة تشغيل حقيقية
        await update.message.reply_text("🔄 ميزة إعادة التشغيل غير مفعلة بعد.")
    elif text == "📥 تحميل ملف IPTV":
        # تحميل ملف IPTV من رابط ثابت ثم ارساله
        iptv_url = "https://raw.githubusercontent.com/hamzapro2020/Iptv/refs/heads/main/stream.html"
        r = requests.get(iptv_url)
        content = r.text
        content = re.sub(r'(video\.xx\.fbcdn\.net)', r'iptv@\1', content)
        content = re.sub(r"\{ *'title' *: *", "", content)
        content = re.sub(r'https?://[^\s]*(?:image|scontent)[^\s]*', '🎄', content)
        content = content.replace(";", "")
        content = content.replace("image", "By @rio3829")
        content = re.sub(r'}', '     \n\n\n', content)
        content = content.replace("}, {'title':", "Channel")
        content = content.replace("'", " ")
        content = re.sub(r'(https)', r'server ➡️ \1', content)
        await update.message.reply_text(content)
    elif text == "➕ إضافة مشترك" and is_admin(user_id):
        await update.message.reply_text("🔹 أرسل معرف المستخدم الذي تريد إضافته كمشترك:")
        return ADD_SUB_USER_ID
    else:
        await update.message.reply_text("❌ أمر غير معروف، استخدم الأزرار أدناه.")

# ===== حوار تجهيز البث =====
async def platform_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    platform = query.data.split("_")[1]
    context.user_data["platform"] = platform
    await query.edit_message_text(f"تم اختيار منصة: {platform}\nأرسل اسم البث:")
    return STREAM_NAME

async def get_stream_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["stream_name"] = update.message.text.strip()
    await update.message.reply_text("أرسل رابط M3U8:")
    return M3U8_LINK

async def get_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.endswith(".m3u8"):
        await update.message.reply_text("❌ الرابط يجب أن ينتهي بـ .m3u8")
        return ConversationHandler.END
    context.user_data["m3u8_link"] = link
    await update.message.reply_text("أرسل مفتاح البث (FB- أو IG- حسب المنصة):")
    return FB_KEY

async def get_fb_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    platform = context.user_data["platform"]
    if platform == "facebook" and not key.startswith("FB-"):
        await update.message.reply_text("❌ مفتاح فيسبوك يجب أن يبدأ بـ FB-")
        return ConversationHandler.END
    if platform == "instagram" and not key.startswith("IG-"):
        await update.message.reply_text("❌ مفتاح إنستاغرام يجب أن يبدأ بـ IG-")
        return ConversationHandler.END

    user_id = update.effective_user.id
    start_stream(
        user_id,
        platform,
        context.user_data["stream_name"],
        context.user_data["m3u8_link"],
        key,
    )
    increment_stream_count(user_id)
    await update.message.reply_text("✅ بدأ البث! يمكنك إيقافه بالأمر ⏹ إيقاف البث")
    return ConversationHandler.END

# ===== حوار إضافة مشترك =====
async def add_sub_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ معرف المستخدم يجب أن يكون رقم فقط. حاول مرة أخرى:")
        return ADD_SUB_USER_ID
    context.user_data["add_sub_user_id"] = text
    await update.message.reply_text("أرسل عدد الأيام للاشتراك:")
    return ADD_SUB_DAYS

async def add_sub_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ يجب إدخال عدد صحيح للأيام. حاول مرة أخرى:")
        return ADD_SUB_DAYS
    user_id = context.user_data["add_sub_user_id"]
    days = int(text)

    users = load_users()
    expire_date = datetime.now() + timedelta(days=days)
    users[user_id] = users.get(user_id, {})
    users[user_id]["expires"] = expire_date.isoformat()
    save_users(users)

    await update.message.reply_text(f"✅ تم إضافة المستخدم {user_id} مع اشتراك لمدة {days} أيام.")
    return ConversationHandler.END

# ===== إعداد البوت =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # حوار تجهيز البث
    stream_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(platform_callback, pattern="^platform_")],
        states={
            PLATFORM: [CallbackQueryHandler(platform_callback, pattern="^platform_")],
            STREAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stream_name)],
            M3U8_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_m3u8)],
            FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fb_key)],
        },
        fallbacks=[],
    )

    # حوار إضافة مشترك
    add_sub_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ إضافة مشترك$"), add_sub_user_id)],
        states={
            ADD_SUB_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sub_user_id)],
            ADD_SUB_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sub_days)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(stream_conv)
    app.add_handler(add_sub_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()