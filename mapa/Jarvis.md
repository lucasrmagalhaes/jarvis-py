---
tags:
  - mapa
---

# Jarvis

Assistente pessoal por voz no estilo Tony Stark, rodando localmente em macOS e Windows. Usa a assinatura do Claude Code como cérebro, sem custo por token.

## Fluxo de uma interação

```
"Hey Jarvis"  →  [[Palavra de ativação]]
                        ↓
   fala do usuário  →  [[Ouvidos]]  (Whisper local)
                        ↓
        texto  →  [[Cérebro]]  (claude -p, sessão contínua)
                        ↓
     resposta  →  [[Voz]]  +  [[Painel HUD]]
```

## Componentes

| Nota | Arquivo | Papel |
|---|---|---|
| [[Palavra de ativação]] | `jarvis/wakeword.py` | Escuta "Hey Jarvis" em standby |
| [[Ouvidos]] | `jarvis/ears.py` | Captura e transcreve a fala |
| [[Cérebro]] | `jarvis/brain.py` | Conversa com o Claude Code |
| [[Vault]] | `jarvis/vault.py` | Lê e grava o vault Obsidian, com sync git |
| [[Operação]] | `jarvis/setup.py` | Instalador, arquivo local e início no login |
| [[Voz]] | `jarvis/voice.py` | Fala a resposta |
| [[Painel HUD]] | `jarvis/panel.py` | Interface web local |
| [[Consulta Android]] | `jarvis/consult.py` | Consulta do vault no Android, só leitura, sem Claude |
| | `jarvis/main.py` | Orquestra a voz |
| | `jarvis/chat.py` | Conversa no terminal, sem microfone |
| | `jarvis/telegram.py` | Bot do Telegram, só para o usuário autorizado |
| | `jarvis/checkins.py` | Briefing do dia, agenda e resumo da semana no domingo |
| | `jarvis/reminders.py` | Avisa lembrete na hora, inclusive o que se repete |
| | `jarvis/bridge.py` | Caixa dos assistentes e resumo dos recados novos |
| | `jarvis/doctor.py` | Diagnostica pré-requisitos e corrige o que é seguro |
| | `jarvis/radar.py` | Avisa PR, issue e e-mail importante, só leitura |
| | `jarvis/journal.py` | Guarda o pedido do dia fora do vault |
| | `jarvis/capture.py` | Foto ou link do Telegram na inbox de notas |

Com `JARVIS_VAULT`, o [[Cérebro]] trabalha dentro do clone do vault e o [[Vault]] sincroniza o git em volta de cada pedido.

## Contexto

- [[Consulta Android]]: leitura do vault no telefone, sem o cérebro e sem gravar
- [[Decisões]] — por que cada escolha de arquitetura foi feita
- [[Operação]] — como rodar, configurar e diagnosticar
- [[Vault]]: notas do Obsidian, pull, commit e push
