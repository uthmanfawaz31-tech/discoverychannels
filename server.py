import os
import re
import csv
import io
import json
import logging
from typing import Optional, List, Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv, set_key
from telethon import TelegramClient
from telethon.tl.types import User, Channel, Chat
from telethon.errors import (
    ChatAdminRequiredError,
    ChannelPrivateError,
    UserBannedInChannelError,
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    BotMethodInvalidError
)
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebScraper")

app = FastAPI(title="Telegram Channel & Group Member Explorer")

ENV_PATH = os.path.abspath(".env")

# Global state for client and auth
user_client: Optional[TelegramClient] = None
bot_client: Optional[TelegramClient] = None
auth_phone_code_hash: Optional[str] = None
auth_phone_number: Optional[str] = None


def get_env_credentials():
    load_dotenv(ENV_PATH, override=True)
    return {
        "api_id": os.getenv("API_ID", "").strip(),
        "api_hash": os.getenv("API_HASH", "").strip(),
        "bot_token": os.getenv("BOT_TOKEN", "").strip(),
        "phone_number": os.getenv("PHONE_NUMBER", "").strip(),
    }


async def get_or_create_user_client() -> Optional[TelegramClient]:
    """Returns an initialized user client if credentials exist."""
    global user_client
    creds = get_env_credentials()
    if not creds["api_id"] or not creds["api_hash"]:
        return None

    try:
        api_id = int(creds["api_id"])
    except ValueError:
        return None

    if user_client is None:
        user_client = TelegramClient("user_session", api_id, creds["api_hash"])

    if not user_client.is_connected():
        await user_client.connect()

    return user_client


async def get_or_create_bot_client() -> Optional[TelegramClient]:
    """Returns an initialized bot client if bot token exists."""
    global bot_client
    creds = get_env_credentials()
    if not creds["api_id"] or not creds["api_hash"] or not creds["bot_token"]:
        return None

    try:
        api_id = int(creds["api_id"])
    except ValueError:
        return None

    if bot_client is None:
        bot_client = TelegramClient("bot_session", api_id, creds["api_hash"])

    if not bot_client.is_connected():
        await bot_client.start(bot_token=creds["bot_token"])

    return bot_client


async def get_active_client():
    """Prefers authenticated user client, otherwise falls back to bot client."""
    u_client = await get_or_create_user_client()
    if u_client and await u_client.is_user_authorized():
        return u_client, "user"

    b_client = await get_or_create_bot_client()
    if b_client and await b_client.is_user_authorized():
        return b_client, "bot"

    if u_client:
        return u_client, "user_unauthorized"

    raise HTTPException(
        status_code=400,
        detail="Telegram credentials not configured. Please open Settings.",
    )


class SettingsPayload(BaseModel):
    api_id: str
    api_hash: str
    bot_token: Optional[str] = ""
    phone_number: Optional[str] = ""


class SendCodePayload(BaseModel):
    phone: str


class VerifyCodePayload(BaseModel):
    code: str
    password: Optional[str] = ""


class ExtractRequest(BaseModel):
    url: str
    limit: Optional[int] = 0
    scan_posts: Optional[int] = 50


def clean_channel_input(raw_text: str) -> str:
    raw_text = raw_text.strip()
    invite_match = re.search(r"t\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)", raw_text)
    if invite_match:
        return f"+{invite_match.group(1)}"

    link_match = re.search(r"(?:https?://)?(?:www\.)?t\.me/([a-zA-Z0-9_]{4,})", raw_text)
    if link_match:
        return link_match.group(1)

    if raw_text.startswith("@"):
        return raw_text[1:]

    return raw_text


@app.get("/api/settings")
async def get_settings():
    creds = get_env_credentials()
    is_user_auth = False
    u_client = await get_or_create_user_client()
    if u_client:
        is_user_auth = await u_client.is_user_authorized()

    is_bot_auth = False
    b_client = await get_or_create_bot_client()
    if b_client:
        is_bot_auth = await b_client.is_user_authorized()

    masked_hash = creds["api_hash"][:4] + "••••" if len(creds["api_hash"]) > 4 else creds["api_hash"]
    masked_token = creds["bot_token"][:6] + "••••" if len(creds["bot_token"]) > 6 else creds["bot_token"]

    return {
        "is_configured": bool(creds["api_id"] and creds["api_hash"]),
        "is_user_authorized": is_user_auth,
        "is_bot_authorized": is_bot_auth,
        "active_mode": "User Account (Full Access)" if is_user_auth else ("Bot Token" if is_bot_auth else "Not Logged In"),
        "api_id": creds["api_id"],
        "api_hash_preview": masked_hash,
        "bot_token_preview": masked_token,
        "phone_number": creds["phone_number"],
    }


