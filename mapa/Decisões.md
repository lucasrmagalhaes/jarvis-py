---
tags:
  - decisões
---

# Decisões

Escolhas de arquitetura e o motivo de cada uma — o tipo de coisa que o código não conta.

## CLI headless em vez do Agent SDK

O Claude Agent SDK exige `ANTHROPIC_API_KEY` do Console, com cobrança por token, e a documentação é explícita: aplicações no SDK não podem usar login ou limites da assinatura claude.ai.

Chamar o `claude -p` do Claude Code já instalado reaproveita a sessão logada — **sem custo por token**. Menos flexível (orquestração por subprocesso em vez de biblioteca), mas é o que torna o projeto viável como assistente pessoal de uso contínuo.

Ver [[Cérebro]].

## Persona em arquivo, não em argumento

A personalidade começou em `--append-system-prompt`. No Windows, o `claude` instalado via npm é um shim `.cmd` que precisa ser invocado por `cmd /c` — e passar um texto longo por argumento nesse caminho é frágil.

A persona virou `workspace/CLAUDE.md`, que o Claude Code lê sozinho. Some o argumento gigante, e a personalidade fica editável sem mexer no código.

## Ferramentas somente leitura por padrão

Em modo headless **não existe prompt de confirmação**: o que estiver em `JARVIS_ALLOWED_TOOLS` executa sem supervisão. Como o Jarvis é acionado por voz — sujeito a erro de transcrição — o padrão é `Read,Glob,Grep,WebSearch,WebFetch`.

Liberar `Edit`, `Write` ou `Bash` é decisão consciente de quem configura.

## Token por execução no painel

Uma revisão de segurança mostrou que o painel, sem autenticação, permitia que **qualquer site aberto no navegador** enviasse comandos ao assistente (CSRF), e que DNS rebinding lesse o histórico de conversas.

Como o Jarvis lê arquivos locais e acessa a web, o risco era concreto. O token aleatório por execução resolve os dois: um atacante não consegue adivinhá-lo, e nem a página nem o fluxo de eventos abrem sem ele.

Custo aceito: a URL muda a cada execução e precisa vir do terminal.

Ver [[Painel HUD]].

## edge-tts como padrão no Windows

O SAPI é offline e sempre existe, mas soa robótico. As vozes neurais da Microsoft via `edge-tts` são gratuitas e muito melhores em pt-BR.

Padrão no Windows: `edge-tts`, com SAPI de reserva quando não há internet. No macOS a ordem se inverte — a Luciana nativa já é boa e não depende de rede.

Ver [[Voz]].

## Calibração de ruído em vez de limiar fixo

Um limiar fixo de silêncio quebrava nos dois extremos: em ambiente barulhento a gravação nunca terminava; em ambiente muito quieto cortava a fala cedo.

Agora os primeiros 300 ms medem o ruído ambiente e o limiar se ajusta. Ver [[Ouvidos]].

## Vault como diretório de trabalho

O vault pessoal já tem `AGENTS.md` e `CLAUDE.md` com as convenções das notas. Apontar o `JARVIS_WORKSPACE` para lá e continuar gravando a persona em `CLAUDE.md` apagaria essas convenções.

O `cwd` do Claude Code passa a ser o clone. Assim o `CLAUDE.md` do vault entra sozinho. A persona vai para um arquivo fora do vault (`--append-system-prompt-file`), no mesmo espírito de não passar texto longo por argumento no Windows.

Desde o Claude Code 2.1.277, um `CLAUDE.md` na pasta faz o `AGENTS.md` ser ignorado, a menos que seja importado. O Jarvis cola o `AGENTS.md` no prompt para as regras de pasta, frontmatter e link valerem mesmo assim. Em conflito de formato, vale o `AGENTS.md`.

O git não fica nas ferramentas do modelo. Um módulo em `jarvis/vault.py` faz fetch, fast-forward ou merge, commit e push. Conflito aborta o merge. Sem rede, o commit local fica. Não há `push --force`, rebase nem `reset --hard`. `Bash` continua desligado para um erro de transcrição não reescrever o histórico.

