---
tags:
  - componente
---

# Palavra de ativação

`jarvis/wakeword.py` — mantém o Jarvis em standby ouvindo por **"Hey Jarvis"**.

Usa o openWakeWord com o modelo pré-treinado `hey_jarvis_v0.1` em ONNX (`inference_framework=onnx`). Roda inteiramente local: nenhum áudio sai da máquina enquanto ele espera ser chamado. O `tflite-runtime` não é necessário. No Linux, a partir do Python 3.12, ele nem tem wheel, então a instalação desse pacote fica num arquivo à parte e não segura o áudio nem a voz.

## Limiar

`JARVIS_WAKE_THRESHOLD` (padrão `0.5`). Menor = mais sensível. Em teste, a frase "Hey Jarvis" sintetizada pontuou **0.82** e uma frase de controle **0.00** — margem confortável.

O modelo foi treinado com a frase completa; só "Jarvis" às vezes dispara, mas com menos confiabilidade.

## Interrupção pelo painel

`wait()` aceita um `stop_when`, verificado a cada bloco de áudio. É assim que uma mensagem digitada no [[Painel HUD]] tira o Jarvis do standby sem precisar da palavra falada.

Manter a escuta pausada durante o processamento é intencional: se o microfone seguisse ativo enquanto ele fala, a própria resposta poderia redisparar o wake word.

## Relacionado

[[Jarvis]] · [[Ouvidos]] · [[Painel HUD]]
