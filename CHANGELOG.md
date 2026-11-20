# Changelog

Registro das entregas do Jarvis, em português. Este arquivo não traz conteúdo de nota.
A atualização do código resume o que mudou a partir daqui.

## 0.34.0

As três propostas que tinham ficado de fora da 0.33.2. Medidas num vault local grande, fora deste repositório, só com contagens e tempos.

- A primeira busca depois de abrir o Jarvis cai de cerca de 34 segundos para cerca de 7. Cada busca seguinte cai de cerca de 1,7 segundo para 0,8. A ordem dos resultados é a mesma: 26 consultas conferidas, com e sem erro de digitação.
- O que mudou por baixo: o catálogo lê a nota e deixa o preparo da busca para quando ele é pedido. Os dois filtros que percorriam todas as palavras de todas as notas agora olham o texto já dobrado. Os n-gramas de uma nota só são calculados quando ela passa pelo filtro, e com numpy o cálculo é vetorizado. A dobra de acento trata só o trecho fora do ASCII. A checagem de sigilo roda uma vez por nota, não duas.
- Nada disso grava texto de nota em `~/.jarvis`. Guardar o catálogo em disco foi descartado por isso: os tokens são o texto.
- `JARVIS_PASTAS_IGNORADAS` tira pastas da busca, dos cartões, das tarefas e dos lembretes. Vale o nome da pasta em qualquer nível, como nas pastas privadas. Não é sigilo: o Claude continua lendo essas pastas, e nota `#sigiloso` dentro delas continua negada. O diagnóstico mostra quantas notas ficaram de fora. Não ponha na lista uma pasta em que o Jarvis grava, como a da nota diária.
- Na nota diária, uma linha que começa com a hora é anotação e não entra em `o que tenho hoje`, na agenda do bom dia nem no amanhã do resumo do dia. Antes o `anota` aparecia como compromisso no horário em que foi anotado. No bom dia do mesmo dia a anotação ainda aparece em Pendências. Lembrete com data e linha com data continuam entrando. No arquivo do dia dentro da pasta da agenda, a hora solta continua valendo como compromisso.

## 0.33.2

Primeira execução fora da máquina dos agentes: macOS, Python 3.13, Claude Code de verdade e contagens de um vault local grande, fora deste repositório.

- Nota com `#sigiloso` e pasta privada saem também da busca e da listagem do Claude Code. Antes só a leitura direta era barrada, e a busca por texto devolvia a linha da nota. O arquivo de configuração de cada turno leva regras de negação por nota e por pasta, que o Read, o Grep e o Glob obedecem. Pasta e arquivo ocultos do vault, como `.trash` e `.claude`, ficam de fora da nuvem. Se a lista não puder ser montada, o turno fecha a leitura.
- A tag no fim de uma nota longa passa a contar. Antes só os primeiros 20 mil caracteres eram olhados na guarda, e 80 mil no catálogo. Nota em UTF-16 do Bloco de Notas também conta.
- A lista de notas sigilosas relê só a nota que mudou e fica em `~/.jarvis/sigilo.json`, com hash do caminho, tamanho e data. Não guarda título nem texto.
- O teto de notas sobe de 5.000 para 50.000. Um vault acima do teto antigo perdia notas na busca, nos cartões e nos lembretes, sem aviso. O diagnóstico mostra quantas notas estão ao alcance e avisa acima do teto.
- Lembrete vencido, lembrete aberto, tarefa e resumo da semana releem só a nota que mudou. Antes o laço de lembretes lia o vault inteiro a cada 15 segundos.
- A busca funciona sem numpy, com a mesma ordem. Antes o modo texto respondia que faltava dependência.
- Número mal digitado no arquivo de ambiente cai no padrão e aparece no diagnóstico. Vírgula decimal é aceita. Antes `JARVIS_SILENCE_THRESHOLD=0,012` derrubava tudo, inclusive o diagnóstico.
- O pull só guarda as notas abertas no stash quando o que chega do GitHub mexe no mesmo arquivo. Sem nada para puxar, o git não toca na pasta. Antes todo pedido guardava e devolvia tudo.
- A suíte roda com casa, arquivo de ambiente e git próprios. Antes um teste gravava no `~/.jarvis` real, e o `~/.jarvis/.env` real entrava no ambiente dos testes. Testes que dependiam da data de hoje, do Linux, do numpy instalado e da configuração global do git foram corrigidos.

## 0.33.1

