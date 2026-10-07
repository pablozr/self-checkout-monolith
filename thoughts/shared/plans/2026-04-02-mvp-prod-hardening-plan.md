# Plano de evolucao para MVP em producao

## Objetivo

Este plano foi escrito para te ajudar a evoluir o projeto de um estado de **MVP funcional** para um estado de **MVP em producao minimamente seguro, previsivel e operavel**, sem tentar sofisticar demais agora.

O foco aqui nao e observabilidade completa, migracao versionada ou rate limiting na aplicacao. O foco e:

1. saber quando a app esta saudavel;
2. saber como ela se recupera;
3. saber como ela falha;
4. melhorar a qualidade dos logs;
5. automatizar um deploy basico.

---

## Ordem recomendada de execucao

Eu seguiria exatamente esta ordem:

1. **Healthcheck, readiness, liveness e comportamento de startup**
2. **Restart automatico e estrategia de recuperacao**
3. **Timeouts, limites e cenarios de falha**
4. **Retry/backoff nas integracoes certas**
5. **Testes de falha de dependencia**
6. **Reorganizacao do logger**
7. **CD basico com GitHub Actions + Docker + deploy via SSH**

Essa ordem e importante porque nao adianta automatizar deploy antes de saber se a app sobe bem, nem melhorar logger antes de decidir como o sistema deve falhar.

---

## Bloco 1 - Healthcheck, readiness e liveness

## O que voce quer atingir

Voce quer responder 3 perguntas diferentes:

- **/health**: a aplicacao esta viva e respondendo?
- **/ready**: a aplicacao esta pronta para receber trafego?
- **/live**: o processo nao travou?

Esses endpoints ajudam no deploy, em restart automatico e no diagnostico rapido.

## Diferenca entre eles

### `/live`
Usa para dizer: "o processo esta rodando".

Esse endpoint deve ser bem simples. Se ele depender de banco, Redis ou Rabbit, pode virar fonte de falso negativo.

### `/ready`
Usa para dizer: "a app consegue operar agora".

Aqui sim voce pode checar dependencias criticas. Para o seu caso, eu recomendo:

- Postgres: **critico**
- Redis: **quase critico**, porque voce usa carrinho, sessao e idempotencia
- RabbitMQ: **importante**, mas talvez nao precise derrubar readiness se o problema for apenas email

### `/health`
Pode ser um resumo mais amigavel para uso humano. Exemplo: status geral + estado das dependencias.

---

## Decisao pratica recomendada

### Minha recomendacao

- `/live`: retorna 200 se a app estiver rodando
- `/ready`: valida Postgres e Redis
- `/health`: retorna um JSON resumido com dependencias e timestamp

Eu **nao** faria `/ready` depender de RabbitMQ no primeiro momento, porque isso pode tirar a API do ar por causa de uma dependencia que nao necessariamente bloqueia todos os fluxos.

---

## Como implementar

Crie uma rota separada, por exemplo:

- `routes/health/router.py`

E nela pense em 3 handlers:

- `GET /live`
- `GET /ready`
- `GET /health`

## O que cada um deve checar

### `/live`
- nao consulta nada externo
- responde algo como:

```json
{
  "status": "alive"
}
```

### `/ready`
- tenta um `SELECT 1` no Postgres
- tenta um `PING` no Redis
- se falhar algo critico, retorna `503`

Resposta boa:

```json
{
  "status": "ready",
  "checks": {
    "postgres": "ok",
    "redis": "ok"
  }
}
```

Resposta ruim:

```json
{
  "status": "not_ready",
  "checks": {
    "postgres": "ok",
    "redis": "failed"
  }
}
```

### `/health`
- pode reaproveitar as checagens
- inclui:
  - timestamp
  - ambiente
  - versao da app, se voce tiver
  - checks por dependencia

---

## O que estudar para implementar

- FastAPI routers
- `JSONResponse`
- retorno `503 Service Unavailable`
- ping em Redis com `redis.asyncio`
- query simples no pool do `asyncpg`

---

## Cuidados importantes

- nao faca healthcheck pesado
- nao rode consulta lenta
- nao coloque log de erro gigante em toda chamada de health
- `/live` deve continuar simples
- `/ready` deve refletir o que realmente impede trafego

---

## Resultado esperado

Ao final desse bloco, voce deve conseguir:

- testar no browser ou curl se a app esta viva
- usar esse endpoint em deploy e restart
- diagnosticar rapidamente se o problema e Postgres ou Redis

