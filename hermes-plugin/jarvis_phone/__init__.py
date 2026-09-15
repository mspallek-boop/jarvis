"""Registration for the JARVIS phone-call tools."""

from . import schemas, tools


def register(ctx):
    ctx.register_tool(name="phone_call", toolset="phone", schema=schemas.PHONE_CALL,
                      handler=tools.phone_call)
    ctx.register_tool(name="phone_call_status", toolset="phone", schema=schemas.PHONE_CALL_STATUS,
                      handler=tools.phone_call_status)