@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    global user_client, bot_client
    if user_client and user_client.is_connected():
        await user_client.disconnect()
        user_client = None
    if bot_client and bot_client.is_connected():
        await bot_client.disconnect()
        bot_client = None

    set_key(ENV_PATH, "API_ID", payload.api_id.strip())
    set_key(ENV_PATH, "API_HASH", payload.api_hash.strip())
    if payload.bot_token is not None:
        set_key(ENV_PATH, "BOT_TOKEN", payload.bot_token.strip())
    if payload.phone_number is not None:
        set_key(ENV_PATH, "PHONE_NUMBER", payload.phone_number.strip())

    return {"status": "success", "message": "Settings saved successfully"}


@app.post("/api/auth/send_code")
async def send_auth_code(payload: SendCodePayload):
    global auth_phone_code_hash, auth_phone_number
    u_client = await get_or_create_user_client()
    if not u_client:
        raise HTTPException(status_code=400, detail="Please configure API_ID and API_HASH first.")

    phone = payload.phone.strip()
    try:
        sent_code = await u_client.send_code_request(phone)
        auth_phone_code_hash = sent_code.phone_code_hash
        auth_phone_number = phone
        return {
            "success": True,
            "message": f"Verification code sent to {phone} via Telegram app or SMS."
        }
    except Exception as e:
        logger.exception("Error sending auth code")
        raise HTTPException(status_code=400, detail=f"Failed to send code: {e}")


@app.post("/api/auth/verify_code")
async def verify_auth_code(payload: VerifyCodePayload):
    global auth_phone_code_hash, auth_phone_number
    u_client = await get_or_create_user_client()
    if not u_client or not auth_phone_number or not auth_phone_code_hash:
        raise HTTPException(status_code=400, detail="No pending login request. Please send code first.")

    try:
        await u_client.sign_in(
            phone=auth_phone_number,
            code=payload.code.strip(),
            phone_code_hash=auth_phone_code_hash
        )
        return {"success": True, "message": "Successfully logged in as Telegram User!"}
    except SessionPasswordNeededError:
        if not payload.password:
            return {"needs_password": True, "message": "Two-factor authentication (2FA) password required."}
        await u_client.sign_in(password=payload.password.strip())
        return {"success": True, "message": "Successfully logged in with 2FA password!"}
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid or expired code: {e}")
    except Exception as e:
        logger.exception("Error verifying auth code")
        raise HTTPException(status_code=400, detail=f"Verification failed: {e}")


