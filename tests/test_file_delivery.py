import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from main import FusOutputPlugin
from document import render_document
from test_document import payload


class TextDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.root = root
        self.plugin = object.__new__(FusOutputPlugin)
        with patch.dict(os.environ, {'FUS_OUTPUT_STATE_DIR': str(root)}):
            await self.plugin.initialize()
        self.plugin.send_message = AsyncMock()
        self.token = self.plugin.routes.begin(1, 'test-bot', 'person', 'test-recipient')
        self.plugin.routes.configure(1, 'test-conversation', 1000)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_short_first_reply_can_be_repaired_before_any_send(self):
        source = payload(self.token)
        source['body'] = '这是一段不足一千字的中性测试正文。'
        result = await self.plugin.send_document(source)
        self.assertEqual(result['status'], 'validation_error')
        self.assertEqual(self.plugin.routes.lookup(self.token).state, 'ready')
        self.plugin.send_message.assert_not_awaited()
        self.assertTrue(self.plugin.is_first_reply('test-conversation'))
        result = await self.plugin.send_document(payload(self.token))
        self.assertEqual(result['status'], 'sent')
        self.assertFalse(self.plugin.is_first_reply('test-conversation'))

    async def test_one_plain_component_with_complete_formatted_reply(self):
        await self.plugin.send_document(payload(self.token))
        self.plugin.send_message.assert_awaited_once()
        bot, kind, target, chain = self.plugin.send_message.call_args.args
        self.assertEqual((bot, kind, target), ('test-bot', 'person', 'test-recipient'))
        self.assertEqual([component.type for component in chain], ['Plain'])
        self.assertEqual(chain[0].text, render_document(payload(self.token), 1000))
        self.assertIn('A. 聊聊画稿', chain[0].text)
        self.assertEqual(list(self.root.rglob('*.txt')), [])

    async def test_repeat_call_sends_once_and_creates_no_file(self):
        source = payload(self.token)
        await self.plugin.send_document(source)
        await self.plugin.send_document(source)
        self.plugin.send_message.assert_awaited_once()
        self.assertEqual(list(self.root.rglob('*.txt')), [])

    async def test_send_exception_is_uncertain_and_never_retried(self):
        self.plugin.send_message.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await self.plugin.send_document(payload(self.token))
        result = await self.plugin.send_document(payload(self.token))
        self.assertEqual(result['status'], 'uncertain')
        self.plugin.send_message.assert_awaited_once()
        self.assertTrue(self.plugin.is_first_reply('test-conversation'))

    async def test_new_conversation_still_requires_its_first_reply(self):
        await self.plugin.send_document(payload(self.token))
        self.assertFalse(self.plugin.is_first_reply('test-conversation'))
        self.assertTrue(self.plugin.is_first_reply('another-conversation'))

    async def test_three_turns_with_wrong_second_token_recover_without_missing_or_duplicate_send(self):
        self.assertEqual((await self.plugin.send_document(payload(self.token)))['status'], 'sent')
        second = self.plugin.routes.begin(2, 'test-bot', 'person', 'test-recipient')
        self.plugin.routes.configure(2, 'test-conversation', 0)
        # An obsolete permit must be caught before body/length validation.
        rejected = await self.plugin.send_document({'route_token': self.token})
        self.assertEqual(rejected['status'], 'stale_route')
        self.assertFalse(rejected['ok'])
        self.assertEqual(self.plugin.send_message.await_count, 1)
        repaired = payload(second)
        repaired['body'] = 'Neutral second-turn transport test.'
        self.assertEqual((await self.plugin.send_document(repaired))['status'], 'sent')
        self.assertEqual((await self.plugin.send_document(repaired))['status'], 'already_sent')
        third = self.plugin.routes.begin(3, 'test-bot', 'person', 'test-recipient')
        self.plugin.routes.configure(3, 'test-conversation', 0)
        self.assertEqual((await self.plugin.send_document(payload(third)))['status'], 'sent')
        self.assertEqual(self.plugin.send_message.await_count, 3)
        self.assertEqual(list(self.root.rglob('*.txt')), [])

    async def test_old_token_after_plugin_reload_can_be_corrected_without_guessing_destination(self):
        rejected = await self.plugin.send_document({'route_token': 'synthetic-token-from-previous-runtime'})
        self.assertEqual(rejected['status'], 'invalid_or_expired_route')
        self.assertTrue(rejected['repair_allowed'])
        self.assertNotIn(self.token, str(rejected))
        self.plugin.send_message.assert_not_awaited()
        self.assertEqual((await self.plugin.send_document(payload(self.token)))['status'], 'sent')


if __name__ == '__main__':
    unittest.main()
