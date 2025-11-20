import os
import base64
import telegram
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import subprocess
import re
from pathlib import Path

# ========================================
# CONFIG
# ========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEMP_DIR = Path("temp_downloads/")
MAX_SIZE = 1900 * 1024 * 1024  # Telegram ~2GB limit

TEMP_DIR.mkdir(exist_ok=True)

# ========================================
# LOAD COOKIES (Base64 -> File)
# ========================================
COOKIES_FILE = "yt_cookies.txt"
cookies_b64 = os.getenv("YT_COOKIES_BASE64")
cookies_preview = ""

if cookies_b64:
    try:
        decoded = base64.b64decode(cookies_b64).decode()
        with open(COOKIES_FILE, "w") as f:
            f.write(decoded)
        cookies_preview = decoded[:500]
        print("✔ Cookies Loaded. Preview:", cookies_preview)
    except Exception as e:
        print("❌ Cookie Decode Error:", e)
else:
    print("⚠ No cookies loaded.")

# ========================================
# TIME RANGE REGEX (supports H:MM:SS)
# ========================================
COMMAND_PATTERN = re.compile(
    r"(\bhttps?://\S+)\s*((\d{1,2}:)?\d{1,2}:\d{2}-(\d{1,2}:)?\d{1,2}:\d{2}|(\d{1,2}:)?\d{1,2}:\d{2}-inf)?"
)

# Store user's default sending format
user_default_format = {}  # chat_id: "doc" or "video"

# ========================================
# /start COMMAND
# ========================================
async def start(update, context):
    await update.message.reply_text(
        "👋 Welcome to the QuickFacts Video Bot!\n\n"
        "Send me a YouTube link + optional time range.\n\n"
        "🕒 **Supported time formats:**\n"
        "- `M:SS`\n"
        "- `MM:SS`\n"
        "- `H:MM:SS`\n"
        "- `HH:MM:SS`\n"
        "- `1:00:00-inf` (until end)\n\n"
        "📌 **Examples:**\n"
        "`https://youtu.be/abc 0:30-1:00`\n"
        "`https://youtu.be/abc 1:02:20-1:10:00`\n"
        "`https://youtu.be/abc 00:10-02:00`\n"
        "`https://youtu.be/abc 1:00:00-inf`\n\n"
        "⚙️ Set a default format:\n"
        "`/format document`\n"
        "`/format video`\n",
        parse_mode="Markdown"
    )

# ========================================
# /format COMMAND (set default)
# ========================================
async def set_format(update, context):
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Use: /format document  OR  /format video")
        return

    choice = context.args[0].lower()

    if choice not in ["document", "video"]:
        await update.message.reply_text("❌ Choose: document OR video")
        return

    user_default_format[chat_id] = "doc" if choice == "document" else "video"

    await update.message.reply_text(
        f"✔ Default format saved: **{choice.capitalize()}**",
        parse_mode="Markdown"
    )

# ========================================
# /checkcookies COMMAND
# ========================================
async def checkcookies(update, context):
    if cookies_preview:
        await update.message.reply_text(
            f"🧪 **Cookies Preview:**\n{cookies_preview}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ No cookies loaded.")

# ========================================
# BUTTON HANDLER (doc/video)
# ========================================
async def format_choice_handler(update, context):
    query = update.callback_query
    await query.answer()

    choice, chat_id = query.data.split("|")
    context.user_data["chosen_format"] = choice

    await query.edit_message_text(
        f"✔ Selected: {'Document' if choice=='doc' else 'Video'}\n"
        "⏳ Downloading..."
    )

    await process_video(query, context)

# ========================================
# MAIN INPUT HANDLER
# ========================================
async def handle_message(update, context):
    text = update.message.text
    chat_id = update.message.chat_id
    match = COMMAND_PATTERN.match(text)

    if not match:
        await update.message.reply_text(
            "❌ Invalid input.\n\nUse:\n"
            "`URL H:MM:SS-H:MM:SS`\n\nExample:\n"
            "`https://youtu.be/xyz 1:00:00-1:05:20`",
            parse_mode="Markdown"
        )
        return

    video_url = match.group(1)
    time_seg = match.group(2)

    context.user_data["pending_url"] = video_url
    context.user_data["pending_seg"] = time_seg

    # If user has default format, skip asking
    if chat_id in user_default_format:
        context.user_data["chosen_format"] = user_default_format[chat_id]
        await update.message.reply_text(
            f"Using default format: {user_default_format[chat_id]}"
        )
        return await process_video(update, context)

    # Ask user which format to send
    keyboard = [
        [
            telegram.InlineKeyboardButton("📄 Document", callback_data=f"doc|{chat_id}"),
            telegram.InlineKeyboardButton("🎬 Video", callback_data=f"video|{chat_id}")
        ]
    ]

    await update.message.reply_text(
        "📌 How should I send the output?",
        reply_markup=telegram.InlineKeyboardMarkup(keyboard)
    )

# ========================================
# PROCESS VIDEO (DOWNLOAD & SEND)
# ========================================
async def process_video(update, context):

    # Determine if update came from callback or message
    if isinstance(update, telegram.CallbackQuery):
        chat_id = update.message.chat_id
        send = update.message.reply_text
        reply_document = update.message.reply_document
        reply_video = update.message.reply_video
    else:
        chat_id = update.message.chat_id
        send = update.message.reply_text
        reply_document = update.message.reply_document
        reply_video = update.message.reply_video

    video_url = context.user_data.get("pending_url")
    time_seg = context.user_data.get("pending_seg")
    choice = context.user_data.get("chosen_format", "doc")

    output_file = TEMP_DIR / f"{chat_id}_video.mp4"

    try:
        # Build yt-dlp command
        command = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--extractor-args", "youtube:player_client=default",
            "--format", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--output", str(output_file),
        ]

        if time_seg:
            command.extend(["--download-sections", f"*{time_seg}"])

        command.append(video_url)

        # Run command
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)

        print("===== YT-DLP LOG =====")
        print("STDERR:", result.stderr)
        print("STDOUT:", result.stdout)
        print("======================")

        if result.returncode != 0:
            await send("❌ Download failed:\n" + result.stderr[:1500])
            return

        if not output_file.exists():
            await send("❌ Output file missing.")
            return

        # SEND FILE
        with open(output_file, "rb") as f:
            if choice == "doc":
                await reply_document(
                    document=f,
                    caption="📄 Document (Best Quality)"
                )
            else:
                await reply_video(
                    video=f,
                    caption="🎬 Video",
                    supports_streaming=True
                )

    except Exception as e:
        await send(f"❌ Error: {e}")

    finally:
        if output_file.exists():
            os.remove(output_file)

# ========================================
# START BOT
# ========================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("format", set_format))
    app.add_handler(CommandHandler("checkcookies", checkcookies))
    app.add_handler(CallbackQueryHandler(format_choice_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot is running…")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    main()
