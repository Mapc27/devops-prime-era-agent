# 10. Системные промпты, persona-файлы, skills и tools

## 1. Системные промпты (`opscrew/prompts/*.md`)

Каждая роль получает **свой** короткий промпт с версией (`Version: <name>@x.y`, попадает в трейс) + только нужные persona-файлы. Принцип — минимальный контекст: локальная 8–12B модель хуже следует длинным инструкциям.

| Промпт | Роль | Persona-контекст | Выход |
|---|---|---|---|
| `supervisor_plan` | план расследования | SOUL, AGENTS, INFRA | JSON `Plan` |
| `investigator` | ReAct по read-only tools | SOUL, TOOLS, INFRA | `FINDINGS:` + evidence |
| `supervisor_diagnose` | диагноз со ссылками на доказательства | SOUL, INFRA | JSON `Diagnosis` |
| `validator_diagnosis` | независимая проверка grounding | SOUL, INFRA | JSON `Verdict` |
| `remediator` | действие из каталога + rollback | SOUL, GUARDRAILS, INFRA | JSON `Remediation` |
| `validator_remediation` | проверка безопасности/соответствия | SOUL, GUARDRAILS | JSON `Verdict` |
| `responder` / `refuser` | ответы на вопросы / вежливый отказ | SOUL, USER / SOUL, GUARDRAILS | текст |
| `fact_extractor` | факты для памяти | — | JSON `Facts` |
| `scribe` | постмортем | + skill `write-postmortem` | markdown |

Приёмы против слабостей малых моделей: строгие JSON-схемы (constrained decoding Ollama `format`), явный формат доказательств `E1..En`, запрет повторных вызовов, бюджет шагов, явная инструкция языка ответа, маркировка недоверенных данных.

## 2. Persona-файлы (`opscrew/persona/`) — по мотивам SOUL.md/AGENTS.md OpenClaw

| Файл | Смысл | Как влияет на поведение |
|---|---|---|
| `SOUL.md` | ценности по приоритету: не навреди → правда важнее уверенности → скорость восстановления → экономия внимания → учись; характер; «никогда» | осторожные действия, отказ от выдумывания, blameless-постмортемы, игнор инструкций из данных |
| `AGENTS.md` | состав команды, кто за что отвечает, протокол (evidence ids, max revisions, execute только с токеном) | Supervisor понимает, кому делегирует, и что диагноз без ссылок отклонят |
| `GUARDRAILS.md` | запрещено всегда / только с подтверждением / без подтверждения / когда эскалировать | Remediator и Validator опираются на один и тот же текст политики |
| `INFRA.md` | сервисы, зависимости, лимиты, stateful/stateless, как устроены деплой и откат, SLO | предметная модель лаборатории: «postgres stateful», «rollback = previous.json» |
| `TOOLS.md` | порядок использования инструментов, полезные PromQL | Investigator начинает с широкого обзора и не зацикливается |
| `USER.md` | формат и язык ответа, предпочтения из памяти | структура ответа «вывод → доказательства → следующий шаг» |

## 3. Skills (`opscrew/skills/<name>/SKILL.md`)

Формат: YAML-frontmatter (`name`, `description`, `when_to_use`) + пошаговый runbook. **Progressive disclosure**: Triage (Jev-like `choice`) видит только описания всех skills и выбирает один; полный текст попадает в контекст Supervisor/Investigator. Если память нашла очень похожий решённый инцидент (score > 0.75), а Triage не уверен, skill берётся из эпизода.

| Skill | Сценарий | Типичное действие |
|---|---|---|
| `triage-http-5xx` | 5xx/502, падение зависимости | restart_service(redis) |
| `diagnose-oom` | OOMKilled, рестарты, exit 137 | rollback_config |
| `disk-pressure` | ENOSPC, 507, диск > 90 % | cleanup_uploads |
| `db-connection-exhaustion` | too many clients | rollback_config (+ terminate_idle_db) |
| `bad-deploy-rollback` | падение после деплоя | rollback_config |
| `latency-regression` | рост p95, медленные запросы | rollback_config (feature flag) |
| `write-postmortem` | шаблон blameless-постмортема | — |

## 4. Tools (MCP-сервер `ops-tools`)

| Tool | Доступ | Кто может вызвать | Защита |
|---|---|---|---|
| `query_metrics(promql, minutes)` | read | Investigator, verify | — |
| `query_logs(service, contains, minutes, limit)` | read | Investigator | вывод в `<untrusted_tool_output>` |
| `list_services()`, `inspect_service(service)` | read | Investigator, verify | — |
| `run_diagnostic(command)` | read (sandbox) | Investigator | allowlist executor, без shell, `BLOCKED by sandbox policy` |
| `list_alerts()` | read | Investigator | — |
| `apply_remediation(action, run_id, approval_token, service)` | **write** | только узел `execute` (не привязан к LLM) | каталог действий + HMAC approval token |

Почему MCP: стандартный протокол (инструменты переиспользуются любым MCP-клиентом — Claude Code, IDE), отдельный процесс/контейнер = отдельная граница доверия, у агента нет credentials к Prometheus/Docker.
