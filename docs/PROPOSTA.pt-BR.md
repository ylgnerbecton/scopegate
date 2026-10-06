# Scopegate proposta de produto e arquitetura

A recomendação é conter os defeitos atuais, substituir a gestão de acessos por relações explícitas e migrar uma organização de cada vez. O resultado esperado é conseguir liberar, explicar e revogar acesso sem depender de listas divergentes ou arriscar permissões de outras contas.

O produto público se chama **Scopegate**. A base técnica usa Python e PostgreSQL pela continuidade do ecossistema; FastAPI formaliza os contratos HTTP, e React com TypeScript atende ao console operacional. A arquitetura concentra políticas e transações em um monólito modular. O produto local está construído e reúne aplicação, contratos, ensaios sintéticos, interface e documentação. A conclusão exige evidências dos gates vinculadas ao commit; integrações reais e piloto permanecem fora do escopo fechado.

## Diagnóstico e perguntas

O problema estrutural é a ausência de um modelo único de identidade, vínculo e permissão. Identificadores de recursos aparecem em listas de texto, usuários têm uma única organização opcional, projeto é um nome repetido e aprovação existe fora de um fluxo de admissão completo. Isso permite que regras e dados se contradigam.

Alguns defeitos são demonstráveis: leitura sem tratar organização inexistente, lista nula que quebra o agregado, busca que ignora o termo e edição de acesso com exclusão e inclusão confirmadas separadamente. Essa última operação também perde o escopo ao substituir todas as associações do usuário. Configurações de relatório guardam outras referências que precisam entrar na migração.

Outras conclusões precisam de evidência adicional. O erro de criação por aprovação existente ocorre antes da inserção; ele não demonstra corrupção da organização. O material inspecionado também não mostra a autorização no momento do consumo. Não vou inventar qual lista hoje determina acesso efetivo.

Antes do piloto, as perguntas prioritárias são: Operações confirma qual é o acesso pretendido quando as listas divergem; Produto e o responsável pelos contratos definem o que cada projeto pode disponibilizar; o responsável pela identidade confirma o provedor e a vinculação de contas; os donos dos consumidores mostram onde relatórios e outras ações autorizam recursos. O [diagnóstico completo](DIAGNOSIS.md) registra as hipóteses, os sinais e os responsáveis.

## Produto e primeira entrega

A primeira fatia útil é um ciclo completo: um administrador seleciona organização, projeto e recursos permitidos; convida um usuário; o destinatário autentica e aceita; o sistema cria o vínculo e as concessões em uma transação; o usuário usa somente os recursos concedidos; a revogação passa a valer no próximo ponto de decisão; a operação explica tudo pela auditoria.

Dois usuários da mesma organização podem ter recursos diferentes. Um usuário interno pode atender várias contas por vínculos explícitos e com prazo. A demonstração deve provar que editar uma conta preserva a outra.

Mediremos o tempo entre convite e primeiro uso, falhas de liberação, recorrência de incidentes e trabalho manual da operação. A linha de base e as metas de melhoria precisam ser medidas. Para segurança, o gate é imediato: nenhuma concessão nova ou perda de acesso sem decisão revisada, nenhuma leitura entre organizações e nenhuma revogação restaurada por rollback.

Vou corrigir os defeitos que interrompem a operação enquanto construímos essa fatia. Uma reescrita completa aumenta risco e demora a devolver valor. Se as medições demonstrarem que a contenção resolve a necessidade atual, podemos adiar a expansão; correção dos vínculos inseguros e prova de isolamento continuam obrigatórias. Microserviços, mecanismo externo de políticas e infraestrutura de busca ficam fora da primeira entrega. O [mini-PRD](PRODUCT.md) detalha a decisão e os cortes.

## Desenho técnico

As relações centrais são:

```text
Identidade -> vínculo com organização -> concessão de recurso em projeto
Organização -> projetos -> recursos contratados e habilitados
Recurso -> identidade estável -> metadados por idioma
```

O acesso exige simultaneamente identidade autenticada, vínculo ativo e vigente, projeto ativo, recurso habilitado para o projeto, publicação válida e concessão individual. Papel de administrador permite administrar acesso; não libera consumo automaticamente. Publicar conteúdo também não cria concessões.

Chaves estrangeiras compostas impedem que um vínculo da organização A receba uma concessão do projeto B. Regras dinâmicas, como expiração e autoridade do operador, são verificadas no serviço. A identidade usa emissor e subject do provedor; e-mail serve para contato e confirmação do convite, sem fundir contas por semelhança.

