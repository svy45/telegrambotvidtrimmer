import os
import base64
import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import subprocess
import re
from pathlib import Path
from typing import Final

# ============================
# CONFIG
# ============================
BOT_TOKEN: Final = os.getenv("BOT_TOKEN")
TEMP_DIR: Final = Path("temp_downloads/")
MAX_SIZE: Final = 100 * 1024 * 1024  # 100 MB max

TEMP_DIR.mkdir(exist_ok=True)

# ============================
# Load Base64 Cookies
# ============================
COOKIES_FILE = "yt_cookies.txt"
cookies_b64 = os.getenv("YT_COOKIES_BASE64")

cookies_preview = ""

if cookies_b64:
    try:
        decoded = base64.b64decode(cookies_b64).decode()

        # Save cookies
        with open(COOKIES_FILE, "w") as f:
            f.write(decoded)

        cookies_preview = decoded[:500]  # Save preview
        print("✔ Cookies Loaded. Preview:", cookies_preview)

    except Exception as e:
        print("❌ Cookie Decode Error:", e)
else:
    print("⚠ No cookies provided")


# ============================
# Regex for URL pattern
# ============================
COMMAND_PATTERN = re.compile(
    r"(\bhttps?://\S+)\s*(\d{1,3}:\d{2}-\d{1,3}:\d{2}|\d{1,3}:\d{2}-inf)?"
)

# ============================
# /start command
# ============================
async def start_command(update: telegram.Update, context):
    await update.message.reply_text(
        "👋 Welcome to the QuickFacts Video Trimmer!\n\n"
        "Send a YouTube URL with or without a time range.\n"
        "Example:\nhttps://youtu.be/id 0:30-1:00"
    )


# ============================
# /checkcookies command
# ============================
async def check_cookies(update: telegram.Update, context):
    global cookies_preview

    if not cookies_preview:
        await update.message.reply_text("❌ No cookies loaded.")
        return

    await update.message.reply_text(
        f"🧪 **Cookies Preview (first 500 chars):**\n\n{cookies_preview}",
        parse_mode="Markdown"
    )


# ============================
# Main handler
# ============================
async def handle_message(update: telegram.Update, context):
    text = update.message.text
    chat_id = update.message.chat_id
    match = COMMAND_PATTERN.match(text)

    if not match:
        await update.message.reply_text("❌ Invalid format. Use URL [start-end]")
        return

    video_url = match.group(1)
    time_segment = match.group(2)
    output_filepath = TEMP_DIR / f"{chat_id}_trimmed.mp4"

    await update.message.reply_text(f"⏳ Processing {video_url}...")

    try:
        # yt-dlp command
        command = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--extractor-args", "youtube:player_client=default",
            "--no-check-certificates",
            "--no-warnings",
            "--format", "bestvideo*+bestaudio/best",
            "--merge-output-format", "mp4",
            "--output", str(output_filepath),
        ]

        if time_segment:
            command.extend(["--download-sections", f"*{time_segment}"])

        command.append(video_url)

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

        # Log for Fly.io
        print("===== YT-DLP LOG =====")
        print("STDERR:", result.stderr)
        print("STDOUT:", result.stdout)
        print("RETURN CODE:", result.returncode)
        print("======================")

        if result.returncode != 0:
            stderr = (result.stderr or "No STDERR")[:1500]
            stdout = (result.stdout or "No STDOUT")[:1500]

            await update.message.reply_text("❌ Video download failed.")
            await update.message.reply_text(f"📌 **STDERR:**\n{stderr}")
            await update.message.reply_text(f"📌 **STDOUT:**\n{stdout}")
            return

        if output_filepath.exists():
            size = output_filepath.stat().st_size
            if size > MAX_SIZE:
                await update.message.reply_text(
                    f"🚨 File too large: {size/1024/1024:.1f}MB"
                )
            else:
                with open(output_filepath, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        caption=f"✅ Trimmed video ({time_segment or 'Full Video'})"
                    )
        else:
            await update.message.reply_text("❌ Output file missing.")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

    finally:
        if output_filepath.exists():
            os.remove(output_filepath)


# ============================
# Start bot
# ============================
def main():
    print("🚀 Bot starting...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("checkcookies", check_cookies))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Polling...")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Missing BOT_TOKEN")
    else:
        main()
