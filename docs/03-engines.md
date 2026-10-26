# 03. Движки локального инференса

## 1. Критерии (под агента на MacBook M4 Pro 24 GB)

| # | Критерий | Почему важно |
|---|---|---|
| E1 | Поддержка Apple Silicon / Metal / MLX | только GPU даёт приемлемую скорость; CUDA-only движки отпадают |
| E2 | Скорость генерации и обработки промпта | агент делает десятки вызовов на инцидент, длинные промпты (evidence) |
| E3 | OpenAI-compatible API + нативный tool calling | LangChain/LangGraph, MCP-агенты |
| E4 | Structured output (JSON schema / grammar) | строгие схемы диагноза/вердикта для слабых моделей |
| E5 | Мульти-модельность: несколько моделей, авто-загрузка/выгрузка | роутинг L0/L1/L2/V на одном железе |
| E6 | Каталог моделей и форматы (GGUF / MLX / safetensors) | быстрый доступ к свежим моделям |
| E7 | Поддержка decision-моделей (Jev-like `/v1/systemone`) | требование «Jev-like model» |
| E8 | Параллельность / батчинг | несколько агентов одновременно |
| E9 | Эксплуатация: сервис, метрики, простота | MVP за 3–4 недели |

## 2. Сравнение

| Движок | E1 Apple | E3 API / tools | E4 structured | E5 multi-model | E6 форматы | E7 systemone | E8 батчинг | Итог |
|---|---|---|---|---|---|---|---|---|
| **Ollama 0.40** | ✅ MLX-бэкенд (с v0.19) + llama.cpp для GGUF | ✅ native + OpenAI, tools | ✅ `format` = JSON schema | ✅ авто-загрузка/выгрузка, keep_alive, LRU | GGUF, MLX, библиотека с тегами | ✅ **с 0.35** (tev1, nimble) | ограниченно (`OLLAMA_NUM_PARALLEL`) | ✅ **выбран** |
| llama.cpp (`llama-server`) | ✅ Metal | ✅ OpenAI, tools (jinja templates) | ✅ GBNF / JSON schema | ⚠️ одна модель на процесс (router-mode в новых версиях) | GGUF | ❌ | ✅ continuous batching, слоты | эталон производительности GGUF, но больше ручной работы |
| MLX / mlx-lm (`mlx_lm.server`) | ✅ нативно Apple | ✅ OpenAI-подобный, tools частично | ⚠️ ограниченно | ❌ одна модель | MLX (HF `mlx-community`) | ❌ | ⚠️ | максимум скорости на Mac, но слабая эксплуатация |
| LM Studio | ✅ MLX + llama.cpp | ✅ OpenAI, tools | ✅ | ✅ JIT-загрузка | GGUF, MLX | ❌ | ⚠️ | удобный GUI; проприетарный, headless-режим вторичен |
| vLLM | ❌ CUDA/ROCm (CPU/Metal — экспериментально) | ✅ OpenAI, tools | ✅ guided decoding | ✅ (несколько инстансов) | safetensors, AWQ/GPTQ/FP8 | ❌ | ✅ PagedAttention, лучший throughput | ✅ для **production на GPU-кластере**, не для Mac |
| SGLang | ❌ CUDA | ✅ | ✅ (самый быстрый constrained decoding) | ✅ | safetensors | ❌ | ✅ RadixAttention | production, агентные нагрузки с общим префиксом |
| LocalAI | ⚠️ через llama.cpp | ✅ OpenAI drop-in | ✅ | ✅ | многие бэкенды | ❌ | ⚠️ | универсальная обёртка, лишний слой |
| TGI (HF) | ❌ CUDA | ✅ | ✅ | ⚠️ | safetensors | ❌ | ✅ | переведён в режим поддержки, уступает vLLM/SGLang |

## 3. Замеры на одном и том же файле модели

GGUF-blob из хранилища Ollama запускается и в Ollama, и в `llama-bench` (Metal), поэтому сравнение честное: одинаковые веса и квантизация. Скрипт: `bench/run_engines.py`, результаты: `bench/results/engines.json`.

| model | Ollama pp tok/s | Ollama tg tok/s | Ollama TTFT ms | llama.cpp pp tok/s | llama.cpp tg tok/s | llama.cpp backend |
|---|---|---|---|---|---|---|
| granite4.2:8b | 300.3 | 36.8 | 3683 | 291.3 | 35.9 | BLAS,MTL |
| qwen2.5:7b-instruct | 366.4 | 41.4 | 4107 | 350.2 | 41.9 | BLAS,MTL |
| ornith:9b | 310.5 | 34.8 | 4854 | 301.7 | 34.7 | BLAS,MTL |

pp — обработка промпта (1.1–1.5k токенов, уникальный префикс, чтобы исключить кэш), tg — генерация 128 токенов, медиана 3 повторов. **Вывод:** на одном GGUF разница Ollama и llama.cpp ≤ 3 % — Ollama исполняет GGUF тем же llama.cpp runner'ом; MLX-модели (gemma4, tev1, nimble) Ollama запускает MLX-runner'ом, llama.cpp их не загружает.

## 4. Выбор и обоснование

**Ollama** — основной движок:
1. Единственный из рассмотренных, кто из коробки обслуживает **Jev-like decision-модели** (`/v1/systemone`): требование задания закрывается без своего сервера.
2. **Несколько моделей на одном endpoint'е** с автозагрузкой и выгрузкой. Это и есть механизм нашего роутинга L0/L1/L2/V на 24 GB.
3. MLX-бэкенд на Apple Silicon плюс llama.cpp для GGUF. Производительность близка к «голому» llama.cpp (см. замеры), а обёртка даёт API, tools, `format`=JSON schema и keep_alive.
4. Нативная интеграция в LangChain (`ChatOllama`: `reasoning=False`, structured output).

**Чем платим:** меньше контроля над батчингом и параметрами KV-cache, чем у llama.cpp/vLLM. Параллельные запросы к разным моделям вытесняют друг друга из памяти. Нет нативных Prometheus-метрик (собираем сами через `/api/ps`).

**Production (GPU-кластер):** vLLM или SGLang за LiteLLM-прокси, OpenAI-compatible API. Код агента не меняется: меняется только `base_url` в `config/models.yaml`. Decision-модели (tev1/nimble — это fine-tune Qwen3.5) там подаются как обычные модели, а `systemone`-обёртку пишем на логитах вариантов.
