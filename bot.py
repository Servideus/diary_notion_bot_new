import os
import logging
from datetime import time
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update, constants
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ApplicationHandlerStop
)

import pytz
from dialogs import (
    scheduled_task,
    process_text_message
)

load_dotenv(Path(__file__).with_name(".env"))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,  # можете поменять на DEBUG, если надо
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.INFO)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('DATABASE_ID')
ALLOWED_USER_ID = int(os.getenv('ALLOWED_USER_ID') or '0')
TIMEZONE = os.getenv('TIMEZONE', 'UTC')

async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! Я бот, который поможет тебе заполнять опрос в Notion.\n"
        "Используй команду /schedule, чтобы настроить ежедневное напоминание, например: /schedule 09:00\n"
        "Или /run_task_manually, чтобы запустить опрос вручную."
    )

async def cancel(update: Update, context: CallbackContext):
    """
    Отмена текущего опроса: чистим chat_data.
    """
    context.chat_data.clear()
    await update.message.reply_text("Опрос отменён.")
    return  # Ничего не возвращаем, т.к. ConversationHandler не используем.

async def schedule_cmd(update: Update, context: CallbackContext):
    """
    Команда /schedule HH:MM для настройки ежедневного напоминания.
    Добавляем misfire_grace_time, чтобы избежать missed job warning при малых опозданиях.
    """
    if not context.args:
        await update.message.reply_text("Использование: /schedule HH:MM (например, /schedule 09:00)")
        return

    time_str = context.args[0]
    if ':' not in time_str:
        await update.message.reply_text("Неверный формат времени. Используйте HH:MM (например, 09:00).")
        return

    try:
        hour, minute = map(int, time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Неверный формат времени. Используйте HH:MM (например, 09:00).")
        return

    job_name = str(update.effective_chat.id)
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    context.job_queue.run_daily(
        scheduled_task,
        time=time(hour, minute, tzinfo=pytz.timezone(TIMEZONE)),
        chat_id=update.effective_chat.id,
        name=job_name,
        job_kwargs={'misfire_grace_time': 60},
    )
    await update.message.reply_text(
        f"Готово! Ежедневный опрос в {time_str}, часовой пояс {TIMEZONE}."
    )

async def run_task_manually(update: Update, context: CallbackContext):
    """
    Команда /run_task_manually для ручного запуска опроса.
    """
    chat_id = update.effective_chat.id
    context._chat_id = chat_id  # для scheduled_task
    await update.message.reply_text("Задача запущена вручную.")
    await scheduled_task(context)

async def error_handler(update: Update, context: CallbackContext):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка при обработке запроса."
            )
        except Exception as e:
            logger.error(f"Error sending error message: {str(e)}")

async def restrict_access(update: Update, context: CallbackContext):
    if (not update.effective_user or update.effective_user.id != ALLOWED_USER_ID
            or not update.effective_chat or update.effective_chat.type != 'private'):
        raise ApplicationHandlerStop


def main():
    required = {'TELEGRAM_TOKEN': TELEGRAM_TOKEN, 'NOTION_TOKEN': NOTION_TOKEN,
                'DATABASE_ID': DATABASE_ID, 'ALLOWED_USER_ID': ALLOWED_USER_ID}
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError('Missing configuration: ' + ', '.join(missing))
    pytz.timezone(TIMEZONE)
    try:
        application = Application.builder() \
            .token(TELEGRAM_TOKEN) \
            .get_updates_read_timeout(30) \
            .get_updates_write_timeout(30) \
            .get_updates_connect_timeout(30) \
            .get_updates_pool_timeout(30) \
            .build()

        # Храним токены Notion в bot_data, чтобы dialogs.py мог их использовать
        application.bot_data['NOTION_TOKEN'] = NOTION_TOKEN
        application.bot_data['DATABASE_ID'] = DATABASE_ID

        application.add_handler(MessageHandler(filters.ALL, restrict_access), group=-1)

        # Хендлеры
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('cancel', cancel))
        application.add_handler(CommandHandler('schedule', schedule_cmd))
        application.add_handler(CommandHandler('run_task_manually', run_task_manually))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text_message))

        application.add_error_handler(error_handler)

        logger.info("Starting bot polling...")
        application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Critical error in main: {str(e)}")
        raise

if __name__ == '__main__':
    main()
