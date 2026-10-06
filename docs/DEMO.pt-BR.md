# Demonstração do Scopegate

Reserve 15 a 20 minutos. Execute `make setup` e `make up` antes de começar e abra `http://localhost:5187`. Todos os nomes e dados são sintéticos.

1. **Problema e proposta — 2 minutos.** Explique quem pode usar qual recurso em qual projeto, com rastreabilidade. Separe identidade, vínculo com a organização, contrato do projeto e permissão explícita. Justifique o monólito modular pela unidade transacional e pelo tamanho do domínio.
2. **Visão do gestor — 3 minutos.** Entre como Amelia Brooks. Mostre Cedar Studio, Harbor e Grove. Compare os recursos disponíveis no projeto com os recursos que o usuário pode consumir. Administração e consumo exigem permissões diferentes.
3. **Convite e primeiro acesso — 4 minutos.** Convide `morgan@example.test`, selecionando Harbor e um recurso. Mostre o estado do convite e o estado da entrega separadamente. Copie o link na caixa local protegida e abra uma janela anônima. Entre como Morgan Lane, revise e aceite. Abra o recurso concedido pela jornada protegida.
4. **Concorrência e revogação — 3 minutos.** No gestor, remova a concessão de Morgan com um motivo. Na janela de Morgan, atualize e tente usar o recurso. A autorização atual deve negar. Explique versão otimista, recibo e por que repetir um pedido antigo não restaura a concessão.
5. **Isolamento e atuação temporária — 2 minutos.** Entre como Rowan Vale e troque entre Cedar Studio e Birch Labs. Mostre a expiração do vínculo e a ausência de consumo implícito pelo papel de suporte.
6. **Migração sem adivinhar intenção — 3 minutos.** Com Rowan, mostre um conflito de associação e uma referência desconhecida. A decisão tem responsável, justificativa, versão e prova. A tela revisa; a troca de autoridade exige fence, watermark e comparação de decisões positivas e negativas pela CLI.
7. **Qualidade e operação — 3 minutos.** Mostre testes e artefatos reais. Explique rollback transacional, limites de fila/conexão e o ensaio de restauração. Uma revogação não reconciliada mantém a recuperação fechada. Indique os limites do produto local e os requisitos de uma integração real.

Se o tempo for curto, priorize convite, uso protegido, revogação e isolamento. Use `docs/screenshots/` como apoio: as capturas registram o produto executado.

Conecte decisão, risco e evidência: “O bloqueio da organização ordena a revogação com a admissão do relatório; a avaliação usa uma leitura nova depois do bloqueio; o teste com duas conexões prova que a admissão posterior ao commit é negada.”

O benchmark local não certifica capacidade de produção. O provedor sintético não representa integração com um tenant externo. Essas diferenças estão registradas no escopo fechado e evitam promessas sem evidência.
