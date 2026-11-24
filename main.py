"""Dedicated plain-text delivery, explicitly bound only to the fus pipeline."""
from contextlib import closing
import os
import sqlite3
import logging
from pathlib import Path

from langbot_plugin.api.definition.plugin import BasePlugin
from langbot_plugin.api.entities.builtin.platform.message import Plain, MessageChain

from route_store import RouteStore
from document import InvalidReply, render_document


class FusOutputPlugin(BasePlugin):
    async def initialize(self):
        self.routes = RouteStore()
        self.state_path = Path(os.environ.get('FUS_OUTPUT_STATE_DIR', '/app/data/comfy_bridge/fus-output')) / 'delivery.sqlite3'
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.state_path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS completed_conversations (conversation_key TEXT PRIMARY KEY)')

    def is_first_reply(self, conversation_key):
        with closing(sqlite3.connect(self.state_path)) as db, db:
            return db.execute('SELECT 1 FROM completed_conversations WHERE conversation_key=?', (conversation_key,)).fetchone() is None

    async def send_document(self, params):
        result = await self._send_document(params)
        # Metadata only: never log reply fields, route tokens or recipient IDs.
        logging.getLogger(__name__).info('fus_delivery status=%s ok=%s', result.get('status'), result.get('ok'))
        return result

    async def _send_document(self, params):
        token = params.get('route_token')
        rejected = self.routes.rejection(token)
        if rejected is not None:
            return rejected
        route = self.routes.lookup(token)
        if route is None or not route.conversation_key:
            return {'ok': False, 'status': 'invalid_or_expired_route', 'retry': False}
        try:
            text = render_document(params, route.minimum_cjk)
        except InvalidReply as exc:
            return {'ok': False, 'status': 'validation_error', 'repair_allowed': True, 'error': str(exc)}

        async def deliver_text(bot, kind, target, rendered):
            await self.send_message(bot, kind, target, MessageChain([
                Plain(text=rendered),
            ]))
            with closing(sqlite3.connect(self.state_path)) as db, db:
                db.execute('INSERT OR IGNORE INTO completed_conversations VALUES(?)', (route.conversation_key,))

        return await self.routes.deliver(token, text, deliver_text)