- Durante a sessão de estudo, explicação, pergunta socrática, revisão semanal, teste e confirmação seguem valendo. A sessão não toma a frase desses modos. `quanto falta`, `pausa` e `continua a sessão` respondem sem derrubar o modo. `cancela` ou `para` encerra o modo da vez. Uma segunda vez encerra a sessão. `nova conversa` encerra os dois.
- Se o Jarvis reinicia antes do sim, a frase do recap não fica gravada. Ele pede de novo. O histórico continua só com tema, duração e horários.
- Kindle, PDF, KOReader e `links.txt` aceitam UTF-16 com BOM, do Bloco de Notas. PDF com páginas demais, anotação em bytes ou número enorme no Lua é recusado. A transcrição longa é cortada e a busca do YouTube tem prazo. O ffmpeg não espera o teclado e, no Windows, caminho longo usa o prefixo estendido. `ffmpeg.exe` entra no diagnóstico.
- Uma nota que ganha `#sigiloso` no meio do embedding, inclusive com BOM ou quebra do Windows, sai do índice. A resposta do que as notas dizem relê o arquivo e não cita nota que ficou sigilosa. O modo privado não envia.

## 0.33.0

- `começa uma sessão de estudo de N minutos sobre um tema` abre uma sessão no estilo Pomodoro. O padrão é 25 minutos. `JARVIS_SESSAO_PAUSA` é a pausa, com padrão de 5 minutos. 0 desliga a pausa. A fala anuncia o começo e fica quieta até o fim. A palavra de ativação continua valendo para `quanto falta?`, `pausa`, `continua a sessão` e `encerra a sessão`.
- No fim, a voz e a bandeja avisam. `JARVIS_SESSAO_TELEGRAM` fica desligado. Com `on`, o Telegram recebe só o tempo e o tema, sem texto de nota e sem o que você aprendeu. O modo privado não envia.
- A sessão pergunta `o que você aprendeu?`. Depois do sim, anexa uma linha curta na nota do tema ou na nota do dia (`JARVIS_SESSAO_NOTA`) e oferece um cartão em rascunho. `revisa rascunhos` confere. `cancela` ou `para` encerra sem gravar. A pergunta segue `JARVIS_MODO_PRAZO`. O relógio da sessão segue os minutos pedidos.
- O registro fica em `~/.jarvis` e guarda tema, duração e horários. Não guarda o texto. A página Progresso mostra os minutos do dia, da semana, por tema e por meta. `quanto estudei essa semana?` e a revisão semanal usam esses minutos. Um dia com sessão entra na sequência.
- `JARVIS_SESSAO_SILENCIO` fica ligado. Enquanto a sessão ou a pausa corre, briefing, lembrete e resumo esperam o fim. Nota com `#sigiloso`, inclusive com BOM ou quebra do Windows, e pasta privada não são alteradas.

## 0.32.0

- `JARVIS_BUSCA` fica em `palavras`. Com `semantica` ou `hibrida`, o Jarvis monta um índice de embeddings só nesta máquina, partido por título, e grava em `~/.jarvis`. O texto da nota não entra no arquivo e não é enviado. Nota com `#sigiloso`, inclusive com BOM ou quebra do Windows, e pasta privada ficam de fora.
- O pacote opcional é `sentence-transformers`, com o modelo pequeno `paraphrase-multilingual-MiniLM-L12-v2`. Se `JARVIS_CEREBRO=ollama`, os embeddings saem do Ollama local. Sem o pacote e sem o Ollama, a fala avisa.
- `hibrida` junta a busca por palavra com a semelhança dos vetores. `semantica` usa só os vetores. O benchmark continua e passa a mostrar os tempos do índice semântico.
- `o que minhas notas dizem sobre` responde só com os trechos recuperados, citados como dado não confiável. A fala cita o título com `[[wikilink]]` e diz quando as notas não cobrem. Na voz a resposta é curta e oferece mandar as fontes no Telegram. No texto vêm as citações. As fontes são títulos. O modo privado não envia.
- `notas relacionadas` e `conecta ideias` usam esse índice quando a busca semântica está ligada.

## 0.31.0

- `resume esse vídeo` e `python -m jarvis video` leem a transcrição do YouTube com o pacote opcional youtube-transcript-api, em português e depois em inglês. A nota de estudo traz resumo, ideias com o tempo (o link volta ao vídeo), citações e perguntas. Uma nota por vídeo, em `JARVIS_ESTUDO_MIDIA_PASTA`. Rodar de novo não cria outra.
- `python -m jarvis audio` transcreve um arquivo local com o Whisper desta máquina. Áudio longo é cortado em trechos com o ffmpeg, e o andamento aparece na saída. O áudio não sai da máquina.
- `JARVIS_MIDIA_ENTRADA` recebe áudios e um `links.txt`. `processa minha fila de mídia` pede confirmação antes de gravar.
- Depois de cada nota, o Jarvis oferece cartões em rascunho e ligações com notas que já existem. A sugestão traz só títulos. Gravar pede confirmação.
- Sem o pacote, ou sem transcrição em português nem inglês, a fala avisa e não grava. Nota com `#sigiloso`, inclusive com BOM ou quebra do Windows, e pasta privada não são alteradas. A transcrição entra no cérebro como dado não confiável. O modo privado não manda isso para a nuvem. O log não leva o texto.

