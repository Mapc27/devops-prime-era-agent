# 06. Фреймворк для агентной системы

## 1. Требования к фреймворку (из ТЗ)

| # | Требование | Почему |
|---|---|---|
| F1 | Явный граф / state machine с циклами | revise-цикл валидатора, ограничение итераций, ветвление по маршруту Triage |
| F2 | Human-in-the-loop с паузой и возобновлением | подтверждение изменяющих действий; процесс может ждать человека минутами |
| F3 | Персистентное состояние (checkpointing) | рабочая память L1, возобновление после interrupt, дебаг траекторий |
| F4 | Работа с локальными моделями (Ollama) и tool calling | основной режим offline |
| F5 | MCP-клиент | tools как отдельный изолированный сервис |
| F6 | Structured output (JSON schema) | диагноз, вердикт, ремедиация — строгие схемы для слабых моделей |
| F7 | Трассировка (OpenTelemetry / OpenInference) | observability траекторий |
| F8 | Детерминированный контроль потока | безопасность нельзя отдавать на «решение LLM, кого вызвать дальше» |

## 2. Сравнение

| Фреймворк | Модель оркестрации | HITL / interrupt | Checkpointing | Local LLM / tools | MCP | Observability | Итог для Ops Crew |
|---|---|---|---|---|---|---|---|
| **LangGraph** | явный StateGraph: узлы, условные рёбра, циклы, reducers | `interrupt()` + `Command(resume)`, нативно | SQLite / Postgres / Redis savers | ChatOllama, bind_tools, with_structured_output | langchain-mcp-adapters | OpenInference / LangSmith / Langfuse | ✅ **выбран** |
| LangChain (agents) | линейные цепочки, `create_agent` (ReAct) | через middleware | через LangGraph | ✅ | ✅ | ✅ | используем как библиотеку моделей и tools под LangGraph |
| CrewAI | роли + задачи, sequential / hierarchical process | `human_input` на задаче, без настоящей паузы с сохранением состояния | ограниченно (Flows) | через LiteLLM | ✅ | собственная телеметрия, OTel | ❌ поток решает «менеджер-LLM» (hierarchical) — слабые локальные модели путаются; revise-цикл и интерактивный HITL неестественны |
| AutoGen / AG2 (Microsoft) | диалог агентов (GroupChat), actor-модель (v0.4+) | `UserProxyAgent` | частично | ✅ | ✅ | OTel | ❌ свободный диалог = непредсказуемое число LLM-вызовов и токенов (на локальном железе — минуты); сложно гарантировать «валидатор всегда перед действием». Microsoft переводит развитие в Microsoft Agent Framework |
| AutoGPT | автономный цикл «цель → план → действия»; сейчас скорее платформа с блоками | слабый | платформа | ✅ | частично | своя | ❌ ориентирован на полную автономность — противоречит политике «не навреди»; тяжёлая платформа |
| Haystack (deepset) | pipelines (DAG) + Agent компонент | breakpoints | сериализация pipeline | ✅ Ollama | ✅ | OTel / Langfuse | ⚠️ силён в RAG-пайплайнах; циклы и HITL возможны, но менее естественны, меньше примеров мультиагентности |
| PydanticAI | типобезопасный агент + pydantic-graph | deferred tools | persistence в graph | ✅ | ✅ | Logfire (OTel) | ⚠️ близкая альтернатива: отличная типизация, но меньше готовых компонентов (checkpointers, MCP-адаптеры) и сообщество |
| OpenAI Agents SDK | handoffs между агентами, guardrails | ✅ | sessions | через LiteLLM | ✅ | встроенный tracing | ⚠️ handoff-модель = LLM решает передачу управления; оптимизирован под OpenAI Responses API |
| smolagents (HF) | code-agents (LLM пишет Python) | — | — | ✅ | ✅ | OTel | ❌ исполнение сгенерированного кода — лишняя поверхность атаки для SRE-агента |
| Google ADK | иерархия агентов, workflow-агенты | ✅ | sessions | через LiteLLM | ✅ | Cloud Trace / OTel | ⚠️ лучше всего с Gemini / Vertex, локальный режим вторичен |
| Без фреймворка | свой цикл | своё | своё | — | своё | своё | ❌ red flag: пришлось бы заново писать checkpointing, interrupt/resume, трассировку |

## 3. Решение и аргументация

**LangGraph + LangChain-компоненты** (ChatOllama, MCP adapters, structured output).

1. **Безопасность через топологию.** Порядок `diagnose → validate → remediate → validate → human_gate → execute` задан рёбрами графа, а не «решением» LLM. Валидатор невозможно обойти: в execute нет других входов.
2. **HITL «из коробки».** `interrupt()` сохраняет состояние в SQLite-checkpointer, HTTP-запрос завершается, человек может подтвердить через 10 минут из Web UI — граф продолжается с того же места (`Command(resume=...)`).
3. **Рабочая память = checkpointer.** Слой L1 памяти не нужно писать отдельно.
4. **Слабые локальные модели.** Каждому агенту — узкая задача и строгая JSON-схема (constrained decoding Ollama). В «болтливых» мультиагентных фреймворках (AutoGen GroupChat, CrewAI hierarchical) локальные 8–12B модели теряют нить и зацикливаются; в бенчмарке мы видели зацикливание даже в простых tool-циклах.
5. **Observability.** OpenInference-инструментирование LangChain/LangGraph даёт дерево спанов «узел → LLM → tool» в Phoenix без ручной разметки.

**Чем платим:** LangGraph многословнее CrewAI (больше кода на узел), API быстро меняется (мажорные версии 0.x → 1.x за год), абстракции LangChain местами избыточны. Мы держим зависимость тонкой: модели и tools вызываются через стандартные интерфейсы и заменимы.

## 4. Паттерн мультиагентности

Используется **supervisor + specialists со слоем верификации** (не хореография и не свободный чат):
- Triage (Jev-like) — роутер: определяет путь в графе и уровень модели;
- Supervisor — планирует и синтезирует диагноз, делегирует Investigator'у;
- Validator — независимый агент другого семейства, может вернуть работу (revise) или эскалировать;
- Remediator, Scribe — специалисты; Human gate — обязательная точка контроля.

Альтернативы: *хореография* (агенты сами публикуют события) — сложно гарантировать порядок проверок; *swarm/handoffs* — LLM сама решает, кому отдать управление, — для SRE-действий недопустимо.
