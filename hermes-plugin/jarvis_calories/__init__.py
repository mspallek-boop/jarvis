"""Registration for the local JARVIS calorie-tracking tools."""

from . import schemas, tools


def register(ctx):
    ctx.register_tool(name="calories_log", toolset="health", schema=schemas.CALORIES_LOG,
                      handler=tools.calories_log)
    ctx.register_tool(name="calories_daily_summary", toolset="health", schema=schemas.CALORIES_DAILY,
                      handler=tools.calories_daily_summary)
    ctx.register_tool(name="calories_weekly_summary", toolset="health", schema=schemas.CALORIES_WEEKLY,
                      handler=tools.calories_weekly_summary)
    ctx.register_tool(name="calories_progress", toolset="health", schema=schemas.CALORIES_PROGRESS,
                      handler=tools.calories_progress)
    ctx.register_tool(name="calories_set_goal", toolset="health", schema=schemas.CALORIES_GOAL,
                      handler=tools.calories_set_goal)
    ctx.register_tool(name="calories_weekly_checkin", toolset="health", schema=schemas.CALORIES_CHECKIN,
                      handler=tools.calories_weekly_checkin)