---

## Bloco 2 - Restart automatico e recuperacao

## O que voce quer atingir

Se a API ou o worker cair, eles devem voltar sozinhos. Se uma dependencia voltar, sua app deve conseguir se reconectar sem comportamento estranho.

---

## O que decidir

### API
- deve reiniciar automaticamente se morrer
- deve falhar no startup se dependencias criticas estiverem inacessiveis

### Worker SMTP
- deve reiniciar automaticamente
- ao voltar, deve reconectar RabbitMQ e continuar consumindo

---

## No Docker Compose

Voce pode começar adicionando politica de restart:

- `restart: unless-stopped`

nos servicos:

- `api`
- `worker_smtp`

Se mais tarde voce usar outro ambiente de deploy, a ideia continua a mesma, mesmo que a sintaxe mude.

---

## Recuperacao: o que isso significa na pratica

### Caso 1 - app sobe antes do banco
Comportamento desejado:

- startup detecta que banco nao esta acessivel
- app nao fica se dizendo pronta
- quando o banco voltar, novo restart sobe corretamente

### Caso 2 - Redis cai depois da app estar rodando
Comportamento desejado:

- logs claros mostram erro
- `/ready` passa a falhar se Redis for considerado critico
- funcionalidades dependentes degradam de modo previsivel

### Caso 3 - worker cai
Comportamento desejado:

- container reinicia
- worker reconecta RabbitMQ
- mensagens nao sao perdidas por causa de `durable queue`

---

## O que estudar para implementar

- politicas de restart no Docker
- `lifespan` do FastAPI
- fechamento limpo de conexoes
- reconexao de dependencias
- diferenca entre falha de startup e falha em runtime

---

## Resultado esperado

Ao final desse bloco, voce deve ter um sistema que:

- volta sozinho quando processo morre
- nao aceita trafego sem estar pronto
- se comporta melhor quando uma dependencia oscila

---

## Bloco 3 - Timeouts, limites e cenarios de falha

## Objetivo

Definir **qual e o comportamento esperado quando uma dependencia fica lenta, indisponivel ou intermitente**.

Sem isso, o sistema funciona em dias bons, mas em dias ruins fica imprevisivel.

---

## Passo 1 - Criar uma tabela de dependencias

Monte uma tabela como esta e salve no repo depois:

| Dependencia | Onde e usada | Criticidade | Se falhar | Comportamento esperado |
|---|---|---:|---|---|
| Postgres | pedidos, pagamentos, usuarios | alta | API nao consegue operar | `/ready` falha e endpoints criticos retornam 503 |
| Redis | carrinho, sessao, idempotencia, cache, SSE | alta | varias features degradam | logar erro e falhar controlado |
| RabbitMQ | fila de email | media | email nao segue | request pode seguir ou falhar conforme regra |
| Stripe | checkout | alta | pagamento nao inicia | erro claro sem duplicidade |

---

## Passo 2 - Escolher limites iniciais

Voce nao precisa acertar o numero perfeito agora. Precisa escolher um numero razoavel e depois ajustar.

### Minha sugestao inicial de coisas para parametrizar

- `DB_POOL_MIN`
- `DB_POOL_MAX`
- `REDIS_TIMEOUT_SECONDS`
- `STRIPE_TIMEOUT_SECONDS`
- `RABBITMQ_PUBLISH_TIMEOUT_SECONDS`
- `SMTP_TIMEOUT_SECONDS`
- `MAX_RETRIES`
- `BACKOFF_BASE_MS`
- `SSE_MAX_CONNECTIONS` se fizer sentido depois

---

## Passo 3 - Definir comportamento por cenario

### Postgres fora
Esperado:

- `/ready` retorna `503`
- endpoints criticos retornam erro controlado
- checkout nao prossegue

### Redis fora
Esperado:

- carrinho pode falhar
- idempotencia pode falhar
- SSE pode falhar
- o log precisa mostrar claramente que a falha veio do Redis

### Stripe lento
Esperado:

- timeout curto
- retry pequeno se for erro transitario
- resposta clara ao cliente
- nada de marcar pagamento como sucesso sem confirmacao

### RabbitMQ fora
Esperado:

- request principal nao trava indefinidamente
- email pode ser marcado como nao enfileirado
- log claro para analise posterior

---

## O que estudar

- timeout vs retry
- latencia de dependencia
- pool de conexao
- status code adequado (`503`, `500`, `504` dependendo do caso)
- degradacao controlada

