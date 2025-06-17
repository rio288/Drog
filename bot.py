import os
import subprocess
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# حالات المحادثة
(
    STATE_NAME,
    STATE_M3U8,
    STATE_FB_KEY,
    STATE_PROTECT_CHOICE,
) = range(4)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "👋 مرحباً في بوت بث Facebook.\n\n"
        "📌 الرجاء إرسال *اسم البث*:",
        parse_mode="Markdown",
    )
    return STATE_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text
    await update.message.reply_text(
        "✅ تم حفظ اسم البث.\n\n"
        "🔗 الآن أرسل *رابط M3U8* للبث:",
        parse_mode="Markdown",
    )
    return STATE_M3U8


async def receive_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["m3u8"] = update.message.text
    await update.message.reply_text(
        "🔑 أرسل *مفتاح البث (Facebook Stream Key)*:",
        parse_mode="Markdown",
    )
    return STATE_FB_KEY


async def receive_fb_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["fb_key"] = update.message.text
    keyboard = [["نعم", "لا"]]
    await update.message.reply_text(
        "🛡️ هل تريد تفعيل حماية الكوبيرايت المتقدمة؟",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return STATE_PROTECT_CHOICE


async def receive_protect_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    use_protect = update.message.text.strip() == "نعم"
    m3u8_url = context.user_data["m3u8"]
    fb_key = context.user_data["fb_key"]
    fb_rtmp_url = f"rtmps://live-api-s.facebook.com:443/rtmp/{fb_key}"

    await update.message.reply_text(
        "🚀 جاري بدء البث، الرجاء الانتظار...",
        reply_markup=ReplyKeyboardRemove(),
    )

    base_cmd = [
        "ffmpeg",
        "-re",
        "-i",
        m3u8_url,
    ]

    if use_protect:
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
            "asetrate=44100*0.97,"
            "atempo=1.03,"
            "highpass=f=200,"
            "lowpass=f=3000"
        )
        base_cmd.extend(["-vf", video_filters, "-af", audio_filters])

    base_cmd.extend(
        [
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-c:v", "libx264",
            "-b:v", "4500k",
            "-maxrate", "5000k",
            "-bufsize", "6000k",
            "-c:a", "aac",
            "-b:a", "192k",
            "-f", "flv",
            fb_rtmp_url,
        ]
    )

    try:
        subprocess.Popen(base_cmd)
        await update.message.reply_text("✅ تم بدء البث إلى Facebook بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء بدء البث:\n{e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ تم إلغاء العملية.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


def main() -> None:
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise RuntimeError("❌ متغير البيئة BOT_TOKEN غير معرف!")

    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            STATE_M3U8: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_m3u8)],
            STATE_FB_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_fb_key)],
            STATE_PROTECT_CHOICE: [
                MessageHandler(filters.Regex("^(نعم|لا)$"), receive_protect_choice)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    print("🔴 بوت البث يعمل الآن...")
    application.run_polling()


if __name__ == "__main__":
    main()