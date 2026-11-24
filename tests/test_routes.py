import asyncio
import unittest

from route_store import RouteStore


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_conversations_keep_their_destinations(self):
        routes = RouteStore()
        a = routes.begin(1, 'bot-a', 'person', 'alice')
        b = routes.begin(2, 'bot-b', 'group', 'group-b')
        sent = []
        async def send(*args):
            sent.append(args)
        await asyncio.gather(routes.deliver(b, 'B', send), routes.deliver(a, 'A', send))
        self.assertCountEqual(sent, [('bot-a', 'person', 'alice', 'A'), ('bot-b', 'group', 'group-b', 'B')])

    async def test_duplicate_calls_send_once(self):
        routes, sent = RouteStore(), []
        token = routes.begin(1, 'bot', 'person', 'alice')
        async def send(*args):
            await asyncio.sleep(0)
            sent.append(args)
        await asyncio.gather(*(routes.deliver(token, 'reply', send) for _ in range(10)))
        self.assertEqual(len(sent), 1)

    async def test_unknown_or_empty_input_cannot_send(self):
        routes = RouteStore()
        async def forbidden(*args):
            self.fail('Must not send')
        self.assertFalse((await routes.deliver('unknown', 'hello', forbidden))['ok'])
        token = routes.begin(1, 'bot', 'person', 'alice')
        self.assertFalse((await routes.deliver(token, '  ', forbidden))['ok'])

    async def test_expired_permit_cannot_send(self):
        now = [0]
        routes = RouteStore(clock=lambda: now[0], ttl=1)
        token = routes.begin(1, 'bot', 'person', 'alice')
        now[0] = 2
        async def forbidden(*args):
            self.fail('Must not send')
        self.assertEqual((await routes.deliver(token, 'hello', forbidden))['status'], 'invalid_or_expired_route')

    async def test_ambiguous_failure_does_not_retry(self):
        routes, calls = RouteStore(), []
        token = routes.begin(1, 'bot', 'person', 'alice')
        async def send(*args):
            calls.append(args)
            raise TimeoutError()
        with self.assertRaises(TimeoutError):
            await routes.deliver(token, 'reply', send)
        result = await routes.deliver(token, 'reply', send)
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(len(calls), 1)

    async def test_capacity_fails_without_reassigning_another_target(self):
        routes = RouteStore(capacity=1)
        token = routes.begin(1, 'bot', 'person', 'alice')
        with self.assertRaises(ValueError):
            routes.begin(2, 'bot', 'person', 'bob')
        self.assertEqual(routes.routes[token].target, 'alice')

    async def test_second_turn_old_token_is_rejected_and_current_token_delivers(self):
        routes, sent = RouteStore(), []
        async def send(*args):
            sent.append(args)
        first = routes.begin(1, 'bot', 'person', 'alice')
        routes.configure(1, 'conversation', 0)
        self.assertEqual((await routes.deliver(first, 'first', send))['status'], 'sent')
        second = routes.begin(2, 'bot', 'person', 'alice')
        routes.configure(2, 'conversation', 0)
        rejected = await routes.deliver(first, 'second', send)
        self.assertFalse(rejected['ok'])
        self.assertEqual(rejected['status'], 'stale_route')
        self.assertTrue(rejected['repair_allowed'])
        self.assertNotIn(second, str(rejected))
        self.assertEqual(len(sent), 1)
        self.assertEqual(routes.lookup(second).state, 'ready')
        self.assertEqual((await routes.deliver(second, 'second', send))['status'], 'sent')
        self.assertEqual([item[-1] for item in sent], ['first', 'second'])

    async def test_duplicate_success_is_explicitly_not_a_new_send(self):
        routes = RouteStore()
        token = routes.begin(1, 'bot', 'person', 'alice')
        async def send(*args):
            pass
        await routes.deliver(token, 'first', send)
        result = await routes.deliver(token, 'again', send)
        self.assertEqual(result, {'ok': False, 'status': 'already_sent', 'retry': False})

    async def test_pending_old_turn_cannot_send_after_conversation_reset(self):
        routes = RouteStore()
        first = routes.begin(1, 'bot', 'person', 'alice')
        routes.configure(1, 'old-conversation', 0)
        routes.begin(2, 'bot', 'person', 'alice')
        routes.configure(2, 'new-conversation', 0)
        async def forbidden(*args):
            self.fail('Must not send an obsolete turn')
        self.assertEqual((await routes.deliver(first, 'old', forbidden))['status'], 'stale_route')

    async def test_late_configuration_cannot_invalidate_a_newer_turn(self):
        routes = RouteStore()
        old = routes.begin(1, 'bot', 'person', 'alice')
        current = routes.begin(2, 'bot', 'person', 'alice')
        routes.configure(2, 'conversation', 0)
        routes.configure(1, 'conversation', 0)
        self.assertEqual(routes.rejection(old)['status'], 'stale_route')
        self.assertIsNone(routes.rejection(current))

    async def test_other_destination_does_not_supersede_a_permit(self):
        routes = RouteStore()
        first = routes.begin(1, 'bot', 'person', 'alice')
        routes.configure(1, 'conversation', 0)
        for query, bot, kind, target in [(2, 'bot', 'person', 'bob'), (3, 'other-bot', 'person', 'alice'), (4, 'bot', 'group', 'alice')]:
            routes.begin(query, bot, kind, target)
            routes.configure(query, 'conversation', 0)
        self.assertIsNone(routes.rejection(first))

    async def test_superseding_uncertain_send_does_not_allow_a_retry(self):
        routes = RouteStore()
        first = routes.begin(1, 'bot', 'person', 'alice')
        routes.configure(1, 'conversation', 0)
        async def fail(*args):
            raise TimeoutError()
        with self.assertRaises(TimeoutError):
            await routes.deliver(first, 'first', fail)
        routes.begin(2, 'bot', 'person', 'alice')
        routes.configure(2, 'conversation', 0)
        self.assertEqual(routes.rejection(first), {'ok': False, 'status': 'uncertain', 'retry': False})


if __name__ == '__main__':
    unittest.main()