Alterações aplicam apenas o delta do vínculo e projeto selecionados. Versão esperada detecta edição concorrente; chave de idempotência protege retries; concessão, versão, auditoria e recibo são confirmados juntos. Uso crítico e revogação têm uma ordem de locks definida: uma operação já admitida antes da revogação pode concluir, mas uma decisão posterior à confirmação da revogação deve negar. Os [contratos](API.md), o [modelo](DATA_MODEL.md) e a [arquitetura](ARCHITECTURE.md) explicam as garantias e seus limites.

## Execução e migração

Primeiro reproduzimos e contemos os defeitos. Depois fechamos modelo e contratos, implementamos identidade e catálogo, política e concessões, convites, consumidor protegido e interface. Ferramentas de reconciliação avançam em paralelo após o modelo estar definido. A validação integrada fecha isolamento, concorrência, acessibilidade e recuperação.

O pacote público executa com dados sintéticos, integração local de identidade, worker e interface; o roteiro de demonstração está em DEMO.pt-BR.md. A migração real depende de inventário dos consumidores, identidades verificadas, acesso pretendido aprovado e comparação de decisões. Esses insumos bloqueiam o corte de produção, não a construção do produto.

Na migração, preservamos os dados existentes, acrescentamos o modelo novo, fazemos backfill rastreável e repetível e colocamos conflitos em revisão. Não escolhemos união ou interseção de listas divergentes como atalho. Comparamos permissões e negativas em shadow, cercamos todos os escritores, drenamos alterações e só então mudamos uma organização. A autoridade permanece no modelo novo depois do corte; rollback troca uma versão compatível da aplicação e preserva revogações. A [migração](MIGRATION.md) define os gates e a resposta a falhas.

A estimativa de planejamento original, preservada para discutir alocação e revisões, para o produto local completo, incluindo ensaio sintético de migração e recuperação, é de 44 a 72 pessoa-dias, com uma faixa de planejamento de 8 a 13 semanas sob disponibilidade de 1,5 pessoa em tempo integral equivalente. É uma hipótese a revisar após a primeira fatia e as integrações, não uma data prometida. O primeiro piloto real e os grupos seguintes são trabalho adicional, dimensionado pelo inventário e pela qualidade dos dados. O [plano de entrega](DELIVERY_PLAN.md) mostra responsáveis, paralelismo e critérios de conclusão.

## Alinhamento com Produto

Assumo o modelo explícito, as transações e as provas de isolamento como decisões técnicas. Escalo a regra de contratação por projeto, a política de concessões ambíguas e a seleção do primeiro grupo real, porque mudam acesso e compromisso com clientes. O trade-off solicitado é entregar um fluxo completo e seguro antes de ampliar funcionalidades.

A [nota pronta para Produto](PRODUCT_ALIGNMENT.pt-BR.md) comunica essa ordem. O [roteiro de revisão](REVIEW_GUIDE.pt-BR.md) organiza a apresentação em aproximadamente 18 minutos e prepara a defesa das escolhas. As [especificações executáveis](../specs/README.md) ligam requisitos a tarefas e evidências, para a implementação avançar sem decisões implícitas.

## Decisões que fecham a implementação

A primeira versão exige um gestor cliente permanente por organização; gestores internos com prazo não atendem essa responsabilidade. Desabilitar um recurso revoga as concessões e os convites pendentes afetados em uma transação limitada. Reabilitar exige novas concessões. Arquivar uma identidade de catálogo é definitivo. São regras explícitas a validar com Produto e Operações antes de um piloto real.

O [desenho de domínio](DOMAIN_DESIGN.md) traz responsabilidades, guardas, portas e os arquivos previstos por tarefa. O [protocolo transacional](DISTRIBUTED_CORRECTNESS.md) define snapshots, locks, concorrência e resultados incertos. [Capacidade](CAPACITY_PLAN.md), [confiabilidade](RELIABILITY_DESIGN.md) e [entrega](DELIVERY_SYSTEM.md) detalham limites, falhas, observabilidade, segurança da publicação e recuperação.

Os quinze grupos de padrões estão mapeados em [230 decisões de engenharia](ENGINEERING_STANDARDS.md), cada uma com aplicação, responsável, gate, evidência e condição de revisão. O [contrato de conclusão](COMPLETION_CONTRACT.md) impede tratar documentação como software concluído. O [guia de estudo](LEARNING_GUIDE.pt-BR.md) ajuda a explicar e exercitar as decisões, os riscos e as alternativas.
