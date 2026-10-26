# 08. Observability агентной системы

## 1. Чем мониторинг агента отличается от мониторинга сервиса

| Обычный сервис | Агентная система |
|---|---|
| детерминированный путь запроса | **траектория** меняется от запуска к запуску: разные узлы, число шагов, tools |
| ошибка = исключение / 5xx | «тихие» ошибки: неверный диагноз, галлюцинация, лишнее действие при HTTP 200 |
| latency = время обработки | latency складывается из LLM-вызовов разных моделей, загрузки моделей в память, ожидания человека |
| стоимость ≈ инфраструктура | стоимость ∝ токенам и выбранному уровню модели (роутинг) |
| качество проверяется тестами | качество проверяется **evals** + онлайн-сигналами (вердикты валидатора, HITL reject, эскалации) |

Поэтому нужны **оба** стека: LLM-native (трейсы/траектории/промпты/токены) и классический (метрики/логи/алерты инфраструктуры).

## 2. Сравнение LLM-observability

| Инструмент | Модель | Self-host | Сильные стороны | Минусы для нас |
|---|---|---|---|---|
| **Arize Phoenix** | OTel/OpenInference-native, трейсы, сессии, evals, datasets | ✅ 1 контейнер | OpenInference-инструментирование LangChain/LangGraph «одной строкой», лёгкий, offline | меньше продуктовых фич (аннотации команд, промпт-менеджмент проще) |
| Langfuse | трейсы, промпт-менеджмент, evals, датасеты, cost | ✅ (v3: web + worker + Postgres + ClickHouse + Redis + S3/MinIO) | богатый UI, промпт-версии, LLM-as-judge | 6 контейнеров, ClickHouse — несколько ГБ RAM: на 24 GB рядом с моделями тесно |
| LangSmith | трейсы, evals, датасеты | ❌ (self-host только enterprise) | лучшая интеграция с LangGraph | облако → данные инцидентов уходят наружу; противоречит offline-требованию |
| Langtrace | OTel SDK + UI | ✅ | OTel-совместимость | меньше сообщество |
| Helicone / OpenLLMetry | прокси / OTel-инструменты | ✅ | cost tracking | прокси-модель не видит граф агента |
| Grafana + Tempo | общий OTel-трейсинг | ✅ | единый стек с метриками | нет LLM-специфичного UI (промпты, токены, сессии) |

**Выбор: Phoenix** (трейсы и траектории) + **Prometheus / Alertmanager / Loki / Alloy / Grafana** (метрики, алерты, логи). Langfuse — рекомендуемая замена Phoenix при развёртывании на сервере, где хватает памяти; код не меняется (OTel-экспортер).

## 3. Что собираем

### 3.1 Трейсы и траектории (Phoenix, OTLP gRPC)
- корневой span `opscrew.run` (`session.id = run_id`), вложенные спаны **каждого узла графа**, LLM-вызовов (модель, промпт, ответ, токены), tool-вызовов MCP, решений Jev-like модели (`decision.triage`, `decision.grounding`, …), операций памяти (`memory.*.search` как RETRIEVER).
- атрибуты: `opscrew.route` (kind/tier/skill/confidence), `validator.model_family`, `opscrew.validation.*`, `opscrew.tool_steps`, `opscrew.injection_detected`, `opscrew.outcome`.
- траектория дублируется в JSON (`.data/trajectories/<run_id>.json`) — для оффлайн-evals траекторий и для UI.

### 3.2 Метрики (Prometheus, `/metrics` агента и ops-tools)

| Категория | Метрики |
|---|---|
| Продуктовые | `opscrew_runs_total{kind,outcome}`, `opscrew_run_duration_seconds{kind}`, `opscrew_hitl_decisions_total{decision}`, `opscrew_eval_score{metric}` |
| Агентные | `opscrew_router_decisions_total{kind,tier,reason}`, `opscrew_validator_verdicts_total{stage,verdict}`, `opscrew_guardrail_blocks_total{reason}`, `opscrew_tool_calls_total{tool,status}`, `opscrew_tool_steps_per_run`, `opscrew_memory_ops_total{layer,op}`, `opscrew_memory_items{layer,state}` |
| LLM | `opscrew_llm_latency_seconds{role,model,tier}`, `opscrew_llm_tokens_total{role,model,direction}`, `opscrew_llm_equiv_cost_usd_total{model}`, `opscrew_llm_errors_total`, `opscrew_decision_latency_seconds{question}` |
| Инфраструктура | `opscrew_llm_engine_up`, `opscrew_llm_loaded_model_bytes{model}`, `opstools_latency_seconds{tool}`, `opstools_calls_total`, + метрики лабы (`lab_container_*`, `http_requests_total`, `pg_*`, `redis_*`) |

### 3.3 Логи (Loki через Alloy)
JSON-логи всех контейнеров (метка `service`), у агента — с `trace_id`, что позволяет из лога перейти к трейсу.

### 3.4 Алерты (Alertmanager)
- **Лаба** (`observability/rules/lab.yml`): HighErrorRate, ServiceDown, ContainerRestarting, HighLatency, DiskAlmostFull, PostgresTooManyConnections → **webhook в Ops Crew** (`target=opscrew`), агент сам начинает расследование (дедуп 15 минут на alertname).
- **Качество** (`observability/rules/evals.yml`): EvalRegression, EvalSafetyRegression, OnlineJudgeLow, EvalPipelineStale.
- **Агент** (`observability/rules/agent.yml`): LLMEngineDown, AgentHighLLMLatency, ValidatorRejectSpike (деградация качества worker-модели), GuardrailBlockedAction, AgentErrors, AgentStuckLoop.

### 3.5 Дашборды (Grafana, provisioning)
- **Ops Crew — Agent**: строки Product / Agentic / LLM / Infrastructure + последние оффлайн-eval-оценки + логи агента.
- **Lab — Production**: golden signals, контейнеры, соединения БД, диск, версия конфига, логи ошибок.

## 4. Специфика и «что ещё стоит отслеживать»

- **Доля эскалаций и HITL-reject** — главный онлайн-прокси качества (люди не согласны с агентом).
- **Validator reject rate по версии промпта/модели** — регрессия после смены модели видна раньше, чем жалобы.
- **Загрузки моделей** (load_duration): на 24 GB переключение L2 ↔ V стоит секунды; если растёт — пересмотреть рабочий набор моделей.
- **Дрифт роутинга**: если доля L2 растёт без роста сложности — Triage деградировал.
- **Injection detections** — сигнал безопасности, а не только качества.
- Не реализовано, но нужно в production: PII-редакция в трейсах, sampling трейсов, хранение промптов с версиями (Langfuse prompt management).
