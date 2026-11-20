---
tags:
  - componente
---

# Painel HUD

`jarvis/panel.py` + `jarvis/static/index.html` — interface web local no estilo do HUD do Homem de Ferro.

Servidor HTTP da biblioteca padrão em `127.0.0.1`, sem dependências extras. O navegador recebe eventos por SSE; o reator arc muda de cor e ritmo conforme o estado (em espera → ouvindo → processando → respondendo).

Também aceita mensagens digitadas, inclusive com o Jarvis em standby.

Com o vault configurado, o reator mostra o último sync e se há commits por enviar. Um lembrete na hora entra no registro e na voz.

## Segurança

O painel dá acesso a um assistente que lê arquivos e busca na web. Sem proteção, qualquer site aberto no navegador poderia comandá-lo. As defesas, todas cobertas por testes:

| Ameaça | Defesa |
|---|---|
| CSRF de outro site | Token aleatório por execução, exigido em toda rota |
| DNS rebinding | Allowlist do cabeçalho `Host` |
| Request smuggling | Rejeições fecham a conexão |
| Clickjacking | `X-Frame-Options: DENY` + CSP `frame-ancestors` |
| Exaustão de memória | Limite de corpo (8 KB), fila e assinantes |
| Slowloris | Timeout de socket |

Consequência prática: a URL precisa do token (`?t=...`, impresso no terminal) e **muda a cada execução**. Ver [[Decisões#Token por execução no painel]].

## Relacionado

[[Jarvis]] · [[Palavra de ativação]] · [[Operação]]
