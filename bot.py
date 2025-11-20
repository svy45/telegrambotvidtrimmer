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
MAX_SIZE: Final = 100 * 1024 * 1024  # 100 MB Max

TEMP_DIR.mkdir(exist_ok=True)

# ============================
# Load Base64 YouTube Cookies
# ============================
COOKIES_FILE = "yt_cookies.txt"
cookies_b64 = os.getenv("YT_COOKIES_BASE64")

if cookies_b64:
    try:
        decoded = base64.b64decode(cookies_b64).decode()
        with open(COOKIES_FILE, "w") as f:
            f.write(decoded)
        print("✔ YouTube cookies loaded successfully.")
    except Exception as e:
        print(f"❌ Failed to decode cookies: {e}")
else:
    print("⚠ No cookies provided. Some YouTube videos may fail.")


# ============================
# Regex for URL + Optional Timerange
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
        "Send me a YouTube URL, optionally with a time range.\n\n"
        "Example:\nhttps://youtu.be/ID 0:30-1:00"
    )


# ============================
# Main message handler
# ============================
async def handle_message(update: telegram.Update, context):
    text = update.message.text
    chat_id = update.message.chat_id
    match = COMMAND_PATTERN.match(text)

    if not match:
        await update.message.reply_text("❌ Invalid format. Use: URL [START-END]")
        return

    video_url = match.group(1)
    time_segment = match.group(2)
    output_filepath = TEMP_DIR / f"{chat_id}_trimmed.mp4"

    await update.message.reply_text(f"⏳ Processing {video_url}...")

    try:
        # ====================================
        # yt-dlp Command
        # ====================================
        command = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--extractor-args", "youtube:player_client=default",
            "--no-check-certificates",
            "--no-warnings",
            "--no-call-home",
            "--format", "bestvideo*+bestaudio/best",
            "--merge-output-format", "mp4",
            "--output", str(output_filepath),
        ]

        if time_segment:
            command.extend(["--download-sections", f"*{time_segment}"])

        command.append(video_url)

        # Execute yt-dlp
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

        # ====================================
        # LOGGING TO FLY.IO
        # ====================================
        print("====== YT-DLP EXECUTION LOG ======")
        print("COMMAND:", " ".join(command))
        print("STDOUT:", result.stdout or "No STDOUT")
        print("STDERR:", result.stderr or "No STDERR")
        print("RETURN CODE:", result.returncode)
        print("==================================")

        # ====================================
        # If download failed
        # ====================================
        if result.returncode != 0:
            stderr_safe = (result.stderr or "No STDERR")[:1500]
            stdout_safe = (result.stdout or "No STDOUT")[:1500]

            await update.message.reply_text("❌ Video download failed.")
            await update.message.reply_text(f"📌 **STDERR:**\n{stderr_safe}")
            await update.message.reply_text(f"📌 **STDOUT:**\n{stdout_safe}")

            return

        # ====================================
        # File exists?
        # ====================================
        if output_filepath.exists():
            size = output_filepath.stat().st_size

            if size > MAX_SIZE:
                await update.message.reply_text(
                    f"🚨 Final file too large: {size/1024/1024:.1f}MB.\n"
                    "Try trimming a smaller segment."
                )
            else:
                with open(output_filepath, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        caption=f"✅ Trimmed Video ({time_segment or 'Full'})"
                    )
        else:
            await update.message.reply_text("❌ Output file missing")

    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏳ Timeout. Try a shorter range.")
    except Exception as e:
        await update.message.reply_text(f"❌ Internal Error: {e}")
    finally:
        # Cleanup
        if output_filepath.exists():
            os.remove(output_filepath)


# ============================
# Main entry
# ============================
def main():
    print("🚀 Bot starting…")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot polling…")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing.")
    else:
        main()
