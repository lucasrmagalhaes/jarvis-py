---
tags:
  - operação
---

# Operação

## Rodar

```
python -m jarvis.main            # mãos-livres (padrão)
python -m jarvis.main --texto    # terminal, Enter vazio usa o microfone
python -m jarvis.chat            # terminal, sem microfone
python -m jarvis.telegram        # segundo plano: Telegram, lembretes, check-ins
python -m jarvis.setup           # instala, configura, pode iniciar no login
python -m jarvis.setup --desativar-inicio
python -m jarvis.doctor          # diagnóstico
python -m jarvis.doctor --corrigir  # arquivo local, permissão e dependências
python -m jarvis.vault           # estado do vault, sem alterar
python -m jarvis.vault --pull    # pull seguro
python -m jarvis.consult         # consulta no Android, só leitura, sem Claude
python -m jarvis.consult --baixar-modelo  # baixa só os pesos do modelo gratuito
```

O diagnóstico verifica Python, dependências, o arquivo de ambiente, Jira, Gmail, GitHub, o início automático, Claude Code **logado**, o vault, o Telegram, os check-ins, os alertas, microfone (dispositivo e permissão), backends de voz, modelos em cache, a porta do painel e a porta da consulta. Não imprime token nem senha. Se houver token sem o usuário autorizado, a pendência impede o funcionamento. Sai com código 1 se algo impedir o funcionamento.

`python -m jarvis.doctor --corrigir` cria `~/.jarvis/.env` se faltar, restringe a permissão e instala dependência ausente. Não grava chave, não clona o vault e não mexe em `.obsidian`. Se faltar vault, chave ou dependência, a frase de erro aponta o comando seguinte. Se o pip falhar, a frase diz o código de saída e o que não importou. Sem a palavra de ativação, a alternativa é `python -m jarvis.chat`. O backend é ONNX, sem tflite-runtime.

O Telegram só responde ao `TELEGRAM_ALLOWED_USER_ID`, em conversa privada. Lembretes, recados novos da Inbox e os alertas de PR, Jira e e-mail importante também seguem para essa conversa enquanto o processo estiver aberto. Foto com legenda e tags, ou um link com título, viram nota na inbox de notas. "Quais minhas prioridades hoje?" cruza lembrete, agenda, Jira e PR e responde as três primeiras. "O que eu te pedi ontem?" lê o log local de pedidos. A primeira consulta desses alertas só memoriza. O mesmo item não se repete, e há uma pausa entre avisos. `JARVIS_RADAR=off` desliga. "Todo dia às 9" e "toda segunda às 10" ficam na nota e disparam de novo na próxima data, por voz e no Telegram. "Adia o lembrete" e "cancela o lembrete" valem na voz, no texto e no Telegram. "Resume os recados" resume o que ainda não foi lido, sem marcar como lido. O briefing sai no primeiro arranque do dia e inclui a agenda do dia. "O que tenho hoje?" e "o que tenho amanhã?" leem os compromissos do vault. O resumo do fim do dia pergunta se grava no vault. No domingo, depois do horário da tarde, o resumo da semana é gravado sem perguntar. No login, o início automático sobe `python -m jarvis.main`, que já carrega esse companheiro. `python -m jarvis.telegram` faz o mesmo companheiro sem microfone. `jarvis.chat` e o Telegram não importam a biblioteca de microfone para subir. O modo mãos-livres importa essa biblioteca só quando vai abrir o microfone.

## Instalador

`python -m jarvis.setup` grava `~/.jarvis/.env` fora do git, com permissão só do usuário, e pode armar o início no login. Pergunta também o Telegram e os check-ins. `--desativar-inicio` remove o LaunchAgent no macOS ou, no Windows, a tarefa agendada e o arquivo da pasta Inicializar. Rodar de novo edita a configuração. No Linux o início automático não é instalado.

## Máquina nova

O Claude Code consegue clonar, criar o venv, instalar dependências e rodar o diagnóstico. Três passos exigem uma pessoa:

1. **Login do Claude Code** — `claude` e login pelo navegador; é a conta que serve de cérebro.
2. **Permissão de microfone** — diálogo do sistema, precisa de clique.
3. **Rodar o assistente** — processo contínuo, precisa de um terminal de verdade.

## Ajustes frequentes

| Variável | Para quê |
|---|---|
| `JARVIS_WAKE_THRESHOLD` | Acorda demais / não acorda (padrão `0.5`, menor = mais sensível) |
| `JARVIS_SILENCE_THRESHOLD` | Corta a fala cedo ou nunca termina |
| `JARVIS_TTS` | Forçar backend de voz: `say`, `edge`, `sapi` |
| `JARVIS_ALLOWED_TOOLS` | Poderes do assistente — ver [[Decisões#Ferramentas somente leitura por padrão]] |
| `JARVIS_VAULT` | Clone local do vault Obsidian. Ver [[Vault]] |
| `JARVIS_PANEL_PORT` | Porta ocupada |
| `JARVIS_PANEL=off` | Rodar sem o [[Painel HUD]] |

Lista completa no `README.md`.

## Primeira execução

Precisa de internet: baixa o Whisper `small` (~460 MB) e os modelos de wake word (~7 MB). Depois disso, transcrição e ativação funcionam offline.

## Relacionado

[[Jarvis]] · [[Decisões]] · [[Painel HUD]] · [[Vault]]
