---
name: triage-http-5xx
description: 'API or nginx returns 5xx / 502 errors, cart or endpoints broken, HighErrorRate alert'
when_to_use: 'error rate alerts, users report 500/502, "site is down"'
---
# Triage HTTP 5xx

1. `list_services` — is any dependency (redis, postgres, api) exited/restarting?
2. `query_logs(service="api", contains="error")` — which dependency does the stack trace name?
   - `redis.exceptions.ConnectionError` → redis is down → check `list_services` for redis.
   - `psycopg.OperationalError ... too many clients` → see skill db-connection-exhaustion.
3. If api itself is restarting/exited and nginx logs `connect() failed` → see skill bad-deploy-rollback.
4. Quantify: `query_metrics('sum by (status) (rate(http_requests_total[1m]))')`.

**Typical fixes:** dependency down → `restart_service` of that dependency (redis is a cache, safe to restart).
**Never:** restart postgres; delete data.
