from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telegram.ext import ApplicationHandlerStop
import bot
import dialogs
import notion_utils


class BotTests(unittest.IsolatedAsyncioTestCase):
    def test_real_application_build_and_job_queue(self):
        with patch.object(bot, 'TELEGRAM_TOKEN', '123456:test'), \
             patch.object(bot, 'NOTION_TOKEN', 'test'), \
             patch.object(bot, 'DATABASE_ID', 'example'), \
             patch.object(bot, 'ALLOWED_USER_ID', 42), \
             patch('telegram.ext.Application.run_polling') as polling:
            bot.main()
            polling.assert_called_once()

    async def test_begin_questionnaire_creates_page_and_asks_question(self):
        context = SimpleNamespace(chat_data={},
                                  bot_data={'NOTION_TOKEN': 'test', 'DATABASE_ID': 'example'},
                                  bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(dialogs, 'create_new_page', AsyncMock(return_value='new-page')), \
             patch.object(dialogs, 'get_notion_properties', AsyncMock(return_value=[
                 {'name': 'Notes', 'type': 'rich_text', 'options': []}])):
            await dialogs.begin_questionnaire(42, context)
            self.assertEqual(context.chat_data['page_id'], 'new-page')
            context.bot.send_message.assert_any_await(42, 'Notes')

    async def test_private_owner_only(self):
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42),
                                 effective_chat=SimpleNamespace(id=42, type='private'))
        with patch.object(bot, 'ALLOWED_USER_ID', 42):
            await bot.restrict_access(update, None)
            update.effective_user.id = 43
            with self.assertRaises(ApplicationHandlerStop):
                await bot.restrict_access(update, None)
            update.effective_user.id = 42
            update.effective_chat.type = 'group'
            with self.assertRaises(ApplicationHandlerStop):
                await bot.restrict_access(update, None)

    async def test_schedule_passes_chat_context(self):
        queue = Mock()
        queue.get_jobs_by_name.return_value = [Mock()]
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=42),
                                 message=SimpleNamespace(reply_text=AsyncMock()))
        context = SimpleNamespace(args=['09:00'], job_queue=queue)
        await bot.schedule_cmd(update, context)
        self.assertEqual(queue.run_daily.call_args.kwargs['chat_id'], 42)
        queue.get_jobs_by_name.return_value[0].schedule_removal.assert_called_once()

    async def test_scheduled_callback_uses_job_chat(self):
        context = SimpleNamespace(job=SimpleNamespace(chat_id=42))
        with patch.object(dialogs, 'begin_questionnaire', AsyncMock()) as begin:
            await dialogs.scheduled_task(context)
            begin.assert_awaited_once_with(42, context)

    async def test_failed_write_keeps_question_and_completion_clears_state(self):
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=42),
                                 message=SimpleNamespace(text='3', reply_text=AsyncMock()))
        state = {'page_id': 'example', 'properties': [{'name': 'Score', 'type': 'number'}],
                 'current_property_index': 0}
        context = SimpleNamespace(chat_data=state, bot_data={'NOTION_TOKEN': 'test'},
                                  bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(dialogs, 'update_notion_property', AsyncMock(return_value=False)):
            await dialogs.process_answer(update, context)
            self.assertEqual(state['current_property_index'], 0)
        with patch.object(dialogs, 'update_notion_property', AsyncMock(return_value=True)):
            await dialogs.process_answer(update, context)
            self.assertEqual(state, {})

    def test_schema_has_no_personal_questionnaire(self):
        props = notion_utils.process_notion_properties({'properties': {
            'Score': {'type': 'number'}, 'Notes': {'type': 'rich_text'},
            'Computed': {'type': 'formula'}}})
        self.assertEqual([p['name'] for p in props], ['Score', 'Notes'])
        self.assertEqual(notion_utils.create_property_data('checkbox', 'true'), {'checkbox': True})
        self.assertEqual(notion_utils.create_property_data('multi_select', 'A, B'),
                         {'multi_select': [{'name': 'A'}, {'name': 'B'}]})


if __name__ == '__main__':
    unittest.main()
