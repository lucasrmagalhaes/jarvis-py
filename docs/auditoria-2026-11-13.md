# Primeira execução no Mac, 13 de novembro de 2026

Base conferida: `f54bf28` (versão 0.33.1, PRs #2 a #35 já em `main`).

Esta nota não contém conteúdo de vault. Os testes usam só texto sintético. As medições em vault real trazem só contagens e tempos.

Até aqui o código só tinha rodado na máquina dos agentes: Linux, com numpy instalado e sem o Claude Code. Esta rodada foi a primeira no macOS, com Python 3.13.9 e o Claude Code 2.1.323 de verdade.

## Como foi conferido

- A suíte inteira no macOS, só com o `requirements-dev.txt`, que é o que o CI instala.
- O modo texto contra o Claude Code real, num vault sintético com remoto git local: leitura de nota, criação de nota com commit e push, pedido de edição em `.obsidian`, pergunta sobre nota sigilosa, resposta em fluxo e continuação da sessão.
- O hook da guarda chamado direto, com os dados que o Claude Code envia.
- Contagens e tempos, só leitura, num vault local grande que não faz parte deste repositório.
- A suíte em três datas futuras, para achar teste que depende do dia. Com a data adiantada, um teste de concorrência do estado falhou uma vez em três rodadas. A trava mede a idade do arquivo ainda vazio pelo relógio, e a ferramenta adianta o relógio sem mudar a data do arquivo. Com o relógio real o mesmo teste passou 30 vezes seguidas. Outro teste compara a data de arquivo recém-criado com o relógio e só falha pela mesma razão.

## O que apareceu

- A suíte tinha 17 testes quebrados de 427. Doze por falta do numpy, que o CI não instala. Um dependia da data de hoje e passou a falhar em 13 de novembro. Os outros dependiam do Linux, da configuração global do git e do caminho temporário sem atalho.
- Um teste gravava contexto e log no `~/.jarvis` real. Numa máquina já configurada, o `~/.jarvis/.env` real entrava no ambiente da suíte, com token, vault e Telegram.
- A leitura direta de nota `#sigiloso` era barrada, mas a busca por texto do Claude Code devolvia a linha da nota. O próprio Claude relatou a brecha no teste. A listagem também mostrava o título.
- A guarda olhava só os primeiros 20 mil caracteres para achar a tag. Nota longa com a tag no fim passava como pública. No catálogo o corte era de 80 mil.
- A busca do Claude Code entra em pasta oculta. Cópia de nota sigilosa em `.trash` ou em `.claude` ficava ao alcance.
- O teto de 5.000 notas cortava um vault grande em silêncio: o que passava do teto ficava fora da busca, dos cartões e dos lembretes.
- O laço de lembretes lia o vault inteiro a cada 15 segundos. Num vault grande cada passada levava alguns segundos.
- Sem numpy, a busca do modo texto respondia que faltava dependência e mandava usar o modo texto.
- Um número mal digitado no arquivo de ambiente, como `0,012` ou `5min`, derrubava tudo na importação, inclusive o diagnóstico. Onze ajustes tinham esse problema.
- Todo pedido guardava as notas abertas num stash antes de consultar a rede e devolvia depois, mesmo sem nada para puxar. Num vault em uso, com dezenas de notas abertas e outros programas gravando, isso tira as notas da pasta por alguns segundos a cada pedido.
- O hook do repositório chamava `python`, que não existe no macOS sem ambiente virtual. A guarda de quem desenvolve falhava sem bloquear.
- No macOS o diagnóstico falava da voz do Windows.

O cérebro em si funcionou de primeira: `--settings`, `--append-system-prompt-file`, saída em json e em fluxo, `--resume` e o hook de escrita.

## O que foi corrigido

- O arquivo de configuração de cada turno leva regras de negação de leitura por nota sigilosa, por pasta privada e para pasta e arquivo ocultos. O Read, o Grep e o Glob do Claude Code obedecem. Conferido com o Claude real: a busca pelas palavras da nota volta vazia e a listagem não mostra o título. Nome com parêntese, colchete ou chave vira curinga na regra. Acima de 300 notas a regra passa a ser por pasta. Se a lista falhar, o turno fecha a leitura.
- A tag é procurada na nota inteira, inclusive em UTF-16. O catálogo marca a nota antes de cortar o texto.
- A lista de notas sigilosas relê só o que mudou e guarda em `~/.jarvis/sigilo.json` o hash do caminho, o tamanho e a data. A redação do Telegram e da nuvem usa essa lista em vez de ler todas as notas a cada pedido. Num vault grande a primeira passada é mais lenta que as seguintes, inclusive num processo novo.
- O teto de notas é 50.000. O catálogo registra quando o teto corta. O diagnóstico mostra a contagem e avisa acima do teto.
- Lembrete vencido, lembrete aberto, tarefa e resumo da semana guardam só as linhas de caixa de cada nota e releem a nota que mudou. Nota gravada há menos de 2 segundos não entra nesse cache nem no da lista de sigilo, para um disco com data grossa não esconder uma troca do mesmo tamanho.
- A ordenação por grafia cai para o cosseno puro quando o numpy falta. O `requirements-dev.txt` passa a instalar o numpy, e a suíte confere os dois caminhos.
- Os onze números caem no padrão quando o valor não serve, aceitam vírgula decimal e aparecem no diagnóstico pelo nome, sem o valor.
- O pull tenta o fast-forward com as notas abertas na pasta. Só guarda no stash se o git recusar por causa de um arquivo aberto, ou quando os dois lados têm commits. Sem nada para puxar, não há stash.
- A suíte cria casa, arquivo de ambiente e configuração de git próprios antes de importar o Jarvis, e tira do ambiente as variáveis `JARVIS_`, `JIRA_`, `GMAIL_`, `TELEGRAM_` e `READWISE_`.
- Os testes do painel fixam o relógio. Dois deles quebrariam em 16 de novembro e no fim de dezembro.
- O hook do repositório procura `python3`, `python` e `py`.

Os regressos estão em `tests/test_sigilo_no_claude.py`, `tests/test_vault_grande.py`, `tests/test_ajustes_numericos.py`, `tests/test_busca.py` e `tests/test_vault.py`.

## O que ficou de fora

- A regra por nota cobre arquivo `.md`. Outro tipo de arquivo com a tag só é barrado na leitura direta. Pasta privada cobre qualquer tipo.
- A lista de sigilo é conferida duas vezes por pedido ao Claude. Num vault grande isso pesa.
- O primeiro índice, as pastas ignoradas e a linha de `anota` lida como compromisso entraram na versão 0.34.0, descrita no fim desta nota.
- O CI não cobre o macOS. A validação no Windows deste relato ficou pendente.
- A rodada 36 (dia de trabalho, versão 0.34.0) não deixou branch nem PR. Por isso esta versão é 0.33.2.

## Versão 0.34.0, no mesmo dia

Base conferida: `425bb6e` (versão 0.33.2). As medições são de um vault local grande, fora deste repositório, só com contagens, tempos e resumo criptográfico da ordem dos resultados.

### Primeira busca e cada busca

O perfil da 0.33.2 mostrou dois custos. No primeiro índice, mais da metade do tempo ia no cálculo de n-gramas de todas as notas. Em cada busca, dois filtros percorriam em Python todas as palavras de todas as notas.

A primeira tentativa só adiou os n-gramas para a busca. Não resolveu: em 26 consultas, a maior parte das notas ainda passava pelo filtro e pagava o cálculo. O ganho veio de trocar os filtros por varredura no texto dobrado, vetorizar os n-gramas com numpy, dobrar só o trecho fora do ASCII, checar o sigilo uma vez por nota e deixar tokens e tags para quando são pedidos.

Medição em sequência, duas rodadas de cada, na mesma máquina:

| | 0.33.2 | 0.34.0 |
|---|---|---|
| Primeira busca | 33,5 e 35,6 s | 8,0 e 6,4 s |
| 26 buscas seguintes | 37,7 e 45,3 s | 27,3 e 30,4 s |
| As mesmas 26, já aquecido | 62,2 e 41,6 s | 21,8 e 21,8 s |
| Memória no pico | 309 e 338 MB | 316 e 319 MB |

A ordem dos resultados é idêntica nas 26 consultas, que incluem palavra com erro de digitação, expressão de duas palavras e termo que não existe. A dobra nova foi comparada com a antiga em todos os pontos de código. Os filtros novos e os n-gramas com numpy têm teste de equivalência com os antigos.

A memória não caiu: depois de dezenas de consultas quase toda nota já tem tokens e n-gramas. O que resta do tempo da primeira busca é leitura de arquivo, cerca de 5 segundos nesta máquina.

Guardar o catálogo em disco foi descartado. Os tokens da busca são o texto da nota, e a regra do projeto é não gravar texto de nota em `~/.jarvis`.

### Pastas ignoradas

`JARVIS_PASTAS_IGNORADAS` sai da varredura das rotinas: busca, cartões, tarefas, lembretes e resumo da semana. A lista de notas sigilosas não usa esse filtro, e há teste para a nota `#sigiloso` dentro de pasta ignorada continuar com regra de negação. O ajuste não é escrito no arquivo de ambiente de ninguém: quais pastas ignorar é escolha do dono do vault.

### Anotação e compromisso

A nota diária é lida sem a regra de hora solta. A suíte inteira passou com a regra ligada, sem teste antigo quebrado: nenhum teste dependia de hora solta na nota diária virar compromisso.

### O que apareceu e não foi mexido

- No bom dia do mesmo dia, a anotação ainda aparece em Pendências, que lista os itens da nota de hoje. A agenda do bom dia ficou certa.
- `anota em` e a escolha da pasta da nota diária usam a mesma varredura das rotinas. Uma pasta ignorada some para as duas, então a lista não deve ter pasta em que o Jarvis grava.
- A pasta padrão da agenda é `Agenda Profissional`. Num vault em que esse é o nome de um projeto, as notas do projeto são lidas como agenda. Só uma nota de 56 tinha data no cabeçalho, então hoje o efeito é pequeno.
- Sem linha de nota diária no `AGENTS.md`, sem configuração do Obsidian e sem nota com nome de data, o `anota` cria `AAAA-MM-DD.md` na raiz do vault.
- A linha do `AGENTS.md` que declara um lugar vale pelo rótulo em qualquer ponto da linha, inclusive dentro do caminho entre crases. Um caminho que contém `Agenda Profissional` declara a agenda sem querer.

Os três últimos pedem uma decisão do dono do vault sobre onde ficam a agenda e a nota diária.
