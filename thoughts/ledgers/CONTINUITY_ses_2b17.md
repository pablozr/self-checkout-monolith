---
session: ses_2b17
updated: 2026-04-02T14:06:04.712Z
---

# Session Summary

## Goal
Produzir uma análise profunda do estado atual do sistema sob a ótica de “MVP em produção”, cobrindo o que existe, o que falta e os riscos/recomendações priorizadas para subir em produção.

## Constraints & Preferences
Retornar em português com: 1) resumo executivo, 2) forças atuais, 3) gaps por criticidade (alto/médio/baixo), 4) riscos mais prováveis ao subir em produção, 5) recomendações priorizadas para curto prazo.

## Progress
### Done
- [x] Foi feito um levantamento estrutural do repositório `C:\Users\Pablo\PycharmProjects\self-checkout-monolith`.
- [x] Foi lido o `README.md` para entender escopo atual, fluxos implementados, stack, arquitetura, setup local/container, endpoints disponíveis e estado declarado do projeto.
- [x] Foi inspecionado o bootstrap da aplicação em `main.py`, incluindo `lifespan`, conexões com PostgreSQL/Redis/RabbitMQ/SSE e configuração de CORS.
- [x] Foi analisada a configuração central em `core\config\config.py`, incluindo variáveis de ambiente, TTLs, nomes de cookies, prefixes Redis, fila de email e ranking de papéis.
- [x] Foi analisada a camada de infraestrutura:
  - [x] `core\postgresql\postgresql.py` (pool asyncpg `min_size=1`, `max_size=3`)
  - [x] `core\redis\redis.py`
  - [x] `core\rabbitmq\rabbitmq.py`
  - [x] `core\security\security.py`
  - [x] `core\sse\sse_manager.py`
- [x] Foi analisada a configuração de deploy/container:
  - [x] `docker-compose.yml`
  - [x] `Dockerfile`
  - [x] `.github\workflows\ci.yml`
- [x] Foi analisada a camada HTTP e dependências:
  - [x] `routes\auth\router.py`
  - [x] `routes\menu\router.py`
  - [x] `routes\cart\router.py`
  - [x] `routes\checkout\router.py`
  - [x] `routes\webhooks\router.py`
  - [x] `routes\realtime\router.py`
  - [x] `dependencies\auth.py`
  - [x] `dependencies\session.py`
  - [x] `dependencies\checkout.py`
  - [x] `dependencies\common.py`
- [x] Foi analisada a camada de serviços de negócio:
  - [x] `services\auth\auth_service.py`
  - [x] `services\user\user_service.py`
  - [x] `services\catalog\catalog_service.py`
  - [x] `services\table\table_service.py`
  - [x] `services\cart\cart_service.py`
  - [x] `services\checkout\checkout_service.py`
  - [x] `services\payment\payment_service.py`
  - [x] `services\order\order_service.py`
  - [x] `services\stripe\stripe_service.py`
  - [x] `services\stripe\webhook_service.py`
  - [x] `services\idempotency\idempotency_service.py`
  - [x] `services\cache\cache_service.py`
  - [x] `services\messaging\messaging_service.py`
  - [x] `services\sse\sse_service.py`
- [x] Foi analisado o worker assíncrono SMTP em `workers\smtp\email_worker.py`.
- [x] Foi analisado o schema relacional em `schema.sql`, incluindo tabelas `users`, `tables`, `products`, `orders`, `order_items`, `payments`, `stripe_events` e índices/uniques existentes.
- [x] Foi analisada a suíte de testes relevante:
  - [x] `tests\services\checkout\test_checkout_service.py`
  - [x] `tests\services\stripe\test_webhook_service.py`
  - [x] `tests\integration\test_checkout_peak.py`
  - [x] `tests\integration\test_webhook_peak.py`
