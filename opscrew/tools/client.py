"""MCP client side: loads ops-tools and splits them by privilege.

READ_TOOLS go to the investigator; apply_remediation is never bound to an LLM — only the
execute node calls it, with an approval token.
"""

import hashlib
import hmac
from datetime import timedelta

from langchain_mcp_adapters.client import MultiServerMCPClient

from opscrew.config import settings

READ_TOOLS = {"golden_signals", "query_metrics", "query_logs", "list_services", "inspect_service", "run_diagnostic", "list_alerts"}
_tools = None


async def load_tools() -> dict:
    global _tools
    if _tools is None:
        c = MultiServerMCPClient({"ops": {"url": settings.mcp_url, "transport": "streamable_http",
                                          "timeout": timedelta(seconds=150), "sse_read_timeout": timedelta(seconds=300)}})
        _tools = {t.name: t for t in await c.get_tools()}
    return _tools


async def read_tools() -> list:
    return [t for n, t in (await load_tools()).items() if n in READ_TOOLS]


def text_of(result) -> str:
    """Flatten MCP content blocks to text."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    if isinstance(result, tuple):
        return text_of(result[0])
    return str(result)


async def call(name: str, args: dict) -> str:
    return text_of(await (await load_tools())[name].ainvoke(args))


def approval_token(run_id: str, action: str, service: str) -> str:
    return hmac.new(settings.approval_secret.encode(), f"{run_id}|{action}|{service}".encode(), hashlib.sha256).hexdigest()
