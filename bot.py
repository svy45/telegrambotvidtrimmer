import os
import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import subprocess
import re
from pathlib import Path
from typing import Final

# --- CONFIGURATION ---
BOT_TOKEN: Final = os.getenv("BOT_TOKEN", "7969174050:AAEj-JK_ZknnNjFHj5fkLhCVlHQumVSvLk4") 
TEMP_DIR: Final = Path('temp_downloads/')
MAX_SIZE: Final = 100 * 1024 * 1024  # 100 MB max

TEMP_DIR.mkdir(exist_ok=True)

# Regex (URL + optional time segment)
COMMAND_PATTERN = re.compile(r'(\bhttps?://\S+)\s*(\d{1,3}:\d{2}-\d{1,3}:\d{2}|\d{1,3}:\d{2}-inf)?')

async def start_command(update: telegram.Update, context):
    await update.message.reply_text(
        "👋 Send a YouTube URL, optionally with a time range.\n"
        "Example:\nhttps://youtu.be/ID 0:30-1:00"
    )

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
        command = [
            "yt-dlp",
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
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
            check=False
        )

        # DEBUG LOGGING (very important)
        print("\n===== YT-DLP STDOUT =====")
        print(result.stdout)
        print("===== YT-DLP STDERR =====")
        print(result.stderr)
        print("==========================\n")

        if result.returncode != 0:
            await update.message.reply_text(
                "❌ Video processing failed.\n"
                "⚠️ Check Fly.io logs for REAL ERROR."
            )
            return

        if output_filepath.exists():
            file_size = output_filepath.stat().st_size
            if file_size > MAX_SIZE:
                await update.message.reply_text(
                    f"🚨 File too large: {file_size/1024/1024:.1f}MB. Trim smaller range."
                )
            else:
                with open(output_filepath, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        caption=f"✅ Trimmed video ({time_segment or 'Full'})"
                    )
        else:
            await update.message.reply_text("❌ Output file missing.")

    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏳ Timeout. Try shorter video.")
    except Exception as e:
        await update.message.reply_text(f"❌ Internal Error: {e}")
    finally:
        if output_filepath.exists():
            os.remove(output_filepath)

def main():
    print("🚀 Bot is starting…")
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot is polling now…")
    application.run_polling(poll_interval=3)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN is missing! Set it in Fly secrets.")
    else:
        main()
