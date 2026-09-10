# Avaliação de linguagem

Carregar exemplos, executar o interpretador, medir e salvar. O fluxo é propositalmente curto,
com funções e contratos pequenos, seguindo a organização direta do beAnalytic case.

## O que foi medido

O corpus `pt-br-v1` contém 30 solicitações e 20 respostas de campos, todas sintéticas.
A saída completa inclui intenção, moeda e valor; acertar apenas a intenção não basta.
Casos ambíguos têm como resposta esperada `unknown` ou `null`.

| Medida | Antes | Depois |
| --- | --- | --- |
| Saídas completas corretas | 30/50 | 43/50 |
| Rótulo de intenção correto | 21/30 | 27/30 |
| Campos normalizados corretamente | 12/20 | 18/20 |
| Recusas esperadas identificadas | 5/11 | 11/11 |
| Recusas emitidas que eram esperadas | 5/8 | 11/14 |
| Falhas de execução | 0 | 0 |

Relatórios completos: [antes](results/local-before.json) e [depois](results/local-after.json).
As sete falhas restantes são paráfrases. Algumas são recusadas; outras têm intenção correta,
mas a entidade ou o valor não foi extraído. A confirmação protege valores interpretados pela LLM;
a política de crédito continua independente do interpretador.

## Limites da comparação

Este é um conjunto de desenvolvimento escrito durante a implementação, usado para orientar
correções. Os 86% não são uma estimativa de acurácia em produção. Não há amostragem de clientes,
separação de treino/teste ou promessa de resistência geral a prompt injection. As regras locais
preferem pedir esclarecimento e podem recusar pedidos válidos.

A versão anterior foi reexecutada com o mesmo corpus e avaliador num checkout isolado. O tree
`5e3c6bf137b9cbda9b31e340195be31690a38872` identifica a base do PR #27 antes desta etapa
(commit remoto equivalente `0a0ddf2a77612002dfbd6fc2e9d808f3664c3e7d`). O commit local do relatório
pode ter outro SHA, pois o envio foi feito pelo conector GitHub. `source_sha256` identifica os
arquivos Python usados; `dataset_sha256` identifica os exemplos. `working_tree_dirty` é explícito
quando o avaliador ou o relatório ainda não estava commitado.

Latência usa relógio monotônico por exemplo, execução sequencial e percentil por nearest rank.
É uma amostra curta num ambiente compartilhado; não representa capacidade de produção.
`unknown` mede recusa do interpretador, não a segurança completa do workflow.
Sucesso ponta a ponta é verificado separadamente por testes e pela demo de crédito.

## Reproduzir

```bash
uv run python -m evaluation.run --mode local --output /tmp/local.json
uv run python -m evaluation.run --mode llm --output /tmp/llm.json
uv run python -m evaluation.run --mode hybrid --output /tmp/hybrid.json
```

Configure a chave no `.env` para os dois últimos comandos. `llm` não usa fallback; `hybrid`
registra quando o fallback respondeu. Erros permanecem no denominador e no relatório.
Falhas de execução retornam código 1; ausência de credenciais retorna código 2 sem criar
resultado. Divergências de resposta são diagnósticos e não fazem a CI falhar automaticamente.
A CI roda apenas o modo local, sem segredos ou cobrança.

**LLM real ainda não medida:** nenhuma credencial estava disponível neste ambiente. O modo
local tem custo de API zero. Para o provedor, contamos requisições e tokens quando informados;
se faltar uso em qualquer tentativa, o total é desconhecido. Custo faturado permanece `null`:
não inferimos preço nem tratamos ausência de informação como zero.

Antes de divulgar ganho de IA, execute ambos os modos sobre o mesmo `dataset_sha256`, examine
falhas individuais e acrescente um conjunto novo, revisado por outra pessoa e não usado no ajuste.
