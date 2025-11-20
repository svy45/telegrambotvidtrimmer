import os
import base64
import subprocess
import re
import datetime
from pathlib import Path
import telegram
from threading import Thread
from http.server import HTTPServer, SimpleHTTPRequestHandler

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters
)

# ======================================================
# CONFIG
# ======================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 678795622  # SVY ONLY
COOKIES_FILE = "yt_cookies.txt"
TEMP_DIR = Path("temp_downloads/")
MAX_SIZE = 1900 * 1024 * 1024  # 1.9GB
TEMP_DIR.mkdir(exist_ok=True)

# Load stored Base64 cookies if exists
cookies_b64_path = Path("cookies.b64")
if cookies_b64_path.exists():
    try:
        decoded = base64.b64decode(cookies_b64_path.read_text()).decode()
        with open(COOKIES_FILE, "w") as f:
            f.write(decoded)
        print("✔ Loaded saved cookies.")
    except:
        print("❌ Failed to decode stored cookies.")
else:
    print("⚠ No stored cookies found. Restricted videos will fail.")


# ======================================================
# REGEX
# ======================================================
YOUTUBE_URL_RE = re.compile(r"(https?://\S+)")
TIME_RE = re.compile(
    r"(\d{1,2}:)?\d{1,2}:\d{2}-(\d{1,2}:)?\d{1,2}:\d{2}|(\d{1,2}:)?\d{1,2}:\d{2}-inf"
)


# ======================================================
# KEEP-ALIVE SERVER FOR FLY.IO (PORT 8080)
# ======================================================
def keep_alive():
    server = HTTPServer(("0.0.0.0", 8080), SimpleHTTPRequestHandler)
    print("🌐 Keep-alive server running on port 8080")
    server.serve_forever()


# ======================================================
# /start COMMAND
# ======================================================
async def start(update, context):
    user = update.effective_user
    name = user.first_name or user.username or "there"

    await update.message.reply_text(
        f"👋 Hi *{name}*, welcome to the QuickFacts Video Bot!\n\n"
        "Send a YouTube link in ANY flexible format:\n\n"
        "📄 *Document Output (Best Quality)*\n"
        "`https://youtu.be/abc123 1:00-2:00 -ft doc`\n"
        "`-ft doc https://youtu.be/abc123 1:00:00-1:05:00`\n\n"
        "🎬 *Video Output (Streamable)*\n"
        "`https://youtu.be/abc123 -ft video 00:01:00-00:02:00`\n\n"
        "🕒 Supports: `M:SS`, `H:MM:SS`, `1:00:00-inf`\n\n"
        "⚙ Default output: *Document*\n\n"
        "*BY SVY*",
        parse_mode="Markdown"
    )


# ======================================================
# COOKIE STATUS CHECK
# ======================================================
REQUIRED_COOKIES = [
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO"
]


def cookies_expired():
    if not os.path.exists(COOKIES_FILE):
        return True

    with open(COOKIES_FILE, "r") as f:
        raw = f.readlines()

    for line in raw:
        if "\t" not in line or line.startswith("#"):
            continue
        parts = line.split("\t")
        try:
            exp = int(parts[4])
            if exp < int(datetime.datetime.now().timestamp()):
                return True
        except:
            continue

    return False


async def cookies_status(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized. Please contact SVY.")
        return

    if not os.path.exists(COOKIES_FILE):
        await update.message.reply_text("❌ No cookies found.")
        return

    with open(COOKIES_FILE, "r") as f:
        raw = f.read()

    missing = [k for k in REQUIRED_COOKIES if k not in raw]

    msg = ""

    if missing:
        msg += f"⚠ Missing cookies: {', '.join(missing)}\n"
    else:
        msg += "🍪 Cookies look valid!\n"

    if cookies_expired():
        msg += "\n❌ Cookies are expired!"
    else:
        msg += "\n✔ Cookies are still valid."

    await update.message.reply_text(msg)


# ======================================================
# /refreshcookies — Admin Uploads cookies.txt
# ======================================================
async def refreshcookies(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized. Contact SVY.")
        return

    await update.message.reply_text(
        "📤 Please upload your *cookies.txt* file.\n\n"
        "Make sure it is in Netscape cookie format."
    )


async def receive_cookie_file(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    doc = update.message.document
    if not doc:
        return

    if "cookie" not in doc.file_name.lower():
        await update.message.reply_text("❌ This does not look like a cookies file.")
        return

    file = await doc.get_file()
    cookie_data = await file.download_as_bytearray()

    decoded = cookie_data.decode()

    # Save raw cookies.txt
    with open(COOKIES_FILE, "w") as f:
        f.write(decoded)

    # Save Base64 version for persistence
    cookies_b64 = base64.b64encode(decoded.encode()).decode()
    Path("cookies.b64").write_text(cookies_b64)

    await update.message.reply_text("✅ Cookies updated successfully!")
    print("✔ Cookies updated from Telegram upload.")


# ======================================================
# MAIN DOWNLOAD PROCESS
# ======================================================
async def handle_message(update, context):
   

    text = update.message.text
    chat_id = update.message.chat_id

    url_match = YOUTUBE_URL_RE.search(text)
    if not url_match:
        await update.message.reply_text("❌ Please send a valid YouTube URL.")
        return

    video_url = url_match.group(1)

    time_match = TIME_RE.search(text)
    time_seg = time_match.group(0) if time_match else None

    output_type = "doc"
    if "-ft video" in text.lower():
        output_type = "video"

    output_path = TEMP_DIR / f"{chat_id}.mp4"

    await update.message.reply_text(
        f"⏳ Processing…\nOutput: *{output_type}*\nTrim: *{time_seg or 'Full Video'}*",
        parse_mode="Markdown"
    )

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

        if result.returncode != 0:
            await update.message.reply_text(
                f"❌ Download error:\n```\n{result.stderr[:1500]}\n```",
                parse_mode="Markdown"
            )
            return

        if not output_path.exists():
            await update.message.reply_text("❌ Output file missing.")
            return

        with open(output_path, "rb") as f:
            if output_type == "doc":
                await update.message.reply_document(f, caption="📄 Best Quality File")
            else:
                await update.message.reply_video(f, supports_streaming=True)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

    finally:
        if output_path.exists():
            os.remove(output_path)


# ======================================================
# MAIN APP
# ======================================================
def main():
    Thread(target=keep_alive).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cookiesstatus", cookies_status))
    app.add_handler(CommandHandler("refreshcookies", refreshcookies))
    app.add_handler(MessageHandler(filters.Document.ALL, receive_cookie_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot is running...")
    app.run_polling(poll_interval=3)


if __name__ == "__main__":
    main()

