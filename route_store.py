"""Per-request delivery permits; no global 'last conversation' routing."""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass


@dataclass
class Route:
    query_id: int
    bot: str
    kind: str
    target: str
    expires: float
    state: str = 'ready'
    conversation_key: str = ''
    minimum_cjk: int = 0
    superseded: bool = False


class RouteStore:
    def __init__(self, clock=time.monotonic, ttl=900, capacity=256):
        self.clock, self.ttl, self.capacity = clock, ttl, capacity
        self.routes: dict[str, Route] = {}
        self.queries: dict[int, str] = {}
        self.lock = asyncio.Lock()

    def prune(self):
        for token, route in list(self.routes.items()):
            if route.expires <= self.clock():
                del self.routes[token]
                if self.queries.get(route.query_id) == token:
                    self.queries.pop(route.query_id, None)

    def begin(self, query_id, bot, kind, target):
        self.prune()
        if query_id in self.queries:
            return self.queries[query_id]
        if not bot or kind not in {'person', 'group'} or not str(target):
            raise ValueError('Missing delivery context')
        if len(self.routes) >= self.capacity:
            raise ValueError('Too many pending delivery permits')
        token = secrets.token_urlsafe(32)
        self.routes[token] = Route(query_id, bot, kind, str(target), self.clock() + self.ttl)
        self.queries[query_id] = token
        return token

    def query_token(self, query_id):
        self.prune()
        return self.queries.get(query_id)

    def rejection(self, token):
        route = self.lookup(token)
        if route is None:
            return {'ok': False, 'status': 'invalid_or_expired_route', 'repair_allowed': True,
                    'error': 'This token is not valid; nothing was sent by this call. '
                             'Use only the token in the CURRENT FUS_DELIVERY_CONTEXT. '
                             'If that current token is unavailable or also rejected, stop.'}
        if route.state in {'sending', 'uncertain'}:
            return {'ok': False, 'status': route.state, 'retry': False}
        if route.superseded:
            return {'ok': False, 'status': 'stale_route', 'repair_allowed': True,
                    'error': 'This route_token belongs to an earlier turn. Nothing was sent by this call. '
                             'Copy the route_token from the CURRENT FUS_DELIVERY_CONTEXT at the end '
                             'of the request history and call again with the current reply fields. '
                             'Do not copy tokens from historical tool calls.'}
        if route.state == 'sent':
            return {'ok': False, 'status': 'already_sent', 'retry': False}
        return None

    async def deliver(self, token, text, send):
        if not isinstance(token, str) or not isinstance(text, str) or not text.strip():
            return {'ok': False, 'status': 'invalid_arguments', 'retry': False}
        async with self.lock:
            rejected = self.rejection(token)
            if rejected is not None:
                return rejected
            route = self.routes[token]
            route.state = 'sending'
        try:
            await send(route.bot, route.kind, route.target, text)
        except BaseException:
            # An exception after a network write does not prove non-delivery.
            route.state = 'uncertain'
            raise
        route.state = 'sent'
        return {'ok': True, 'status': 'sent', 'retry': False}

    def configure(self, query_id, conversation_key, minimum_cjk):
        token = self.query_token(query_id)
        if not token:
            return None
        route = self.routes[token]
        route.conversation_key = conversation_key
        route.minimum_cjk = minimum_cjk
        # A newer request invalidates older permits for this exact destination,
        # including permits from a conversation reset. Never redirect a send.
        destination = (route.bot, route.kind, route.target)
        for other in self.routes.values():
            if (other.bot, other.kind, other.target) == destination:
                if other.query_id < route.query_id:
                    other.superseded = True
                elif other.query_id > route.query_id and other.conversation_key:
                    route.superseded = True
        return token

    def lookup(self, token):
        self.prune()
        return self.routes.get(token) if isinstance(token, str) else None
