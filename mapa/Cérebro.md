---
tags:
  - componente
---

# Cérebro

`jarvis/brain.py` — converte texto em resposta chamando o Claude Code em modo headless.

A [[Consulta Android]] não passa por este módulo. Ela lê o clone e responde com trechos.

## Como funciona

Executa `claude -p --output-format json`, enviando a mensagem por **stdin** (nunca por argumento, para que textos começando com `-` não sejam lidos como flags). A resposta volta em JSON, de onde saem `result` e `session_id`.

O `session_id` é guardado e devolvido no próximo turno via `--resume`, o que dá memória à conversa. Se o resume falhar (sessão expirada), ele descarta o id e tenta de novo do zero — em vez de travar para sempre.

## Personalidade

A persona não vai na linha de comando: é escrita em `workspace/CLAUDE.md`, que o Claude Code lê automaticamente. Ver [[Decisões#Persona em arquivo, não em argumento]].

## Ferramentas

Por padrão só leitura e busca: `Read`, `Glob`, `Grep`, `WebSearch`, `WebFetch`. Em modo headless não existe confirmação, então liberar `Edit`, `Write` ou `Bash` significa execução sem supervisão — ver [[Decisões#Ferramentas somente leitura por padrão]].

Com o [[Vault]] configurado, `Edit` e `Write` entram sozinhos. `Bash` fica de fora, para o modelo não rodar git.

## Vault

Se `JARVIS_VAULT` aponta para o clone, o `cwd` da consulta é essa pasta. O `CLAUDE.md` do vault permanece intocado. A persona e o texto lido do `AGENTS.md` do clone vão num arquivo fora do vault, passado com `--append-system-prompt-file`. A persona vale para a resposta falada. O conteúdo da nota segue o vault.

Antes de cada pedido o [[Vault]] atualiza o clone. Depois, se o pedido editou notas, faz commit só desses arquivos e push.

"Bom dia", "anota", "o que eu escrevi sobre", "o que anotei sobre", "me lembra", "quais minhas prioridades hoje" e "o que eu te pedi ontem" são resolvidos no próprio Jarvis. A busca responde com um trecho e o caminho da nota. As prioridades cruzam lembrete, agenda, issue do Jira e PR, e a fala fica nas três primeiras. O histórico lê o log local de pedidos, não o vault. Os outros pedidos seguem para o Claude Code.

## Relacionado

[[Jarvis]] · [[Ouvidos]] · [[Voz]] · [[Operação]] · [[Vault]]
