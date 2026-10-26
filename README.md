# Ops Crew — мультиагентный SRE-ассистент на локальных LLM

Ops Crew расследует инциденты в инфраструктуре. Он принимает алерт или сообщение дежурного, собирает логи и метрики, ставит диагноз со ссылками на доказательства и проверяет его агентом-валидатором из **другого семейства моделей**. Затем предлагает безопасное действие, которое выполняется **только после подтверждения человека**, проверяет восстановление и пишет постмортем в долговременную память.

Работает полностью офлайн на MacBook M4 Pro 24 GB: Ollama + LangGraph + MCP + Docker.

```
Alertmanager / человек
        │
   Triage (tev1:4b, Jev-like) ── question ─► Responder
        │            ├─ knowledge ─► Fact extractor ─► temporal memory
        │            └─ dangerous ─► Refuser
        ▼ incident
 Knowledge (memory) ► Supervisor ► Investigator ⇄ MCP ops-tools ⇄ lab
                          ▲              │
                       revise      diagnosis + evidence
                          └─── Validator (gemma4, Google) ─── approve
                                                              ▼
                       Remediator ► Validator ► Human gate ► execute ► verify ► Scribe
```

## Какую проблему решает

Первые 15–30 минут инцидента дежурный вручную собирает одно и то же: кто упал, был ли деплой, что в логах и метриках, что делали в прошлый раз. Ops Crew делает эту работу сам, начиная прямо с алерта. Он приносит диагноз со ссылками на доказательства и безопасное действие, которое выполняется только после подтверждения человека. Работает локально, чтобы чувствительные логи не уходили в облако. Это не универсальный агент вроде Claude Code, а дежурный первой линии со строгим регламентом и узкими правами. Подробнее — §0 отчёта и [тезисы защиты](docs/11-defense.md).

## Быстрый старт

```bash
brew install ollama uv && brew services start ollama
make models-min # ~20 GB: только модели рантайма (make models — все ~80 GB для бенчмарка)
make setup      # Python 3.12 deps
make up         # лаборатория + observability + агент в Docker
make test       # офлайн-тесты
make demo       # внедрить сбой redis_down и расследовать из CLI
```

| Что | URL |
|---|---|
| Web UI агента (чат и подтверждения) | http://localhost:8088 |
| Grafana (дашборды Ops Crew — Agent / Lab — Production) | http://localhost:3000 |
| Phoenix (трейсы и траектории) | http://localhost:6006 |
| Prometheus / Alertmanager | http://localhost:9090 / http://localhost:9093 |

Сбои: `make chaos-list`, `uv run python lab/chaos/chaos.py inject <scenario>`, `make reset`.

## Структура

| Путь | Что |
|---|---|
| `opscrew/graph.py` | граф LangGraph: маршруты, revise-циклы, HITL `interrupt()` |
| `opscrew/agents/nodes.py` | агенты: Triage, Knowledge, Supervisor, Investigator, Validator, Remediator, Human gate, Scribe |
| `opscrew/llm/` | роутер моделей L0/L1/L2/V/L3 с fallback; клиент Jev-like `/v1/systemone` |
| `opscrew/memory/store.py` | память: episodic (гибридный поиск) + semantic (bi-temporal факты) |
| `opscrew/tools/` | MCP-сервер `ops-tools` и клиент; approval token |
| `opscrew/prompts/`, `opscrew/persona/`, `opscrew/skills/` | системные промпты, SOUL/AGENTS/GUARDRAILS/INFRA/TOOLS/USER.md, skills |
| `config/models.yaml` | роли → модели, семейства, роутинг, fallback, цены |
| `lab/` | «production» для расследований + chaos-сценарии с ground truth |
| `observability/` | Prometheus rules, Alertmanager, Loki/Alloy, Grafana dashboards |
| `bench/` | бенчмарки LLM, Jev-like моделей и движков |
| `evals/` | eval-набор (33 кейса) и раннер |
| `docs/` | ТЗ, исследования, архитектура, диаграммы |
| `report/` | отчёт (PDF) |

## Документация

0. [Разбор задания, требования, критерии приёмки, тест-кейсы](docs/00-task-analysis.md)
1. [ТЗ на агента](docs/01-spec.md)
2. [Шорт-лист моделей](docs/02-models-shortlist.md) · [Бенчмарк моделей и выбор](docs/03-models-benchmark.md)
3. [Движки инференса](docs/03-engines.md)
4. [Архитектура, C4 и sequence-диаграммы](docs/04-architecture.md)
5. [Память](docs/05-memory.md) · 6. [Фреймворки](docs/06-frameworks.md) · 7. [Изоляция](docs/07-isolation.md)
8. [Observability](docs/08-observability.md) · 9. [Evals](docs/09-evals.md) · 10. [Промпты, skills, tools](docs/10-prompts-skills-tools.md) · 11. [Тезисы защиты](docs/11-defense.md)
