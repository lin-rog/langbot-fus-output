"""Exercise the deployed LangBot wrapper with a stub connector, no network sends."""
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

if importlib.util.find_spec('langbot') is None:
    raise unittest.SkipTest('Requires a compatible LangBot host checkout')
from langbot.pkg.core import app as _startup_order
from langbot.pkg.pipeline.wrapper.wrapper import ResponseWrapper
from langbot.pkg.pipeline.entities import ResultType
from langbot_plugin.api.entities.builtin.pipeline.query import Query
from langbot_plugin.api.entities.builtin.provider.message import Message
from langbot_plugin.api.entities.builtin.provider.session import LauncherTypes, Session

path = Path(__file__).resolve().parents[1] / 'components/event_listener/default.py'
spec = importlib.util.spec_from_file_location('fus_wrapper_guard', path)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class WrapperTests(unittest.IsolatedAsyncioTestCase):
    async def run_wrapper(self, binding):
        session = Session(launcher_type=LauncherTypes.PERSON, launcher_id='validation-only')
        query = Query.model_construct(
            query_id=987654321, launcher_type=LauncherTypes.PERSON,
            launcher_id='validation-only', sender_id='validation-only',
            variables={'_pipeline_bound_plugins': binding},
            resp_messages=[Message(role='assistant', content='plain model text must be blocked for fus')],
            resp_message_chain=[], pipeline_config={'output': {'misc': {'track-function-calls': False}}},
        )
        async def emit(event, bindings):
            state = {'prevented': False}
            ctx = SimpleNamespace(
                event=event, get_query_var=AsyncMock(return_value=bindings),
                prevent_default=lambda: state.update(prevented=True),
                is_prevented_default=lambda: state['prevented'],
            )
            if await guard.in_scope(ctx):
                ctx.prevent_default()
            return ctx
        app = SimpleNamespace(sess_mgr=SimpleNamespace(get_session=AsyncMock(return_value=session)),
                              plugin_connector=SimpleNamespace(emit_event=emit))
        results = [result async for result in ResponseWrapper(app).process(query, 'ResponseWrapper')]
        return query, results

    async def test_fus_text_never_reaches_send_stage(self):
        query, results = await self.run_wrapper(['local/fus-output'])
        self.assertEqual([result.result_type for result in results], [ResultType.INTERRUPT])
        self.assertEqual(query.resp_message_chain, [])

    async def test_other_pipeline_continues_with_original_text(self):
        query, results = await self.run_wrapper(['local/irodori-tts'])
        self.assertEqual([result.result_type for result in results], [ResultType.CONTINUE])
        self.assertEqual(str(query.resp_message_chain[0]), 'plain model text must be blocked for fus')

    async def test_basic_commands_do_not_disable_fus_response_suppression(self):
        query, results = await self.run_wrapper(['local/fus-output', 'langbot-team/EssentialCommands'])
        self.assertEqual([result.result_type for result in results], [ResultType.INTERRUPT])
        self.assertEqual(query.resp_message_chain, [])


if __name__ == '__main__':
    unittest.main()
