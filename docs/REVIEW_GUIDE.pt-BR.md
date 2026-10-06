# Guia de apresentação e revisão do Scopegate

O Scopegate propõe uma fronteira explícita para acesso a recursos publicados por organização e projeto. A apresentação deve mostrar como o desenho contém os defeitos atuais, protege o acesso e permite uma migração controlada com a capacidade disponível.

Reserve 18 minutos para a apresentação e 15 minutos para perguntas. O produto local está implementado: combine decisões, contratos, a demonstração em DEMO.pt-BR.md e os resultados registrados em implementation-evidence.json. O piloto real e suas aprovações continuam fora dessa entrega.

## Cinco entregas centrais

| Entrega | Leitura principal | O que o público deve conseguir decidir |
| --- | --- | --- |
| Diagnóstico | [DIAGNOSIS.md](DIAGNOSIS.md) | Quais sintomas estão confirmados, quais hipóteses exigem reprodução e onde conter o impacto |
| Produto | [PRODUCT.md](PRODUCT.md) | O que entra primeiro, como o acesso funciona e quais metas serão medidas |
| Desenho técnico | [ARCHITECTURE.md](ARCHITECTURE.md) e [DATA_MODEL.md](DATA_MODEL.md) | Onde estão as invariantes, as transações, as integrações e os limites |
| Execução e migração | [DELIVERY_PLAN.md](DELIVERY_PLAN.md) e [MIGRATION.md](MIGRATION.md) | Em que ordem entregar, com qual capacidade e sob quais condições liberar ou retornar |
| Alinhamento com Produto | [PRODUCT_ALIGNMENT.pt-BR.md](PRODUCT_ALIGNMENT.pt-BR.md) | Quais decisões comerciais e históricas precisam de responsável antes do piloto |

[UX.md](UX.md) e [API.md](API.md) sustentam os fluxos e os contratos. O [índice das especificações](../specs/README.md) conecta o plano ao trabalho executável.

## Roteiro de 18 minutos

| Tempo | Conteúdo | Ponto a demonstrar |
| --- | --- | --- |
| 0 a 2 minutos | Problema, impacto e decisão de escopo | Conter primeiro e substituir uma fronteira pequena reduz risco operacional |
| 2 a 5 minutos | Diagnóstico e estabilização | Metadados ausentes, indisponibilidade, busca e alterações de recursos precisam de reproduções e efeito persistido observável |
| 5 a 8 minutos | Produto e exemplo concreto | Associação, direito do projeto e concessão individual são decisões distintas |
| 8 a 12 minutos | Arquitetura, modelo e fluxo | Escopo explícito, transação, identidade verificada, publicação e revogação sustentam o comportamento |
| 12 a 15 minutos | Execução e migração | Capacidade declarada, dependências, simulação, comparação de acesso, piloto e retorno |
| 15 a 18 minutos | Qualidade, metas e alinhamento | Condições verificáveis de liberação e decisões atribuídas às pessoas certas |

Abra com a decisão: reconstruir a fronteira de acesso depois de estabilizar os caminhos atuais. Explique o impacto das alternativas em poucas frases. A tecnologia vem depois da regra de acesso que ela precisa proteger.

## Exemplo para explicar acesso

Use duas organizações, Cedar e Harbor, e dois recursos, Atlas e Beacon. Maya tem uma associação ativa de visualizadora em Cedar e uma associação temporária de equipe interna em Harbor. Cedar/Launch tem direito a Atlas e Beacon; Harbor/Review tem direito apenas a Atlas.

Uma concessão Cedar/Launch/Atlas permite somente essa combinação. Maya continua sem acesso a Cedar/Launch/Beacon e Harbor/Review/Atlas. Para Harbor, é necessária uma concessão separada. Se Maya também administrar acesso em Cedar, essa função não amplia seu consumo. Quando a validade de Harbor termina, a próxima admissão é negada mesmo que um cartão permaneça no navegador.

Mostre que traduzir Atlas ou trocar seu título não altera a identidade do recurso. Em seguida, mostre a prévia de uma alteração com uma adição e uma remoção: o usuário confirma o efeito no escopo certo e o servidor valida tudo antes de gravar uma vez.

## Decisões que sustentam o desenho

