# Ops Crew — common commands
MODELS = tev1:4b tev1:0.8b nimble:9b granite4.2:8b gemma4:12b gemma4:26b qwen3.8:27b muse-glimmer:30b ornith:9b embeddinggemma-2


.PHONY: eval-continuous online-judge models-min charts
.PHONY: setup models up down ps test bench bench-decision bench-engines eval eval-quick demo diagrams dashboards report chaos-list reset

setup:            ## python deps (uv, Python 3.12)
	uv sync

models:           ## pull all local models used by the system and the benchmark
	@for m in $(MODELS); do ollama pull $$m; done

up:               ## build and start lab + observability + agent
	docker compose build config-init executor lab-control agent
	docker compose up -d --no-build
	@echo "UI: http://localhost:8088  Grafana: http://localhost:3000  Phoenix: http://localhost:6006  Prometheus: http://localhost:9090"

down:
	docker compose down

ps:
	docker compose ps

test:             ## offline unit tests (no LLM needed)
	uv run pytest -q

bench:            ## LLM benchmark for agentic properties (all candidate models)
	uv run python bench/run_bench.py --all

bench-decision:   ## Jev-like decision models vs LLM-as-classifier
	uv run python bench/run_decision_bench.py

bench-engines:    ## Ollama vs llama.cpp on the same GGUF file
	uv run python bench/run_engines.py

eval:             ## full offline eval suite on the lab (~1h)
	uv run python evals/run_evals.py

eval-continuous:  ## continuous evals + online judge every 60 min (Ctrl+C to stop)
	uv run python evals/continuous.py --interval 60

online-judge:     ## LLM-judge over new production traces in Phoenix
	uv run python evals/online_judge.py

models-min:       ## only the models used at runtime (~20 GB)
	@for m in tev1:4b granite4.2:8b ornith:9b gemma4:12b embeddinggemma-2; do ollama pull $$m; done

charts:           ## charts + LangGraph render for the report
	uv run python report/make_charts.py && uv run python report/render_graph.py && uv run python report/claude_usage.py

eval-quick:
	uv run python evals/run_evals.py --only questions dangerous knowledge

demo:             ## inject an incident and investigate it from the CLI (interactive approval)
	uv run python lab/chaos/chaos.py inject redis_down
	uv run opscrew chat "Users report the shop cart is broken, api returns 500 errors."

chaos-list:
	uv run python lab/chaos/chaos.py list

reset:
	uv run python lab/chaos/chaos.py reset-all

diagrams:         ## render C4 + sequence diagrams (PlantUML) to report/img
	cd docs/diagrams && plantuml -tpng -o ../../report/img *.puml

dashboards:
	python3 observability/build_dashboards.py

report:           ## build report/report.pdf
	uv run python report/build_report.py
