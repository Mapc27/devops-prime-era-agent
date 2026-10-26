---
name: latency-regression
description: 'API latency / p95 grows, slow responses, timeouts without errors, HighLatency alert'
when_to_use: '"slow", "медленно", p95 alerts, timeouts'
---
# Latency regression

1. `query_metrics('histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route="/cart"}[1m])))')`.
2. `query_logs(service="api", contains="slow")` — slow query warnings, feature flags mentioned.
3. `query_metrics('app_config_version')` — feature flag rollout = config change.
4. Exclude DB saturation: `pg_stat_activity_count` vs max.

**Typical fix:** feature flag introduced slow query → `rollback_config`.
