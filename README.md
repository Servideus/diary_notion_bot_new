# Telegram diary questionnaire for Notion

A single-user Telegram bot that creates a Notion page and asks questions based on the database's editable properties. Answers are saved to Notion as the questionnaire progresses.

## Setup

Requires Python 3.11 or later, your own BotFather token, and a Notion integration with read/write access to your database.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill in `TELEGRAM_TOKEN`, `NOTION_TOKEN`, `DATABASE_ID` and `ALLOWED_USER_ID` (your numeric Telegram user ID). Access is restricted to that user in a private chat. Set `TIMEZONE` to an IANA timezone, for example `UTC`.

Share your database with the Notion integration. Supported property types: title, text, number, select, multi-select, date and checkbox. Formula, relation and other calculated properties are skipped. Property names become questions; no personal questionnaire or example diary entries are bundled. The order follows the database schema returned by the API.

This version retains the original `Notion-Version: 2022-06-28` database API. Use a database with a single data source. New multi-source configurations need migration to the data-source API; see [Notion's upgrade guide](https://developers.notion.com/docs/upgrade-guide-2025-09-03).

## Run

```powershell
./start_bot.bat
```

- `/start`: help.
- `/run_task_manually`: create a page and start the questionnaire.
- `/schedule HH:MM`: replace the daily reminder for this chat.
- `/cancel`: end the active questionnaire; the created page remains in Notion.

Keep this process running for reminders. Schedules and questionnaire state are in memory and are lost on restart; reissue `/schedule` after restarting. Use a dedicated test database first. Diary answers go to Telegram and Notion. Runtime logs remain local and may contain error details; do not publish them.

## Verification and publication

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The public export excludes original credentials, SSH keys, logs and personal property names. A fresh Git history is used. The export also fixes the reminder's chat context, prevents advancing after a failed Notion write, and clears questionnaire state after completion.

Offline tests cover access restrictions, scheduling with chat context, property parsing and failed/successful answer handling. Live Telegram delivery and Notion permissions are not verified. Scheduling follows the [python-telegram-bot JobQueue documentation](https://docs.python-telegram-bot.org/en/stable/telegram.ext.jobqueue.html).

MIT license; third-party dependencies retain their own licenses.
