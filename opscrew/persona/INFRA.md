# INFRA — описание стенда (лаборатории)

## Сервисы
| Сервис | Роль | Зависит от | Лимит памяти | Stateful |
|---|---|---|---|---|
| nginx | входная точка, proxy `/api/*` → api:8000 | api | 64 MB | нет |
| api | FastAPI: `/cart` (redis + postgres), `/upload` (volume /data, 8 MB), `/health` | postgres, redis, config | 256 MB | нет |
| worker | фоновые задачи из redis-очереди; `batch_size` из конфига | redis, config | 96 MB | нет |
| reporter | ночные отчёты, ходит в postgres | postgres, config | 128 MB | нет |
| postgres | основная БД, `max_connections=40` | — | 256 MB | **да** |
| redis | кэш и очередь, без persistence | — | 128 MB | нет (кэш) |

## Конфигурация и деплой
- Конфигурация версионируется: `/config/current.json` и `/config/previous.json`. Деплой = новая версия
  (метрика `app_config_version`). `rollback_config` восстанавливает предыдущую и перезапускает api/worker/reporter.
- Типичные ключи: `api.database_url`, `api.search_query_v2` (feature flag), `worker.batch_size`,
  `reporter.leak_connections`.

## Наблюдаемость
- Метрики — Prometheus, логи — Loki (метка `service`), алерты — Alertmanager → Ops Crew webhook.
- SLO api: availability 99.9% / 30 дней, p95 `/cart` < 500 ms.
