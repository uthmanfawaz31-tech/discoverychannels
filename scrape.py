import os
import sys
import re
import csv
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.types import User
from telethon.errors import ChatAdminRequiredError, ChannelPrivateError, FloodWaitError
import config

if not config.validate_config():
    sys.exit(1)

client = TelegramClient("scraper_session", config.API_ID, config.API_HASH)

def clean_input(text: str) -> str:
    text = text.strip()
    match = re.search(r"(?:https?://)?(?:www\.)?t\.me/([a-zA-Z0-9_]{4,})", text)
    if match:
        return match.group(1)
    if text.startswith("@"):
        return text[1:]
    return text

async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else input("Enter Telegram channel link or @username: ").strip()
    target_clean = clean_input(target)

    if config.BOT_TOKEN and not config.PHONE_NUMBER:
        print("[*] Starting using BOT_TOKEN...")
        await client.start(bot_token=config.BOT_TOKEN)
    else:
        print("[*] Starting using User Session...")
        await client.start(phone=config.PHONE_NUMBER if config.PHONE_NUMBER else None)

    print(f"[*] Resolving: {target_clean}...")
    try:
        entity = await client.get_entity(target_clean)
        title = getattr(entity, 'title', target_clean)
        print(f"[+] Found: {title} (ID: {entity.id})")
        print("[*] Fetching all members, please wait...")

        members = []
        async for user in client.iter_participants(entity):
            if not isinstance(user, User):
                continue
            first_name = user.first_name or ""
            last_name = user.last_name or ""
            full_name = f"{first_name} {last_name}".strip() or "Deleted Account"
            username = f"@{user.username}" if user.username else "N/A"
            phone = user.phone if getattr(user, 'phone', None) else "N/A"

            members.append({
                "User ID": user.id,
                "First Name": first_name,
                "Last Name": last_name,
                "Full Name": full_name,
                "Username": username,
                "Phone": phone,
                "Is Bot": "Yes" if user.bot else "No"
            })

        print(f"\n[+] Total Members Detected: {len(members)}")
        print("=" * 60)
        for i, m in enumerate(members[:20], 1):
            print(f"{i:3d}. {m['Full Name']:<25} | {m['Username']:<18} | ID: {m['User ID']}")

        if len(members) > 20:
            print(f"... and {len(members) - 20} more members.")
        print("=" * 60)

        os.makedirs("exports", exist_ok=True)
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:30]
        csv_file = f"exports/members_{sanitized}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["User ID", "First Name", "Last Name", "Full Name", "Username", "Phone", "Is Bot"])
            writer.writeheader()
            writer.writerows(members)

        print(f"[+] All members saved to: {csv_file}")

    except ChatAdminRequiredError:
        print("[!] Error: Telegram's server requires admin privileges to access member list for this channel.")
    except ChannelPrivateError:
        print("[!] Error: Channel is private or not accessible.")
    except FloodWaitError as e:
        print(f"[!] Rate limit reached. Wait {e.seconds} seconds.")
    except Exception as e:
        print(f"[!] Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