O `AGENTS.md` do vault pede para não versionar a pasta inteira: o Obsidian Git sincroniza o dia a dia, e um commit deve trazer só arquivos pertinentes. O Jarvis versiona a nota que o pedido acabou de criar ou editar. O que já estava modificado fica de fora. Na hora do pull, essas alterações ficam na pasta. Só vão para um stash, e voltam em seguida, quando o que chegou do GitHub mexe no mesmo arquivo ou quando os dois lados têm commits. Um vault em uso tem dezenas de notas abertas, e guardar tudo a cada pedido tirava essas notas da pasta enquanto a rede respondia. Se não couberem no que chegou, permanecem no stash. A persona vale para a fala. O texto da nota segue o vault: linguagem direta, YAML e links preservados, sem o tratamento de senhor.

Briefing, captura com "anota", busca com "o que eu escrevi sobre", agenda com "o que tenho hoje" e lembretes com "me lembra" rodam no Jarvis, sem passar pelo Claude. Assim a nota diária, o horário e a citação da nota de origem ficam estáveis. Na nota diária, a linha que começa com a hora é anotação, não compromisso: o `anota` grava a hora em que a frase foi dita, e a agenda lia essa hora como horário marcado. Compromisso com hora solta vale no arquivo do dia dentro da pasta da agenda. O lugar da nota diária, da agenda e dos lembretes é lido do clone: uma linha do AGENTS.md, do CLAUDE.md ou do README.md com o caminho entre crases. Se a nota diária não estiver lá, vale a configuração do Obsidian e, por fim, um arquivo AAAA-MM-DD.md na raiz. A agenda do briefing usa a pasta ou a nota indicada, no padrão `Agenda Profissional`: arquivo do dia, frontmatter `data` e `hora`, linha com data e lembrete daquele dia. O lembrete fica numa tarefa markdown. Enquanto o processo está aberto, um laço avisa por voz, no HUD e no Telegram. O aviso de um horário único fica marcado na nota e sobrevive a reinício. Um lembrete com "todo dia", "nos dias úteis" ou "toda segunda" guarda `@repete` e, depois do aviso, avança a data em vez de encerrar. "Adia o lembrete" troca o horário e tira `@avisado`. "Cancela o lembrete" grava `[x]` e `@cancelado`, então o que se repete também para. "Resume os recados" lê `novo` e `avisado` sem gravar. "O que os assistentes mandaram?" continua marcando `lido`. O HUD mostra o último sync e quantos commits ainda não foram enviados.

A conversa continua por alguns segundos depois da resposta, sem um novo "Hey Jarvis". "Valeu, Jarvis" volta ao standby. "Jarvis, para" ou a palavra de ativação cortam a fala. As últimas trocas da sessão acompanham o pedido seguinte, só enquanto o processo está aberto. "Como foi minha semana?" resume as notas e as tarefas da semana e pergunta se grava. "Sim" cria a nota no caminho indicado no clone para revisão semanal, ou ao lado da nota diária. No domingo, depois do horário do check-in da tarde, essa nota é gravada sem a pergunta, uma vez, se ainda não existir. "Marca como feito" marca a tarefa com `[x]`. Se houver mais de uma parecida, o Jarvis pede o número antes de gravar. O mesmo número vale para adiar ou cancelar quando há mais de um lembrete. Falha do Claude Code, do microfone ou da rede vira uma frase curta. O detalhe fica no log local, em `~/.jarvis/logs/jarvis.log` ou no caminho de `JARVIS_LOG`.

Jira, PRs do GitHub e e-mail não lido são consultas somente leitura, por variáveis de ambiente ou pelo `gh` já autenticado. Sem configuração, o pedido responde com uma frase e o "bom dia" segue sem esse trecho. A ponte com outros assistentes fica no vault: caixa de entrada, caixa de saída e nota de perfil, com o caminho lido do clone quando a linha existe. O formato trocado é frontmatter com `de`, `para`, `data` e `status`. O fato de "lembra que eu" entra no pedido seguinte ao cérebro.

