"""Generate Grafana dashboards (provisioned from observability/grafana/dashboards)."""

import json
from pathlib import Path

OUT = Path(__file__).parent / "grafana/dashboards"
_id = 0


def panel(title, exprs, kind="timeseries", w=8, h=7, unit=None, legend=None, ds="prom", desc=""):
    global _id
    _id += 1
    targets = []
    for i, e in enumerate(exprs if isinstance(exprs, list) else [exprs]):
        if ds == "loki":
            targets.append({"refId": chr(65 + i), "expr": e, "datasource": {"type": "loki", "uid": "loki"}})
        else:
            targets.append({"refId": chr(65 + i), "expr": e, "legendFormat": (legend or [None])[i] if legend and i < len(legend) else None,
                            "datasource": {"type": "prometheus", "uid": "prom"}})
    p = {"id": _id, "type": kind, "title": title, "description": desc, "targets": targets,
         "gridPos": {"w": w, "h": h, "x": 0, "y": 0},
         "datasource": {"type": "loki" if ds == "loki" else "prometheus", "uid": ds},
         "fieldConfig": {"defaults": {"unit": unit} if unit else {}, "overrides": []}, "options": {}}
    if kind == "logs":
        p["options"] = {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending"}
    return p


def layout(rows):
    panels, y = [], 0
    for row_title, ps in rows:
        global _id
        _id += 1
        panels.append({"id": _id, "type": "row", "title": row_title, "gridPos": {"w": 24, "h": 1, "x": 0, "y": y}, "collapsed": False})
        y += 1
        x, rowh = 0, 0
        for p in ps:
            if x + p["gridPos"]["w"] > 24:
                x, y = 0, y + rowh
                rowh = 0
            p["gridPos"].update({"x": x, "y": y})
            x += p["gridPos"]["w"]
            rowh = max(rowh, p["gridPos"]["h"])
        y += rowh
        panels += ps
    return panels


def dashboard(uid, title, rows, refresh="10s"):
    return {"uid": uid, "title": title, "schemaVersion": 39, "refresh": refresh, "time": {"from": "now-1h", "to": "now"},
            "tags": ["opscrew"], "panels": layout(rows), "templating": {"list": []}}


agent = dashboard("opscrew-agent", "Ops Crew — Agent", [
    ("Product", [
        panel("Runs by outcome (1h)", 'sum by (outcome) (increase(opscrew_runs_total[1h]))', "bargauge", w=8),
        panel("Runs by kind (1h)", 'sum by (kind) (increase(opscrew_runs_total[1h]))', "piechart", w=6),
        panel("Run duration p50/p95 by kind", ['histogram_quantile(0.5, sum by (le,kind) (rate(opscrew_run_duration_seconds_bucket[15m])))',
                                                'histogram_quantile(0.95, sum by (le,kind) (rate(opscrew_run_duration_seconds_bucket[15m])))'],
              w=10, unit="s", legend=["p50 {{kind}}", "p95 {{kind}}"]),
        panel("HITL decisions", 'sum by (decision) (increase(opscrew_hitl_decisions_total[1h]))', "bargauge", w=6),
        panel("Latest offline eval scores", 'opscrew_eval_score{metric=~"product.*|agent.root_cause_accuracy|agent.fix_accuracy|llm.hallucination_resistance|agent.routing_accuracy"}',
              "bargauge", w=18, legend=["{{metric}}"]),
        panel("Online LLM-judge on production traces", 'opscrew_eval_score{metric=~"online.judge_mean|online.judge_low_share"}', "bargauge", w=12, legend=["{{metric}}"]),
        panel("Continuous evals: minutes since last run", '(time() - opscrew_eval_score{metric="meta.last_run_unixtime"}) / 60', "stat", w=6),
        panel("Quality alerts firing", 'count(ALERTS{alertstate="firing", alertname=~"Eval.*|OnlineJudgeLow"}) or vector(0)', "stat", w=6),
    ]),
    ("Agentic: routing, validation, tools, memory", [
        panel("Router decisions (tier)", 'sum by (tier, kind) (increase(opscrew_router_decisions_total[1h]))', "bargauge", w=6),
        panel("Validator verdicts", 'sum by (stage, verdict) (increase(opscrew_validator_verdicts_total[1h]))', "bargauge", w=6),
        panel("Guardrail blocks", 'sum by (reason) (increase(opscrew_guardrail_blocks_total[1h]))', "bargauge", w=6),
        panel("Tool steps per investigation (p50/p95)", ['histogram_quantile(0.5, sum by (le) (rate(opscrew_tool_steps_per_run_bucket[30m])))',
                                                         'histogram_quantile(0.95, sum by (le) (rate(opscrew_tool_steps_per_run_bucket[30m])))'], w=6, legend=["p50", "p95"]),
        panel("Tool calls by status", 'sum by (tool, status) (increase(opscrew_tool_calls_total[1h]))', "bargauge", w=8),
        panel("MCP tool latency p95", 'histogram_quantile(0.95, sum by (le, tool) (rate(opstools_latency_seconds_bucket[15m])))', w=8, unit="s", legend=["{{tool}}"]),
        panel("Memory ops", 'sum by (layer, op) (increase(opscrew_memory_ops_total[1h]))', "bargauge", w=8),
        panel("Memory items", 'opscrew_memory_items', "stat", w=8, legend=["{{layer}} {{state}}"]),
    ]),
    ("LLM", [
        panel("LLM latency p95 by role/model", 'histogram_quantile(0.95, sum by (le, role, model) (rate(opscrew_llm_latency_seconds_bucket[15m])))',
              w=12, unit="s", legend=["{{role}} / {{model}}"]),
        panel("Jev-like decision latency p95", 'histogram_quantile(0.95, sum by (le, question) (rate(opscrew_decision_latency_seconds_bucket[15m])))',
              w=12, unit="s", legend=["{{question}}"]),
        panel("Tokens/min by model", 'sum by (model, direction) (rate(opscrew_llm_tokens_total[5m])) * 60', w=12, legend=["{{model}} {{direction}}"]),
        panel("Equivalent cloud cost (USD, 24h)", 'sum by (model) (increase(opscrew_llm_equiv_cost_usd_total[24h]))', "bargauge", w=6, unit="currencyUSD"),
        panel("LLM errors / fallbacks", 'sum by (role, model, kind) (increase(opscrew_llm_errors_total[1h]))', "bargauge", w=6),
    ]),
    ("Infrastructure", [
        panel("Ollama engine up", 'opscrew_llm_engine_up', "stat", w=4),
        panel("Loaded models memory", 'opscrew_llm_loaded_model_bytes', "bargauge", w=10, unit="bytes", legend=["{{model}}"]),
        panel("Firing alerts", 'ALERTS{alertstate="firing"}', "table", w=10),
        panel("Agent logs (Loki)", '{service="agent"}', "logs", w=24, h=10, ds="loki"),
    ]),
])

lab = dashboard("lab-prod", "Lab — Production", [
    ("Golden signals", [
        panel("Requests/s by status", 'sum by (status) (rate(http_requests_total[1m]))', w=8, legend=["{{status}}"]),
        panel("5xx ratio", 'sum(rate(http_requests_total{status=~"5.."}[1m])) / clamp_min(sum(rate(http_requests_total[1m])), 0.001)', w=8, unit="percentunit"),
        panel("/cart p95 latency", 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route="/cart"}[1m])))', w=8, unit="s"),
    ]),
    ("Saturation & containers", [
        panel("Container up", 'lab_container_up', "stat", w=8, legend=["{{service}}"]),
        panel("Restarts", 'lab_container_restarts', "stat", w=8, legend=["{{service}}"]),
        panel("Container memory", 'lab_container_memory_bytes', w=8, unit="bytes", legend=["{{service}}"]),
        panel("Postgres connections vs max", ['sum(pg_stat_activity_count)', 'max(pg_settings_max_connections)'], w=8, legend=["active", "max"]),
        panel("Uploads disk usage", 'uploads_disk_usage_ratio', "gauge", w=8, unit="percentunit"),
        panel("Config version (deploys)", 'app_config_version', "stat", w=8),
    ]),
    ("Logs", [panel("Errors (all services)", '{project="lab", service=~"api|worker|reporter|nginx|postgres|redis"} |~ "(?i)error|fatal|critical"', "logs", w=24, h=10, ds="loki")]),
])

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "opscrew-agent.json").write_text(json.dumps(agent, indent=1))
(OUT / "lab-prod.json").write_text(json.dumps(lab, indent=1))
print("dashboards written")
