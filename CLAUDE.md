# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

TraceHunter é uma biblioteca open source de observabilidade local para aplicações de IA (traces e spans gravados em SQLite, com uma interface web de leitura). O código é orientado a objetos de propósito: classes, atributos privados com `_` expostos por propriedades, tipagem completa e docstrings, comentários e mensagens **em inglês** (o projeto é internacional; a documentação é em inglês e português).

## Comandos

```
uv venv && uv pip install -e ".[dev]"         # ambiente local (.venv) com todas as ferramentas
python -m pytest                              # todos os testes
python -m pytest tests/test_tracer.py::TestTracer::test_observe_sync   # um teste
python -m tracehunter [caminho.db]                # UI web em http://127.0.0.1:8000 (padrão: tracehunter.db)
```

Qualidade e segurança (as mesmas checagens rodam no CI, em `.github/workflows/ci.yml`; use o `.venv` do projeto):

```
ruff check . && ruff format --check .         # lint e formatação (linha de 100 colunas)
mypy                                          # strict em tracehunter/; testes têm anotações relaxadas
bandit -r tracehunter -c pyproject.toml           # segurança estática
xenon --max-absolute B --max-modules A --max-average A tracehunter   # complexidade
pip-audit                                     # vulnerabilidades nas dependências
gitleaks detect --config .gitleaks.toml --redact   # segredos
```

Python mínimo 3.10 (mypy 2.x não aceita alvo 3.9). O `pre-commit` (`.pre-commit-config.yaml`) roda os hooks locais com `uv run --no-sync`.

## Arquitetura

Camadas com dependência apontando para o domínio (`tracehunter/`):

- `domain/models.py`: `Span` e `Trace` são encapsulados (atributos privados, propriedades somente leitura, `Status` enum). Datas são normalizadas para UTC. `to_dict`/`from_dict` fazem o ida-e-volta usado pela persistência, e `to_jsonable` garante JSON estrito (chaves viram texto, NaN vira texto, nunca levanta exceção). `Trace` é seguro entre threads e recusa `span_id` duplicado.
- `domain/context.py`: `TraceContext` guarda o trace ativo e a pilha de spans em `ContextVar`s (pilha imutável), então cada thread/task asyncio tem a sua. `activate`/`deactivate` isolam a pilha ao abrir um trace. Não troque por atributos de instância comuns.
- `domain/repository.py`: `TraceRepository` (ABC); `check_limit` rejeita `limit` negativo e limita a 1000. Implementações em `infrastructure/`: memória e SQLite (grava o trace inteiro como JSON, ordena por `start_ts` numérico, ignora linhas corrompidas, arquivo 0600). Os testes de repositório rodam nas duas via fixture parametrizada.
- `application/tracer.py`: `Tracer.trace()`/`span()` são context managers; `observe()` é o decorator (sync e async; geradores são recusados). Regra central: a instrumentação nunca quebra nem esconde erros da aplicação observada (`repr` seguro e limitado, falha ao salvar só vai para o log). Argumentos com nome de segredo são mascarados; `capture_io=False` não grava nada.
- `api/app.py` + `api/static/`: FastAPI somente leitura (limit 1 a 200, sem /docs). Só responde aos `Host` permitidos (anti DNS rebinding) e envia CSP estrita: não use `<style>`, `<script>` nem `onclick` inline, tudo vai em arquivos estáticos. A interface tem visual propositalmente simples, "site de 2010"; não modernize nem troque por framework.
- `domain/collector.py` + `infrastructure/claude_code_collector.py` + `application/collector_sync.py`: um `Collector` por CLI lê os arquivos de sessão locais e devolve `Trace`s. O do Claude Code cria um trace por prompt humano (`origin.kind == "human"`), um span por resposta do modelo e spans filhos por ferramenta; grava só resumos curtos mascarados por `domain/redaction.py` e nunca o "thinking". `CollectorSync` roda em thread e só regrava o que mudou. Ativar com `python -m tracehunter <db> --claude-code`. Novos coletores seguem o mesmo contrato.
- `tui/`: interface de terminal (Textual, extra `tui`), aberta com `tracehunter tui <db>`. `tui/view.py` é lógica pura sem Textual (testável); `tui/app.py` é o app. Somente leitura.
- `api/static/i18n.js` + `app.js`: a interface tem 18 idiomas, detecta o do navegador e lembra a escolha; `tests/test_collectors.py::TestI18n` exige as mesmas chaves em todos. Ao criar texto novo na UI, adicione a chave nos 18 idiomas.
- `catalog.py`: catálogo de CLIs de IA e onde cada uma guarda sessões, com nível de `Confidence`. O Claude Code já tem coletor; os demais ainda não.

## Cuidados

- A interface web não tem login. Nunca faça o servidor escutar fora de loopback por padrão, nem publique a porta do Docker em 0.0.0.0 (o compose usa 127.0.0.1).
- No catálogo, só `VERIFIED_LOCAL` foi visto em disco; `OFFICIAL` vem da documentação e `THIRD_PARTY` de blogs. Confirme nos arquivos reais antes de escrever um coletor, e não copie credenciais das sessões de outras CLIs.
- Actions do CI ficam fixadas por SHA (tag no comentário). As tags do Trivy têm prefixo `v`. A imagem Docker remove pip, setuptools, wheel e ensurepip no fim (o Trivy acusava o setuptools embutido).
- O Mutmut não roda no Windows (só Linux/WSL); no CI ele é semanal e não bloqueia merge.
- Fora do escopo atual: ingestão HTTP, OpenTelemetry, avaliação de RAG, campos de LLM de primeira classe no span (tipo, custo): o coletor do Claude Code já grava modelo, tokens e stop_reason em `metadata`, e a tela mostra os tokens.
