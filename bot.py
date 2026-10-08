import os
import logging
import io
from PIL import Image, ImageOps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Supported formats
SUPPORTED_FORMATS = ["JPEG", "PNG", "WEBP", "BMP", "GIF", "TIFF"]

# Preset resize options
RESIZE_OPTIONS = {
    "1080": (1920, 1080),
    "720": (1280, 720),
    "480": (854, 480),
    "square": (1080, 1080),
    "thumb": (500, 500),
}

# Compression presets
QUALITY_PRESETS = {
    "high": 90,
    "medium": 75,
    "low": 50,
}


# ---------- Helper Functions ----------

def human_size(size_bytes):
    """Format bytes to human readable."""
    if not size_bytes:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def detect_format(image: Image.Image):
    """Detect image format, fallback to PNG."""
    fmt = (image.format or "PNG").upper()
    if fmt == "JPG":
        fmt = "JPEG"
    return fmt if fmt in SUPPORTED_FORMATS else "PNG"


def convert_to_rgb(image: Image.Image):
    """Convert image to RGB (needed for JPEG output)."""
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        background.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
        return background
    return image.convert("RGB")


# ---------- Commands ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message."""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        f"Welcome to **PicTools** — your image toolkit.\n\n"
        f"**How to use:**\n"
        f"1️⃣ Send me any image\n"
        f"2️⃣ Choose what you want to do\n"
        f"3️⃣ Download the processed result\n\n"
        f"**Features:**\n"
        f"🗜️ Compress images\n"
        f"📐 Resize images\n"
        f"🔄 Convert formats\n"
        f"✨ Optimize quality\n"
        f"📦 Reduce file size\n\n"
        f"**Commands:**\n"
        f"/start - This menu\n"
        f"/help - Full instructions\n"
        f"/about - About this bot",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help text."""
    await update.message.reply_text(
        "🆘 **PicTools Help**\n\n"
        "**Step 1:** Send an image\n"
        "**Step 2:** Tap the action you want:\n\n"
        "🗜️ **Compress** — Reduce file size (keep quality)\n"
        "📐 **Resize** — Change dimensions\n"
        "🔄 **Convert** — Change format (JPG/PNG/WEBP)\n"
        "✨ **Optimize** — Best quality + small size\n\n"
        "**Supported input:** JPG, PNG, WEBP, BMP, GIF, TIFF\n"
        "**Supported output:** JPG, PNG, WEBP\n\n"
        "**Limits:**\n"
        "• Max file size: 20 MB\n"
        "• One image at a time",
        parse_mode="Markdown",
    )


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """About the bot."""
    await update.message.reply_text(
        "ℹ️ **About PicTools**\n\n"
        "PicTools is a free image utility bot. Compress, resize, convert, "
        "and optimize images right inside Telegram.\n\n"
        "No account. No signup. No API key. Just send an image.",
        parse_mode="Markdown",
    )


# ---------- Image Handler ----------

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming images or image documents."""
    message = update.message
    user_id = update.effective_user.id

    # Download the largest available image or document
    try:
        if message.photo:
            file = await message.photo[-1].get_file()
            original_name = "image.jpg"
        elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
            file = await message.document.get_file()
            original_name = message.document.file_name or "image"
        else:
            await message.reply_text("❌ Please send an image file.")
            return
    except Exception as e:
        logger.error(f"Download error: {e}")
        await message.reply_text("❌ Could not download the image.")
        return

    # Check file size (Telegram download limit)
    if file.file_size and file.file_size > 20 * 1024 * 1024:
        await message.reply_text("❌ Image too large. Max 20 MB.")
        return

    # Store in user context for later actions
    try:
        file_bytes = await file.download_as_bytearray()
    except Exception as e:
        logger.error(f"Bytearray error: {e}")
        await message.reply_text("❌ Failed to read the image.")
        return

    # Save original to context
    context.user_data["image_bytes"] = bytes(file_bytes)
    context.user_data["original_name"] = original_name

    # Try opening the image
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()
        fmt = detect_format(img)
        size = len(file_bytes)
        width, height = img.size
    except Exception as e:
        logger.error(f"PIL open error: {e}")
        await message.reply_text("❌ Unsupported or corrupted image file.")
        return

    # Build action menu
    keyboard = [
        [InlineKeyboardButton("🗜️ Compress", callback_data="act_compress")],
        [InlineKeyboardButton("📐 Resize", callback_data="act_resize")],
        [InlineKeyboardButton("🔄 Convert", callback_data="act_convert")],
        [InlineKeyboardButton("✨ Optimize", callback_data="act_optimize")],
    ]
    await message.reply_text(
        f"✅ **Image received!**\n\n"
        f"📄 Format: `{fmt}`\n"
        f"📐 Size: `{width}×{height}`\n"
        f"📦 File size: `{human_size(size)}`\n\n"
        f"**What would you like to do?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ---------- Callback Handlers ----------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()

    if "image_bytes" not in context.user_data:
        await query.edit_message_text("❌ Please send an image first.")
        return

    data = query.data

    if data == "act_compress":
        await show_compress_options(query)

    elif data == "act_resize":
        await show_resize_options(query)

    elif data == "act_convert":
        await show_convert_options(query)

    elif data == "act_optimize":
        await process_optimize(query, context)

    elif data.startswith("compress_"):
        quality_key = data.replace("compress_", "")
        await process_compress(query, context, quality_key)

    elif data.startswith("resize_"):
        preset = data.replace("resize_", "")
        await process_resize(query, context, preset)

    elif data.startswith("convert_"):
        target = data.replace("convert_", "").upper()
        await process_convert(query, context, target)


# ---------- Submenus ----------

async def show_compress_options(query):
    keyboard = [
        [InlineKeyboardButton("🌟 High Quality (90%)", callback_data="compress_high")],
        [InlineKeyboardButton("⚖️ Medium (75%)", callback_data="compress_medium")],
        [InlineKeyboardButton("📉 Low Size (50%)", callback_data="compress_low")],
        [InlineKeyboardButton("⬅️ Back", callback_data="act_back")],
    ]
    await query.edit_message_text(
        "🗜️ **Choose compression level:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def show_resize_options(query):
    keyboard = [
        [InlineKeyboardButton("🖥️ 1920 × 1080 (FHD)", callback_data="resize_1080")],
        [InlineKeyboardButton("📺 1280 × 720 (HD)", callback_data="resize_720")],
        [InlineKeyboardButton("📱 854 × 480 (SD)", callback_data="resize_480")],
        [InlineKeyboardButton("⬜ 1080 × 1080 (Square)", callback_data="resize_square")],
        [InlineKeyboardButton("🔳 500 × 500 (Thumb)", callback_data="resize_thumb")],
        [InlineKeyboardButton("⬅️ Back", callback_data="act_back")],
    ]
    await query.edit_message_text(
        "📐 **Choose a size:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def show_convert_options(query):
    keyboard = [
        [InlineKeyboardButton("🖼️ JPG", callback_data="convert_JPEG")],
        [InlineKeyboardButton("🖼️ PNG", callback_data="convert_PNG")],
        [InlineKeyboardButton("🖼️ WEBP", callback_data="convert_WEBP")],
        [InlineKeyboardButton("⬅️ Back", callback_data="act_back")],
    ]
    await query.edit_message_text(
        "🔄 **Convert to format:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ---------- Processors ----------

async def process_compress(query, context, quality_key):
    """Compress image at given quality."""
    await query.edit_message_text("⏳ Compressing...")

    try:
        quality = QUALITY_PRESETS[quality_key]
        img = Image.open(io.BytesIO(context.user_data["image_bytes"]))

        # Convert to RGB for JPEG output
        img_rgb = convert_to_rgb(img)

        buf = io.BytesIO()
        img_rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        buf.seek(0)

        original_size = len(context.user_data["image_bytes"])
        new_size = buf.getbuffer().nbytes
        saved = (1 - new_size / original_size) * 100

        await query.message.reply_document(
            document=InputFile(buf, filename="compressed.jpg"),
            caption=(
                f"🗜️ **Compressed!**\n\n"
                f"📦 Original: `{human_size(original_size)}`\n"
                f"📦 New: `{human_size(new_size)}`\n"
                f"💾 Saved: `{saved:.1f}%`"
            ),
            parse_mode="Markdown",
        )
        await query.delete_message()

    except Exception as e:
        logger.error(f"Compress error: {e}")
        await query.edit_message_text("❌ Compression failed.")


async def process_resize(query, context, preset):
    """Resize image to preset dimensions."""
    await query.edit_message_text("⏳ Resizing...")

    try:
        target_size = RESIZE_OPTIONS.get(preset)
        if not target_size:
            await query.edit_message_text("❌ Invalid preset.")
            return

        img = Image.open(io.BytesIO(context.user_data["image_bytes"]))
        fmt = detect_format(img)

        # Resize while preserving aspect ratio
        img_resized = ImageOps.contain(img, target_size, Image.LANCZOS)

        buf = io.BytesIO()
        if fmt in ("JPEG", "JPG"):
            img_resized = convert_to_rgb(img_resized)
            img_resized.save(buf, format="JPEG", quality=90, optimize=True)
        elif fmt == "PNG":
            img_resized.save(buf, format="PNG", optimize=True)
        elif fmt == "WEBP":
            img_resized.save(buf, format="WEBP", quality=90)
        else:
            img_resized = convert_to_rgb(img_resized)
            img_resized.save(buf, format="JPEG", quality=90, optimize=True)
        buf.seek(0)

        await query.message.reply_document(
            document=InputFile(buf, filename=f"resized_{target_size[0]}x{target_size[1]}.jpg"),
            caption=(
                f"📐 **Resized!**\n\n"
                f"📏 New size: `{img_resized.size[0]}×{img_resized.size[1]}`"
            ),
            parse_mode="Markdown",
        )
        await query.delete_message()

    except Exception as e:
        logger.error(f"Resize error: {e}")
        await query.edit_message_text("❌ Resize failed.")


async def process_convert(query, context, target):
    """Convert image to a target format."""
    await query.edit_message_text("⏳ Converting...")

    try:
        img = Image.open(io.BytesIO(context.user_data["image_bytes"]))

        buf = io.BytesIO()
        ext_map = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
        ext = ext_map.get(target, "png")

        if target == "JPEG":
            img = convert_to_rgb(img)
            img.save(buf, format="JPEG", quality=90, optimize=True)
        elif target == "PNG":
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            img.save(buf, format="PNG", optimize=True)
        elif target == "WEBP":
            img.save(buf, format="WEBP", quality=90)

        buf.seek(0)

        await query.message.reply_document(
            document=InputFile(buf, filename=f"converted.{ext}"),
            caption=f"🔄 **Converted to {target}!**",
            parse_mode="Markdown",
        )
        await query.delete_message()

    except Exception as e:
        logger.error(f"Convert error: {e}")
        await query.edit_message_text("❌ Conversion failed.")


async def process_optimize(query, context):
    """Optimize: best quality-to-size ratio."""
    await query.edit_message_text("⏳ Optimizing...")

    try:
        img = Image.open(io.BytesIO(context.user_data["image_bytes"]))
        img_rgb = convert_to_rgb(img)

        original_size = len(context.user_data["image_bytes"])

        # Try WEBP for best compression (if possible), else JPEG
        buf = io.BytesIO()
        img_rgb.save(buf, format="WEBP", quality=85, method=6)
        buf.seek(0)

        # Compare with JPEG
        buf_jpeg = io.BytesIO()
        img_rgb.save(buf_jpeg, format="JPEG", quality=85, optimize=True)
        buf_jpeg.seek(0)

        if buf.getbuffer().nbytes < buf_jpeg.getbuffer().nbytes:
            final_buf = buf
            ext = "webp"
            fmt = "WEBP"
        else:
            final_buf = buf_jpeg
            ext = "jpg"
            fmt = "JPEG"

        new_size = final_buf.getbuffer().nbytes
        saved = (1 - new_size / original_size) * 100

        await query.message.reply_document(
            document=InputFile(final_buf, filename=f"optimized.{ext}"),
            caption=(
                f"✨ **Optimized!**\n\n"
                f"📄 Format: `{fmt}`\n"
                f"📦 Original: `{human_size(original_size)}`\n"
                f"📦 New: `{human_size(new_size)}`\n"
                f"💾 Saved: `{saved:.1f}%`"
            ),
            parse_mode="Markdown",
        )
        await query.delete_message()

    except Exception as e:
        logger.error(f"Optimize error: {e}")
        await query.edit_message_text("❌ Optimization failed.")


# ---------- Error Handler ----------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


# ---------- Main ----------

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set!")
        return

    application = ApplicationBuilder().token(token).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))

    # Callback queries (buttons)
    application.add_handler(CallbackQueryHandler(button_handler))

    # Image messages (photos and image documents)
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(
        MessageHandler(filters.Document.IMAGE, handle_image)
    )

    # Errors
    application.add_error_handler(error_handler)

    logger.info("Starting @PicToolsBot with long polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
