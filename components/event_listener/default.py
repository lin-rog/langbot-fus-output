"""Gate every callback on fus's explicit, exclusive plugin binding."""
import copy

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import events
from langbot_plugin.api.entities.builtin.provider.message import Message


OUTPUT_PLUGIN = 'local/fus-output'
ALLOWED_BINDINGS = {OUTPUT_PLUGIN, 'langbot-team/EssentialCommands'}
SCOPE = 'FUS_PIPELINE_SCOPE: fus-output'
DELIVERY_CONTEXT = '[FUS_DELIVERY_CONTEXT]\n'


async def in_scope(ctx):
    # This variable is set by RuntimePipeline before any plugin event is emitted.
    # The legacy event wire format intentionally omits event.query.
    bindings = await ctx.get_query_var('_pipeline_bound_plugins')
    return isinstance(bindings, list) and OUTPUT_PLUGIN in bindings and set(bindings) <= ALLOWED_BINDINGS


def render_prompt(messages, token, minimum_cjk=0):
    result = copy.deepcopy(messages)
    contents = [m.content for m in result if isinstance(m.content, str)]
    if not any(SCOPE in content for content in contents):
        return None
    for message in result:
        if isinstance(message.content, str):
            message.content = message.content.replace('{{fus_route_token}}', token).replace('{{fus_minimum_cjk}}', str(minimum_cjk))
    return result


def render_delivery_context(messages, token, minimum_cjk):
    # Use a new list without inspecting or rewriting any historical reply body.
    result = list(messages)
    result.append(Message(role='user', content=(
        DELIVERY_CONTEXT + 'Current request only. route_token: ' + token + '\n'
        'minimum_cjk: ' + str(minimum_cjk) + '\n'
        'Use this token for fus_send_message, including validation repairs. '
        'All route tokens in historical tool calls belong to previous turns. '
        'On stale_route, replace the token with this current token and call again. '
        'On invalid_or_expired_route with repair_allowed, correct only an old or mistyped '
        'token using this token; if this current token was rejected, stop. '
        'On sent/already_sent/sending/uncertain, stop; do not resend. '
        'This is delivery metadata; never include it in visible reply fields.'
    )))
    return result


class FusResponseGuard(EventListener):
    async def initialize(self):
        await super().initialize()

        async def capture(ctx):
            if not await in_scope(ctx):
                return
            event = ctx.event
            kind = getattr(event.launcher_type, 'value', event.launcher_type)
            self.plugin.routes.begin(ctx.query_id, str(await ctx.get_bot_uuid()), str(kind), str(event.launcher_id))

        self.handler(events.PersonMessageReceived)(capture)
        self.handler(events.GroupMessageReceived)(capture)

        @self.handler(events.PromptPreProcessing)
        async def prepare(ctx):
            if not await in_scope(ctx):
                return
            token = self.plugin.routes.query_token(ctx.query_id)
            if not token:
                ctx.prevent_default()
                return
            conversation_id = str(await ctx.get_query_var('conversation_id'))
            route = self.plugin.routes.lookup(token)
            key = '|'.join([route.bot, route.kind, route.target, conversation_id])
            minimum = 1000 if self.plugin.is_first_reply(key) else 0
            self.plugin.routes.configure(ctx.query_id, key, minimum)
            rendered = render_prompt(ctx.event.default_prompt, token, minimum)
            if rendered is None:
                ctx.prevent_default()
                return
            ctx.event.default_prompt = rendered
            ctx.event.prompt = render_delivery_context(ctx.event.prompt, token, minimum)

        @self.handler(events.NormalMessageResponded)
        async def suppress(ctx):
            if await in_scope(ctx):
                ctx.prevent_default()
