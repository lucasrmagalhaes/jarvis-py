---
tags:
  - componente
---

# Consulta Android

`jarvis/consult.py` e `jarvis/consult_http.py` servem uma página instalável no Chrome do Android. A página consulta o clone local do vault e devolve trechos com o caminho da nota.

## Por que esta forma

O telefone não recebe uma cópia do vault. O processo fica no computador, em `127.0.0.1`, e o Chrome do Android chega nele pelo `adb reverse`. A página é um PWA: dá para instalar na tela inicial, e a consulta continua no Jarvis que já lê o `JARVIS_VAULT`.

A consulta básica não usa o Claude Code e não usa API paga. O [[Cérebro]] segue responsável pela voz, pelo terminal e pelo Telegram. Esta tela não entra nessa fila e não dispara a escrita que esses modos já fazem.

## Busca

A busca é híbrida e local. O BM25 ordena pela palavra. Com os pesos do modelo já em disco, os embeddings locais ordenam pelo significado e o Reciprocal Rank Fusion junta as duas listas. Sem os pesos, fica a palavra: BM25 e a ordenação por n-gramas, no mesmo fusionamento. "nos livros" limita a `Tecnologia/Livros`, "nos vídeos" a `Tecnologia/Vídeos` e "nos cursos" a `Tecnologia/Cursos`. A pasta `.obsidian` não entra. Sem trecho suficiente, a resposta diz que não há evidência no vault. Cada trecho sai com o caminho da nota.

O modelo é o `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, licença Apache-2.0, cerca de 220 MB, pelo pacote `fastembed`. O comando de download manda só uma frase fixa de aquecimento. As notas não vão nesse pedido. Na consulta, o carregamento pede arquivo local e liga `HF_HUB_OFFLINE` em volta dessa carga.

O índice dos trechos fica na memória do processo. Ao encerrar, ele some. A página manda `Cache-Control: no-store` e o service worker não guarda resposta nem nota.

## O que a tela mostra

Cada resposta traz o trecho, o caminho, o wikilink e um link `obsidian://` para abrir no Obsidian daquele aparelho, se o mesmo vault já estiver lá por outro meio. Esta consulta não clona o vault no telefone.

Quando há evidência, a tela também sugere cartões de revisão e ligações entre notas. Nada disso é gravado. Sem evidência, essas sugestões ficam vazias.

## Uso no Android

No computador, com o clone e o `JARVIS_VAULT` apontando para ele:

```bash
python -m jarvis.consult
```

O terminal imprime um link com o token da execução. Esse token não fica no código da página. Ele vai para um cookie `HttpOnly` quando o link de entrada abre.

No telefone, com depuração USB:

```bash
adb reverse tcp:8766 tcp:8766
```

Troque `8766` se `JARVIS_CONSULT_PORT` for outra. Abra o link do terminal no Chrome do Android e use Instalar app ou Adicionar à tela inicial. O contexto seguro é o `127.0.0.1` do cabo. Sem o cabo, o padrão não escuta a rede.

`JARVIS_CONSULT_BIND=lan` escuta um IP privado da mesma Wi-Fi. Não encaminhe a porta no roteador e não use rede pública. Esse endereço é HTTP, então o Chrome pode não oferecer a instalação. O caminho com cabo continua o modo de instalar.

## Modelo gratuito

```bash
pip install -r requirements-consult.txt
python -m jarvis.consult --baixar-modelo
```

Sem esse passo, a consulta segue na busca vetorial e na textual. `JARVIS_CONSULT_MODEL=off` ignora pesos já baixados. `JARVIS_CONSULT_MODEL_DIR` troca a pasta. O padrão é `~/.jarvis/models/consult`.

## Limites

A resposta é o trecho encontrado, com o caminho. Ela não redige um resumo novo e não puxa o git. O que estiver no clone local é o que a consulta vê. A sincronização continua nos outros comandos do Jarvis.

A página não atende comando de escrita. `PUT` e `DELETE` recebem método não permitido. A escrita existente da voz, do terminal e do Telegram permanece nesses modos.

O histórico do Chrome pode guardar o link de entrada, porque ele leva o token. Apague esse acesso se o aparelho for compartilhado. Reiniciar o processo troca o token.

## Relacionado

[[Jarvis]] · [[Vault]] · [[Decisões]] · [[Operação]] · [[Painel HUD]] · [[Cérebro]]
