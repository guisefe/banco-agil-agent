# Banking Service Agent

[![CI](https://github.com/guisefe/banco-agil-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/guisefe/banco-agil-agent/actions/workflows/ci.yml)

Assistente de atendimento bancário com LangGraph, interpretação de linguagem via Groq e
políticas de crédito determinísticas em Python. **Banco Ágil** é o banco fictício da demonstração.

A aplicação demonstra como combinar linguagem natural com decisões controladas: o modelo
interpreta solicitações; autenticação, avaliação de crédito e gravação permanecem no software.
É uma simulação local com dados sintéticos, não um serviço bancário em produção.

## Executar

Python 3.12 e uv:

```bash
git clone https://github.com/guisefe/banco-agil-agent.git
cd banco-agil-agent
cp .env.example .env
uv sync --locked --dev
uv run python -m scripts.launch_demo
```

Abra `http://localhost:8501`. Cada execução começa com cópias temporárias das fixtures;
feche e execute novamente para restaurar os cenários. Sem chave, a interpretação é local.
Para experimentar a LLM, configure `GROQ_API_KEY` no `.env` e reinicie a aplicação.
A interface informa se o último turno utilizou a LLM ou o fallback.

## O que está implementado

- Autenticação demonstrativa por CPF e nascimento com limite de tentativas.
- Consulta de limite e score, aumento por política e redução com confirmação.
- Entrevista financeira com recálculo e reanálise do pedido pendente.
- Consulta cambial com provedores alternativos e falha controlada.
- Validação de respostas do modelo, timeout, tentativas limitadas e fallback.
- Confirmação explícita de valores interpretados pela LLM antes do processamento.
- Avaliação versionada com 50 casos em português e relatório de acertos, erros e latência.
- Auditoria pseudonimizada, testes, tipagem estrita e CI.

## Arquitetura e responsabilidades

| Componente | Responsabilidade |
| --- | --- |
| Streamlit | Apresentação e sessão do usuário |
| LangGraph / agentes | Estado da conversa e transições entre quatro especialidades |
| `ProcessCreditIncrease` | Coordenar política, auditoria e persistência do aumento |
| `evaluate_increase` | Avaliar o valor solicitado contra o teto permitido, sem I/O |
| Interpretadores | Módulos separados para regras locais, provedor HTTP e fallback |
| Repositórios | Ler política, acessar clientes, persistir pedidos e consultar câmbio |

A separação do aumento é a primeira etapa da refatoração: redução, entrevista e seus efeitos
persistentes ainda são coordenados pelos agentes. O [ADR](docs/ADR-001-credit-use-case.md)
registra a fronteira e os limites assumidos.

## Demonstração reproduzível

```bash
uv run python -m scripts.demo_credit
```

O roteiro usa cópias temporárias dos cinco clientes sintéticos, não chama provedores e verifica
aprovação, rejeição e entrevista pendente. Não altera `data/` nem lê credenciais do `.env`.
Ele comprova o caminho local; não mede a qualidade da LLM.

Para a demo visual, use Ana (`00000000000`, `20/05/1990`). Os demais cenários e o roteiro completo
estão no [guia de implementação](docs/IMPLEMENTATION_GUIDE.md).

## Verificação

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests evaluation scripts
uv run pytest
```

Os testes de fluxo cobrem decisões, reanálise, falhas de armazenamento/auditoria e concorrência
local. O gate de cobertura é 90% com branches; cobertura não mede acurácia da LLM.

## Limites que importam

- CSV, locks locais e compensação não oferecem transação durável entre múltiplas instâncias.
- O evento de decisão registra a avaliação da política; não comprova a conclusão da gravação.
- CPF + nascimento é autenticação de demonstração. O score é uma fórmula sintética, sem validação
  como modelo de risco real.
- A mensagem corrente enviada à LLM pode conter valores financeiros. A redação de padrões de
  CPF/data não elimina dados pessoais arbitrários: use apenas dados sintéticos nesta demo.
- O conjunto de desenvolvimento passou de 30/50 para 43/50 saídas corretas no modo local.
  Isso não mede generalização. Comparação com LLM real e impacto de negócio ainda pendentes.

## Avaliar a linguagem

```bash
uv run python -m evaluation.run --mode local --output /tmp/banking-local.json
uv run python -m evaluation.run --mode llm --output /tmp/banking-llm.json
uv run python -m evaluation.run --mode hybrid --output /tmp/banking-hybrid.json
```

`llm` mede o provedor sem fallback; `hybrid` mede o comportamento com contingência.
Os dois exigem chave configurada. O comando falha claramente se ela estiver ausente.
O relatório distingue intenção, entidades, campos, recusas, erros e chamadas HTTP.
Tokens ausentes e custo real desconhecido permanecem nulos.

[Resultados e limitações](evaluation/README.md) incluem as sete paráfrases ainda não entendidas
pelo modo local. Nenhum resultado de LLM é simulado como medição real.

Consulte [privacidade e auditoria](docs/PRIVACY_AND_AUDIT.md),
[roteiro do case](docs/CASE_STUDY.md) e [plano de evolução](https://github.com/guisefe/banco-agil-agent/issues/26).