Ver [[Vault]].

## Configuração fora do repositório

O instalador grava `~/.jarvis/.env` com permissão só do usuário. O arquivo fica fora do git. O Jarvis lê esse arquivo ao iniciar e não cobre variável que já veio do ambiente.

O LaunchAgent (macOS) e a tarefa agendada (Windows) apontam para o Python e a pasta do projeto. Não copiam token para o plist nem para o agendador. Se a tarefa não puder ser criada, um arquivo na pasta Inicializar faz o mesmo papel.

Jira e Gmail são chaves opcionais nesse arquivo. O GitHub continua no `gh auth login`, sem token gravado pelo Jarvis.

O início no login é opt-in e só vale no próximo login. `python -m jarvis.setup --desativar-inicio` desliga.

## Alertas e primeiro teste

Com o processo aberto, o Jarvis consulta o que mudou fora do vault: PR seu com review pedido, issue do Jira que mudou de status e e-mail importante não lido. A primeira consulta de cada fonte só memoriza. O aviso sai depois, por voz e no Telegram, com pausa entre falas e no máximo três itens. O mesmo item não se repete. Não comenta PR, não muda status e não envia e-mail. `JARVIS_RADAR=off` desliga.

"O que anotei sobre" continua no clone. A fala traz o trecho em que os termos aparecem juntos e o caminho da nota. Não passa pelo Claude.

`python -m jarvis.doctor --corrigir` cria o arquivo de ambiente se ele não existir, restringe a permissão e instala dependência faltante. Não grava chave e não clona o vault. Isso continua no `python -m jarvis.setup`. Se faltar vault, chave ou dependência, a frase de erro diz o comando seguinte. O comando só diz que instalou quando o pip sai com código 0 e o módulo importa.

## Foco, captura e histórico

"Quais minhas prioridades hoje?" fica no Jarvis, sem Claude. A ordem é lembrete atrasado, agenda que já passou, review de PR, issue do Jira em andamento, o resto da agenda e do dia, PR aberto e issue a fazer. A fala corta nas três primeiras. As consultas de Jira e GitHub continuam só leitura. E-mail não entra nessa lista e nada é enviado.

Foto e link no Telegram não passam pelo modelo. A nota vai para a inbox de notas, com título e tags, no formato do vault e sem o tratamento da fala. Link com usuário ou senha é recusado. `.obsidian` continua de fora.

"O que eu te pedi ontem?" lê um log por dia em `~/.jarvis/logs/interacoes`. O arquivo guarda o pedido, não a resposta, e não entra no git do vault. O dia usa o fuso do clone.

## Áudio só quando o microfone abre

`sounddevice` fica fora do import de módulo. `jarvis.chat`, o Telegram e a suíte de testes sobem sem microfone e sem essa biblioteca. O modo mãos-livres carrega o áudio na hora de gravar ou de esperar o "Hey Jarvis". Se a biblioteca faltar, a fala de erro manda usar o modo texto. O diagnóstico avisa a pendência em vez de quebrar o processo.

## Palavra de ativação sem tflite

O openwakeword 0.6 no Linux pede tflite-runtime, sem wheel no Python 3.12 e no 3.13. O `requirements.txt` marca essa linha para ela não derrubar sounddevice, edge-tts e soundfile. O instalador chama `pip install --no-deps -r requirements-wake.txt`, e o modelo sobe com `inference_framework=onnx`. Se a palavra de ativação não ficar disponível, o diagnóstico aponta `python -m jarvis.chat`.

## Consulta Android em PWA local

O telefone precisa consultar o vault sem levar as notas para um serviço público e sem depender da assinatura do Claude. Um aplicativo nativo teria outra base de código e outra cópia dos dados. A página instalável reutiliza o clone de `JARVIS_VAULT`, a busca textual já existente e o mesmo tipo de token por execução do [[Painel HUD]].