- [x] Foi feita busca específica por sinais de prontidão operacional e foi constatado que não há implementação aparente de endpoints/artefatos de healthcheck de aplicação, readiness, liveness, métricas, tracing, rate limiting ou observabilidade dedicada no código analisado.
- [x] Foram identificados achados importantes para a análise de produção, como:
  - [x] CORS aberto com `allow_origins=["*"]` e `allow_credentials=True`
  - [x] ausência de health endpoints
  - [x] ausência de migrações/versionamento de schema
  - [x] ausência de pipeline de deploy/rollback
  - [x] ausência de instrumentação/metrics/tracing
  - [x] ausência de rate limiting
  - [x] cookies marcados como `secure=True`
  - [x] idempotência de checkout em Redis
  - [x] deduplicação de webhook Stripe persistida em Postgres
  - [x] pool de banco muito pequeno (`max_size=3`)
  - [x] testes cobrindo principalmente concorrência/idempotência de checkout e webhook

### In Progress
- [ ] Consolidar os achados em uma análise executiva estruturada por arquitetura, segurança, confiabilidade, experiência operacional, deploy, rollback, dados, observabilidade, testes, performance, isolamento de falhas e governança de configuração.
- [ ] Classificar gaps por criticidade (alto/médio/baixo) e transformar os achados em riscos prováveis e recomendações de curto prazo.

### Blocked
- (none)

## Key Decisions
- **Analisar o sistema a partir do código-fonte e artefatos operacionais existentes**: Isso permite avaliar o estado real do MVP em produção em vez de depender apenas da descrição do `README.md`.
- **Focar em readiness de produção e não só em completude funcional**: O pedido do usuário explicitamente exige visão de arquitetura, segurança, confiabilidade, operação, deploy, rollback, dados e governança.
- **Usar os testes existentes como evidência de maturidade técnica**: Os testes lidos mostram força específica em idempotência e deduplicação concorrente, o que é relevante para checkout e webhook.
- **Considerar ausências explícitas como gaps de produção**: A busca por `health|ready|live|metrics|prometheus`, `rate limit`, `trace|opentelemetry|sentry|prometheus|statsd` e migrações não encontrou implementação útil no código do projeto analisado.
- **Preservar a análise no contexto de monólito FastAPI com SQL direto**: O projeto segue separação `routes/`, `services/`, `core/`, `workers/`, sem ORM, o que impacta recomendações de governança, deploy e testes.

## Next Steps
1. Redigir o **resumo executivo** em português, sintetizando prontidão atual vs. lacunas críticas para produção.
2. Listar as **forças atuais** com base nas evidências do código: separação em camadas, checkout idempotente, dedupe de webhook, uso de transações, worker SMTP, SSE admin e testes de burst.
3. Organizar os **gaps por criticidade** cobrindo explicitamente arquitetura, segurança, confiabilidade, operação, deploy, rollback, dados, observabilidade, testes, performance, isolamento de falhas e governança de configuração.
4. Descrever os **riscos mais prováveis ao subir em produção**, conectando diretamente cada risco aos achados do código.
5. Priorizar **recomendações de curto prazo** com foco em MVP em produção: health/readiness, restrição de CORS, secrets/config, migrações, observabilidade mínima, estratégia de deploy/rollback, hardening de worker e sizing/conexões.
6. Entregar a resposta final no formato solicitado pelo usuário, em português.

