import asyncio

from langbot_plugin.api.definition.components.tool.tool import Tool


class FusSendMessage(Tool):
    async def call(self, params):
        try:
            return await self.plugin.send_document(params)
        except asyncio.CancelledError:
            raise
        except Exception:
            return {'ok': False, 'status': 'uncertain', 'retry': False}
