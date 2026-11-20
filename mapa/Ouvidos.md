---
tags:
  - componente
---

# Ouvidos

`jarvis/ears.py` — captura o áudio do microfone e transcreve com Whisper local (`faster-whisper`, modelo `small`, int8).

## Detecção de fim de fala

O microfone é lido em blocos de 30 ms. Nos primeiros 300 ms o ruído ambiente é medido e o limiar se ajusta a ele — sem isso, um ambiente barulhento faria a captura nunca terminar.

Salvaguardas contra travamento:

- **Silêncio inicial**: se ninguém falar em ~6 s, desiste (antes ficava 60 s parado).
- **Buffer pré-fala**: os 300 ms anteriores ao início da fala entram na gravação, para não cortar a primeira sílaba.
- **Fila com timeout**: se o microfone parar de enviar áudio (desconexão), levanta `EarsError` em vez de bloquear para sempre.

## Permissão negada é silenciosa

No macOS, microfone sem permissão **não dá erro** — entrega áudio zerado. É por isso que o [[Operação|diagnóstico]] acusa "silêncio absoluto (0.0)" como provável falta de permissão.

## Sem microfone

A biblioteca `sounddevice` só é importada quando a captura, a palavra de ativação ou o corte da fala vão abrir o microfone. Modo texto e Telegram não passam por esse import. Se a biblioteca não estiver instalada, a captura explica o problema e o resto do Jarvis segue.

## Relacionado

[[Jarvis]] · [[Palavra de ativação]] · [[Cérebro]]
