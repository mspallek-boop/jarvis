"""Registration for Jarvis ↔ Botschaft Jarvis / Grok file-queue tools."""

from . import schemas, tools


def register(ctx):
    ctx.register_tool(name="grok_delegate", toolset="grok", schema=schemas.GROK_DELEGATE,
                      handler=tools.grok_delegate)
    ctx.register_tool(name="grok_delegate_status", toolset="grok",
                      schema=schemas.GROK_DELEGATE_STATUS,
                      handler=tools.grok_delegate_status)
