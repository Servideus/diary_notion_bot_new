import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext
from notion_utils import (
    create_new_page,
    get_notion_properties,
    update_notion_property
)

logger = logging.getLogger(__name__)

async def scheduled_task(context: CallbackContext):
    """
    APScheduler вызывает эту функцию по расписанию.
    Создаём новую запись в Notion и начинаем опрос.
    """
    if context.job:
        chat_id = context.job.chat_id
        logger.info(f"scheduled_task: запущен через JobQueue, chat_id={chat_id}")
    else:
        chat_id = getattr(context, '_chat_id', None)
        logger.info(f"scheduled_task: ручной запуск, chat_id={chat_id}")

    if not chat_id:
        logger.warning("scheduled_task: нет chat_id, выходим.")
        return

    try:
        await begin_questionnaire(chat_id, context)
    except Exception as e:
        logger.error(f"Error in scheduled_task for chat {chat_id}: {str(e)}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Произошла ошибка при выполнении запланированного опроса. Пожалуйста, проверьте работу бота командой /start"
            )
        except Exception as send_error:
            logger.error(f"Could not send error message to user: {str(send_error)}")


async def begin_questionnaire(chat_id: int, context: CallbackContext):
    """
    Начало опроса:
      - Очищаем любые старые данные по опросу
      - Создаём новую запись в Notion
      - Получаем список свойств
      - Начинаем задавать вопросы по очереди
    """
    chat_data = context.chat_data
    bot_data = context.bot_data

    # Start a new questionnaire
    chat_data.clear()

    notion_token = bot_data['NOTION_TOKEN']
    database_id = bot_data['DATABASE_ID']

    new_page_id = await create_new_page(notion_token, database_id)
    if not new_page_id:
        await context.bot.send_message(
            chat_id,
            "Не удалось создать новую запись в Notion. Пожалуйста, попробуйте позже."
        )
        return

    properties = await get_notion_properties(notion_token, database_id)
    if not properties:
        await context.bot.send_message(
            chat_id,
            "Не удалось получить свойства из Notion. Пожалуйста, попробуйте позже."
        )
        return

    chat_data['page_id'] = new_page_id
    chat_data['properties'] = properties
    chat_data['current_property_index'] = 0  # будем перебирать свойства по очереди

    await context.bot.send_message(chat_id, "Опрос начался! Отвечайте на вопросы.")
    await ask_next_question(chat_id, context)


async def ask_next_question(chat_id: int, context: CallbackContext):
    """
    Задаёт следующий вопрос. Если вопросы закончились, говорит пользователю «Опрос завершён».
    """
    chat_data = context.chat_data
    current_property_index = chat_data['current_property_index']
    properties = chat_data['properties']

    if current_property_index >= len(properties):
        # All answers have been saved. Remove active questionnaire state.
        chat_data.clear()
        await context.bot.send_message(chat_id, "Опрос завершён. Все ответы сохранены в Notion.")
        return

    current_prop = properties[current_property_index]
    question_text = current_prop['name']
    prop_type = current_prop['type']

    if prop_type == 'select':
        options = [o['name'] for o in current_prop['options']]
        keyboard = [[opt] for opt in options]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await context.bot.send_message(chat_id, question_text, reply_markup=reply_markup)
        return

    if prop_type == 'multi_select':
        options = [o['name'] for o in current_prop['options']]
        question_text += f" (выберите несколько, вводите через запятую: {', '.join(options)})"
        await context.bot.send_message(chat_id, question_text)
        return

    if prop_type == 'number':
        question_text += " (введите число)"
        await context.bot.send_message(chat_id, question_text)
        return

    if prop_type == 'date':
        question_text += " (формат YYYY-MM-DD)"
        await context.bot.send_message(chat_id, question_text)
        return

    if prop_type == 'checkbox':
        keyboard = [['Да', 'Нет']]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await context.bot.send_message(chat_id, question_text, reply_markup=reply_markup)
        return

    # Иначе общий случай (rich_text, title, или неизвестный тип)
    await context.bot.send_message(chat_id, question_text)


async def process_text_message(update: Update, context: CallbackContext):
    """
    Обрабатывает текстовые сообщения (ответы на вопросы).
    Если нет активного опроса, выводим подсказку о /schedule.
    """
    chat_data = context.chat_data
    chat_id = update.effective_chat.id

    if 'properties' not in chat_data:
        # Нет активного опроса
        await update.message.reply_text(
            "Чтобы начать опрос, используйте /schedule HH:MM или запустите /run_task_manually."
        )
        return

    # Иначе продолжаем опрос
    await process_answer(update, context)


async def process_answer(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id      # <-- Добавили, чтобы знать chat_id
    chat_data = context.chat_data
    bot_data = context.bot_data

    user_input = update.message.text
    current_index = chat_data['current_property_index']
    props = chat_data['properties']
    current_prop = props[current_index]

    parsed_value = parse_answer(current_prop['type'], user_input)
    if parsed_value is None:
        await update.message.reply_text("Некорректный формат. Попробуйте снова.")
        return

    notion_token = bot_data['NOTION_TOKEN']
    page_id = chat_data['page_id']

    success = await update_notion_property(
        notion_token,
        page_id,
        current_prop['name'],
        current_prop['type'],
        str(parsed_value)
    )
    if not success:
        await update.message.reply_text(
            f"Не удалось записать ответ '{current_prop['name']}' в Notion."
        )
    else:
        await update.message.reply_text("Ответ записан в Notion!")

    if not success:
        return

    # Переходим к следующему вопросу
    chat_data['current_property_index'] += 1
    await ask_next_question(chat_id, context)  # теперь chat_id известен


def parse_answer(prop_type: str, user_input: str):
    """
    Простейшая валидация/преобразование ответа для number/date/checkbox.
    Если неверный ввод, возвращаем None.
    """
    if prop_type == 'number':
        try:
            return float(user_input)
        except ValueError:
            return None
    elif prop_type == 'date':
        try:
            datetime.strptime(user_input, '%Y-%m-%d')
            return user_input
        except ValueError:
            return None
    elif prop_type == 'checkbox':
        low = user_input.lower()
        if low in ['да', 'yes', '1']:
            return 'true'
        elif low in ['нет', 'no', '0']:
            return 'false'
        else:
            return None
    else:
        # select, multi_select, rich_text, title и пр.
        return user_input
