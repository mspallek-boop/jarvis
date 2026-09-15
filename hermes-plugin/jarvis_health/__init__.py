"""Registration for the phone health-snapshot tool."""

from . import schemas, tools


def register(ctx):
    ctx.register_tool(name="health_today", toolset="health", schema=schemas.HEALTH_TODAY,
                      handler=tools.health_today)