## 0.30.0

- `python -m jarvis destaques kindle` lê o My Clippings do Kindle, em português e em inglês. Marcador fica de fora. BOM e quebra do Windows entram. Edições do mesmo título e autor viram uma nota só.
- `python -m jarvis destaques pdf` lê destaque, sublinhado e nota, com o número da página. Sem o pacote opcional pypdf, avisa e não grava.
- `python -m jarvis destaques koreader` lê o sidecar `metadata.*.lua` e a exportação em JSON ou Markdown.
- `importa destaques` e `importa destaques do kindle` usam `JARVIS_DESTAQUES_ENTRADA` e pedem confirmação antes de gravar. A fala traz a contagem de livros e de destaques novos. O log não leva o texto.
- Depois da importação, o Jarvis oferece cartões em rascunho para os destaques novos. `revisa rascunhos` confere.
- Nota com `#sigiloso`, inclusive com BOM ou quebra do Windows, e pasta privada não são alteradas. O modo privado não manda isso para fora.

## 0.29.0

- `cancela` ou `para` encerra explicação, pergunta socrática, revisão semanal, teste falado e confirmação. `nova conversa` também encerra e não deixa o teste voltar no turno seguinte.
- `para a revisão` pausa a revisão espaçada e não encerra explicação nem teste. `acertei` durante o teste vale como resposta do teste. Durante a explicação, a mesma palavra não vira nota da revisão.
- `JARVIS_MODO_PRAZO` vale 1800 segundos. Depois disso o modo encerra e a frase seguinte não vira resposta.
- Nota com BOM do Bloco de Notas continua sigilosa. A exportação do Anki recusa caminho com atalho, nome de dispositivo, caractere de controle ou componente longo demais.
- Ligar notas e gravar rascunho de lacuna releem o arquivo dentro da fila de escrita. Se a nota virou sigilosa nesse intervalo, ela não é alterada.
- O diagnóstico mostra o toque da sequência e o prazo do modo. A chamada local ao cérebro respeita o prazo total, mesmo quando a resposta chega aos poucos.

## 0.28.0

- A página Progresso do painel local mostra cartões de hoje e da semana, a sequência, a tendência de acerto, as notas criadas por semana, as metas de estudo e o foco da última revisão semanal. Entram contagens e títulos. O texto da nota fica de fora. Nota com `#sigiloso` ou em pasta privada não aparece.
- `quanto estudei essa semana?` e `qual minha sequência?` respondem com esses mesmos números.
- `python -m jarvis anki exportar` conta os cartões públicos. Com `--saida` grava um texto separado por tabulação (frente, verso, etiquetas) para o Anki importar. `--tema` filtra. Sem `--saida` nada é gravado.
- `exporta meus cartões` pede confirmação e salva em `~/.jarvis/exportacoes`. O arquivo não entra no vault e não é enviado a lugar nenhum.
- `JARVIS_TOQUE_SEQUENCIA` fica desligado. Com `on`, o Telegram avisa à noite se não houve revisão no dia. Não leva texto de nota. O modo privado não envia.

## 0.27.0

- `me deixa explicar` pede a explicação com palavras simples, compara com as notas e os cartões pelo cérebro e aponta lacuna, erro e jargão. As notas entram como dado não confiável. O cartão da lacuna fica em rascunho. `revisa rascunhos` confere.
- `me pergunta sobre` faz perguntas de por que e de como, uma por vez, a partir das notas. No fim, resume os pontos fracos e liga com a meta de `quero aprender` quando o tema casa.
- `revisão semanal` conduz quatro perguntas, mostra o contexto da semana e, depois da confirmação, grava `revisao-semanal-AAAA-Www.md`. O foco da próxima semana entra no foco do dia.
- `JARVIS_REVISAO_SEMANAL` fica desligado. Com `on`, o Telegram lembra no domingo de começar a revisão. Não manda texto de nota. O modo privado não envia.
- `JARVIS_REVISAO_SEMANAL_PASTA` escolhe a pasta da nota. O padrão é `Diario/Revisao`.
- Nota com `#sigiloso` ou em pasta privada fica de fora da comparação, do contexto e do Telegram.

## 0.26.0

