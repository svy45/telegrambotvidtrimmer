import os
import base64
import subprocess
import re
from pathlib import Path
import telegram
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters
)

# ============================================
# CONFIG
# ============================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEMP_DIR = Path("temp_downloads/")
COOKIES_FILE = "yt_cookies.txt"
MAX_SIZE = 1900 * 1024 * 1024

TEMP_DIR.mkdir(exist_ok=True)

# ============================================
# DECODE BASE64 COOKIES
# ============================================
cookies_b64 = os.getenv("YT_COOKIES_BASE64")
cookies_preview = ""

if cookies_b64:
    try:
        decoded = base64.b64decode(cookies_b64).decode()
        with open(COOKIES_FILE, "w") as f:
            f.write(decoded)
        cookies_preview = decoded[:500]
        print("✔ Cookies loaded.")
    except Exception as e:
        print("❌ Cookie decode error:", e)
else:
    print("⚠ No cookies loaded (restricted videos may fail).")

# ============================================
# REGEX
# ============================================
YOUTUBE_URL_RE = re.compile(r"(https?://\S+)")
TIME_RE = re.compile(
    r"(\d{1,2}:)?\d{1,2}:\d{2}-(\d{1,2}:)?\d{1,2}:\d{2}|(\d{1,2}:)?\d{1,2}:\d{2}-inf"
)


# ============================================
# START COMMAND (PERSONALIZED)
# ============================================
async def start(update, context):
    user = update.effective_user

    name = (
        user.first_name
        or user.username
        or "there"
    )

    await update.message.reply_text(
        f"👋 Hi *{name}*, welcome to my bot!\n\n"
        "Send your YouTube link in ANY flexible format.\n\n"
        "📄 *Document Output (Best Quality)*\n"
        "`https://youtu.be/abc123 1:00-2:00 -ft doc`\n"
        "`-ft doc https://youtu.be/abc123 1:00:00-1:05:00`\n\n"
        "🎬 *Video Output (Streamable)*\n"
        "`https://youtu.be/abc123 -ft video 00:01:00-00:02:00`\n\n"
        "🕒 *Supports:*\n"
        "`M:SS`, `MM:SS`, `H:MM:SS`, `HH:MM:SS`, `1:00:00-inf`\n\n"
        "⚙ If no `-ft` is provided → output = *Document*.\n\n"
        "*BY SVY*",
        parse_mode="Markdown"
    )



# ============================================
# CHECK COOKIES
# ============================================
async def checkcookies(update, context):
    if cookies_preview:
        await update.message.reply_text(
            f"🧪 *Cookies preview:*\n\n{cookies_preview}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ No cookies loaded.")


# ============================================
# MAIN MESSAGE HANDLER
# ============================================
async def handle_message(update, context):
    text = update.message.text
    chat_id = update.message.chat_id

    # Detect YouTube URL
    url_match = YOUTUBE_URL_RE.search(text)
    if not url_match:
        await update.message.reply_text("❌ Please send a valid YouTube URL.")
        return

    video_url = url_match.group(1)

    # Detect trimming time
    time_match = TIME_RE.search(text)
    time_seg = time_match.group(0) if time_match else None

    # Detect output format
    choice = "doc"  # default
    if "-ft video" in text.lower():
        choice = "video"
    elif "-ft doc" in text.lower():
        choice = "doc"

    output_path = TEMP_DIR / f"{chat_id}_output.mp4"

    await update.message.reply_text(
        f"⏳ Processing…\n"
        f"📌 Output: *{choice}*\n"
        f"✂ Trim: *{time_seg or 'Full Video'}*",
        parse_mode="Markdown"
    )

    # ============================================
    # RUN YT-DLP
    # ============================================
    try:
        command = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--extractor-args", "youtube:player_client=default",
            "--format", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--output", str(output_path),
        ]

        if time_seg:
            command.extend(["--download-sections", f"*{time_seg}"])

        command.append(video_url)

        result = subprocess.run(
            command, capture_output=True, text=True, timeout=600
        )

        print("STDERR:", result.stderr)
        print("STDOUT:", result.stdout)

        if result.returncode != 0:
            await update.message.reply_text(
                f"❌ *Download failed:*\n```\n{result.stderr[:1500]}\n```",
                parse_mode="Markdown"
            )
            return

        if not output_path.exists():
            await update.message.reply_text("❌ Output file missing.")
            return

        # ============================================
        # SEND AS DOCUMENT OR VIDEO
        # ============================================
        with open(output_path, "rb") as f:
            if choice == "doc":
                await update.message.reply_document(
                    document=f,
                    caption="📄 Sent as Document (Best Quality)"
                )
            else:
                await update.message.reply_video(
                    video=f,
                    caption="🎬 Sent as Video",
                    supports_streaming=True
                )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

    finally:
        if output_path.exists():
            os.remove(output_path)


# ============================================
# MAIN
# ============================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("checkcookies", checkcookies))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot running…")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    main()