---

## Entregavel desse bloco

Crie um arquivo ou secao de documentacao com:

- dependencias
- criticidade
- timeout definido
- comportamento esperado quando falhar

Esse material vai te ajudar em teste, logger e CD.

---

## Bloco 4 - Retry e backoff

## Regra principal

**Retry serve para erro transitorio, nao para erro de negocio.**

Use retry quando existe boa chance da proxima tentativa funcionar.

---

## Onde eu usaria primeiro

### 1. Stripe
Usaria retry para:

- timeout de rede
- erro temporario do provider
- falha de conexao externa

Nao usaria retry para:

- payload invalido
- configuracao errada
- erro de validacao da propria aplicacao

### 2. RabbitMQ publish
Usaria retry para:

- publish falhou por oscilacao de conexao

### 3. Worker SMTP
Usaria retry para:

- timeout de envio
- falha transitora do provedor SMTP

---

## Estrategia recomendada para MVP

- no maximo **3 tentativas**
- backoff exponencial pequeno
- jitter
- timeout curto

Exemplo mental:

- tentativa 1: agora
- tentativa 2: 200ms depois
- tentativa 3: 500ms depois
- depois disso: falha definitiva

---

## Como organizar no codigo

Minha sugestao e nao espalhar retry manual em todo lugar.

Crie uma camada simples, por exemplo:

- `core/retry.py`

Ela pode ter:

- um helper generico para operacoes assincronas
- classificacao simples de erros retryable vs non-retryable
- logging centralizado de tentativa

Exemplo conceitual do helper:

- recebe uma funcao
- recebe numero maximo de tentativas
- recebe base de backoff
- recebe nome da operacao para log

---

## Cuidados muito importantes no seu caso

### Checkout + Stripe
Como envolve pagamento, retry sem criterio pode gerar medo de duplicidade.

Por isso:

- use idempotencia
- registre bem o que aconteceu
- se houver duvida de estado, prefira falhar claramente a assumir sucesso

### Worker
No worker, retry e mais natural, mas voce precisa evitar loop infinito silencioso.

---

## O que estudar

- backoff exponencial
- jitter
- tratamento de exception em Python async
- diferenca entre falha transitora e falha permanente
- bibliotecas possiveis no futuro, como `tenacity`, mas voce pode começar manualmente

---

## Entregavel desse bloco

Ao final, voce deve ter:

- uma politica de retry escrita
- helper central de retry
- aplicacao inicial em Stripe, RabbitMQ e SMTP

---

## Bloco 5 - Testes de falha de dependencia

## Objetivo

Garantir que o sistema falha do jeito que voce planejou, e nao de qualquer jeito.

---

## Como pensar nesses testes

Voce nao precisa comecar com caos engineering real. Pode comecar com mocks e monkeypatch.

---

## Casos que eu criaria primeiro

### 1. Stripe timeout no checkout
Simular:

- criacao de sessao Stripe levantando timeout

Esperado:

- checkout falha de forma controlada
- logs deixam claro que foi Stripe
- pagamento nao fica marcado como sucesso
- se houver persistencia de falha, ela fica coerente

### 2. Redis indisponivel ao acessar carrinho ou idempotencia
Simular:

- `ConnectionError` no Redis

Esperado:

- retorno consistente
- log com contexto suficiente
- comportamento alinhado com o que voce definiu na tabela de falha

### 3. RabbitMQ indisponivel ao enfileirar email
Simular:

- falha no publish

Esperado:

- request principal nao fica pendurada
- comportamento definido: ou falha controlada, ou segue sem email
- log claro

### 4. Falha no banco no meio do checkout
Simular:

- erro ao salvar order ou payment dentro da transacao

Esperado:

- rollback coerente
- nada fica parcialmente persistido
- resposta de erro controlada

### 5. Worker SMTP falha ao enviar
Simular:

- timeout ou erro do SMTP

Esperado:

- retry se aplicavel
- log das tentativas
- sem crash silencioso do worker

---

## Estrutura recomendada de testes

### Testes unitarios
Para logica de erro e retry.

Exemplos:

- retry tenta 3 vezes e para
- erro nao retryable nao tenta de novo
- timeout gera evento de log correto

### Testes de integracao
Para garantir comportamento dos services/rotas.

Exemplos:

- endpoint de checkout com provider mockado falhando
- endpoint `/ready` retornando `503` quando Redis falha

---

## O que estudar