@app.post("/api/extract")
async def extract_members(req: ExtractRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Please provide a valid Telegram link or username.")

    target = clean_channel_input(req.url)
    client, client_mode = await get_active_client()

    if client_mode == "user_unauthorized":
        raise HTTPException(
            status_code=401,
            detail="User account not logged in. Click Settings ⚙️ and click 'Log In with Phone' to activate user privileges, or add your Bot Token."
        )

    try:
        # 1. Resolve entity
        if target.startswith("+"):
            invite_hash = target[1:]
            invite = await client(CheckChatInviteRequest(invite_hash))
            entity = invite.chat
        else:
            entity = await client.get_entity(target)

        title = getattr(entity, "title", str(target))
        chat_id = getattr(entity, "id", "unknown")
        is_channel = getattr(entity, "broadcast", False)
        is_megagroup = getattr(entity, "megagroup", False)
        chat_type = "Channel" if is_channel else ("Supergroup" if is_megagroup else "Chat")

        unique_users: Dict[int, dict] = {}
        extraction_method = "Direct Member List"

        # Attempt 1: Direct Participant Extraction (Works for Groups and Admin Channels)
        direct_scrape_success = False
        try:
            iter_limit = req.limit if req.limit and req.limit > 0 else None
            async for user in client.iter_participants(entity, limit=iter_limit):
                if not isinstance(user, User):
                    continue
                first_name = user.first_name or ""
                last_name = user.last_name or ""
                full_name = f"{first_name} {last_name}".strip() or "Deleted Account"
                username = f"@{user.username}" if user.username else ""
                phone = user.phone if getattr(user, "phone", None) else ""

                unique_users[user.id] = {
                    "id": user.id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": full_name,
                    "username": username,
                    "phone": phone,
                    "is_bot": bool(user.bot),
                    "source": "Subscribed Member"
                }
            direct_scrape_success = True
        except ChatAdminRequiredError:
            logger.info("Direct participants list is restricted by Telegram. Falling back to commenters & linked chat...")
        except BotMethodInvalidError:
            raise HTTPException(
                status_code=403,
                detail="Telegram restricts Bot Tokens from scraping channel members. Please log in with your Phone in Settings ⚙️ to use Account mode."
            )

        # Attempt 2: Channel Fallback (Linked Discussion + Post Commenters)
        if not direct_scrape_success and is_channel:
            extraction_method = "Post Commenters & Discussion Community"

            # Check linked discussion group
            try:
                full_info = await client(GetFullChannelRequest(entity))
                linked_chat_id = getattr(full_info.full_chat, "linked_chat_id", None)
                if linked_chat_id:
                    logger.info(f"Found linked discussion chat ID: {linked_chat_id}")
                    linked_chat = await client.get_entity(linked_chat_id)
                    try:
                        async for user in client.iter_participants(linked_chat, limit=200):
                            if isinstance(user, User) and user.id not in unique_users:
                                first_name = user.first_name or ""
                                last_name = user.last_name or ""
                                full_name = f"{first_name} {last_name}".strip() or "Deleted Account"
                                unique_users[user.id] = {
                                    "id": user.id,
                                    "first_name": first_name,
                                    "last_name": last_name,
                                    "full_name": full_name,
                                    "username": f"@{user.username}" if user.username else "",
                                    "phone": user.phone if getattr(user, "phone", None) else "",
                                    "is_bot": bool(user.bot),
                                    "source": "Discussion Community"
                                }
                    except Exception as e:
                        logger.warning(f"Could not iterate linked chat: {e}")
            except Exception as e:
                logger.warning(f"Could not fetch full channel info: {e}")

            # Scan recent posts for commenters
            posts_to_scan = req.scan_posts or 50
            logger.info(f"Scanning up to {posts_to_scan} recent posts for active commenters...")
            try:
                async for message in client.iter_messages(entity, limit=posts_to_scan):
                    # Check if post has replies/comments
                    if message.replies and message.replies.replies > 0:
                        try:
                            async for comment in client.iter_messages(entity, reply_to=message.id, limit=50):
                                sender = await comment.get_sender()
                                if isinstance(sender, User) and sender.id not in unique_users:
                                    first_name = sender.first_name or ""
                                    last_name = sender.last_name or ""
                                    full_name = f"{first_name} {last_name}".strip() or "Deleted Account"
                                    unique_users[sender.id] = {
                                        "id": sender.id,
                                        "first_name": first_name,
                                        "last_name": last_name,
                                        "full_name": full_name,
                                        "username": f"@{sender.username}" if sender.username else "",
                                        "phone": sender.phone if getattr(sender, "phone", None) else "",
                                        "is_bot": bool(sender.bot),
                                        "source": "Post Commenter"
                                    }
                        except Exception as e:
                            logger.debug(f"Error reading comments on msg {message.id}: {e}")
            except Exception as e:
                logger.warning(f"Error scanning post messages: {e}")

        members_list = list(unique_users.values())

        if not members_list:
            if is_channel:
                raise HTTPException(
                    status_code=403,
                    detail="This channel has its subscriber list hidden by Telegram, and has no public comments or discussion groups enabled to detect members from."
                )
            else:
                raise HTTPException(status_code=404, detail="No members detected.")

        return {
            "success": True,
            "title": title,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "extraction_method": extraction_method,
            "total_detected": len(members_list),
            "members": members_list,
        }

    except ChannelPrivateError:
        raise HTTPException(
            status_code=403,
            detail="This channel is private. Your account must be joined to this channel to access it.",
        )
    except UserBannedInChannelError:
        raise HTTPException(status_code=403, detail="The connected account is banned in this channel.")
    except FloodWaitError as e:
        raise HTTPException(status_code=429, detail=f"Rate limit reached. Please wait {e.seconds} seconds.")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Extraction error")
        raise HTTPException(status_code=500, detail=f"Error: {type(e).__name__}: {str(e)}")


@app.post("/api/export_csv")
async def export_csv(request: Request):
    data = await request.json()
    members = data.get("members", [])
    title = data.get("title", "members")

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "first_name", "last_name", "full_name", "username", "phone", "is_bot", "source"],
    )
    writer.writeheader()
    for m in members:
        writer.writerow({
            "id": m.get("id"),
            "first_name": m.get("first_name"),
            "last_name": m.get("last_name"),
            "full_name": m.get("full_name"),
            "username": m.get("username"),
            "phone": m.get("phone"),
            "is_bot": "Yes" if m.get("is_bot") else "No",
            "source": m.get("source", "Member"),
        })

    output.seek(0)
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", title)[:30]
    filename = f"{sanitized}_members.csv"

    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Frontend index.html missing</h1>"


os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
