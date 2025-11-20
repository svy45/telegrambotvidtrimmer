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
BOT_TOKEN: Final = os.getenv("BOT_TOKEN", "7969174050:AAEj-JK_ZknnNjFHj5fkLhCVlHQumVSvLk4") 
TEMP_DIR: Final = Path('temp_downloads/')
MAX_SIZE: Final = 100 * 1024 * 1024   # 100MB Max

TEMP_DIR.mkdir(exist_ok=True)

# ============================
# Load YouTube cookies (Base64 -> File)
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
    print("⚠ No cookies provided. Restricted YouTube videos may fail.")


# ============================
# Regex for URL + optional time range
# ============================
COMMAND_PATTERN = re.compile(
    r'(\bhttps?://\S+)\s*(\d{1,3}:\d{2}-\d{1,3}:\d{2}|\d{1,3}:\d{2}-inf)?'
)


# ============================
# Commands
# ============================
async def start_command(update: telegram.Update, context):
    await update.message.reply_text(
        "👋 Welcome to the QuickFacts Video Trimmer!\n\n"
        "Send me a YouTube URL, optionally with a time range.\n\n"
        "Example:\nhttps://youtu.be/ID 0:30-1:00"
    )


async def handle_message(update: telegram.Update, context):
    text = update.message.text
    chat_id = update.message.chat_id
    match = COMMAND_PATTERN.match(text)

    if not match:
        await update.message.reply_text("❌ Format invalid. Use URL [START-END]")
        return

    video_url = match.group(1)
    time_segment = match.group(2)
    output_filepath = TEMP_DIR / f"{chat_id}_trimmed.mp4"

    await update.message.reply_text(f"⏳ Processing {video_url}...")

    try:
        # ================================
        # yt-dlp command
        # ================================
        command = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--extractor-args", "youtube:player_client=default",
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
            "--merge-output-format", "mp4",
            "--output", str(output_filepath),
        ]

        if time_segment:
            command.extend(["--download-sections", f"*{time_segment}"])

        command.append(video_url)

        # Execute
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False
        )

        # Debug logs
        print("===== YT-DLP STDOUT =====")
        print(result.stdout)
        print("===== YT-DLP STDERR =====")
        print(result.stderr)
        print("=========================")

        if result.returncode != 0:
            await update.message.reply_text(
                "❌ Video download failed.\n"
                "Check logs for details."
            )
            return

        if output_filepath.exists():
            size = output_filepath.stat().st_size

            if size > MAX_SIZE:
                await update.message.reply_text(
                    f"🚨 File too large ({size / 1024 / 1024:.1f}MB). Trim smaller range."
                )
            else:
                with open(output_filepath, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        caption=f"✅ Trimmed video ({time_segment or 'Full Video'})"
                    )
        else:
            await update.message.reply_text("❌ File missing after download.")

    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏳ Timeout. Try a shorter video.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
    finally:
        if output_filepath.exists():
            os.remove(output_filepath)


def main():
    print("🚀 Bot is starting...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot is polling...")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing. Set it in secrets.")
    else:
        main()
