# Alinhamento de produto para o Scopegate

O Scopegate organiza acesso por organização, projeto e recurso publicado. A proposta é conter os defeitos atuais, validar uma nova fronteira de acesso em um fluxo completo e ampliar a migração somente quando o acesso aprovado estiver preservado.

O conteúdo abaixo está pronto para revisão e adaptação em uma conversa com Produto, Operações e a equipe técnica. É um rascunho de mensagem; não foi enviado.

## Mensagem para alinhamento

Pessoal, proponho começar estabilizando os fluxos que hoje falham e reconstruir apenas a fronteira de acesso. O primeiro passo trata metadados ausentes, recursos indisponíveis, busca no escopo correto e alterações de recursos em uma transação. Vamos registrar o estado antes e depois de cada reprodução: uma resposta 400, isoladamente, não comprova que os dados da organização foram alterados.

O piloto terá um fluxo completo: convite com identidade verificada e recursos explicitamente selecionados, associação à organização e concessões confirmadas na mesma transação, uso autorizado, revogação e histórico de auditoria. Uma pessoa da equipe interna também será verificada em duas organizações para provar isolamento. Essa pessoa terá associação e validade próprias em cada organização, sem acesso global implícito.

Precisamos fechar três decisões de Produto antes de migrar o piloto: quais solicitações podem receber aprovação automática; qual fonte determina os recursos contratados por organização e projeto; e quem decide as exceções históricas que não permitem concluir o acesso com segurança. Enquanto essas regras estiverem abertas, não haverá aprovação automática nem migração dos registros afetados.

Minha recomendação é que o papel de gestor permita administrar acesso, mas não dê acesso ao conteúdo. Para consumir um recurso, qualquer pessoa precisará de associação ativa, recurso disponível naquele projeto e concessão individual explícita. A publicação e as traduções continuam sob responsabilidade do catálogo, com identidade estável independente do título.

Para planejar, considero três engenheiros com responsabilidades no produto atual e disponibilidade conjunta de 1,5 pessoa em tempo integral. Com essa premissa, a estabilização fica estimada em 1 a 2 semanas, o primeiro fluxo completo em 3 a 5 semanas e a observação do piloto em 1 a 2 semanas. O produto público completo, incluindo os fluxos de gestão, a migração, a operação e a qualidade de P0 a P2, tem estimativa inicial de 44 a 72 dias de engenharia, com faixa de planejamento de 8 a 13 semanas. São estimativas dependentes das integrações e decisões, sem prazo imposto; vamos revisá-las após as primeiras reproduções e a leitura dos dados. Grupos adicionais de migração real serão estimados conforme o inventário.

As metas propostas para o piloto são zero ampliação de acesso sem aprovação, zero perda de acesso aprovado e nenhuma falha crítica de autorização durante a observação. Também vamos medir incidentes e tempo de entrada de usuários. A redução de 30% no tempo mediano de processamento é uma meta inicial a confirmar depois de medir a referência, separando espera por aprovação do tempo do sistema.

A migração começará com uma simulação que não altera acesso ativo. Cada diferença terá motivo, responsável e decisão registrada. Só um grupo de organizações reconciliado, com comparação de acesso aprovada e retorno ensaiado, poderá entrar no piloto. Depois da mudança, a nova fronteira continua sendo a autoridade de acesso, inclusive em um retorno de versão da aplicação. Revogações não podem ser apagadas por um snapshot antigo. Se houver divergência ou falha de autorização, a expansão para e o problema fica contido.

O resultado esperado é uma fronteira de acesso menor, verificável e fácil de operar. Não precisamos substituir o produto inteiro para provar esse resultado. Produto decide as regras comerciais e as exceções; a liderança técnica responde pelas invariantes, pela ordem de execução e pelas evidências de qualidade; Operações responde pela configuração, pelas associações temporárias da equipe interna e pela execução da migração.

## Decisões e responsáveis

| Decisão | Responsável | Condição para o piloto |
| --- | --- | --- |
| Política de aprovação automática | Produto | Critérios explícitos; pendências continuam sem aprovação automática |
| Fonte dos recursos contratados | Produto com responsável pelo catálogo | Organização e projeto reconciliados com a fonte autorizada |
| Exceções históricas de acesso | Produto com Operações | Resolução justificada de cada exceção do grupo piloto |
| Atribuição e validade da equipe interna | Operações | Associação explícita por organização, com expiração obrigatória |
| Identidade e publicação | Responsáveis pelas integrações | Adaptador OIDC real e contrato do catálogo verificados |
| Condições de liberação e retorno | Liderança técnica com Operações | Comparação de acesso, restauração e retorno ensaiados |

O detalhe de escopo está em [produto](PRODUCT.md); estimativas e condições de execução estão no [plano de entrega](DELIVERY_PLAN.md). A [migração](MIGRATION.md) descreve como reconciliar, liberar e retornar sem resolver dúvidas por permissões amplas.
