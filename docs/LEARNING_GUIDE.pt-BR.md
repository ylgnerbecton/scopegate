# Guia de estudo e defesa técnica do Scopegate

Este guia ajuda a explicar o desenho a partir de suas causas, garantias e limites. O objetivo é conseguir prever o comportamento diante de uma corrida, de uma falha e de uma mudança de escopo, além de reconhecer quando a solução precisaria mudar. A aplicação local está implementada. Use os testes e artefatos registrados para distinguir garantias já verificadas de exercícios propostos e integrações externas.

Leia [produto](PRODUCT.md), [modelo](DATA_MODEL.md), [domínio](DOMAIN_DESIGN.md) e [correção distribuída](DISTRIBUTED_CORRECTNESS.md) antes de tentar defender mecanismos específicos. O [registro de padrões](../specs/standards.json) liga cada princípio a uma decisão, responsável e evidência.

## Separar os fatos que autorizam acesso

Identidade responde quem é a pessoa. Associação responde em qual organização ela participa. O direito do projeto responde quais recursos aquela organização pode disponibilizar no projeto. A concessão individual responde quais desses recursos a pessoa pode consumir. Publicação e tradução pertencem ao catálogo.

Considere Maya, Cedar/Launch, Harbor/Review e o recurso Atlas. Maya participa das duas organizações; a associação em Harbor é temporária. Ambas podem ter direito a Atlas, mas uma concessão em Cedar não vale em Harbor. Se Maya for gestora em Cedar, ela pode administrar acesso naquela organização sem consumir Atlas. Para consumir, precisa da mesma concessão explícita exigida dos demais usuários.

A consequência prática é importante: trocar o título, traduzir Atlas ou promover alguém para uma função administrativa não pode modificar a concessão. Suspender uma associação ou deixar sua validade terminar deve impedir uma nova admissão mesmo que o recurso continue publicado.

Para defender o modelo, enumere cada condição que precisa ser verdadeira. Depois retire uma de cada vez: organização suspensa, projeto suspenso, associação ausente, associação suspensa, validade encerrada, recurso arquivado, direito desativado, concessão revogada. A resposta deve continuar sendo negação para gestores e equipe interna. Esse exercício vira uma tabela independente de teste, sem copiar a implementação do predicado.

## Constraints e transações resolvem problemas diferentes

Uma chave estrangeira composta inclui a organização junto do identificador relacionado. Ela impede que uma concessão use uma associação de Harbor e um projeto de Cedar, mesmo quando os dois identificadores existem. A unicidade impede duplicar a mesma relação; checks restringem os estados válidos. Essas proteções continuam funcionando se uma rota estiver errada.

Mas uma constraint de linha não prova que haverá um último gestor ativo após duas suspensões concorrentes. Essa regra envolve um conjunto de linhas e uma sequência de decisões. O serviço precisa serializar a mudança no escopo da organização, verificar o conjunto atual e gravar dentro da mesma transação. A prova combina regra de domínio, protocolo de lock e teste com conexões independentes.

O modelo propõe ao menos um gestor cliente ativo sem expiração para continuidade. Gestores temporários da equipe interna não satisfazem essa condição: podem estar ativos agora e expirar depois, sem um comando de suspensão. Produto e Operações precisam confirmar essa premissa antes do corte real. A mesma revisão cobre a desativação de um direito, que revoga concessões dependentes e não as recupera automaticamente ao reativar o direito, e o arquivamento terminal de uma identidade de recurso.

Atomicidade também não significa autorização. Uma transação pode gravar uma alteração completa no escopo errado. Por isso o comando precisa identificar ator, organização, associação, projeto, diferença e versão esperada. A transação garante que concessões, versão, recibo e auditoria sejam confirmados juntos ou revertidos juntos.

Pergunta para revisão: se a auditoria falhar depois de alterar a concessão, qual estado fica? A resposta exigida é nenhum efeito parcial. Se a resposta HTTP se perder depois do commit, a resposta muda: o efeito já existe e deve ser recuperado pelo recibo de idempotência, sem outra concessão.

