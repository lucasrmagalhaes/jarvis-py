---
tags:
  - componente
---

# Vault

`jarvis/vault.py` sincroniza o clone local do vault pessoal com o GitHub.

## Configuração

`JARVIS_PASTAS_IGNORADAS` tira pastas da busca, dos cartões e dos lembretes, sem torná-las sigilosas.

`JARVIS_VAULT` é o caminho do clone. Sem essa variável o Jarvis segue na pasta `workspace`, só com leitura. `python -m jarvis.setup` grava esse caminho em `~/.jarvis/.env` e clona o vault se a pasta ainda não existir.

Não há remoto padrão. `JARVIS_VAULT` é o clone. Com `JARVIS_VAULT_REMOTE` vazio, o sync usa o `origin` desse clone. Se a variável estiver preenchida, HTTPS e SSH do mesmo repositório contam como o mesmo destino, e outro remoto é recusado.

## Fluxo

1. `git fetch`. Sem nada novo no GitHub, o git não toca na pasta.
2. Notas já modificadas e ainda sem commit só vão para um stash quando o que chegou mexe no mesmo arquivo, ou quando os dois lados têm commits. O Jarvis não as commita.
3. Fast-forward quando só o remoto andou. Merge quando os dois lados andaram.
4. Se houve stash, ele volta. Se não couber, as notas permanecem nele.
5. O [[Cérebro]] atende o pedido dentro dessa pasta. A fala segue a persona. A nota segue o vault.
6. Commit só dos arquivos que esse pedido alterou, e push sem force. `.obsidian/` fica de fora.

A consulta do Android (`python -m jarvis.consult`) é outro caminho somente leitura. Ela cita trechos do clone, não faz commit e não dispara a escrita dos outros modos. Ver [[Consulta Android]].

Briefing, captura ("anota"), busca ("o que eu escrevi sobre" ou "o que anotei sobre", com trecho e caminho da nota), agenda ("o que tenho hoje"), foco ("quais minhas prioridades hoje") e lembrete ("me lembra", "adia o lembrete", "cancela o lembrete") não passam pelo Claude. A busca junta BM25 e, se houver pesos locais, embeddings, com Reciprocal Rank Fusion. "nos livros", "nos vídeos" e "nos cursos" limitam a pasta. A pasta `.obsidian` não entra na busca. Escrita em `.obsidian/`, em arquivo de credencial e em texto com cara de segredo é recusada no código. WebFetch e `Jarvis/Inbox` são dado não confiável no prompt. A nota diária, a agenda e o arquivo de lembretes saem do `AGENTS.md`, do `CLAUDE.md` e do `README.md` do clone. O lembrete é uma tarefa `- [ ] assunto @ AAAA-MM-DD HH:MM`. Com o processo aberto, o Jarvis avisa na hora e marca `@avisado` na mesma linha. Adiar troca esse horário. Cancelar marca `[x]` e `@cancelado`.

A agenda do dia lê a pasta `Agenda Profissional`, ou o caminho que o clone indicar. Na nota diária, uma linha que começa com a hora é anotação do `anota` e não entra na agenda. Hora solta só vale como compromisso no arquivo do dia dentro da pasta da agenda. Entram nota `AAAA-MM-DD.md`, frontmatter `data` e `hora`, linha com data explícita e lembrete em aberto naquele dia. O briefing fala esses compromissos. "O que tenho amanhã?" responde só isso.

"Valeu, Jarvis" encerra a conversa e volta ao standby. "Como foi minha semana?" resume a semana e só grava a nota se a pessoa confirmar. No domingo, depois do horário do check-in da tarde, a mesma nota é gravada sem perguntar, se ainda não existir. "Marca como feito" fecha a tarefa com `[x]`. Uma frase curta avisa quando o Claude, o microfone ou a rede falham. O log local não entra no vault.

Jira, GitHub (`gh`) e Gmail entram por consulta somente leitura e, sem configuração, ficam de fora com uma frase curta. O "bom dia" inclui Jira e PRs quando estão configurados. "Quais minhas prioridades hoje?" usa o mesmo Jira e os mesmos PRs, só leitura, junto da agenda e dos lembretes, e fala as três primeiras. Assistentes trocam notas em `Jarvis/Inbox` e `Jarvis/Outbox`, com frontmatter `de`, `para`, `data` e `status`, salvo se o clone apontar outra pasta. Foto ou link no Telegram grava uma nota em `Jarvis/Notas`, ou no caminho da linha `inbox de notas`, com título e tags. A foto fica em `anexos/`. `.obsidian` não entra. "Lembra que eu..." grava fatos em `Jarvis/Perfil.md`, e o cérebro lê essa nota em cada pedido. "O que eu te pedi ontem?" lê o log local de pedidos, fora do vault.

## Quando algo dá errado

| Situação | O que o Jarvis faz |
|---|---|
| Sem rede | Mantém o commit do pedido, se houve alteração, e avisa |
| Notas abertas em conflito com o pull | Deixa essas notas no stash |
| Conflito de merge entre commits | Aborta o merge, deixa as duas histórias intactas |
| Merge ou rebase já em andamento | Não mexe no repositório |
| Remoto diferente do esperado | Recusa o envio |
| HEAD desanexado | Recusa o sync e pede para voltar à branch |

## Convenções das notas

O formato mora no `AGENTS.md`, no `CLAUDE.md` e no `README.md` do próprio vault. O Jarvis não copia essas regras para o código. A cada execução ele lê o `AGENTS.md` do clone e entrega esse texto ao [[Cérebro]]. O `CLAUDE.md` do vault entra porque a pasta é o diretório de trabalho. A persona não entra no texto da nota.

## Relacionado

[[Cérebro]] · [[Decisões]] · [[Operação]] · [[Jarvis]]
