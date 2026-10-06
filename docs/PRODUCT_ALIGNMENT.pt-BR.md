# Alinhamento de produto para o Scopegate

O Scopegate organiza acesso por organização, projeto e recurso publicado. A entrega local implementa o fluxo completo e os ensaios com dados sintéticos; uma migração real exige decisões comerciais, inventário privado e integrações próprias.

O texto abaixo é uma mensagem para revisão com Produto e Operações. Não foi enviado. As estimativas descrevem premissas de planejamento; não representam prazo imposto nem tempo medido desta implementação.

## Mensagem para alinhamento

Pessoal, proponho estabilizar os fluxos de acesso e substituir sua fronteira por etapas. Vamos reproduzir metadados ausentes, recursos indisponíveis, busca e alterações de concessões, registrando o estado persistido antes e depois. Uma resposta 400, isoladamente, não prova perda de dados.

Assumo três decisões técnicas: um monólito modular com PostgreSQL como autoridade; identidade, associação, direito do projeto e concessão individual separados; e comandos atômicos, auditáveis e reversíveis, com controle de concorrência. O papel de gestor permite administrar acesso, mas não consumir conteúdo sem concessão explícita. Publicação e tradução não concedem permissão.

A entrega local demonstra convite verificado, aceitação, uso, revogação, auditoria e isolamento de uma pessoa interna em duas organizações. Também ensaia migração, comparação de acesso e retorno de versão com dados sintéticos. Esses resultados não autorizam uma mudança em clientes reais.

Preciso de Produto para definir a fonte dos recursos contratados, os critérios de aprovação automática e o responsável por cada exceção histórica. Operações confirma identidade, validade das associações internas, proprietários dos consumidores e recuperação. Registros ambíguos continuam bloqueados; não serão resolvidos concedendo acesso amplo.

Planejamos por capacidade disponível, sem comprimir verificações para cumprir uma data. A preparação sintética é separada da observação de um piloto real, cujo esforço e janela serão definidos após a descoberta privada. Antes de liberar um grupo real, exigirei comparação aprovada, integrações verificadas e recuperação ensaiada. Qualquer ampliação indevida, perda de acesso aprovado ou falha de autorização interrompe a expansão. Produto decide as regras comerciais; a liderança técnica responde pelas invariantes e evidências; Operações executa a transição controlada.

## Decisões técnicas que assumo

| Decisão | Razão e consequência | Evidência esperada |
| --- | --- | --- |
| Monólito modular e uma autoridade de acesso | Uma equipe pequena mantém transações e ordem de bloqueios explícitas, sem coordenação distribuída desnecessária | [Arquitetura](ARCHITECTURE.md), implantação e fronteiras de módulos |
| Associações e concessões normalizadas por organização | Uma alteração preserva as demais organizações; títulos, papéis e publicação não viram permissões | [Modelo](DATA_MODEL.md), restrições compostas e testes negativos |
| Comandos atômicos com revisão, recibo e auditoria | Falha muda nada; conflito preserva intenção; retorno de versão preserva revogações | [Correção concorrente](DISTRIBUTED_CORRECTNESS.md), [migração](MIGRATION.md) e ensaios de recuperação |

## Decisões que escalo

| Decisão | Responsável | Regra até a resolução |
| --- | --- | --- |
| Fonte dos recursos contratados | Produto com responsável pelo catálogo | Nenhuma concessão inferida de nomes, domínios ou dados ambíguos |
| Aprovação automática | Produto | Desativada enquanto critérios não forem explícitos |
| Exceções históricas de acesso | Produto com Operações | Registro exige responsável, justificativa e comparação; grupo afetado permanece bloqueado |
| Atribuição e validade da equipe interna | Operações | Associação explícita por organização e expiração obrigatória |
| Identidade e entrega reais | Responsáveis pelas integrações | Adaptadores locais não certificam provedores reais |
| Liberação e retorno do grupo real | Liderança técnica com Operações | Paridade, responsáveis pelos escritores/consumidores e recuperação verificadas |

## Premissas e indicadores

O [plano de entrega](DELIVERY_PLAN.md) assume três engenheiros com disponibilidade conjunta de 1,5 pessoa em tempo integral. As faixas históricas são 1–2 semanas para estabilização, 3–5 para o primeiro fluxo e 1–2 para **preparação do ensaio sintético**, dentro de 44–72 dias de engenharia e uma faixa total de 8–13 semanas. O primeiro piloto real T13 e novos grupos são trabalho adicional, a estimar após a descoberta privada; sua observação exige uma janela aprovada e uso representativo.

As metas propostas para um piloto são zero ampliação não aprovada, zero perda de acesso aprovado e nenhuma falha crítica de autorização. A redução de 30% no tempo mediano de processamento depende de medir uma referência e separar espera por aprovação do tempo do sistema. Esses indicadores não são resultados já alcançados nem compromissos comerciais.

A [proposta](PROPOSTA.pt-BR.md) organiza as cinco entregas. [Requisitos](REQUIREMENTS.md) e [especificações](../specs/README.md) ligam decisões a comportamento e evidências. A entrega local e as etapas reais têm limites explícitos em [LOCAL_PRODUCT.md](LOCAL_PRODUCT.md).