## Comparar isolamento com a ordem exigida pelo produto

No PostgreSQL, READ COMMITTED usa um snapshot por instrução; duas consultas na mesma transação podem observar commits diferentes. REPEATABLE READ mantém um snapshot estável e pode exigir reinício após conflito. SERIALIZABLE rejeita execuções que não possam corresponder a uma ordem serial e também exige tratamento de reinício. Esses níveis não substituem a regra de autorização. [Documentação de isolamento](https://www.postgresql.org/docs/18/transaction-iso.html).

O desenho do Scopegate usa READ COMMITTED com protocolo explícito. Primeiro adquire os locks necessários; depois executa uma nova leitura autoritativa da política. Não combine espera por advisory lock e avaliação da política em uma única consulta presumindo que a espera atualiza seu snapshot. Essa é uma condição da aplicação que precisa de um teste determinístico.

Um snapshot estável parece atraente para relatórios, mas uma revogação confirmada durante a espera pode não fazer parte daquele snapshot. Mudar apenas o nível de isolamento exige revisar o contrato de admissão e toda a estratégia de repetição; não é uma otimização local. SERIALIZABLE ordena transações bem sucedidas, enquanto o produto também exige uma relação observável entre commit de revogação e admissão posterior. A [correção distribuída](DISTRIBUTED_CORRECTNESS.md) especifica essa relação.

## Explicar a corrida entre usar e revogar

Há dois resultados válidos, definidos pela aquisição de locks e confirmação:

| Ordem | Resultado exigido |
| --- | --- |
| O uso obtém os locks compartilhados, confirma política válida e grava antes da revogação | O uso pode concluir; a revogação espera e depois confirma |
| A revogação confirma antes de o uso obter a proteção e reler a política | O uso é negado e não cria saída protegida |

O uso mantém locks compartilhados nos recursos e na organização enquanto valida referências e cria a saída durável. A revogação usa proteção exclusiva na organização. Locks de transação são liberados ao finalizar a transação; o advisory lock é um acordo da aplicação e todos os caminhos precisam respeitá-lo. [Documentação de locks](https://www.postgresql.org/docs/18/explicit-locking.html).

Ordenar recursos antes de organização e associação evita introduzir um caminho inverso quando publicação e revogação se cruzam. Arquivamento pelo catálogo disputa o lock de recurso. Um comando que primeiro trava a organização e depois busca novos locks de recurso pode quebrar esse acordo. O desenho precisa definir o conjunto antes de adquirir proteção; mudanças de conjunto requerem validação e reinício seguro, conforme o contrato.

A espera também consome tempo de validade. `CURRENT_TIMESTAMP` representa o início da transação; `clock_timestamp()` acompanha o relógio atual. A verificação de expiração precisa usar o tempo depois da espera, não um instante capturado antes. [Funções de tempo](https://www.postgresql.org/docs/18/functions-datetime.html).

Para provar, use duas conexões e barreiras explícitas: uma segura o lock, outra tenta prosseguir, a primeira confirma, e a segunda verifica o estado final. Um teste que só dispara duas tarefas e espera um pouco pode nunca ter exercitado a interleaving importante. A execução deve afirmar resposta, linhas, versão, auditoria e ausência de saída negada.

## Versão e idempotência não são a mesma proteção

`If-Match` com a versão de acesso protege contra uma pessoa salvar uma edição antiga sobre uma edição mais nova. A chave de idempotência protege a repetição do mesmo comando depois de resposta perdida ou falha transitória. Uma não substitui a outra.

Suponha que Maya carregue a versão 7 e Theo carregue a mesma versão. Theo confirma uma diferença e a versão passa a 8. Uma nova edição de Maya com versão 7 deve conflitar. Porém, repetir o comando já confirmado de Theo com o mesmo ator, escopo, corpo, alvo e chave deve recuperar o resultado anterior, depois de verificar autoridade atual. Não deve reaplicar o estado pendente nem tratá-lo como uma edição nova.

Se a mesma chave vier com outro corpo, associação, projeto ou versão, há conflito. Se vier de outra identidade, não pode retornar um recibo alheio. O recibo e sua retenção são parte do contrato, não um cache informal em memória. Expirar recibos exige definir o limite seguro de repetição.

No convite, a identidade é o par imutável emissor e sujeito. Email verificado recente comprova quem pode aceitar aquele token, mas o email de contato não une identidades. Consumo do token, associação, concessões explícitas, recibo e auditoria confirmam juntos. Uma associação suspensa não é reativada por conveniência e um gestor existente não é rebaixado ao aceitar um convite de visualizador.

## Entender o outbox sem prometer execução única

Gravar acesso no banco e enviar uma mensagem externa são efeitos em autoridades diferentes. O outbox grava a intenção de entrega junto da mudança de estado. O worker envia depois do commit, com chave estável, limite de tentativas e prazo. Assim, uma falha entre commit e envio não apaga a intenção.

O envio pode repetir: o processo pode entregar e falhar antes de registrar o resultado. A defesa é deduplicação suportada pelo destino e efeito seguro da repetição, além de estado de entrega verificável. O convite não é aceito porque o email foi entregue. Um payload irrecuperável vai para falha terminal revisável, não para repetição infinita.

Observer em memória não fornece essa durabilidade. Inbox só se torna necessário quando existir um consumidor de eventos com identificadores e ordenação próprios; os recibos de publicação já cobrem o comando atual. Event sourcing é outra decisão: uma auditoria não contém automaticamente todos os fatos e versões necessários para reconstruir o domínio.

## Medir escala e falha parcial

Adicionar réplicas da API não aumenta indefinidamente a capacidade do PostgreSQL. Cada processo, worker, migração e implantação sobreposta consome conexões e tempo de banco. Some os limites e reserve margem antes de dimensionar o pool. Depois meça espera de conexão, espera de lock, duração da transação e percentis por operação.

Use um conjunto representativo com organizações desiguais e mistura de busca, convite, edição e uso. Um teste só de GET em dados pequenos não explica o custo de um projeto com muitas concessões ou de uma disputa de revogação. Evitar N+1 precisa de número de consultas e planos; usar um índice não prova que ele serve o filtro real.

Backpressure limita admissão e trabalho pendente antes da exaustão. Bulkheads separam recursos de API, entrega e migração. Timeout limita espera; retry usa classificação de falha, atraso com jitter, tentativas e prazo total. Circuit breaker pode conter uma dependência instável, mas jamais autoriza acesso quando a identidade falha.

Degradação segura permite que um painel de metadados falhe enquanto outros painéis autorizados continuam. Uma política desconhecida fecha o uso protegido. Cache de metadados é uma discussão diferente de cache positivo de autorização. Read replica atrasada pode servir informação antiga; por isso não vira autoridade de revogação no primeiro desenho. [Capacidade](CAPACITY_PLAN.md) e [confiabilidade](RELIABILITY_DESIGN.md) definem quando reavaliar essas escolhas.

## Diferenciar migração de cópia de dados

Reconcilie decisões efetivas para principal, organização, projeto, recurso, ação e tempo equivalente. Contar concessões ou somar listas antigas não prova equivalência. Compare permissões e negações; uma linha ausente na comparação é informação faltando, não sucesso.

Um registro ambíguo precisa de motivo, responsável e decisão. Não escolha a união das listas para evitar reclamações nem a interseção para parecer conservador: ambas podem contrariar acesso aprovado. A organização com bloqueio não corta para a nova autoridade.

Antes da troca, cerca os escritores, drena o trabalho relevante, alcança o watermark e compara novamente. O epoch impede que uma requisição antiga confirme depois de perder a autoridade. Depois da troca, o estado alvo continua canônico. Uma versão anterior da aplicação só pode voltar se entender essa fronteira e preservar revogações; restaurar um backup anterior não é esse procedimento.

Na recuperação de desastre, uma revogação posterior ao backup pode desaparecer. Tráfego permanece bloqueado até que um diário durável independente ou a reconciliação aprovada estabeleça o estado atual. Se essa evidência não existe, o sistema não pode prometer preservação de permissões. [Migração](MIGRATION.md) e [entrega](DELIVERY_SYSTEM.md) tornam esses limites operacionais.

## Escolher padrões sem transformar o desenho em catálogo

Factory monta adaptadores reais; Adapter isola protocolos; Service Layer coordena o comando; Unit of Work preserva seus efeitos; Repository faz consultas de escopo específico. Specification é o predicado explícito de acesso e State Machine define transições. Esses nomes explicam responsabilidades existentes.

Antes de adicionar Strategy, Decorator ou Builder, identifique a variação real, o contrato preservado e a repetição que ficou difícil. Uma classe nova precisa diminuir complexidade total. Template Method não foi escolhido porque esconder passos de lock e transação em herança dificulta revisar o fluxo. Microserviços, atores e plataformas de workflow permanecem adiados enquanto não houver benefício medido que pague seus novos modos de falha.

Discuta SOLID com um exemplo concreto: o domínio não deve conhecer o SDK do provedor, o adaptador local deve preservar a semântica de verificação do port, e um cliente de entrega não deve precisar implementar funções de catálogo. DRY compartilha a regra; não transforma convite e publicação em um comando genérico com dezenas de opções.

## Provar qualidade sem usar porcentagens como argumento final

Prepare uma explicação de qual defeito cada camada de verificação consegue detectar. Unidade prova a regra; integração prova o mecanismo de banco; contrato prova a fronteira; poucos E2E provam a jornada; carga mede o orçamento; falha controlada prova contenção e recuperação.

Complexidade acima de 10 exige atenção, acima de 15 exige refatoração ou exceção explícita e acima de 20 bloqueia sem a exceção limitada. Isso não transforma uma função com valor 9 em código automaticamente bom. Coesão, acoplamento, clareza e riscos ainda precisam de revisão. Maintainability Index e estimativas de dívida não ganham uma meta numérica sem referência medida.

Mutation testing do predicado crítico pergunta se remover uma condição de grant, organização ou validade faria um teste falhar. O orçamento inicial de execução é proposto e limitado; uma mutação sobrevivente precisa de investigação. Exaurir o orçamento não equivale a provar qualidade. Não é necessário executar mutações em cada componente visual para defender autorização.

## Perguntas para ensaiar a defesa

1. Qual decisão muda quando Maya troca Cedar por Harbor, e onde isso é imposto além do navegador?
2. Que parte da garantia vem de constraint, versão, lock, transação e verificação de identidade?
3. Se a revogação confirmar enquanto um comando espera, de qual instante vêm estado e tempo?
4. Por que SERIALIZABLE não é uma troca local que resolve todos os problemas?
5. O que acontece se o commit tiver sucesso, a resposta se perder e o usuário autenticar novamente?
6. Como provar que o destino não recebeu uma segunda mensagem e qual limite existe se ele não deduplicar?
7. Qual orçamento impede entrega e migração de consumir todas as conexões da API?
8. Que sinal mostra um ganho de acesso indevido, e qual ação interrompe a expansão?
9. Que mudança de código pode voltar sem perder uma revogação posterior?
10. Qual medição justificaria uma réplica de leitura, um cache, particionamento ou separação de serviço?

Uma resposta madura identifica a condição, o mecanismo, a evidência que pode refutá-la e o limite aceito. Quando a condição ainda não foi verificada, registre a hipótese e o responsável. Planejamento consistente é necessário; somente execução independente dos gates comprova a aplicação.