- `pytest`
- `monkeypatch`
- `unittest.mock.AsyncMock`
- como simular excecoes em clients externos

---

## Entregavel desse bloco

Uma pequena bateria de testes cobrindo as falhas mais perigosas:

- Stripe timeout
- Redis down
- RabbitMQ down
- DB rollback
- worker SMTP com retry

---

## Bloco 6 - Reorganizacao do logger

## Objetivo

Transformar o logger atual em algo mais consistente, legivel e util para operacao, mesmo sem uma stack completa de observabilidade.

---

## Problemas comuns de logger em MVP

Normalmente o logger cresce assim:

- mensagens soltas
- frases diferentes para o mesmo evento
- muito `logger.error(str(e))`
- pouco contexto de negocio
- dificil filtrar depois

---

## O que eu recomendaria para o seu projeto

### 1. Padronizar formato

Voce pode escolher entre:

- **texto bem formatado**, mais facil de ler localmente
- **JSON estruturado**, melhor para evoluir depois

Minha recomendacao: **JSON** ou pelo menos um formato que imite JSON em campos.

---

### 2. Padronizar campos base

Quase todo log deveria carregar, quando existir:

- `timestamp`
- `level`
- `service`
- `component`
- `event`
- `request_id`
- `user_id`
- `table_id`
- `order_id`
- `payment_id`
- `idempotency_key`
- `error_type`

Voce nao precisa ter tudo em todos os logs, mas precisa de um padrao.

---

### 3. Padronizar nome de evento

Em vez de frases livres, use eventos consistentes.

Exemplos bons:

- `app.startup`
- `app.shutdown`
- `health.ready_failed`
- `checkout.started`
- `checkout.idempotency_hit`
- `checkout.stripe_session_created`
- `checkout.failed`
- `webhook.received`
- `webhook.duplicate_ignored`
- `email.publish_failed`
- `smtp.send_retry`

---

### 4. Diferenciar nivel de log

- `DEBUG`: detalhe tecnico para dev
- `INFO`: fluxo normal importante
- `WARNING`: degradacao ou anomalia recuperavel
- `ERROR`: falha real
- `EXCEPTION`: erro com stacktrace

---

## Como organizar em codigo

Minha recomendacao:

- manter `core/logger/logger.py` como base
- criar helpers pequenos, por exemplo:
  - `log_event(...)`
  - `log_dependency_failure(...)`
  - `log_checkout_event(...)`
  - `log_worker_event(...)`

Isso evita string solta espalhada no projeto inteiro.

---

## Adicao muito valiosa: request_id

Se puder melhorar uma coisa so no logger, eu escolheria isso.

### O que e
Um identificador unico por request HTTP.

### Por que ajuda
Voce consegue juntar todos os logs do mesmo fluxo.

### Como aplicar
- middleware gera o ID se nao vier do cliente
- salva em `request.state`
- adiciona no logger dos handlers/services
- retorna no header da resposta, por exemplo `X-Request-ID`

---

## Estilo recomendado de mensagem

Evite:

- `erro stripe`
- `falhou checkout`
- `problema redis`

Prefira algo como:

- `event=checkout.failed`
- `component=stripe_service`
- `order_id=...`
- `payment_id=...`
- `error_type=timeout`
- `retryable=true`

---

## O que estudar

- logger padrao do Python
- formatter customizado
- `json.dumps` para formatter simples
- middleware no FastAPI
- request correlation

---

## Entregavel desse bloco

Ao final, voce deve ter:

- logger com formato padrao
- nomes de evento consistentes
- `request_id` por request
- logs melhores em checkout, webhook, health e worker

---

## Bloco 7 - CD basico com GitHub Actions

## Objetivo

Automatizar o caminho minimo entre commit e deploy, sem inventar uma pipeline sofisticada demais.

---

## Estrategia recomendada para agora

Eu faria um **CD simples e manualmente confiavel**:

1. push na branch principal
2. GitHub Actions roda lint e testes
3. GitHub Actions builda imagem Docker
4. GitHub Actions publica imagem em registry
5. GitHub Actions conecta por SSH no servidor
6. servidor faz pull da nova imagem
7. sobe a stack
8. roda smoke check no `/ready` ou `/health`

---

## Registry sugerido

Voce pode usar:

- **GHCR** (GitHub Container Registry)
- ou Docker Hub

Minha recomendacao: **GHCR**, porque integra bem com GitHub Actions.

---

## Estrutura do workflow

Voce pode pensar em 3 jobs:

