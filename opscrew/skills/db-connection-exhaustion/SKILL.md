---
name: db-connection-exhaustion
description: 'Postgres too many clients / connection pool exhausted, API slow with database errors, PostgresTooManyConnections alert'
when_to_use: '"too many clients already", connection timeouts, pg_stat_activity near max_connections'
---
# DB connection exhaustion

1. `query_metrics('sum(pg_stat_activity_count)')` and `query_metrics('pg_settings_max_connections')`.
2. `run_diagnostic('psql -c "SELECT application_name, client_addr, state, count(*) FROM pg_stat_activity GROUP BY 1,2,3 ORDER BY 4 DESC"')`
   — who holds the connections? Many `idle` connections from one client = leak.
3. `query_logs(service="reporter")` / `query_logs(service="api", contains="too many")` — which service leaks.
4. `query_metrics('app_config_version')` — config change right before?

**Typical fix:** leak introduced by config (`reporter.leak_connections`) → `rollback_config`;
as an extra mitigation `terminate_idle_db`. **Never:** restart postgres.