- `conecta ideias` acha notas de fontes diferentes sobre o mesmo assunto no índice de embeddings e sugere um mapa só com títulos. Gravar o mapa ou ligar as notas pede confirmação e passa pela validação da escrita.
- `me lembra algo` traz o título de uma nota antiga e um ponto que você escreveu, de preferência uma nota que faz tempo que não abre. Nota com `#sigiloso` ou em pasta privada fica de fora.
- `JARVIS_LEMBRETE_NOTA` fica desligado. Com `on`, o Telegram recebe esse lembrete uma vez por dia. O modo privado não envia.
- `quero aprender` guarda a meta em `~/.jarvis`. Mostra notas, cartões e fontes que já existem, aponta lacunas por subtema e monta um plano da semana com esse material.
- `JARVIS_METAS_VAULT` fica desligado. Com `on`, a meta também vira nota no vault, depois da validação da escrita.
- `como estou em` conta acertos, lapsos e vencimentos da revisão espaçada nos cartões do tema.
- Para uma lacuna, o Jarvis sugere livro, curso ou vídeo em texto. Não busca na rede.

## 0.25.0

- A versão aparece em `python -m jarvis --versao`, no diagnóstico, no painel e na pergunta "qual sua versão?".
- `python -m jarvis atualizar` e o pedido "se atualiza" puxam só o clone do Jarvis, com confirmação na voz e no Telegram. O pull é `--ff-only`. Não há força e o vault fica de fora.
- `python -m jarvis relatorio` grava um zip na pasta do usuário com diagnóstico, versão, nomes de configuração e linhas de log sem texto.
- `scripts/testar-windows.ps1` roda a suíte, o diagnóstico e o benchmark no Windows.

## Vault e notas

- PR #2: integra o Jarvis ao vault do Obsidian.
- PR #7: facilita o primeiro teste, avisa o que mudou e cita o caminho da nota.
- PR #8: guarda foto ou link.
- PR #14: confirma destino ambíguo e valida a escrita.
- PR #15: importa destaques do Readwise para o vault local.
- PR #22: grava resumo de vídeo, artigo e podcast.

## Agenda, lembretes e o dia

- PR #5: avisa lembretes que se repetem e resume a caixa sem microfone.
- PR #6: inclui a agenda do dia, adiar ou cancelar lembrete e o resumo de domingo.
- PR #8: responde as prioridades do dia e lembra o pedido de ontem.
- PR #10: detalha o fim do dia e lista os pedidos.
- PR #17: adiciona o bom dia.

## Voz, texto e painel

- PR #3: adiciona instalador guiado e início automático no login.
- PR #4: abre o Jarvis por texto, Telegram e check-ins do dia.
- PR #9: corrige a instalação da palavra de ativação no Python 3.13 e o relatório do diagnóstico.
- PR #10: responde sem o Claude no PATH.
- PR #17: adiciona o resumo do painel.
- PR #19: mantém o contexto recente, interrompe a fala e reembute só o que mudou.

## Estudo e revisão

- PR #12: adiciona revisão espaçada e controle dos avisos.
- PR #13: adiciona busca híbrida e avaliação.
- PR #17: adiciona teste falado e notas relacionadas.
- PR #22: revisa os cartões em rascunho.
- PR #23: limita a revisão no primeiro uso de um vault grande.

## Memória e cérebro

- PR #14: mostra a memória local.
- PR #16: carrega a persona do vault, responde no Ollama e resume a semana no Telegram.
- PR #19: guarda o contexto recente fora da nota.

## Integrações somente leitura

- PR #5: resume a caixa sem microfone. Gmail continua só leitura. O Jarvis não envia e-mail.
- PR #8 e PR #10: Jira e GitHub entram na leitura do dia e na lista de pedidos. Não há escrita nesses serviços.
- PR #15: o Readwise só baixa destaque.

## Telegram

- PR #4: abre o canal de texto e os check-ins.
- PR #16: manda o resumo da semana.
- PR #24: abre o Telegram como remoto e encolhe o catálogo na memória.

## Privacidade

- PR #13: bloqueia escrita quando o vault não aceita.
- PR #20: impede nota sigilosa de sair da máquina e adiciona o modo privado.
- PR #25: fecha furos de sigilo.

## Consulta

- PR #11: adiciona a consulta somente leitura do vault para o Android.

## Diagnóstico, instalação e escala

- PR #9: acerta o relatório do diagnóstico.
- PR #18: adiciona CI, setup de um comando e checklist do diagnóstico.
- PR #21: reúne comandos e configuração num só lugar e reescreve o guia.
- PR #23: prepara o primeiro uso para um vault grande, com medição e assistente.

## Concorrência

- PR #25: fecha corridas de escrita e encerra processos que ficaram abertos. A fila de escrita do vault é uma só.