## Critical Context
- O projeto já implementa fluxos principais de self-checkout: autenticação por cookie, reset de senha com Redis + RabbitMQ + worker SMTP, sessão anônima por mesa, carrinho em Redis, checkout Stripe com idempotência e webhook Stripe com SSE admin.
- `main.py` conecta PostgreSQL, Redis, SSE e RabbitMQ no startup, mas não expõe endpoints de health/readiness/liveness.
- `main.py` configura `CORSMiddleware` com `allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`, o que é um ponto crítico para produção.
- O pool de banco em `core\postgresql\postgresql.py` está fixado em `min_size=1`, `max_size=3`, potencial gargalo para produção.
- `routes\auth\router.py` e `routes\menu\router.py` setam cookies com `httponly=True`, `secure=True`, `samesite="lax"`.
- `dependencies\session.py` renova TTL da sessão anônima no Redis com `expire`.
- `services\checkout\checkout_service.py` usa `idempotency_service.initialize_checkout_request`, cria `orders` e `payments` em transação e persiste o resultado da idempotência no Redis.
- `services\idempotency\idempotency_service.py` protege contra mesmo `Idempotency-Key` com payload diferente e contra concorrência, retornando mensagens como `"Checkout request already in progress"` e `"Idempotency key already used with a different payload"`.
- `services\stripe\webhook_service.py` registra eventos em `stripe_events` com `ON CONFLICT DO NOTHING`, faz validação contra DB com `FOR UPDATE`, controla transições de status e publica evento SSE após commit lógico.
- `services\sse\sse_service.py` publica em canal Redis `sse:admin:orders`; `core\sse\sse_manager.py` faz fanout para clientes SSE com fila limitada por cliente.
- `workers\smtp\email_worker.py` usa RabbitMQ durable queue e `message.process()`, mas não há supervisão, DLQ, retry/backoff explícitos ou health próprio do worker.
- `schema.sql` existe como schema único/manual; não foram encontrados artefatos de migração/versionamento tipo Alembic.
- `.github\workflows\ci.yml` roda apenas `ruff check .` e `pytest -q`; não há pipeline de build de imagem, deploy, smoke test ou rollback.
- O `Dockerfile` é simples, de estágio único, sem hardening visível, sem usuário não-root explícito e sem healthcheck.
- `docker-compose.yml` possui healthchecks para Postgres/Redis/RabbitMQ e `depends_on` para a API/worker, mas isso é ambiente local/compose, não estratégia de produção.
- Não foram encontrados sinais de métricas, tracing, Sentry, Prometheus, OpenTelemetry, StatsD ou rate limiting.
- Os testes lidos mostram cobertura relevante para concorrência/idempotência:
  - `test_checkout_peak_burst_same_key_allows_single_winner`
  - `test_webhook_peak_burst_dedupes_event_and_publishes_once`
  - `test_start_stripe_checkout_returns_replay_without_touching_db_or_provider`
  - `test_start_stripe_checkout_marks_payment_failed_and_saves_failed_payload_when_provider_fails`
  - dedupe/validação em `test_handle_event_duplicate_event_returns_already_processed`, `test_handle_event_publishes_sse_after_successful_dispatch`, `test_validate_checkout_against_db_rejects_amount_mismatch`
- Não houve modificações de arquivo nesta sessão.
- Não houve erro de execução do código; apenas buscas que retornaram ausência de implementação útil para certos tópicos:
  - busca por `rate.?limit|throttle|limiter`: sem resultados úteis
  - busca por `trace|opentelemetry|sentry|prometheus|statsd`: sem resultados úteis
  - busca por `health|ready|live|metrics|prometheus`: sem endpoints/implementações operacionais úteis
- Uma busca ampla por “migration” retornou muitos resultados de `.venv`, ou seja, ruído de dependências; no projeto em si não foi encontrada solução de migração/versionamento de banco.

## File Operations
### Read
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\.github\workflows\ci.yml`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\Dockerfile`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\core\config\config.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\core\postgresql\postgresql.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\core\rabbitmq\rabbitmq.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\core\redis\redis.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\core\security\security.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\core\sse\sse_manager.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\dependencies\auth.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\dependencies\checkout.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\dependencies\common.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\dependencies\session.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\docker-compose.yml`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\main.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\routes\auth\router.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\routes\cart\router.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\routes\checkout\router.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\routes\menu\router.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\routes\realtime\router.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\routes\webhooks\router.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\schema.sql`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\auth\auth_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\cache\cache_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\cart\cart_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\catalog\catalog_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\checkout\checkout_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\idempotency\idempotency_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\messaging\messaging_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\order\order_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\payment\payment_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\sse\sse_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\stripe\stripe_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\stripe\webhook_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\table\table_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\services\user\user_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\tests\integration\test_checkout_peak.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\tests\integration\test_webhook_peak.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\tests\services\checkout\test_checkout_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\tests\services\stripe\test_webhook_service.py`
- `C:\Users\Pablo\PycharmProjects\self-checkout-monolith\workers\smtp\email_worker.py`

### Modified
- (none)
