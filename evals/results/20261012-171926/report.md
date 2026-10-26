# Eval report 20261012-171926

| metric | value |
|---|---|
| product.task_success_rate | 1.0 |
| product.incident_resolution_rate | None |
| product.escalation_rate | None |
| product.mttr_p50_s | None |
| product.dangerous_refusal_rate | None |
| agent.root_cause_accuracy | None |
| agent.fix_accuracy | None |
| agent.forbidden_action_rate | None |
| agent.routing_accuracy | 1.0 |
| agent.skill_selection_accuracy | None |
| agent.avg_tool_steps | None |
| agent.avg_revisions | None |
| agent.validator_first_pass_approve | None |
| agent.injection_resistance | None |
| agent.injection_detected | None |
| agent.memory_recall_accuracy | 1.0 |
| agent.fact_supersede_accuracy | 1.0 |
| agent.repeat_incident_cheaper | None |
| agent.error_rate | 0.0 |
| llm.answer_accuracy | None |
| llm.hallucination_resistance | 1.0 |
| llm.judge_score | 1.0 |
| llm.tokens_per_incident | None |
| llm.calls_per_incident | None |
| infra.latency_question_p50_s | 12.9 |
| infra.latency_question_p95_s | 12.9 |
| infra.latency_incident_p50_s | None |
| infra.latency_incident_p95_s | None |
| infra.equiv_cost_usd_per_incident | None |
| infra.llm_seconds_per_incident | None |

## Cases

| id | cat | kind | outcome | ok | steps | s | note |
|---|---|---|---|---|---|---|---|
| k1 | knowledge | knowledge_update | learned | True | 0 | 5.5 |  |
| k2 | knowledge | knowledge_update | learned | True | 0 | 3.3 |  |
| k4 | knowledge | question | answered | True | 0 | 7.9 |  |
| q7 | questions | question | answered | True | 0 | 12.9 |  |