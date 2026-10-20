# Telegram Channel & Group Member Detector

A Telegram bot and scraper tool that detects all members from a given Telegram channel or group link, displays them directly in chat/terminal, and exports the complete member database to a CSV spreadsheet.

---

## 🚀 Quick Setup (2 Minutes)

### 1. Configure Credentials
Open the `.env` file in this directory and enter your Telegram credentials:

```ini
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
PHONE_NUMBER=
```

* **`API_ID` & `API_HASH`**: Get them for free from [my.telegram.org](https://my.telegram.org) (under "API development tools").
* **`BOT_TOKEN`**: Get it from [@BotFather](https://t.me/BotFather) on Telegram.
* **`PHONE_NUMBER`** *(Optional)*: If you want to scrape using your personal account privileges (useful for public channels/supergroups where bots might be restricted), provide your phone number with country code (e.g. `+1234567890`).

---

## 🤖 Running the Telegram Bot

Run:
```bash
python bot.py
```

1. Open your bot in Telegram and click **/start**.
2. Paste any channel or group link (e.g., `https://t.me/example_channel` or `@example_channel`).
3. The bot will:
   - Detect and count all members.
   - Print a live preview of members in the chat.
   - Send you an attached `.csv` file containing the full roster with IDs, usernames, and names.

---

## 💻 Running via CLI / Terminal

If you prefer to run it directly from your command line without chatting in Telegram:

```bash
python scrape.py https://t.me/example_channel
```
or simply:
```bash
python scrape.py
```
The script will fetch all participants and save them into the `exports/` folder.
