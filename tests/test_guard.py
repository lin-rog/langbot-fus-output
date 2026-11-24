import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langbot_plugin.api.entities.builtin.provider.message import Message

path = Path(__file__).resolve().parents[1] / 'components/event_listener/default.py'
spec = importlib.util.spec_from_file_location('fus_guard', path)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_chatpipeline_binding_never_matches(self):
        for binding in [None, [], ['local/irodori-tts'], ['langbot-team/EssentialCommands'], ['local/fus-output', 'local/irodori-tts']]:
            ctx = SimpleNamespace(get_query_var=AsyncMock(return_value=binding))
            self.assertFalse(await guard.in_scope(ctx))
        ctx = SimpleNamespace(get_query_var=AsyncMock(return_value=['local/fus-output']))
        self.assertTrue(await guard.in_scope(ctx))

    async def test_basic_commands_are_compatible_in_either_order(self):
        for binding in [['local/fus-output', 'langbot-team/EssentialCommands'], ['langbot-team/EssentialCommands', 'local/fus-output']]:
            ctx = SimpleNamespace(get_query_var=AsyncMock(return_value=binding))
            self.assertTrue(await guard.in_scope(ctx))

    async def test_prompt_render_keeps_the_persistent_preset_unchanged(self):
        messages = [Message(role='user', content=guard.SCOPE + '\n{{fus_route_token}}')]
        rendered = guard.render_prompt(messages, 'this-turn-only')
        self.assertIn('this-turn-only', rendered[0].content)
        self.assertIn('{{fus_route_token}}', messages[0].content)
        self.assertEqual(rendered[0].role, 'user')

    async def test_unrelated_prompt_cannot_receive_a_route_permit(self):
        self.assertIsNone(guard.render_prompt([Message(role='system', content='Another pipeline')], 'token'))

    async def test_current_delivery_context_follows_history_without_rewriting_it(self):
        history = [Message(role='user', content='Synthetic history'),
                   Message(role='assistant', content='Synthetic prior reply')]
        rendered = guard.render_delivery_context(history, 'fresh-token', 0)
        self.assertEqual(len(history), 2)
        self.assertEqual(rendered[:-1], history)
        self.assertIs(rendered[1], history[1])
        self.assertTrue(rendered[-1].content.startswith(guard.DELIVERY_CONTEXT))
        self.assertIn('route_token: fresh-token', rendered[-1].content)
        self.assertIn('minimum_cjk: 0', rendered[-1].content)
        next_rendered = guard.render_delivery_context(history, 'next-token', 0)
        self.assertNotIn('fresh-token', next_rendered[-1].content)

    async def test_prepare_event_attaches_current_token_only_for_fus(self):
        from route_store import RouteStore
        from unittest.mock import patch
        handlers = {}
        listener = object.__new__(guard.FusResponseGuard)
        def register(event_class):
            def attach(function):
                handlers[event_class.__name__] = function
                return function
            return attach
        listener.handler = register
        routes = RouteStore()
        token = routes.begin(8, 'test-bot', 'person', 'test-recipient')
        listener.plugin = SimpleNamespace(routes=routes, is_first_reply=lambda key: False)
        with patch.object(guard.EventListener, 'initialize', new=AsyncMock()):
            await listener.initialize()
        original_history = [Message(role='assistant', content='Synthetic prior reply')]
        for bindings, expected_extra in [(['local/fus-output'], 1), (['other/plugin'], 0)]:
            original_preset = [Message(role='user', content=guard.SCOPE + '\n{{fus_route_token}}')]
            event = SimpleNamespace(default_prompt=original_preset, prompt=original_history)
            async def get_var(key):
                return bindings if key == '_pipeline_bound_plugins' else 'test-conversation'
            ctx = SimpleNamespace(query_id=8, event=event, get_query_var=get_var,
                                  prevent_default=lambda: self.fail('Should not block this valid preparation'))
            await handlers['PromptPreProcessing'](ctx)
            self.assertEqual(len(event.prompt), 1 + expected_extra)
            self.assertEqual(len(original_history), 1)
            self.assertIn('{{fus_route_token}}', original_preset[0].content)
            if expected_extra:
                self.assertIn(token, event.prompt[-1].content)
                self.assertIn(token, event.default_prompt[0].content)

    async def test_normal_response_is_suppressed_only_for_fus(self):
        handlers = {}
        class FakeListener:
            plugin = SimpleNamespace()
            def handler(self, event_class):
                def register(function):
                    handlers[event_class.__name__] = function
                    return function
                return register
        from unittest.mock import patch
        with patch.object(guard.EventListener, 'initialize', new=AsyncMock()):
            listener = FakeListener()
            # super() requires a real instance, so construct the SDK object and
            # supply just the registration and plugin attributes used here.
            listener = object.__new__(guard.FusResponseGuard)
            listener.handler = FakeListener().handler
            listener.plugin = SimpleNamespace()
            await listener.initialize()
        for binding, expected in [(['local/fus-output'], True), (['local/fus-output', 'langbot-team/EssentialCommands'], True), (['local/irodori-tts'], False)]:
            prevented = []
            ctx = SimpleNamespace(get_query_var=AsyncMock(return_value=binding), prevent_default=lambda: prevented.append(True))
            await handlers['NormalMessageResponded'](ctx)
            self.assertEqual(bool(prevented), expected)


if __name__ == '__main__':
    unittest.main()
