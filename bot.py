import os
import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import subprocess 
import re 
from pathlib import Path
from typing import Final 

# --- CONFIGURATION ---
# IMPORTANT: This token will be read from the Railway Environment Variable in the final deployment, 
# but we keep a fallback here, though it's best to rely on the environment variable.
BOT_TOKEN: Final = os.getenv("BOT_TOKEN", "7969174050:AAEj-JK_ZknnNjFHj5fkLhCVlHQumVSvLk4") 
TEMP_DIR: Final = Path('temp_downloads/')
MAX_SIZE: Final = 100 * 1024 * 1024  # 100 MB max for a single file upload

TEMP_DIR.mkdir(exist_ok=True)

# Regex to find the URL and the optional trimming segment (e.g., URL 0:30-1:00 or 1:00-inf)
COMMAND_PATTERN = re.compile(r'(\bhttps?://\S+)\s*(\d{1,3}:\d{2}-\d{1,3}:\d{2}|\d{1,3}:\d{2}-inf)?')

async def start_command(update: telegram.Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    """Greets the user and explains usage."""
    await update.message.reply_text(
        '👋 Welcome to the QuickFacts Video Trimmer!\n\n'
        'Send me a YouTube URL, optionally followed by a time range in M:SS-M:SS format.\n\n'
        'Example: https://youtu.be/VIDEO_ID 0:30-1:00'
    )

async def handle_message(update: telegram.Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE):
    """Processes the message to find URL and timestamps, then executes the download/trim."""
    text = update.message.text
    chat_id = update.message.chat_id
    match = COMMAND_PATTERN.match(text)

    if not match:
        await update.message.reply_text("❌ Please send a valid YouTube URL. Format: URL [START-END]")
        return

    video_url = match.group(1)
    time_segment = match.group(2)
    output_filepath = TEMP_DIR / f"{chat_id}_trimmed.mp4"

    await update.message.reply_text(f"⏳ Processing {video_url}...")
    
    try:
        # --- YT-DLP Command Construction ---
        command = [
            'yt-dlp', 
            '--format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]', 
            '--merge-output-format', 'mp4',
            '--output', str(output_filepath),
        ]
        
        if time_segment:
            # Requires FFmpeg, which the Dockerfile installs
            command.extend(['--download-sections', f"*{time_segment}"])
            
        command.append(video_url)

        # Execute the command
        result = subprocess.run(
            command, 
            capture_output=True, 
            text=True,
            timeout=600, # 10 minute timeout
            check=False 
        )

        if result.returncode != 0:
            error_message = f"❌ Video processing failed. This often means FFmpeg is missing, or the video is restricted."
            await update.message.reply_text(error_message)
            return
            
        # --- Uploading the file ---
        if output_filepath.exists():
            file_size = output_filepath.stat().st_size
            
            if file_size > MAX_SIZE:
                await update.message.reply_text(f"🚨 File is too large ({file_size / (1024*1024):.1f}MB). Please trim a shorter segment.")
            else:
                with open(output_filepath, 'rb') as f:
                    await update.message.reply_document(
                        document=f, 
                        caption=f"✅ Trimmed video ({time_segment or 'Full Video'})"
                    )
        else:
            await update.message.reply_text("❌ Download failed. The output file was not created.")

    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏳ Processing timed out (took longer than 10 minutes). Try a shorter video or segment.")
    except Exception as e:
        await update.message.reply_text(f"❌ An internal server error occurred: {e}")
    finally:
        # --- CRUCIAL CLEANUP ---
        if output_filepath.exists():
            os.remove(output_filepath) 


def main():
    """Starts the bot."""
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # We use run_polling because the code is structured for it, 
    # but a webhook setup is more efficient on Railway.
    print("Bot is polling... (Quickfactspower is online!)")
    application.run_polling(poll_interval=3.0)

if __name__ == '__main__':
    # When using the env var, it will be None before set, so we check first
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is missing! Please set the environment variable on Railway.")
    else:
        main()