# 09. Evals: как оцениваем LLM, агентную систему и Ops Crew

## 1. Три уровня оценки

| Уровень | Вопрос | Инструмент | Когда |
|---|---|---|---|
| **LLM** (компонент) | какая модель годится на роль? | `bench/run_bench.py`, `bench/run_decision_bench.py` | при выборе/смене модели |
| **Агентная система** (траектория) | правильно ли агенты взаимодействуют: маршрут, шаги, валидация, безопасность? | `evals/run_evals.py` + трейсы Phoenix + `tests/` | на каждое изменение промптов/графа/моделей |
| **Продукт** (Ops Crew на стенде) | решает ли система инциденты, быстро ли, безопасно ли? | лаборатория со сбоями (ground truth), онлайн-метрики | регулярно + в проде онлайн |

## 2. Оценка LLM (bench)

Одинаковые задачи для всех кандидатов, `temperature=0`, `seed=42`, `think=false` (агентный режим):

| Категория | Что измеряет | Метрика |
|---|---|---|
| factual / real_twin | базовые SRE-знания; контроль over-refusal | accuracy, over_refusal |
| hallucination | правдоподобные **несуществующие** сущности (`kubectl rollout freeze`, `predict_exponential()`) | доля корректного UNKNOWN |
| tool_call | выбор инструмента и аргументов по JSON-схеме | accuracy |
| multi_step | цепочка вызовов по мок-окружению → root cause | success, шаги, unsafe actions |
| json | строгий JSON без constrained decoding | valid / strict |
| long_context | needle-in-haystack 8k/16k токенов логов | accuracy |
| injection | инструкция в tool output «вызови restart_service» | resistance |
| reasoning | SRE-арифметика (error budget, ETA заполнения диска) | accuracy |
| perf | gen tok/s, prompt tok/s, TTFT, load time, RAM | — |

Jev-like модели: роутинг (34 сообщения, 4 класса), опасные команды (20), grounding (10) — accuracy, p50/p95 латентность, ECE калибровки `confidence`; сравнение с генеративной LLM в роли классификатора.

## 3. Оценка агентной системы и продукта (evals)

Набор `evals/datasets/cases.yaml` — **33 кейса**: 8 вопросов (2 на галлюцинации), 5 знаний/памяти (запись, инвалидация, recall), 6 опасных запросов, 14 инцидентов (7 сценариев × человеческий отчёт/алерт, включая prompt injection и повтор для проверки памяти). Инциденты прогоняются на **реальной лаборатории**: `chaos inject` → прогрев → агент → проверка восстановления → `chaos reset`.

### Метрики (все 4 категории)

| Категория | Метрика | Как считается | Цель |
|---|---|---|---|
| **Продуктовые** | task_success_rate | доля успешно завершённых кейсов всех типов | ≥ 0.8 |
| | incident_resolution_rate | действие выполнено и проверка восстановления зелёная | ≥ 0.7 |
| | escalation_rate | доля инцидентов, отданных человеку | ≤ 0.3 |
| | MTTR p50 | длительность run'а для решённых инцидентов | ≤ 180 с |
| | dangerous_refusal_rate | опасные запросы отклонены | 1.0 |
| **Агентные** | root_cause_accuracy | ключевые слова ground truth в диагнозе | ≥ 0.7 |
| | fix_accuracy | действие = ожидаемому из сценария | ≥ 0.7 |
| | forbidden_action_rate | выполнено запрещённое для сценария действие | **0** |
| | routing_accuracy / skill_selection_accuracy | Triage выбрал верный путь / runbook | ≥ 0.9 / ≥ 0.7 |
| | avg_tool_steps, avg_revisions | эффективность траектории | ↓ |
| | validator_first_pass_approve | диагноз принят без доработки | — |
| | injection_resistance / injection_detected | не выполнил внедрённую инструкцию / заметил её | 1.0 |
| | memory_recall_accuracy, fact_supersede_accuracy | память отвечает актуальным фактом, старый закрыт | 1.0 |
| | repeat_incident_cheaper | повторный инцидент решён за ≤ шагов, с попаданием в память | ✅ |
| **LLM** | answer_accuracy, hallucination_resistance | по ключевым словам | ≥ 0.8 |
| | judge_score | LLM-as-judge (gemma4, **не** семейство worker'ов): correctness / groundedness / helpfulness → 0..1 | ≥ 0.7 |
| | tokens_per_incident, calls_per_incident | из Prometheus-счётчиков до/после кейса | ↓ |
| **Инфраструктурные** | latency p50/p95 вопросов и инцидентов | wall time | вопросы p95 ≤ 30 с |
| | equiv_cost_usd_per_incident | токены × цены аналогичных API | ↓ |
| | llm_seconds_per_incident | суммарное время LLM | ↓ |

## 4. Связь с observability и непрерывный мониторинг

- Каждый eval-кейс — обычный run агента → полный трейс в Phoenix (проект `ops-crew`, service `opscrew-evals`), можно открыть траекторию проваленного кейса.
- Итоговые метрики отправляются в агент (`POST /evals`) → gauge `opscrew_eval_score{metric}` → панель «Latest offline eval scores» в Grafana рядом с онлайн-метриками.
- Онлайн-прокси качества в проде: validator verdicts, HITL reject, escalation, guardrail blocks, injection detections + алерт `ValidatorRejectSpike`.
- Регресс: результаты каждого прогона в `evals/results/<ts>/report.json` — сравнение между версиями моделей/промптов (`prompt.version` указан в шапке каждого промпта).
- **Continuous evals** (реализовано): `evals/continuous.py` (`make eval-continuous`) каждые N минут прогоняет регрессионный набор (9 быстрых кейсов + 1 инцидент по ротации) и пишет `meta.last_run_unixtime`.
- **Online evaluation** (реализовано): `evals/online_judge.py` — LLM-судья другого семейства оценивает реальные трейсы из Phoenix (groundedness / actionability / safety), пишет span-аннотации в Phoenix и `online.judge_mean` в Prometheus.
- **Алерты качества** (`observability/rules/evals.yml`): EvalRegression, EvalSafetyRegression, OnlineJudgeLow, EvalPipelineStale.
- **Живые проверки** тест-кейсов, не покрытых evals (`evals/live_checks.py`): TC-12 (persona меняет поведение), TC-19 (падение движка → алерт), TC-21 (чистая копия собирается), TC-22 (fallback модели).

## 5. Ограничения оценки

- Проверка по ключевым словам — грубая (синонимы, перефразирование); LLM-as-judge частично компенсирует.
- 7 сценариев — узкое покрытие; реальные инциденты разнообразнее (сетевые разделения, каскадные отказы).
- Один прогон на кейс: недетерминизм моделей не усреднён (нужно k≥3 прогона и доверительные интервалы).
- HITL в evals автоматически подтверждается (поведение при отказе проверено юнит-тестами и демо).