| Decisão | Resultado esperado | Limite aceito |
| --- | --- | --- |
| Monólito modular com um banco relacional | Invariantes e transações permanecem próximas dos dados | Escala deve ser medida antes de separar serviços |
| Concessões explícitas por associação, projeto e recurso | Autoridade administrativa não vira acesso ao conteúdo | Há mais atribuições, compensadas por clareza e auditoria |
| Equipe interna com associação temporária por organização | Trabalho entre organizações preserva isolamento | Operações precisa manter atribuições e validade |
| Identidade externa por OIDC | Convite vinculado a identidade verificada | Integração real é condição anterior ao piloto |
| Alteração de recursos por diferença atômica | Falha de validação não aplica uma mudança parcial | Conflitos exigem recarregar e revisar a diferença |
| Revogação coordenada com a admissão | Uma nova admissão não passa depois da revogação confirmada | Conteúdo já admitido antes pode concluir |
| Migração por grupo reconciliado | Exceções não se tornam permissões amplas | A expansão espera decisões e comparação de acesso |
| Mutações confirmadas na interface | O usuário vê o estado persistido após a resposta | Existe espera explícita em vez de confirmação antecipada |

## Perguntas e respostas de defesa

**Por que não reescrever tudo?** O risco central está na regra e na fronteira de acesso. Uma substituição completa acrescenta comportamentos e dados que ainda não precisam mudar. A escolha pode ser revista se a estabilização e as medições mostrarem um bloqueio mais amplo.

**Por que o gestor precisa de concessão para consumir?** Administrar acesso e consumir conteúdo são autoridades diferentes. A separação evita que um papel operacional amplie silenciosamente direitos individuais ou comerciais.

**A equipe interna precisa de uma exceção global?** Não. Associações explícitas, temporárias e auditadas em cada organização permitem trabalhar entre clientes sem eliminar a fronteira de isolamento. O piloto deve provar esse caminho em duas organizações.

**Como evitar a diferença entre verificar e usar?** A admissão protegida precisa ser coordenada com a revogação no limite transacional definido pela arquitetura. Uma verificação antiga no navegador não autoriza um uso posterior. A verificação concorrente deve registrar a ordem: admissões novas são negadas depois do commit de revogação; uma admissão anterior pode concluir.

**Como lidar com títulos e traduções ausentes?** Identidade estável e autorização não dependem de texto. A interface usa uma ordem de fallback explícita e mantém os painéis independentes; o recurso continua identificável sem fabricar metadados.

**Quem decide os dados ambíguos?** Produto decide os direitos contratados, a política de aprovação e as exceções históricas. Engenharia registra a diferença e seu efeito, sem preencher a dúvida com concessões. O registro afetado fica fora do grupo até resolução.

**Como provar que a migração não amplia nem perde acesso?** Compare as combinações aprovadas antes e depois em uma simulação versionada. O grupo piloto precisa ter zero ampliação sem aprovação e zero perda de acesso aprovado, com toda exceção resolvida e retorno ensaiado.

**O retorno é restaurar um backup?** Não basta. Depois da migração, a nova fronteira continua como autoridade de acesso. Podemos retornar para uma versão compatível da aplicação sem perder concessões, revogações ou o controle de escrita. Voltar à autorização do legado fica fora desta migração. Se não houver uma versão anterior compatível, cercamos a operação afetada e corrigimos mantendo a nova autoridade. Restaurar um snapshot antigo isoladamente pode apagar mudanças e reativar acesso revogado.

**Como garantir qualidade com três engenheiros ocupados?** Declare a capacidade conjunta, estime por faixa e proteja o caminho crítico. O plano considera 1,5 pessoa em tempo integral e 44 a 72 dias de engenharia para o produto completo de P0 a P2, com faixa inicial de planejamento de 8 a 13 semanas. O primeiro fluxo e o piloto são etapas, não a entrega inteira. A revisão de escopo corta capacidades adicionais antes de cortar prova de autorização, migração ou retorno.

**Como interpretar as métricas?** Zero ampliação e zero perda são condições propostas de liberação do piloto. Incidentes e tempo de entrada ainda precisam de referência medida. A redução de 30% no tempo mediano de processamento é uma meta inicial, separada do tempo de espera por aprovação, a confirmar com Produto.

## Encerramento e perguntas

Termine identificando o que libera o piloto: integração de identidade real, direito do projeto reconciliado, concessões explícitas, invariantes verificadas, zero divergência de acesso no grupo, auditoria e retorno ensaiado. Apresente as decisões pendentes com responsável e efeito na execução.

Nos 15 minutos de perguntas, priorize regras de acesso, migração e operação. Use os documentos para responder sobre mecanismos específicos e registre uma decisão nova quando ela alterar o contrato. Uma resposta deve separar comportamento garantido pelo desenho, condição ainda pendente e resultado já verificado.
