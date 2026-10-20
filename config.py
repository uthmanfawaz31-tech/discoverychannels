import os
import sys
from dotenv import load_dotenv

load_dotenv()

API_ID_RAW = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")

def validate_config():
    errors = []
    if not API_ID_RAW:
        errors.append("API_ID is missing in .env")
    if not API_HASH:
        errors.append("API_HASH is missing in .env")
    if not BOT_TOKEN and not PHONE_NUMBER:
        errors.append("At least BOT_TOKEN or PHONE_NUMBER must be provided in .env")

    if errors:
        print("\n[Configuration Error]")
        for err in errors:
            print(f"- {err}")
        print("\nPlease update the .env file with your Telegram credentials.")
        return False
    return True

try:
    API_ID = int(API_ID_RAW) if API_ID_RAW else 0
except ValueError:
    API_ID = 0