### Job 1 - test
- instala dependencias
- roda `ruff check .`
- roda `pytest -q`

### Job 2 - build-and-push
- faz login no registry
- builda a imagem
- publica com tag

### Job 3 - deploy
- conecta via SSH no servidor
- atualiza stack
- valida healthcheck

---

## No servidor, o deploy pode ser simples

Fluxo basico:

1. `docker login` no registry
2. `docker compose pull`
3. `docker compose up -d`
4. bater no `/ready`

Se quiser deixar mais seguro, use tags versionadas alem de `latest`.

---

## Segredos que voce provavelmente vai precisar no GitHub

- `SSH_HOST`
- `SSH_USER`
- `SSH_PRIVATE_KEY`
- `SSH_PORT` se necessario
- `GHCR_TOKEN` se usar token dedicado

---

## Smoke test pos-deploy

Depois do deploy, rode algo simples:

- chamar `/live`
- chamar `/ready`
- opcionalmente chamar um endpoint leve autenticado ou publico

Se falhar, pelo menos voce detecta rapido.

---

## Rollback no inicio

Voce nao precisa automatizar rollback ja.

Comece com rollback manual simples:

- manter imagem da versao anterior
- voltar compose para tag anterior
- subir novamente

---

## O que estudar

- GitHub Actions
- GHCR
- deploy via SSH em workflow
- `docker compose pull`
- tags de imagem
- secrets no GitHub

---

## Entregavel desse bloco

Ao final, voce deve ter:

- workflow de CI/CD simples
- build e push de imagem automatizados
- deploy basico no servidor
- smoke test depois do deploy

---

## Cronograma sugerido de execucao

Se voce quiser fazer por etapas sem se perder, eu faria assim:

### Etapa 1 - infraestrutura minima da app
- criar `/live`, `/ready`, `/health`
- ajustar startup/shutdown
- adicionar restart automatico

### Etapa 2 - resiliencia
- documentar limites e dependencias
- adicionar timeouts configuraveis
- criar retry helper
- aplicar primeiro em Stripe e SMTP

### Etapa 3 - validacao
- escrever testes de falha de dependencia
- validar cenarios de rollback e erro de startup

### Etapa 4 - operacao
- reorganizar logger
- adicionar request_id
- padronizar eventos

### Etapa 5 - deploy
- build e push de imagem
- deploy via GitHub Actions
- smoke test pos-deploy

---

## Checklist resumida

## Fase 1 - obrigatorio para o proximo passo

- [ ] Criar `/live`
- [ ] Criar `/ready`
- [ ] Criar `/health`
- [ ] Definir checks criticos de readiness
- [ ] Adicionar restart automatico em API e worker
- [ ] Garantir comportamento de startup coerente

## Fase 2 - resiliencia

- [ ] Mapear dependencias e impacto de falha
- [ ] Definir timeouts por integracao
- [ ] Criar helper de retry/backoff
- [ ] Aplicar retry em Stripe
- [ ] Aplicar retry em SMTP
- [ ] Avaliar retry no publish RabbitMQ

## Fase 3 - testes

- [ ] Teste de Stripe timeout
- [ ] Teste de Redis indisponivel
- [ ] Teste de RabbitMQ indisponivel
- [ ] Teste de rollback no banco
- [ ] Teste do worker com falha de SMTP

## Fase 4 - logger

- [ ] Definir formato padrao de log
- [ ] Definir nomes de evento
- [ ] Adicionar `request_id`
- [ ] Melhorar logs de checkout
- [ ] Melhorar logs de webhook
- [ ] Melhorar logs de startup/health/worker

## Fase 5 - CD

- [ ] Criar workflow de build e push de imagem
- [ ] Publicar imagem em registry
- [ ] Configurar deploy via SSH
- [ ] Rodar smoke test pos-deploy
- [ ] Definir rollback manual inicial

---

## Conclusao

O seu projeto ja tem base boa de negocio e de fluxo critico. O que falta agora e principalmente **amadurecimento operacional**.

Se voce seguir este plano, o resultado nao vai ser apenas "subir em prod". Vai ser:

- subir em prod sabendo quando a app esta pronta;
- entender melhor quando algo falha;
- reduzir comportamento imprevisivel;
- diagnosticar problemas com mais facilidade;
- deployar com menos medo.

O ponto mais importante e: **nao tente resolver tudo de uma vez**. Faz por blocos, valida cada um, e so depois passa para o proximo.
