import os
import re
import csv
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User
from telethon.errors import (
    ChatAdminRequiredError,
    ChannelPrivateError,
    UserBannedInChannelError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError
)
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest

import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("TelegramMemberBot")

if not config.validate_config():
    exit(1)

# Initialize bot client
bot = TelegramClient("bot_session", config.API_ID, config.API_HASH)

# Optional user client for channels where bot tokens are restricted
user_client = None
if config.PHONE_NUMBER:
    user_client = TelegramClient("user_session", config.API_ID, config.API_HASH)


def clean_channel_input(raw_text: str) -> str:
    """Extract clean username, invite link, or channel identifier."""
    raw_text = raw_text.strip()

    # Matches https://t.me/joinchat/XXXXX or https://t.me/+XXXXX
    invite_match = re.search(r"t\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)", raw_text)
    if invite_match:
        return f"+{invite_match.group(1)}"

    # Matches https://t.me/username or t.me/username
    link_match = re.search(r"(?:https?://)?(?:www\.)?t\.me/([a-zA-Z0-9_]{4,})", raw_text)
    if link_match:
        return link_match.group(1)

    # Matches @username
    if raw_text.startswith("@"):
        return raw_text[1:]

    return raw_text


def save_members_to_csv(members: list, filename: str) -> str:
    """Export member details into a CSV file."""
    os.makedirs("exports", exist_ok=True)
    file_path = os.path.join("exports", filename)

    fieldnames = ["User ID", "First Name", "Last Name", "Full Name", "Username", "Phone", "Is Bot"]
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in members:
            writer.writerow(m)

    return file_path


async def get_active_client():
    """Return user client if active and authorized, otherwise bot client."""
    if user_client:
        try:
            if not user_client.is_connected():
                await user_client.connect()
            if await user_client.is_user_authorized():
                return user_client
        except Exception as e:
            logger.warning(f"User client not available, using bot client: {e}")
    return bot


@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    welcome_text = (
        "🤖 **Telegram Channel & Group Member Detector**\n\n"
        "Send me the link or username of any Telegram channel or group.\n\n"
        "**Supported Formats:**\n"
        "• `https://t.me/example_channel`\n"
        "• `@example_channel`\n"
        "• `https://t.me/+InviteHash`\n\n"
        "I will detect all members and send you the complete list along with a downloadable CSV file!"
    )
    await event.respond(welcome_text)


@bot.on(events.NewMessage(pattern="/help"))
async def help_handler(event):
    await event.respond(
        "Paste any public channel/group link or username in chat to detect and view all its members."
    )


@bot.on(events.NewMessage)
async def message_handler(event):
    text = event.raw_text.strip()
    if text.startswith("/"):
        return

    target = clean_channel_input(text)
    status_msg = await event.respond(f"🔍 **Analyzing target:** `{target}`...\nPlease wait.")

    fetch_client = await get_active_client()

    try:
        # Resolve target entity
        entity = None
        if target.startswith("+"):
            invite_hash = target[1:]
            try:
                invite = await fetch_client(CheckChatInviteRequest(invite_hash))
                entity = invite.chat
            except Exception as e:
                await status_msg.edit(f"❌ Could not access private invite link: {e}")
                return
        else:
            entity = await fetch_client.get_entity(target)

        title = getattr(entity, "title", str(target))
        chat_id = getattr(entity, "id", "unknown")
        is_channel = getattr(entity, "broadcast", False)
        is_megagroup = getattr(entity, "megagroup", False)

        chat_type = "Channel" if is_channel else ("Supergroup" if is_megagroup else "Chat")
        await status_msg.edit(f"📥 Found **{chat_type}**: `{title}`\nFetching members now...")

        members_data = []
        async for user in fetch_client.iter_participants(entity):
            if not isinstance(user, User):
                continue
            first_name = user.first_name or ""
            last_name = user.last_name or ""
            full_name = f"{first_name} {last_name}".strip() or "Deleted Account"
            username = f"@{user.username}" if user.username else "N/A"
            phone = user.phone if getattr(user, "phone", None) else "N/A"

            members_data.append({
                "User ID": user.id,
                "First Name": first_name,
                "Last Name": last_name,
                "Full Name": full_name,
                "Username": username,
                "Phone": phone,
                "Is Bot": "Yes" if user.bot else "No"
            })

        total_count = len(members_data)
        if total_count == 0:
            await status_msg.edit(f"⚠️ No members could be retrieved from `{title}`.")
            return

        # Generate CSV file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:30]
        csv_filename = f"members_{sanitized_title}_{timestamp}.csv"
        csv_path = save_members_to_csv(members_data, csv_filename)

        # Build response message with preview
        preview_limit = min(15, total_count)
        preview_lines = []
        for i, m in enumerate(members_data[:preview_limit], 1):
            user_display = m['Username'] if m['Username'] != "N/A" else m['Full Name']
            preview_lines.append(f"{i}. {user_display} `(ID: {m['User ID']})`")

        preview_text = "\n".join(preview_lines)
        summary = (
            f"✅ **Extraction Complete!**\n\n"
            f"📌 **Target:** {title}\n"
            f"👥 **Total Members Detected:** `{total_count}`\n\n"
            f"📋 **Preview (Top {preview_limit}):**\n{preview_text}\n\n"
            f"📁 *The full member database has been attached below as a CSV file.*"
        )

        await status_msg.delete()
        await event.respond(summary)
        await event.respond(file=csv_path)

    except ChatAdminRequiredError:
        await status_msg.edit(
            f"❌ **Admin Permission Required by Telegram Server**\n\n"
            f"`{target}` is a broadcast channel. Telegram's servers restrict member list access "
            f"in broadcast channels exclusively to channel administrators."
        )
    except ChannelPrivateError:
        await status_msg.edit(
            f"❌ **Channel is Private**\n\n"
            f"You must add this bot/account as a member or administrator to `{target}` to view members."
        )
    except UserBannedInChannelError:
        await status_msg.edit("❌ The account/bot is banned from viewing this channel.")
    except FloodWaitError as e:
        await status_msg.edit(f"⏳ Telegram rate limit reached. Please wait {e.seconds} seconds.")
    except ValueError as e:
        await status_msg.edit(f"❌ Invalid link or channel not found: `{target}`\nError: {e}")
    except Exception as e:
        logger.exception("Unexpected error during member extraction")
        await status_msg.edit(f"❌ An error occurred: `{type(e).__name__}: {e}`")


async def main():
    logger.info("Starting Telegram Bot...")
    await bot.start(bot_token=config.BOT_TOKEN)

    if user_client:
        try:
            logger.info("Initializing User Client...")
            await user_client.start(phone=config.PHONE_NUMBER)
            logger.info("User Client connected successfully.")
        except Exception as e:
            logger.warning(f"Could not initialize user client: {e}")

    logger.info("Bot is active and listening for messages.")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    bot.loop.run_until_complete(main())