O processo é separado de propósito. `python -m jarvis.consult` não entra na fila do [[Cérebro]] e não chama a escrita do vault. A voz, o terminal e o Telegram continuam podendo gravar, cada um no próprio comando.

O padrão escuta só em `127.0.0.1`. No Android, `adb reverse` faz o Chrome do telefone abrir esse endereço como `localhost`, que o navegador trata como contexto seguro e permite instalar o PWA. Um IP privado é opt-in (`JARVIS_CONSULT_BIND=lan`) e recusa `0.0.0.0` e endereço público. A página não guarda nota: a resposta sai com `Cache-Control: no-store` e o service worker não escreve cache.

A busca gratuita tem três degraus, todos locais. O modelo multilíngue do `fastembed` só entra se os pesos já estiverem em disco. Sem ele, a ordenação vetorial por n-gramas cobre variação de palavra. Se a pontuação não sustenta a resposta, vale a busca textual. Se nenhum trecho sustenta, a frase declara a falta de evidência. Cartões e ligações entre notas aparecem como sugestão e não são gravados.

## Sem o Claude no PATH

Pergunta que não é um pedido conhecido não chama o Claude quando o executável não está no PATH. A resposta busca a frase nas notas do vault. Sem acerto, lista os pedidos do dia e diz como instalar: comando `claude` no PATH e login com `claude`. "Ajuda" responde essa lista direto, com ou sem o Claude. A lista inclui revisão do dia, pausa e retomada, acertei e errei, silenciar aviso, pausa dos alertas e a busca com nos livros, nos vídeos ou nos cursos. A busca não entra em `.obsidian`.

"Como foi meu dia?" inclui os lembretes concluídos na data e o que a agenda e os lembretes marcaram para amanhã. Lembrete cancelado não entra como feito. A nota continua em `fim-AAAA-MM-DD.md`, ao lado da nota diária, só depois do sim.

A caixa de entrada e a de saída dos outros assistentes já ficam no vault. Esta rodada não criou outra.

## Relacionado

[[Jarvis]] · [[Operação]] · [[Vault]] · [[Consulta Android]]

## Busca sem texto em disco

O primeiro índice de um vault grande era lento. Guardar o catálogo em `~/.jarvis` resolveria, mas os tokens da busca são o texto da nota, e a regra é que texto de nota não sai do vault. A saída foi não fazer o trabalho que a busca não usa: o preparo de cada nota fica para quando é pedido, os filtros olham o texto dobrado em vez de percorrer palavra por palavra, e os n-gramas só existem para a nota que passou pelo filtro. A ordem dos resultados não muda.

`JARVIS_PASTAS_IGNORADAS` tira da busca as pastas que não são nota do dono, como memória de agente e cópia histórica. Não é fronteira de sigilo: a lista de notas sigilosas continua percorrendo tudo.

## Busca híbrida e escrita recusada no código

A consulta por voz e a do Android usam o mesmo ranking: BM25 para a palavra e embeddings locais para o significado, unidos por Reciprocal Rank Fusion. O modelo já estava no projeto e continua opcional. Sem os pesos, a busca fica na palavra. As três pastas nomeadas na fala ("nos livros", "nos vídeos", "nos cursos") só filtram o clone. Não viram convenção nova de frontmatter.

A avaliação (`python -m jarvis.avaliar`) mede acerto nos três primeiros e a frase de falta de evidência. O git leva só um vault inventado. As perguntas reais ficam em `~/.jarvis/avaliacao.yaml`.

A regra de não escrever em `.obsidian/`, em credencial ou em texto com cara de segredo não fica só no prompt. O módulo de guardas recusa a gravação, e um hook gratuito do Claude Code aplica o mesmo critério quando a ferramenta é Write ou Edit. WebFetch e a caixa `Jarvis/Inbox` são marcados no prompt como dado não confiável.
