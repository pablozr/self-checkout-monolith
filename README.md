# Self Checkout Monolith API

API em FastAPI para fluxo de self-checkout em restaurante: autenticação, gestão de utilizador, leitura de menu por mesa e carrinho anonimo com sessao em Redis.

## Estado atual do projeto (ate onde ja produzimos)

### Pronto

- Auth completa por cookie (`/auth/login`, `/auth/google-login`, `/auth/logout`)
- Fluxo de reset de password com Redis + RabbitMQ + worker SMTP
- CRUD basico de usuario (`/users/`, `/users/me`)
- Bootstrap de sessao anonima por mesa (`/menu?table=<numero>`)
- Carrinho anonimo em Redis (`/cart`, add/update/remove/clear)
- Catalogo ativo vindo do Postgres, com cache por produto no Redis

### Ainda nao implementado neste repo

- Checkout/pagamento
- Persistencia de pedido em tabela `orders`
- Integracoes de cozinha/comanda/impressao

## Stack

- Python 3.12+
- FastAPI + Uvicorn
- PostgreSQL (`asyncpg`)
- Redis (`redis.asyncio`)
- RabbitMQ (`aio-pika`)
- Pydantic v2 (`pydantic-settings`)
- JWT (`PyJWT`) + bcrypt
- Google Sign-In (`google-auth`)

Sem ORM: consultas SQL diretas, com placeholders `$1`, `$2`, etc.

## Arquitetura

- `routes/`: camada HTTP (parsing, Depends, cookies, status code)
- `services/`: regra de negocio e acesso a DB/Redis/Rabbit
- `schemas/`: contratos de entrada e mapeamentos de saida
- `core/`: conexoes, seguranca, config, logger
- `workers/`: processos assinc separados (ex.: SMTP)

## Estrutura principal

```text
.
├── core/
├── routes/
│   ├── auth/router.py
│   ├── users/router.py
│   ├── menu/router.py
│   └── cart/router.py
├── services/
│   ├── auth/
│   ├── user/
│   ├── catalog/
│   ├── table/
│   ├── cart/
│   ├── cache/
│   └── messaging/
├── schemas/
├── workers/smtp/email_worker.py
├── schema.sql
├── .env.example
├── main.py
└── requirements.txt
```

## Setup rapido

1. Criar e ativar venv

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Instalar dependencias

```bash
pip install -r requirements.txt
```

3. Criar `.env` a partir do exemplo

```bash
copy .env.example .env
```

4. Subir infraestrutura (Postgres, Redis, RabbitMQ) e aplicar schema

```bash
psql -U postgres -d your_db -f schema.sql
```

## Rodando a API

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- Swagger: `http://localhost:8000/docs`
- OpenAPI: `http://localhost:8000/openapi.json`

## Worker de email

```bash
python -m workers.smtp.email_worker
```

## Variaveis de ambiente

Use o arquivo `.env.example` como base. Blocos principais:

- Aplicacao: `ENVIRONMENT`, `API_PORT`
- DB: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- Redis: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- Rabbit: `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`
- JWT: `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- SMTP: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`
- Google: `GOOGLE_CLIENT_ID`
- Stripe: `STRIPE_SECRET_KEY`, `STRIPE_CHECKOUT_SUCCESS_URL`, `STRIPE_CHECKOUT_CANCEL_URL`, `STRIPE_CURRENCY`, `STRIPE_WEBHOOK_SECRET`

## Endpoints disponiveis hoje

### Auth

- `POST /auth/login`
- `POST /auth/google-login`
- `POST /auth/logout`
- `POST /auth/forget-password`
- `POST /auth/validate-code`
- `POST /auth/update-password`

### Usuarios

- `POST /users/`
- `GET /users/me`
- `PUT /users/me`

### Menu e Carrinho

- `GET /menu?table=1` (valida mesa ativa, carrega sessao anonima, retorna produtos e carrinho)
- `GET /cart/`
- `POST /cart/items`
- `PUT /cart/items/{product_id}`
- `DELETE /cart/items/{product_id}`
- `DELETE /cart/`

## Regras importantes de seguranca

- Cookies HttpOnly + `SameSite=lax` (`auth`, `auth_reset`, `anon_session`)
- JWT para auth e reset
- Sessao anonima do carrinho com TTL renovado no Redis

## Banco atual (`schema.sql`)

- `users`
- `tables`
- `products`

## Como testar fluxo principal rapido

1. Criar uma mesa e produtos no Postgres
2. Chamar `GET /menu?table=1`
3. Copiar cookie `anon_session`
4. Adicionar item em `POST /cart/items`
5. Conferir carrinho em `GET /cart/`

## Licenca

MIT. Veja `LICENSE`.
