# Banco Ágil - Agente Bancário Inteligente

[![CI](https://github.com/guisefe/banco-agil-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/guisefe/banco-agil-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![Status](https://img.shields.io/badge/status-MVP%20completo-brightgreen)

MVP de atendimento bancário conversacional com quatro agentes especializados, interface
Streamlit e orquestração por LangGraph. A solução cobre o fluxo completo do desafio técnico
da Tech For Humans: autenticação, crédito, entrevista financeira, reanálise e câmbio.

> **Entrega completa:** 242 testes, 100% de linhas e branches cobertos, MyPy strict, Ruff,
> CI, auditoria pseudonimizada e container não-root com health check.

## Visão Geral do Projeto

Para o cliente, o Banco Ágil se comporta como um único assistente. Internamente, o
atendimento é dividido entre quatro agentes com escopos bem definidos:

| Agente | Responsabilidade |
| --- | --- |
| Triagem | Recepcionar, autenticar por CPF e nascimento e identificar a solicitação. |
| Crédito | Consultar limite e processar pedidos de aumento de crédito. |
| Entrevista de Crédito | Coletar informações financeiras e recalcular o score. |
| Câmbio | Consultar cotações atuais por meio de uma API externa. |

O usuário pode solicitar o encerramento a qualquer momento. As transições entre agentes
são implícitas, preservando a experiência de uma conversa única.

### Fluxos demonstráveis

| Fluxo | Resultado |
| --- | --- |
| Autenticação | Valida CPF e nascimento no `clientes.csv`, com até três tentativas. |
| Consulta de crédito | Exibe o limite atual somente após autenticação. |
| Aumento de limite | Registra o pedido e aplica a política do `score_limite.csv`. |
| Entrevista financeira | Recalcula o score, atualiza o cliente e reanalisa o pedido original. |
| Câmbio | Consulta a AwesomeAPI e retorna a cotação atual pela mesma interface. |
| Encerramento | Finaliza qualquer etapa e remove dados pessoais e financeiros do estado. |

## Arquitetura do Sistema

```mermaid
flowchart TD
    UI[Interface Streamlit] --> ORCH[Orquestrador da conversa]
    ORCH --> END{Usuário pediu encerramento?}
    END -->|Sim| FIN[Ferramenta de encerramento]
    END -->|Não| TRI[Agente de Triagem]
    TRI --> AUTH[(clientes.csv)]
    TRI -->|Crédito| CRED[Agente de Crédito]
    TRI -->|Câmbio| FX[Agente de Câmbio]
    CRED --> SCORE[(score_limite.csv)]
    CRED --> REQUESTS[(solicitacoes_aumento_limite.csv)]
    CRED -->|Score insuficiente e aceite| INTERVIEW[Agente de Entrevista]
    INTERVIEW -->|Atualiza score| AUTH
    INTERVIEW -->|Nova análise| CRED
    FX --> API[API externa de câmbio]
    ORCH -. eventos mínimos .-> AUDIT[(Trilha de auditoria)]
```

### Componentes

- **Interface:** Streamlit oferece o chat usado para simular o atendimento disponível.
- **Orquestração:** um grafo de estados controla turnos, autenticação, handoffs e
  encerramento.
- **Agentes:** cada agente executa apenas ações pertencentes ao seu escopo.
- **Ferramentas:** autenticação, leitura e escrita de CSV, cálculo de score, consulta de
  câmbio e encerramento são funções explícitas e testáveis.
- **Auditoria:** eventos de negócio são registrados separadamente das mensagens e dos
  dados financeiros.

### Fluxo de autenticação

1. A Triagem solicita CPF e data de nascimento separadamente.
2. Os dados são comparados com `clientes.csv`.
3. Após uma autenticação válida, a intenção do cliente é identificada.
4. Em caso de falha, são permitidas mais duas tentativas.
5. A terceira falha consecutiva encerra o atendimento de maneira amigável.

Nenhum agente de Crédito, Entrevista ou Câmbio será acessado antes da autenticação.

### Manipulação dos dados

| Recurso | Operação | Finalidade |
| --- | --- | --- |
| `clientes.csv` | Leitura e atualização controlada | Autenticação, limite e score do cliente. |
| `score_limite.csv` | Somente leitura | Determinar o limite permitido para cada faixa de score. |
| `solicitacoes_aumento_limite.csv` | Escrita | Registrar solicitações com o esquema exigido pelo desafio. |
| API de câmbio | Consulta | Obter cotação atual da moeda solicitada. |
| Auditoria JSONL | Append-only no MVP | Registrar eventos técnicos e de negócio sem dados brutos. |

CPF e data de nascimento são utilizados no fluxo funcional exigido pelo desafio, mas não
são gravados na auditoria. Quando for necessário correlacionar eventos, o titular será
representado por uma referência pseudonimizada com HMAC-SHA-256. Veja as decisões e
limitações em [Privacidade e Auditoria](docs/PRIVACY_AND_AUDIT.md).

## Funcionalidades Implementadas

| Capacidade | Implementação |
| --- | --- |
| Identidade | CPF + nascimento, três tentativas, dados fictícios e falhas controladas. |
| Crédito | Consulta, aumento, decisão determinística, persistência e rollback. |
| Entrevista | Cinco perguntas, score versionado entre 0–1000 e compensação em falha. |
| Câmbio | USD, EUR, ARS, GBP e JPY; timeout, retry de transporte e payload validado. |
| Orquestração | LangGraph, estado tipado, escopos isolados e handoffs invisíveis. |
| Interface | Streamlit cobrindo os quatro agentes e mascarando entradas sensíveis. |
| Auditoria | JSONL mínimo, motivos controlados e referência HMAC-SHA-256. |
| Qualidade | Pytest, cobertura integral, Ruff, MyPy strict, CI e Dependabot. |
| Entrega | Execução local ou Docker não-root com health check verificado na CI. |

## Estrutura do Código

```text
app/
├── agents/          # Comportamento e escopo de cada agente
├── audit/           # Eventos, pseudonimização e persistência de auditoria
├── models/          # Estado e tipos compartilhados da conversa
├── repositories/    # Clientes, política de score e solicitações em CSV
├── tools/           # Identidade, valores monetários e encerramento
├── graph/           # Orquestração e roteamento entre agentes disponíveis
└── ui/              # Interface Streamlit e proteção de dados exibidos
tests/               # Testes unitários e de integração
docs/                # Decisões de arquitetura, privacidade e operação
```

## Desafios Enfrentados e Como Foram Resolvidos

### Rastreabilidade sem expor dados pessoais

Registrar conversas completas facilitaria a depuração, mas aumentaria a exposição de CPF,
nascimento e informações financeiras. A solução foi auditar eventos mínimos, motivos
controlados e versões das regras. A referência do titular é pseudonimizada e a chave não é
armazenada no Git.

### Decisões de crédito explicáveis

Uma LLM não participa da autenticação, aprovação de crédito ou cálculo de score. Essas
decisões são determinísticas e registram `reason_code` e `policy_version`, permitindo
reprodução, teste e revisão.

### Confiabilidade desde o início

O limite mínimo de cobertura inicialmente falhava porque ainda não havia testes. Foram
adicionados testes unitários para estado e auditoria, além de um pipeline que impede a
integração de código sem formatação, lint, tipagem e testes aprovados.

### Consistência entre pedido e limite aprovado

Os CSVs exigidos não oferecem transações entre arquivos. No MVP de processo único, a
decisão completa é serializada para sempre validar o pedido contra o limite mais recente.
A atualização do cliente usa substituição atômica e o caso de falha ao registrar uma
aprovação restaura o limite anterior. Em produção, os dois registros pertenceriam à mesma
transação em um banco de dados e teriam chave de idempotência.

### Recálculo reproduzível sem decisão da LLM

A fórmula sugerida pelo desafio foi implementada com `Decimal`, pesos explícitos e
arredondamento `ROUND_HALF_UP`. O resultado é limitado entre 0 e 1000 antes de ser salvo.
Se a auditoria crítica do novo score falhar, o repositório restaura o score anterior; uma
falha posterior apenas no evento de handoff não desfaz uma atualização já confirmada.

### Integração externa resiliente

O agente de Câmbio usa a AwesomeAPI por meio de um adaptador isolado. O adaptador aceita
somente USD, EUR, ARS, GBP e JPY, aplica timeout de cinco segundos e faz uma única repetição
para falhas de transporte. Respostas HTTP não exitosas, payloads inválidos e indisponibilidade
retornam uma mensagem controlada, sem expor detalhes técnicos ou o conteúdo da resposta.

### Limite claro entre MVP e produção

CSV e JSONL são proporcionais ao desafio e tornam a demonstração reproduzível. Eles não
simulam garantias inexistentes: uma implantação bancária real exigiria banco transacional,
auditoria centralizada e imutável, gestão de segredos, autorização, rate limiting,
observabilidade, retenção formal e procedimentos operacionais.

## Escolhas Técnicas e Justificativas

| Escolha | Justificativa |
| --- | --- |
| Python 3.12 | Tipagem moderna, ecossistema de IA e compatibilidade com o desafio. |
| `uv` | Instalação rápida e ambiente reproduzível por meio de `uv.lock`. |
| `httpx` | Cliente HTTP com timeout explícito e transporte simulável nos testes. |
| Estado tipado | Torna transições explícitas e reduz erros entre agentes. |
| Regras determinísticas | Garante autenticação, score e crédito reproduzíveis e testáveis. |
| Grafo de estados | Representa os handoffs e impede que agentes atuem fora do escopo. |
| Streamlit | Permite construir rapidamente a UI simples solicitada no desafio. |
| CSV por repositórios/ferramentas | Cumpre a especificação sem acoplar os agentes ao armazenamento. |
| Auditoria estruturada | Oferece rastreabilidade sem armazenar o conteúdo completo da conversa. |
| Pytest, Ruff e MyPy | Automatizam testes, padronização e verificação estática. |
| GitHub Actions | Executa os mesmos controles em toda PR e na branch principal. |
| Docker não-root | Empacota a demonstração sem executar a aplicação como administrador. |

O MVP não depende de uma LLM. A interpretação necessária é deliberadamente determinística,
adequada ao vocabulário fechado do desafio e executável sem credenciais pagas. Uma LLM
poderia ser adicionada futuramente apenas para linguagem ambígua ou formulação de respostas,
sempre com fallback determinístico e sem participar das regras críticas.

## Tutorial de Execução e Testes

### Pré-requisitos

- Python 3.12 ou superior;
- [uv](https://docs.astral.sh/uv/);
- Git.

### Preparação do ambiente

```bash
git clone https://github.com/guisefe/banco-agil-agent.git
cd banco-agil-agent
uv sync --locked --dev
```

Para manter uma referência de auditoria estável entre reinicializações, configure uma
chave secreta de pelo menos 32 bytes. Sem ela, a demonstração gera uma chave efêmera segura
por processo:

```bash
export AUDIT_PSEUDONYMIZATION_KEY="substitua-por-um-segredo-com-32-bytes-ou-mais"
```

Opcionalmente, configure uma chave da AwesomeAPI fora do Git. A demonstração funciona sem
ela quando o provedor permite a consulta pública:

```bash
export EXCHANGE_API_KEY="sua-chave-opcional"
```

### Testes e qualidade

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pytest
```

O `pytest` mede a cobertura do pacote `app` e falha quando o total fica abaixo de 95%.
Esses mesmos comandos são executados automaticamente pelo GitHub Actions.

### Executar com Docker

O container executa o mesmo aplicativo Streamlit com usuário sem privilégios e possui
health check no endpoint nativo do Streamlit:

```bash
docker build -t banco-agil-agent .
docker run --rm -p 8501:8501 \
  -e AUDIT_PSEUDONYMIZATION_KEY="substitua-por-um-segredo-com-32-bytes-ou-mais" \
  banco-agil-agent
```

Acesse `http://localhost:8501`. A CI constrói a imagem e aguarda o container ficar
saudável antes de permitir a integração.

### Executar a aplicação

```bash
uv run streamlit run streamlit_app.py
```

Use um dos clientes fictícios para testar a Triagem:

| CPF | Nascimento |
| --- | --- |
| `000.000.000-00` | `20/05/1990` |
| `111.111.111-11` | `03/11/1985` |

Depois da autenticação, escolha crédito e consulte o limite ou solicite um aumento. Para o
cliente com score 650, `R$ 5.000,00` é aprovado e um valor superior oferece a entrevista.
Responda às cinco perguntas; ao final, o score é atualizado e o mesmo limite é reanalisado
automaticamente. Para câmbio, peça a cotação de dólar, euro, peso argentino, libra ou iene;
após a resposta, o atendimento retorna naturalmente ao menu. Nenhuma chave real deve ser
adicionada ao repositório.

## Segurança e Privacidade

Este é um projeto educacional com dados fictícios. As medidas implementadas são alinhadas
a princípios de segurança e proteção de dados, mas não constituem certificação de
conformidade legal para uso bancário em produção.

Consulte [docs/PRIVACY_AND_AUDIT.md](docs/PRIVACY_AND_AUDIT.md) para conhecer o contrato de
minimização, as limitações do JSONL, os requisitos de produção e as referências oficiais.
