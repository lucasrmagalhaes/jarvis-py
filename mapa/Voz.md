---
tags:
  - componente
---

# Voz

`jarvis/voice.py` — fala a resposta, escolhendo o backend conforme o sistema.

## Backends

| Sistema | Ordem de tentativa |
|---|---|
| macOS | `say` (Luciana, offline) → `edge-tts` |
| Windows | `edge-tts` (Antônio neural) → SAPI offline |

Forçar um específico: `JARVIS_TTS=say|edge|sapi`.

Se todos falharem, o terminal mostra `[voz indisponível: resposta apenas em texto]`. Silêncio sem explicação seria pior.

## Cuidados que o código toma

- O texto vai por **stdin**, não por argumento: resolve de uma vez respostas começando com `-`, acentuação e limite de tamanho da linha de comando.
- Markdown é removido antes de falar (links viram só o texto, listas perdem os marcadores).
- O SAPI procura uma voz `pt-*` instalada; sem isso o Windows leria português com voz inglesa.

## Relacionado

[[Jarvis]] · [[Cérebro]] · [[Decisões#edge-tts como padrão no Windows]]
