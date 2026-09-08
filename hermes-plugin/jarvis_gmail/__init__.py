"""Read-only Gmail access for the JARVIS Hermes agent."""

from . import schemas, tools


def register(ctx):
    ctx.register_tool(
        name="gmail_list_emails",
        toolset="gmail",
        schema=schemas.GMAIL_LIST_EMAILS,
        handler=tools.gmail_list_emails,
    )
