"""Ops Crew CLI.

  uv run opscrew chat "api returns 500"          # interactive, asks for approval
  uv run opscrew chat --auto-approve "..."       # eval/demo mode
"""

import asyncio
import json
import os

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

app = typer.Typer(add_completion=False)
con = Console()


def _show_trajectory(state):
    for e in state.get("trajectory", []):
        d = {k: v for k, v in e.items() if k not in ("node", "ts")}
        con.print(f"[dim]{e['node']:>20}[/dim] {json.dumps(d, ensure_ascii=False, default=str)[:220]}")


async def _chat(text: str, auto: bool, trace: bool):
    if auto:
        os.environ["OPSCREW_AUTO_APPROVE"] = "true"
    from opscrew.graph import Runner
    from opscrew.observability import setup_logging, setup_tracing
    setup_logging()
    if trace:
        setup_tracing()
    async with Runner() as r:
        res = await r.run(text)
        while res["status"] == "pending_approval":
            req = res["approval_request"]
            con.print(Panel(f"[bold]Diagnosis:[/bold] {req['diagnosis']['root_cause']}\n"
                            f"[bold]Action:[/bold] {req['remediation']['action']} {req['remediation'].get('service', '')}\n"
                            f"[bold]Why:[/bold] {req['remediation']['rationale']}\n"
                            f"[bold]Rollback:[/bold] {req['remediation']['rollback_plan']}\n"
                            f"[bold]Validator:[/bold] {req['validation']}", title=f"Approval required (run {res['run_id']})"))
            dec = "approve" if typer.confirm("Approve this action?") else "reject"
            res = await r.resume(res["run_id"], dec, by=os.getenv("USER", "human"))
        _show_trajectory(res["state"])
        con.print(Panel(Markdown(res.get("answer") or ""), title=f"Ops Crew — {res.get('outcome')} (run {res['run_id']})"))
    from opentelemetry import trace as t
    p = t.get_tracer_provider()
    if hasattr(p, "force_flush"):
        p.force_flush()


@app.command()
def chat(text: str, auto_approve: bool = typer.Option(False, "--auto-approve"), trace: bool = True):
    """Send a message / incident to Ops Crew."""
    asyncio.run(_chat(text, auto_approve, trace))


@app.command()
def check():
    """Validate configuration (cross-family rule) and engine availability."""
    from opscrew.config import models_cfg
    from opscrew.llm.router import probe_engine
    cfg = models_cfg()
    con.print({k: v["model"] for k, v in cfg["roles"].items()})
    con.print(f"engine up: {probe_engine()}")


if __name__ == "__main__":
    app()
