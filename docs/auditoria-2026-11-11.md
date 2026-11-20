# Auditoria de 11 de novembro de 2026

Base conferida: `2a33add` (PRs #2 a #24 já estavam em `main`).

Esta nota não contém conteúdo de vault. Os testes usam só texto sintético.

## O que foi conferido

- Corridas entre o loop de voz, o Telegram, o resumo semanal, o briefing, o painel e o git do vault.
- Arquivos em `~/.jarvis`: estado, revisão, contexto, memória, índice, pedidos, token do painel e estado do Readwise.
- Escrita de nota e `git commit`/`git push` acontecendo ao mesmo tempo.
- Modo privado no diário, no log de pedidos e no Telegram.
- Remoto do Telegram quando o estado local falha.
- Caminho de nota que sai do vault, inclusive atalho que aponta para fora.
- Ctrl+C e saída da bandeja: painel, descarga do contexto e processos do Claude e do ffmpeg.
- Prazo do fluxo do Claude, do fluxo do Ollama e da transcrição.

## O que apareceu

- A trava antiga era roubada depois de 30 segundos mesmo com o processo vivo. O git pode passar de 30 segundos, então duas operações se cruzavam.
- Estado, contexto, memória, índice, pedidos, revisão, token e Readwise gravavam sem troca atômica, ou com trava que outro processo podia tomar.
- A escrita de nota e o git não compartilhavam uma fila.
- `mark_task`, lembretes e o status da caixa de entrada validavam o texto, mas o caminho podia sair do vault quando a raiz não era informada.
- No modo privado o diário e o log de pedidos ainda eram gravados. O Telegram ainda executava o comando e só escondia a resposta.
- O resumo de domingo e o briefing marcavam o envio mesmo quando o modo privado engolia o Telegram.
- Falha ao ler o estado do remoto era tratada como remoto ligado.
- O fluxo do Claude e a transcrição não tinham prazo. O fluxo do Ollama tinha prazo no soquete, mas não no tempo total. Um processo do Claude ou do ffmpeg podia ficar órfão no Ctrl+C.

## O que foi corrigido

- Trava com pid: processo vivo não perde a trava. Processo morto libera. A gravação usa um arquivo temporário no mesmo diretório e `os.replace`, com nova tentativa no Windows.
- Uma fila só (`vault-escrita.lock`) para git e escrita de nota. Se a fila estoura o prazo, o git responde ocupado e não altera o vault.
- A raiz do vault acompanha as escritas de nota, tarefa, lembrete e caixa de entrada.
- Modo privado não grava diário nem pedido e não executa comando no Telegram, fora a frase de sair.
- Resumo e briefing só marcam o envio quando o Telegram confirma.
- Remoto fechado se o estado não puder ser lido.
- O encerramento para o painel, grava o contexto, sincroniza os JSON e mata os processos rastreados, além de ffmpeg e claude que ficaram filhos.
- Prazo no fluxo do Claude, no fluxo do Ollama e na transcrição.

Os regressos estão em `tests/test_auditoria.py`. A suíte local passou em 333 testes e o `ruff check .` ficou limpo.

## Estabilização de 11 de novembro de 2026

Base conferida: `4611d4f` (versão 0.28.0, PRs #2 a #29 já em `main`). Esta nota não contém conteúdo de vault. Os testes usam só texto sintético.

### O que foi conferido

Código novo desde 0.25.0: atualização, relatório, ligação de notas, lembretes, metas, explicação, pergunta socrática, revisão semanal, painel de progresso e exportação para o Anki.

- Fila única de escrita do vault e leitura fora dessa fila.
- `#sigiloso`, pasta privada e modo privado no painel, no Telegram, na exportação, nas contagens e no log.
- `--saida` da exportação, inclusive atalho, nome de dispositivo e caractere de controle.
- Token do painel nas rotas novas.
- Prazo da chamada local ao cérebro quando a resposta chega aos poucos.
- UTF-8 com BOM, CRLF e caminho longo no Windows.
- Modos de vários turnos: cancelar, prazo, troca de modo e `nova conversa`.

### O que apareceu

- Um arquivo com BOM do Bloco de Notas escondia `#sigiloso` e a tag no frontmatter. A nota podia aparecer no painel, na exportação e nas contagens.
- Ligar notas e gravar rascunho de lacuna liam o arquivo antes de entrar na fila. Uma nota que ganhava `#sigiloso` enquanto esperava podia ser alterada, e o título privado podia ir para uma nota pública.
- `--saida` absoluto ganhava `.txt` depois da checagem. Um atalho com esse nome final, apontando para dentro do vault, passava. Nome de dispositivo, caractere de controle e componente longo demais também passavam.
- A chamada local sem fluxo tinha prazo só no soquete. Um byte de vez em quando renovava a espera.
- `cancela` e `para` viravam resposta do modo. O teste gravado em disco voltava depois de `nova conversa` e depois de outro modo. Sem prazo, uma confirmação antiga aceitava a frase seguinte.
- `para a revisão` e `acertei` derrubavam explicação ou teste e caíam na revisão espaçada.
- `JARVIS_TOQUE_SEQUENCIA` estava no catálogo e no README, mas não no diagnóstico.

O painel já conferia o token em `/progresso` e `/progresso.json`. Não havia rota nova sem essa checagem.

### O que foi corrigido

- A leitura tira o BOM e a tag é procurada com quebra de linha normalizada. Codificação inválida continua de fora, sem chute de página.
- Ligar notas e gravar rascunho releem dentro da fila. Nota que ficou sigilosa não é alterada.
- A exportação coloca a extensão antes da checagem, recusa atalho, nome de dispositivo, caractere de controle e componente longo. Caminho longo no Windows usa o prefixo estendido na gravação atômica.
- A chamada local respeita o prazo total.
- `cancela` e `para` encerram o modo. `nova conversa` também. `JARVIS_MODO_PRAZO` vale 1800 segundos, entre 60 e 7200. Depois do prazo, resposta e nota de revisão não entram. Outro comando segue, já sem o modo antigo.
- `para a revisão` só pausa a revisão espaçada. `acertei` no teste é a resposta do teste. Na explicação, essa palavra não vira nota da revisão.
- O diagnóstico mostra o toque da sequência e o prazo do modo. O catálogo, o exemplo de ambiente, a ajuda e o README trazem o ajuste. O script do Windows faz smoke de versão, ajuda e classificação, sem ler nota e sem exportar.

Os regressos estão em `tests/test_estabilidade.py`. A suíte local passou em 372 testes e o `ruff check jarvis tests` ficou limpo.

## Estabilização de 11 de novembro de 2026, versão 0.33.1

Base conferida: `4599964` (versão 0.33.0, PRs #2 a #34 já em `main`). Esta nota não contém conteúdo de vault. Os testes usam só texto sintético.

### O que foi conferido

Código novo desde 0.29.0: importação de destaques (Kindle, PDF, KOReader), nota de estudo de vídeo e áudio, fila de mídia, busca semântica, resposta do que as notas dizem e sessão de estudo.

- Arquivo de entrada malformado: recorte sem meta, bookmark com nulo, PDF com milhares de páginas, anotação em bytes, Lua fundo demais e número enorme, `links.txt` com senha, esquema estranho, host bloqueado e linha longa.
- Prazo da transcrição, tamanho do trecho, stdin do ffmpeg e caminho longo no Windows.
- Segunda importação depois de falha no meio e trava com pid morto.
- `#sigiloso` com BOM e quebra do Windows no meio do embedding e na resposta fundamentada.
- Pedido escondido na transcrição e no destaque, dentro do bloco não confiável.
- Sessão contra explicação, pergunta socrática, revisão semanal, teste e confirmação. `cancela`, `para` e o prazo do modo. Reinício antes do sim.
- Registro de comandos, catálogo, exemplo de ambiente, diagnóstico e o script do Windows.

### O que apareceu

- Com a sessão em andamento, a frase de explicação, da revisão semanal, do teste e o sim de uma confirmação viravam silêncio da sessão. O outro modo era descartado.
- Se o processo reiniciava com a pergunta do recap no sim, a frase estava só na memória. O sim seguinte dizia que a frase não servia e não havia como gravar.
- Um PDF que anunciava páginas demais era percorrido. Anotação em bytes ia para a nota como representação de bytes. Número Lua com dezenas de dígitos era convertido. Arquivo UTF-16 do Bloco de Notas falhava como codificação.
- URL com espaço, barra invertida, caractere de controle ou senha podia seguir. A transcrição não tinha prazo de rede e um pedaço enorme entrava inteiro.
- O ffmpeg da nota de áudio lia o stdin e, no diagnóstico do Telegram, `ffmpeg.exe` não contava.
- Uma nota que ganhava `#sigiloso` enquanto o vetor era calculado podia ficar no índice. A resposta fundamentada usava o trecho já carregado, sem reler o arquivo.

A fila única, a trava com pid morto e o histórico da sessão (só tema, duração e horários) já se comportavam como o previsto. O catálogo, o `.env.exemplo`, o README e a ajuda já listavam os ajustes e os comandos novos.

### O que foi corrigido

- Enquanto outro modo tem a palavra, a sessão não toma a frase. `quanto falta`, `pausa` e `continua a sessão` respondem e deixam o modo. `cancela` ou `para` encerra o modo da vez. Sem modo, encerram a sessão. `nova conversa` encerra os dois. O relógio da sessão não usa `JARVIS_MODO_PRAZO`. O prazo continua valendo para a revisão semanal e para a explicação.
- Sem a frase na memória, o sim pede de novo e não grava. A frase não entra em `sessao-estudo.json` nem em `sessoes.json`.
- PDF acima de 2500 páginas ou de 4000 anotações para. Conteúdo em bytes é decodificado e cortado. Lua recusa número com mais de 18 caracteres e tabela funda demais. Kindle, KOReader e `links.txt` leem UTF-16 com BOM. Atalho é recusado. A importação que falha no segundo livro deixa o primeiro. A repetição não duplica. Trava com pid 0 é tratada como morta.
- URL longa, com controle, barra invertida ou credencial não entra. A busca da transcrição tem prazo. Cada pedaço e o total são cortados.
- O ffmpeg usa `-nostdin` e não lê o teclado. Caminho longo no Windows ganha o prefixo estendido. O diagnóstico aceita `ffmpeg.exe`.
- O índice relê a nota antes de gravar o vetor. A resposta do que as notas dizem também relê. Nota que ficou sigilosa sai dos dois. O texto não vai para o log.

Os regressos estão em `tests/test_estabilizacao.py` e em `tests/test_sessao.py`. O script `scripts/testar-windows.ps1` faz smoke de `destaques --help` e classifica importa destaques, pausa e continua a sessão. A suíte local rodou 427 testes, com 1 ignorado, e o `ruff check .` ficou limpo.
