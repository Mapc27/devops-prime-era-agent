# 04. Архитектура Ops Crew

## 1. Архитектурный стиль и обоснование

**Supervisor + специалисты + отдельный слой верификации, оркестрация явным графом (state machine).**

| Альтернатива | Почему нет |
|---|---|
| Один агент с кучей tools | смешивает роли; слабая модель теряет фокус; нет независимой проверки |
| Несколько независимых агентов без общего флоу | ред-флаг задания: нет роутинга/хореографии |
| Хореография (event-driven) | порядок проверок (validate → human → execute) не гарантирован топологией |
| Swarm / handoffs (LLM решает, кому передать) | для изменяющих действий недопустимо: обход валидатора возможен «по ошибке модели» |
| Свободный групповой чат (AutoGen) | непредсказуемое число вызовов → минуты на локальном железе |

Выбранный стиль даёт: детерминированный контроль потока (безопасность в топологии), независимого валидатора, дешёвые решения роутинга на Jev-like модели и тяжёлые модели только там, где они нужны.

## 2. Слои агента

| Слой | Компоненты | Ответственность |
|---|---|---|
| Interface | FastAPI (`/chat`, `/runs/{id}/approve`, `/alert`, `/metrics`), Web UI, CLI | вход: человек и Alertmanager |
| Orchestration | LangGraph `StateGraph` + `AsyncSqliteSaver` | маршруты, циклы, лимиты, interrupt/resume |
| Agents | Triage, Knowledge, Supervisor, Investigator, Remediator, Scribe, Responder | предметная работа |
| **Verification** | Guardrails (детерминированные) → Jev-like pre-checks → **Validator другого семейства** → **Human gate** + approval token | отсечение галлюцинаций и опасных действий |
| Capabilities | Model router, Memory (L1–L3), MCP tools, Persona & Skills | модели, знания, инструменты |
| Observability | OTel/OpenInference → Phoenix; Prometheus метрики; JSON-логи → Loki | трейсы, траектории, метрики, алерты |

## 3. Роутинг моделей

| Уровень | Модель | Семейство | Для чего |
|---|---|---|---|
| L0 | `tev1:4b` (Jev-like, `/v1/systemone`) | Qwen3.5-based | классификация запроса, severity, сложность, выбор skill; grounding/fit pre-checks; инвалидация фактов |
| L1 | `granite4.2:8b` | IBM Granite | простые инциденты, ответы на вопросы, извлечение фактов, постмортем |
| L2 | `ornith:9b` (Q4_K_M, Qwen3.5-based) | Qwen | сложные инциденты: план, расследование, ремедиация; лучший средний балл в бенчмарке, reasoning 1.0 |
| V | `gemma4:12b` | Google Gemma | валидатор и LLM-as-judge — **другое семейство**, проверяется при старте (`ConfigError`) |
| L3 | облачный OpenAI-compatible (Gemini Flash), выключен | — | fallback, если локальные уровни недоступны |

Правила: `kind ∈ {question, knowledge_update, dangerous}` → L1; `incident` → по `complexity` (simple → L1, complex → L2); каскад: `confidence < 0.6` → на уровень выше; fallback-цепочки `heavy → light → cloud`, `validator → light`. Решение роутера пишется в атрибуты трейса и в `opscrew_router_decisions_total`.

## 4. Диаграммы

Исходники — `docs/diagrams/*.puml` (PlantUML + C4-PlantUML stdlib), рендер — `make diagrams` → `report/img/*.png`.

| # | Диаграмма | Файл |
|---|---|---|
| 1 | C4 System Landscape | `c4-1-landscape.puml` |
| 2 | C4 System Context | `c4-2-context.puml` |
| 3 | C4 Container (с границами изоляции) | `c4-3-container.puml` |
| 4 | C4 Component (слои агента, слой верификации) | `c4-4-component.puml` |
| 5 | C4 Code (типы и модули) | `c4-5-code.puml` |
| 6 | C4 Dynamic (расследование по алерту) | `c4-6-dynamic.puml` |
| 7 | C4 Deployment (MVP + целевой K8s) | `c4-7-deployment.puml` |
| S1 | Sequence: инцидент happy path | `seq-1-incident.puml` |
| S2 | Sequence: revise → escalate | `seq-2-revise.puml` |
| S3 | Sequence: HITL reject и защита от прямого вызова | `seq-3-hitl-reject.puml` |
| S4 | Sequence: темпоральная инвалидация факта | `seq-4-memory.puml` |
| S5 | Sequence: роутинг и fallback | `seq-5-routing.puml` |

## 5. Граф (фактическая топология из кода)

```
triage ─┬─ question ──────────► answer ──────────────────────────────┐
        ├─ knowledge_update ──► learn ───────────────────────────────┤
        ├─ dangerous ─────────► refuse ──────────────────────────────┤
        └─ incident ─► recall ► plan ► investigate ► diagnose ► validate_diagnosis
                                         ▲     revise │ approve │ escalate ─────┤
                                         └────────────┘         ▼               │
                            remediate ◄── revise ── validate_remediation        │
                                                approve │ escalate ─────────────┤
                                                 human_gate (interrupt)         │
                                        approve ▼               reject ▼        │
                                    execute ► verify ► scribe ◄─────────┘        │
                                                         └────► respond ◄───────┘
```

Лимиты: `max_revisions=2` (диагноз и ремедиация), `max_tool_steps=8`, `recursion_limit=60`, дедуп идентичных tool-вызовов.
