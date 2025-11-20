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
MAX_SIZE = 1900 * 1024 * 1024  # Telegram limit ~2GB

TEMP_DIR.mkdir(exist_ok=True)

# ========================================
# COOKIE LOADING
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
    print("⚠ No cookies provided — restricted videos may fail.")


# ========================================
# REGEX (supports H:MM:SS)
# ========================================
COMMAND_PATTERN = re.compile(
    r"(\bhttps?://\S+)\s*((\d{1,2}:)?\d{1,2}:\d{2}-(\d{1,2}:)?\d{1,2}:\d{2}|(\d{1,2}:)?\d{1,2}:\d{2}-inf)?"
)

# Store default preferences (doc/video)
user_default_format = {}

# ========================================
# START COMMAND
# ========================================
async def start(update, context):
    await update.message.reply_text(
        "👋 Welcome to the QuickFacts Video Bot!\n\n"
        "Send me a YouTube link and an optional time range.\n\n"
        "🕒 **Supported time formats:**\n"
        "- `M:SS` (1:20)\n"
        "- `MM:SS` (15:30)\n"
        "- `H:MM:SS` (1:02:15)\n"
        "- `HH:MM:SS` (02:10:05)\n"
        "- Ending with `-inf` to download until end\n\n"
        "📌 **Examples:**\n"
        "`https://youtu.be/ABC123 0:30-1:00`\n"
        "`https://youtu.be/ABC123 1:02:20-1:10:00`\n"
        "`https://youtu.be/ABC123 00:10-02:00`\n"
        "`https://youtu.be/ABC123 1:00:00-inf`\n\n"
        "⚙️ Set default format:\n"
        "`/format document`\n"
        "`/format video`\n",
        parse_mode="Markdown",
    )


# ========================================
# CHECK COOKIES
# ========================================
async def checkcookies(update, context):
    if not cookies_preview:
        await update.message.reply_text("❌ No cookies loaded.")
    else:
        await update.message.reply_text(
            f"🧪 **Cookies Preview (first 500 chars):**\n\n{cookies_preview}",
            parse_mode="Markdown",
        )


# ========================================
# SET DEFAULT FORMAT
# ========================================
async def set_format(update, context):
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Usage:\n/format document\n/format video")
        return

    choice = context.args[0].lower()

    if choice not in ["document", "video"]:
        await update.message.reply_text("❌ Invalid choice. Choose: document OR video")
        return

    user_default_format[chat_id] = "doc" if choice == "document" else "video"

    await update.message.reply_text(
        f"✔ Default format set to **{choice.capitalize()}**", parse_mode="Markdown"
    )


# ========================================
# CALLBACK HANDLER (DOC/VIDEO BUTTON)
# ========================================
async def format_choice_handler(update, context):
    query = update.callback_query
    await query.answer()

    choice, chat_id = query.data.split("|")
    chat_id = int(chat_id)
    context.user_data["chosen_format"] = choice

    await query.edit_message_text(
        f"✔ Selected: {'Document' if choice=='doc' else 'Video'}\n"
        "⏳ Downloading..."
    )

    await process_video(update, context)


# ========================================
# MAIN MESSAGE HANDLER
# ========================================
async def handle_message(update, context):
    text = update.message.text
    chat_id = update.message.chat_id
    match = COMMAND_PATTERN.match(text)

    if not match:
        await update.message.reply_text(
            "❌ Invalid format.\n\n"
            "Use:\n"
            "`URL H:MM:SS-H:MM:SS`\n\n"
            "Example:\n"
            "`https://youtu.be/xyz 1:00:00-1:05:20`",
            parse_mode="Markdown",
        )
        return

    video_url = match.group(1)
    time_segment = match.group(2)

    context.user_data["pending_url"] = video_url
    context.user_data["pending_seg"] = time_segment

    # If user has default preference → skip asking
    if chat_id in user_default_format:
        context.user_data["chosen_format"] = user_default_format[chat_id]
        return await process_video(update, context)

    # Ask via inline keyboard
    keyboard = [
        [
            telegram.InlineKeyboardButton("📄 Document", callback_data=f"doc|{chat_id}"),
            telegram.InlineKeyboardButton("🎬 Video", callback_data=f"video|{chat_id}"),
        ]
    ]

    await update.message.reply_text(
        "📌 How should I send the output?",
        reply_markup=telegram.InlineKeyboardMarkup(keyboard),
    )


# ========================================
# DOWNLOAD & SEND
# ========================================
async def process_video(update, context):
    chat_id = update.effective_chat.id

    video_url = context.user_data.get("pending_url")
    time_segment = context.user_data.get("pending_seg")
    choice = context.user_data.get("chosen_format", "doc")

    output_file = TEMP_DIR / f"{chat_id}_out.mp4"

    try:
        command = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--extractor-args", "youtube:player_client=default",
            "--format", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--output", str(output_file),
        ]

        if time_segment:
            command.extend(["--download-sections", f"*{time_segment}"])

        command.append(video_url)

        result = subprocess.run(
            command, capture_output=True, text=True, timeout=600
        )

        print("===== YT-DLP LOG =====")
        print("STDERR:", result.stderr)
        print("STDOUT:", result.stdout)
        print("======================")

        if result.returncode != 0:
            await update.effective_chat.send_message(
                "❌ Download failed.\n\n"
                f"📌 STDERR:\n{result.stderr[:1500]}"
            )
            return

        if not output_file.exists():
            await update.effective_chat.send_message("❌ Output file missing.")
            return

        # SEND OUTPUT
        with open(output_file, "rb") as f:
            if choice == "doc":
                await update.effective_chat.send_document(
                    document=f,
                    caption="📄 Sent as Document (Best Quality)"
                )
            else:
                await update.effective_chat.send_video(
                    video=f,
                    caption="🎬 Sent as Video",
                    supports_streaming=True
                )

    except Exception as e:
        await update.effective_chat.send_message(f"❌ Error: {e}")

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

    print("🤖 Bot running…")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    main()
