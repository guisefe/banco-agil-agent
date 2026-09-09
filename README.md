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
uv run streamlit run streamlit_app.py
```

Abra `http://localhost:8501`. Sem chave, a interpretação é local e determinística.
Para experimentar a LLM, configure `GROQ_API_KEY` no `.env` e reinicie a aplicação.
A interface informa se o último turno utilizou a LLM ou o fallback.

## O que está implementado

- Autenticação demonstrativa por CPF e nascimento com limite de tentativas.
- Consulta de limite e score, aumento por política e redução com confirmação.
- Entrevista financeira com recálculo e reanálise do pedido pendente.
- Consulta cambial com provedores alternativos e falha controlada.
- Validação de respostas do modelo, timeout, tentativas limitadas e fallback.
- Auditoria pseudonimizada, testes, tipagem estrita e CI.

## Arquitetura e responsabilidades

| Componente | Responsabilidade |
| --- | --- |
| Streamlit | Apresentação e sessão do usuário |
| LangGraph / agentes | Estado da conversa e transições entre quatro especialidades |
| `ProcessCreditIncrease` | Coordenar política, auditoria e persistência do aumento |
| `evaluate_increase` | Avaliar o valor solicitado contra o teto permitido, sem I/O |
| Interpretadores | Classificar intenção e normalizar campos; validar saída da LLM |
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
uv run mypy app tests
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
- Benchmark de linguagem natural, latência de provedor e impacto de negócio ainda não publicado.

Consulte [privacidade e auditoria](docs/PRIVACY_AND_AUDIT.md),
[roteiro do case](docs/CASE_STUDY.md) e [plano de evolução](https://github.com/guisefe/banco-agil-agent/issues/26).
