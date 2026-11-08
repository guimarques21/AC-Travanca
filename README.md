# AC Travanca — gestão de futebol de 7

Passo 1: fundação (Flask + pandas), ecrã inicial e música de fundo.
Passo 2: sorteio e escolha dos 7 jogadores (modo offline).
Passo 3: escolher a tática, pôr os 7 jogadores no campo e calcular a força (escondida) da equipa.
Passo 4: a liga offline (22 jogos contra 11 equipas), classificação, melhores marcadores e Top 10 de todos os utilizadores.
Passo 5: modo online (parte 1): salas privadas com link de convite, sorteio à vez em tempo real e escolha da tática.
Passo 6: funções de cada jogador, estilo de jogo (obrigatório), quem bate livres e cantos; base de dados externa para o Top 10.
Passo 7: o motor de jogo do modo online: simula o jogo completo (atributos × função × estilo × tática) e mostra o resultado e as estatísticas aos dois.
Passo 8: a simulação visual do jogo online: campo, jogadores e bola em movimento (passes, remates, defesas, cortes, dribles, cantos, livres, laterais, golos e festejos), com os resultados e as estatísticas só no fim.

## Estrutura de pastas

```
Jogo ACT(claude)/
├── app.py                  ← aplicação Flask (ecrã inicial, validação do nome, modo online)
├── data_loader.py          ← leitura dos Excel com pandas (offline / online separados)
├── draft.py                ← lógica do sorteio (5 jogadores, 7 escolhas), sem Flask nem Excel
├── taticas.py              ← as 4 táticas: posições, pesos dos atributos, colocar/trocar jogadores
├── forca.py                ← força de cada jogador e da equipa (só no servidor, nunca mostrada)
├── liga.py                 ← a liga offline: calendário, golos, marcadores, classificação (sem Flask)
├── armazem.py              ← base de dados: ligas jogadas e Top 10 (SQLite no PC, PostgreSQL externo na internet)
├── testar_base_de_dados.py ← confirma que a base de dados (DATABASE_URL) está bem ligada
├── modo_offline.py         ← rotas do modo offline (sorteio, tática, equipa, trocas, liga)
├── salas.py                ← as salas do modo online: sorteio à vez, tática, funções, estilo, «estou pronto» (sem Flask)
├── funcoes.py              ← funções por posição, estilos de jogo, livres e cantos (dados e regras, sem Flask)
├── match_engine.py         ← o motor de jogo do modo online: `match_engine_online()` simula 2 × 25 min (sem Flask)
├── visual.py               ← o «realizador» (Passo 8): transforma os eventos do motor num filme (trajetórias, bola, animações) (sem Flask)
├── modo_online.py          ← rotas do modo online (criar sala, convite, sala, jogadas, funções e estilo)
├── tempo_real.py           ← SocketIO (opcional): avisa os dois jogadores quando algo muda
├── requirements.txt
├── render.yaml             ← configuração do deploy no Render
├── .gitignore
├── dados/
│   ├── Jogadores_e_Estatísticas.xlsx            ← SÓ modo offline
│   ├── Jogadores e Estatísticas ModoOnline.xlsx ← SÓ modo online
│   ├── Lista_de_equipas_e_Força.xlsx            ← equipas adversárias (offline; força já baixada em 1 ponto)
│   └── _copias_de_seguranca/                    ← o Excel das equipas como estava antes de baixar 1 ponto
├── static/
│   ├── musica.mp3
│   ├── css/style.css
│   ├── js/audio.js         ← música: arranca no 1.º gesto do utilizador
│   ├── js/camisola.js      ← nome na camisola, ao vivo
│   ├── js/equipa.js        ← trocar dois jogadores de posição no campo (sem recarregar a página)
│   ├── js/filme.js         ← lê o filme: onde está cada jogador e a bola em cada instante (sem desenho)
│   ├── js/cena.js          ← desenha o campo, a bancada, os jogadores (bonecos), o árbitro e a bola no canvas
│   ├── js/jogo_visual.js   ← o comando da simulação: play, velocidades, lances principais, intervalo, fim
│   ├── js/home.js          ← validação do nome + botões de modo
│   ├── js/liga.js          ← os jogos da liga aparecem um a um, "Saltar para o fim"
│   ├── js/sala.js          ← sala online: atualiza o painel sozinho, jogadas, convite, tempo real
│   └── img/favicon.svg
└── templates/
    ├── base.html           ← estrutura comum (campo, botão da música, <audio>)
    ├── _camisola.html      ← camisola SVG (número 67)
    ├── _ficha_equipa.html  ← lista da equipa por ordem de escolha
    ├── index.html          ← ecrã inicial
    ├── sorteio.html        ← modo offline: escolher 1 de 5
    ├── tatica.html         ← modo offline: escolher a tática (4 cartões)
    ├── equipa.html         ← modo offline: "Equipa pronta" (jogadores no campo)
    ├── _campo.html         ← o campo desenhado com os 7 jogadores
    ├── liga.html           ← os 22 jogos do utilizador (aparecem um a um)
    ├── classificacao.html  ← tabela das 12 equipas + melhores marcadores
    ├── top10.html          ← Top 10 de todos os utilizadores (+ a posição do utilizador)
    ├── indisponivel.html   ← «Já volto»: a base de dados não respondeu
    └── online/             ← modo online: lobby, convite, erro, sala (e os painéis de cada fase; _opcoes.html = funções, estilo e bolas paradas; _fase_pronta.html = a simulação visual e, por baixo, o «Fim do jogo»: resultado e estatísticas; _visual.html = a simulação)
```

## Como funciona o sorteio (modo offline)

- Cada ronda sorteia 5 jogadores de entre todos os do Excel offline (guarda-redes e jogadores
  de campo juntos), sem os que já estão na equipa. Os sorteados e não escolhidos podem voltar.
- São 7 rondas. Depois da 7.ª, escolhe-se a tática.
- O jogo fica guardado na sessão (cookie assinado): atualizar a página não volta a sortear e
  entrar com o nome no ecrã inicial começa sempre um jogo novo.
- Os jogadores aparecem só com nome e posição. Os atributos nunca chegam ao browser.

## Tática, posições e força (modo offline)

Depois da 7.ª escolha: **escolher a tática** (4 cartões) → **equipa no campo**. Os jogadores são
colocados automaticamente nas posições onde jogam naturalmente (o utilizador pode trocá-los: toca
num jogador e depois noutro). "Mudar de tática" volta aos cartões; ao mudar, cada jogador tenta
ficar no mesmo papel (guarda-redes, defesa, médio, avançado).

| Tática | Esquema | Posições (números da imagem do enunciado) |
|---|---|---|
| 1 | 2-3-1 | p1 GR · p2, p3 defesas · p4 médio central · p5, p6 médios alas · p7 avançado |
| 2 | 3-1-2 | p1 GR · p2, p3 defesas laterais · p4 defesa central · p5 médio · p6, p7 avançados |
| 3 | 2-2-2 | p1 GR · p2, p4 defesas · p3, p5 médios · p6, p7 avançados |
| 4 | 3-2-1 | p1 GR · p2, p3 defesas laterais · p4 defesa central · p5, p6 médios · p7 avançado |

Regras de "fora de posição" (como no enunciado), aplicadas em `forca.py`:

- Jogador fora da sua posição: todos os atributos baixam 5.
- Quem não é guarda-redes a jogar a guarda-redes: habilidade de guarda-redes = 40.
- Guarda-redes a jogar no campo: Defesa, Drible, Remate, Físico, Passe e Velocidade = 40.
- Um jogador com duas posições (ex.: "Defesa/Médio") não é penalizado em nenhuma delas.
- Força da equipa = média da força dos 7 jogadores (`forca.forca_equipa`).

**A força e os atributos nunca chegam ao browser nem ao cookie.** O cookie guarda só o nome, os 7
jogadores, a tática e quem está em cada posição. No campo, um jogador fora da sua posição natural
aparece com um "!" (sem números).

Fórmulas por posição (percentagens do enunciado, já com a tática 4 corrigida pelo autor):

| Posição | Pesos |
|---|---|
| Guarda-redes (todas as táticas) | Guarda-redes 100% |
| Defesa (T1, T3) | Defesa 42, Físico 42, Passe 11, Drible+Remate+Velocidade 5 |
| Defesa central (T2, T4) | Defesa 43, Físico 43, Passe 10, Drible+Remate+Velocidade 4 |
| Defesa lateral (T2, T4) | Defesa 31, Físico 31, Passe 15, Velocidade 10, Drible 10, Remate 3 |
| Médio central (T1, T2) | Defesa 10, Drible 30, Físico 10, Passe 35, Velocidade 5, Remate 10 |
| Médio ala (T1) | Drible 30, Remate 15, Passe 25, Velocidade 20, Defesa 5, Físico 5 |
| Médio (T3, T4) | Defesa 10, Drible 30, Físico 10, Passe 35, Velocidade 10, Remate 5 |
| Avançado (todas) | Drible 23, Remate 28, Físico 23, Passe 10, Velocidade 15, Defesa 1 |

Interpretações minhas, onde o texto deixava margem:

1. **"Drible+Remate+Velocidade (5%)":** repartido em partes iguais pelos três atributos.
2. **Posições no campo:** o Word não tem imagens; deduzi as formações do texto (nº1 GR, 2 e 3 defesas, etc.).
   Na tática 3 uso p2/p4 para defesas e p3/p5 para médios, como indica o enunciado.

## A liga (modo offline, Passo 4)

Na página "Equipa pronta" o botão **Começar a liga** simula tudo no servidor, **uma só vez**:

1. **22 jogos**: 2 contra cada uma das 11 equipas adversárias (ida e volta). As outras equipas
   também jogam entre si, por isso há uma classificação com as 12 equipas.
2. Os jogos do AC Travanca aparecem **um a um, depressa** (cerca de 10 segundos), com o resultado, V/E/D
   e os marcadores de cada golo. Há um botão **Saltar para o fim**. Se atualizares a página, ou voltares
   atrás, aparece tudo de uma vez (e é sempre a mesma liga: o resultado fica guardado).
3. No fim, o botão **Ver classificação**: tabela final (pontos; em caso de empate, saldo de golos; depois
   golos marcados) e a lista dos melhores marcadores ao lado.
4. Por fim, o botão **Ver o Top 10**, que diz claramente que é o top 10 de **todos os utilizadores** que
   jogaram o modo offline. Se o utilizador não está no top 10, aparece o top 10 e, por baixo, a sua linha
   com a posição (por exemplo, 16.º).
5. **Jogar outra vez** começa um jogo novo com o mesmo nome. O resultado anterior continua no Top 10.

Depois de a liga começar, a **equipa e a tática já não se podem mudar**. Senão bastava repetir até sair
uma liga boa.

Como o resultado é calculado (`liga.py`; as constantes estão no topo do ficheiro para ajustares):

- A **força da equipa do utilizador** vem de `forca.py` (Passo 3) e a das adversárias do Excel. **Nunca é
  mostrada** e não chega ao browser nem ao cookie: a página só recebe golos, nomes e pontos.
- Cada jogo: os golos são sorteados (distribuição de Poisson) com um total esperado de cerca de 4,6 golos
  por jogo, repartido conforme a diferença de forças (`SENSIBILIDADE = 0,20`). Com forças iguais há ~40% de
  vitória para cada lado e ~19% de empate; com 5 pontos de diferença, ~77% de vitórias da mais forte; com 10,
  ~93-96%. Não há vantagem de jogar em casa.
- Os marcadores saem da equipa do utilizador: avançados marcam mais que médios, médios mais que defesas, o
  guarda-redes nunca marca; dentro de cada posição pesa o Remate, o Drible e a Velocidade.
- O calendário é feito pelo método da roda (todas as equipas jogam em todas as jornadas).

### Top 10 de todos os utilizadores (base de dados)

Cada liga jogada fica guardada na base de dados (`armazem.py`): num ficheiro SQLite no PC (já vem com o
Python) ou, na internet, num PostgreSQL externo (a seguir). A sessão do
utilizador só guarda um código aleatório para voltar a encontrar a sua liga. Ordem do Top 10: pontos,
saldo de golos, golos marcados e, em caso de empate total, quem jogou primeiro. O mesmo nome pode aparecer
várias vezes (cada liga jogada conta).

- No PC o ficheiro fica em `instance/ranking.sqlite3` (a pasta é criada sozinha; está no `.gitignore`).
- Na internet usa-se uma base de dados externa e gratuita (a seguir), para o Top 10 não se perder.

### Top 10 guardado para sempre, sem pagar

O disco do Render gratuito é apagado sempre que o serviço reinicia, é publicado de novo ou adormece, por
isso um ficheiro lá dentro não serve. Os discos persistentes e a base de dados do próprio Render são pagos
(a base gratuita do Render **expira ao fim de 30 dias**). A solução gratuita é uma base de dados PostgreSQL
**fora** do Render. Recomendo o **Neon**: o plano gratuito dá 1 GB por projeto e a própria página dos
limites diz que os limites «não apagam os teus dados» (a base «adormece» ao fim de 5 minutos sem
uso e acorda sozinha no pedido seguinte: o primeiro acesso depois disso pode demorar um ou dois segundos).
Uma liga ocupa cerca de 7 a 10 KB (medido), por isso 1 GB chega para dezenas de milhares de ligas.
(Confirma no site do Neon as condições do plano gratuito, porque podem mudar.)

Passo a passo (os nomes dos botões podem mudar um pouco):

1. Cria uma conta gratuita em neon.com e **cria um projeto** (por exemplo, `ac-travanca`; escolhe a região da
   Europa). Não precisas de criar tabelas: o jogo cria-as sozinho.
2. No painel do projeto, carrega em **Connect** e copia o **endereço de ligação** (começa por `postgresql://`
   e tem `sslmode=require` no fim). Tem lá a palavra-passe: não o partilhes nem o ponhas no GitHub.
3. (Opcional, no PC) confirma que funciona: `pip install -r requirements.txt`, define a variável e corre o teste:
   PowerShell `$env:DATABASE_URL = "postgresql://..."` e depois `python testar_base_de_dados.py`
   (grava uma liga de teste, lê-a e apaga-a; não deixa nada no Top 10).
4. No Render, abre o serviço, **Environment**, **Add Environment Variable**: nome `DATABASE_URL`, valor = o
   endereço copiado. Guarda: o Render volta a publicar o jogo.
5. Nos registos (Logs) do Render deve aparecer «Classificação geral em PostgreSQL (…neon.tech)». Joga uma
   liga, publica o jogo de novo (Manual Deploy) e confirma que o Top 10 continua lá.

Se a variável `DATABASE_URL` não existir, o jogo usa o ficheiro SQLite (é o que acontece no PC). Se a base
não responder durante um momento, o jogo mostra «Já volto — tenta outra vez» em vez de dar erro.

**Tem de ser testado por ti:** o servidor onde fiz este passo não tem rede, por isso o SQL foi testado num
PostgreSQL 16 verdadeiro instalado lá, mas a ligação ao Neon (e o pacote `psycopg`) só podem ser testados
por ti com o passo 3 acima.

O Render gratuito também **adormece** ao fim de 15 minutos sem visitas (a primeira visita seguinte demora cerca
de um minuto a acordar). Isso não perde nada (as ligas estão no Neon), mas as salas do modo online, que vivem
na memória, perdem-se. As 750 horas gratuitas por mês chegam para um serviço ligado o mês inteiro, por isso um
serviço externo gratuito que visite `/healthz` de 10 em 10 minutos (por exemplo, o UptimeRobot) mantém o jogo
acordado.

## Modo online (Passo 5): salas, convite, sorteio à vez e tática

O que já existe: o utilizador escolhe **Jogar Online**, cria uma **sala privada** e recebe um **link único**
(`/jogar/online/convite/<código>`, com um código aleatório UUID impossível de adivinhar). Quem abrir o link
(depois de escrever o nome) confirma e entra. Cada sala tem exatamente 2 jogadores.

1. **Sorteio à vez.** Começa quem o sorteio decidir; depois alternam (A, B, A, B…) até cada um ter 7 jogadores.
   Em cada vez, o jogador da vez vê 5 jogadores sorteados e escolhe 1. Um jogador escolhido por qualquer um dos
   dois **deixa de aparecer** (não pode ficar nas duas equipas). Cada um vê as duas equipas (só nomes e posições).
2. **Tática.** Cada um escolhe a sua (podem escolher a mesma) e põe os jogadores no campo, como no modo offline.
   Pode mudar de tática e trocar jogadores **até carregar em «Estou pronto»**; «Editar» desfaz o «pronto».
   **A tática do adversário não se vê** (só se vê se já escolheu e se já está pronto).
3. **Funções, estilo e bolas paradas (Passo 6).** Com a equipa no campo, cada um escolhe, até carregar em «Estou pronto»:
   - **o estilo de jogo** da equipa (**obrigatório**, não há estilo «Equilibrado» nem nenhum escolhido por defeito):
     Bola longa, Posse de bola, Contra-ataque, Jogar pelas alas ou Park the bus. Sem estilo escolhido o botão
     «Estou pronto» fica desativado e a página explica porquê;
   - **a função de cada jogador** (toca no jogador para ver as opções). Cada tipo de posição tem as suas funções, e os
     **médios alas** da tática 1 e os **defesas laterais** das táticas 2 e 4 têm opções só deles (o avançado das
     táticas 2 e 3, que são «centro/extremos», tem também a função «De ala»). O resto das posições partilha as
     opções do seu tipo (defesa, médio, avançado), e o guarda-redes tem duas (Tradicional e Líbero);
   - **quem bate os livres** e **quem bate os cantos** (qualquer jogador de campo; o guarda-redes fica na baliza).
   As funções vêm escolhidas por defeito («normais») e os livres e cantos para o primeiro jogador de campo; o estilo
   tem de ser escolhido. **Nada disso dá vantagem escondida**: as funções «normais» não mexem nos atributos. Se mudares
   de tática, as funções voltam às normais (as posições mudaram), mas o estilo e os marcadores mantêm-se. Se trocares o marcador para a
   baliza, volta ao do defeito. **O adversário nunca vê estas escolhas.**
4. Quando os dois estão prontos a sala fica «pronta» e o jogo é simulado (Passo 7, mais abaixo).

### O que as funções e os estilos fazem (usado pelo motor do Passo 7)

No ecrã só há nomes e descrições em linguagem de futebol. Os números ficam em `funcoes.py`, no servidor:

- Cada **função** tem multiplicadores sobre atributos do Excel online (1,0 é o normal; 1,3 quer dizer que esse atributo
  conta 30 % mais na fórmula da posição; 0,9, que conta 10 % menos). Os atributos que a função não cita contam como
  sempre: a função «puxa» para um lado, não deita fora o resto.
- Cada **estilo** tem multiplicadores por tipo de posição (guarda-redes, defesa, médio, avançado) e «tendências» de
  –1 a +1 (posse, jogo direto, ritmo, largura, linha defensiva, risco), que o motor de jogo usa para o estilo se
  **notar** na simulação. No Passo 7 foram afinados com centenas de jogos simulados (ver «O jogo online»).
- `funcoes.multiplicadores(tática, posição, função, estilo)` junta função × estilo. O resultado fica sempre entre 0,72 e 1,82.
- **Livres:** cerca de 1,6 por jogo; o sucesso depende do atributo *Bola Parada* de quem bate. **Cantos:** além de
  *Bola Parada*, depende de *Cabeceamento*, *Impulsão* e *Altura* de quem vai à bola.
- No arranque, o servidor confirma que todos os atributos citados existem no Excel online (se não, não arranca e diz qual).

O modo online usa **só** o Excel `Jogadores e Estatísticas ModoOnline.xlsx` (24 jogadores). As posições abreviadas
(GR, D, M, A) são convertidas em palavras (Guarda-redes, Defesa, Médio, Avançado) para reutilizar as táticas.

### Como é que os dois ecrãs ficam sincronizados

- O **estado da sala vive no servidor** (`salas.py`). Cada jogador só recebe o que pode ver (sem atributos,
  sem forças, sem a tática do adversário). O cookie guarda só um **token secreto do lugar** por sala.
- O servidor desenha o painel para quem pede; o browser (`sala.js`) só o troca quando muda. Os pedidos são
  normais (POST JSON): o servidor valida tudo (de quem é a vez, jogador sorteado, posição…).
- **Tempo real:** o Flask-SocketIO serve só de «campainha»: quando algo muda, avisa a sala e cada browser
  pergunta logo o estado. Se o SocketIO não estiver instalado, ou o WebSocket for bloqueado, o browser
  pergunta de 2 em 2 segundos e **tudo funciona na mesma**.
- Aparece «Nome: ligado / sem ligação» (pelos pedidos dos últimos 12 segundos).
- Uma sala sem atividade há 3 horas fecha-se sozinha; no máximo 500 salas ao mesmo tempo.

### Correr no PC

```
pip install -r requirements.txt     # inclui flask-socketio e simple-websocket
python app.py                       # http://127.0.0.1:5000
```

Para ver os dois jogadores no mesmo PC, usa **dois browsers diferentes** (ou uma janela privada), porque o
cookie identifica cada jogador.

### No Render

- **Tem de ser um só processo** com várias threads (`render.yaml` já tem
  `gunicorn -k gthread -w 1 --threads 100 app:app`): as salas ficam na memória do processo; com vários
  processos, cada jogador poderia cair num processo que não conhece a sala.
- Cada ligação em tempo real ocupa uma das 100 threads: o plano gratuito aguenta cerca de 100 jogadores ligados ao mesmo
  tempo. Acima disso (ou se o WebSocket for bloqueado) os jogadores usam a consulta de 2 em 2 segundos, que gasta menos.
- **As salas perdem-se** quando o serviço reinicia, é publicado de novo, ou (plano gratuito) adormece por
  falta de visitas. Guardá-las em base de dados é possível mais tarde, se for preciso.
- O cliente do SocketIO (`socket.io.min.js`) é carregado do cdnjs. Se preferires servi-lo tu, põe o ficheiro
  em `static/js/` e muda `URL_SOCKETIO` no topo do `sala.js`.
- Quem perder o cookie (outro browser, janela privada fechada) não volta ao seu lugar: a sala é de quem
  tem o token.
- **Erro «Ficheiro … não encontrado» ou «A pasta de dados não existe» no arranque.** Os 3 Excel têm de estar no GitHub,
  dentro da pasta `dados/` (também se aceita «Dados» ou os Excel soltos ao lado do `app.py`). A mensagem de erro, nos
  Logs do Render, diz onde procurou e que ficheiros e pastas existem no servidor. Depois de corrigir, faz
  **Manual Deploy → Clear build cache & deploy**.

## O jogo online (Passo 7): o motor de jogo

Quando os dois carregam em «Estou pronto», a sala sorteia uma **semente** e o jogo é simulado **uma só vez** no servidor
(`match_engine.py`, cerca de 0,15 s). Os dois veem **o mesmo jogo**, cada um com ele próprio à esquerda (azul) e o adversário à
direita (amarelo). Mesma semente + mesmas equipas = exatamente o mesmo jogo.

```python
from match_engine import fichas_de, match_engine_online
fichas = fichas_de(df_jogadores_online)           # só o Excel do modo online
resultado = match_engine_online(config_a, config_b, fichas, semente=123)
# config = {"nome", "tatica", "escalacao", "funcoes", "estilo", "livres", "cantos"}
```

### Tudo conta: atributos × função × estilo × tática

Nenhuma ação é um «dado solto»: passa sempre pelos jogadores envolvidos.

1. **Onde cada um está.** A tática dá o sítio base; a *função* desloca-o (ex.: «Em profundidade» sobe, «De apoio» recua, o lateral
   «Ofensivo» sobe); o *estilo* muda a linha defensiva e a largura; a bola e a fase (atacar/defender) mexem a equipa toda. Quem
   está sem bola desliza para o lado da bola e fecha o corredor central. Velocidade, Aceleração, Resistência e Índice de Trabalho
   limitam o quão depressa cada um lá chega e o quanto se cansa.
2. **O que o portador decide**: passe curto, a progredir, de rutura, bola longa, cruzamento, drible, remate ou alívio. Cada opção tem
   uma utilidade (quanto melhora a posição × hipótese de correr bem − o que se perde se correr mal). O estilo muda o que a equipa
   valoriza, a função muda o gosto de cada jogador (o Extremo cruza e dribla mais) e os traços do Excel também (ex.: «Tenta Remates
   de Longe», «Fica Sempre na Defesa»).
3. **Como a ação corre.** A hipótese de cada passe, desarme, drible, remate e defesa sai dos **atributos** dos envolvidos (e do
   guarda-redes) e da situação (distância, ângulo, pressão, linha de passe, quantos defesas fecham a baliza). A função e o estilo
   mudam o **peso** dos atributos, mas centrados na média do plantel: só ajudam quem é mesmo bom no que pedem e custam a quem é
   fraco nisso. Não há bónus de graça.
4. **Fora de posição:** −5 em todos os atributos (igual ao offline).
5. **Bolas paradas.** Livres perigosos ≈ 1,5 por jogo; o resultado depende da *Bola Parada* de quem bate. Cantos: *Bola Parada* de
   quem bate + duelo aéreo (Cabeceamento, Impulsão, Altura) dos que vão à bola contra os que os marcam. Bate sempre quem o
   treinador escolheu (nunca o guarda-redes).
6. **A tática não dá bónus de força**: só geometria (e o ajuste ao estilo, a seguir).
7. **O estilo é um plano de jogo e só funciona na medida em que a tática e as funções o conseguem executar** (ver a secção
   seguinte).

### O plano de jogo: estilo × tática × funções

Cada equipa tem uma **eficácia do plano** (`Equipa.ef` em `match_engine.py`, entre 0,45 e 1,55; 1,0 = neutro) que depende de:

- **tática × estilo** (`funcoes.AJUSTE_TATICA`, de −1 a +1, centrada: nenhuma tática é «melhor em tudo»). Exemplos: a 2-2-2 não tem
  ninguém nas zonas laterais, por isso é a pior com «Pelas alas»; a 3-2-1 (muitos defesas e médios) é a melhor com «Park the bus»;
  a 3-1-2 (só 1 médio) é a pior com «Posse»; a 2-3-1 e a 3-2-1 sustentam a posse; com 1 só avançado a «Bola longa» fica isolada.
- **funções × estilo** (`funcoes.SINERGIA_FUNCAO`, de −1 a +1): o Extremo, o lateral Ofensivo e o «De ala» sustentam as alas; o
  Organizador, o Interior, o «Sai a jogar» e o Construtor sustentam a posse; o Posicional, a Cobertura e o Recuperador fecham o
  autocarro; o Pivô e o «Em profundidade» sustentam a bola longa e o contra-ataque, etc.

A eficácia **não é um bónus de graça**: multiplica só o que o estilo faz de específico (criar espaço com a circulação de bola, o
espaço de um contra-ataque, fechar o bloco baixo, cruzar quem joga pelas alas, ganhar duelos de bola longa) e dá uma pequena
coesão geral aos passes e duelos. Quem escolhe o que não combina fica pior do que se não tivesse escolhido estilo nenhum.

Resultados medidos (centenas de jogos simulados por célula, números aleatórios comuns):

| O que se mediu | Resultado |
|---|---|
| Golos por jogo, dois treinadores no mesmo estilo | «Park the bus» ≈ 2 · «Contra-ataque» ≈ 4 · «Posse» ≈ 5,5 · «Pelas alas» ≈ 6,5 a 7 (média de todas as combinações: 4,9) |
| Posse de bola, «Posse» contra os outros | 68 % contra «Park the bus» (mais bola em 100 % dos jogos), 65 % contra «Contra-ataque» (100 %), 58 % contra «Pelas alas» (≈ 90 %), 62 % contra «Bola longa» (≈ 100 %) |
| Posse média de cada estilo | Posse 63 % · Pelas alas 53 % · Bola longa 48 % · Contra-ataque 44 % · Park the bus 42 % |
| Tática × estilo (desvio em pontos %, em relação ao que a tática e o estilo valem sozinhos) | 2-2-2 com «alas» −9 a −14 · 3-1-2 com «posse» −13 · 3-2-1 com «bola longa» −5 a −10 · 3-2-1 com «autocarro» +5 · 2-2-2 com «bola longa» +7 a +9 |
| Funções coerentes com o estilo contra funções contrárias (mesmo plantel, tática e estilo) | ganham entre 56 % e 83 % dos pontos conforme o estilo (média ≈ 68 %), nunca de forma garantida |
| Plantel superior (todos os atributos +4 / +8 / +12) | vitórias 71 % / 90 % / 95 %; golos 4,0-2,1 / 5,0-1,3 / 6,2-0,7; remates 18-11 / 21-9 / 25-7 |
| Pontos médios de cada estilo contra os outros quatro | entre 43 % e 55 % (a média é 47 %: os empates valem 1 ponto) |

A posse de bola dá mais bola, **não** dá o jogo: contra «Park the bus» a equipa de posse tem 68 % da bola e apenas cerca de 1 ponto
a mais em remates, e os resultados ficam equilibrados (os contra-ataques contam).

### O que os dois veem no fim

Página **«Fim do jogo»**: «Ganhaste! / Perdeste / Empate», placar, golos (minuto, marcador, assistência e como foi), a **tabela de
estatísticas** — Golos, Posse de bola %, Remates, Remates à baliza, Defesas do guarda-redes, Passes completos / tentados, Passes
completos %, Desarmes e Interceções — com barras azul/amarelo, «Mais números» (cantos, livres perigosos, faltas, cruzamentos, passes
longos, dribles, contra-ataques, remates bloqueados, golos de bola parada), as duas equipas com funções e estilos (só se
revelam depois do jogo) e o relato dos lances principais. Quem sai depois do jogo não estraga o ecrã ao outro; a sala fecha quando
os dois saem. **Atributos, forças e multiplicadores nunca aparecem.**

### Eventos do jogo

`GET /jogar/online/sala/<id>/eventos` devolve (só a quem tem lugar na sala, e só depois do jogo) o jogo completo em JSON comprimido
(`Content-Encoding: deflate`): cerca de 600 eventos, cada um com o minuto, o tipo e **a posição dos 14 jogadores** (`q`, no instante
`tq`). Alguns eventos trazem ainda o sítio por onde a bola saiu (`saiu`), quem vai à área num canto ou cruzamento (`area`) e o
pontapé de saída (`saida`). É a matéria-prima do Passo 8; o motor não mudou (mesmos resultados, mesmas estatísticas).

## A simulação visual (Passo 8)

Quando os dois ficam prontos, em vez de saltar logo para o resultado, cada jogador vê o **jogo a acontecer**, como numa
transmissão de televisão: câmara de lado, ligeiramente de cima, que segue a bola. O resultado e as estatísticas ficam escondidos até
a simulação acabar (ou até se carregar em «Saltar para o resultado»), para não estragar a surpresa; sem JavaScript mostra-se tudo logo.

**O que se vê** — não são botões nem bolinhas, são jogadores: cabeça, tronco, braços e pernas, com a passada a acompanhar a velocidade,
camisola, calções e meias (quem joga: amarelo e azul; adversário: azul e branco; guarda-redes: laranja e rosa), o número nas costas e o
nome de quem tem a bola. Remates com balanço da perna, passes e cruzamentos com a bola no ar (arco e sombra no chão), desarmes com
deslize, faltas e quedas, defesas com voo do guarda-redes, cabeceamentos com salto, lançamentos laterais com as mãos por cima da
cabeça, cantos e livres com os jogadores a tomar posição, festejo do golo (o marcador corre para o lado e os colegas juntam-se; a
bancada salta), árbitro que acompanha o jogo, balizas com rede, bandeirolas, painéis «AC TRAVANCA» e bancada azul e amarela.

**As regras do jogo estão respeitadas**: se a bola sai, repõe a *outra* equipa no sítio por onde saiu (lançamento lateral na linha,
canto no canto, pontapé de baliza); depois de um golo, a bola retira-se da rede e **a equipa que sofreu bate a saída do meio-campo**;
se um jogador tira a bola, é ele que fica com ela; a bola nunca salta de um sítio para outro nem atravessa o campo sem voar (quando
um jogador apanha uma bola parada, ela rola até aos pés dele); ninguém se teletransporta. Tudo isto vem dos mesmos eventos do motor: o
filme só mostra o que o motor decidiu.

**Ritmo (pedido a 8 nov)**: o filme anda a um ritmo de jogo corrido, não ao ritmo «real» do motor. Cada jogada é comprimida para o
tempo que a ação precisa (o portador corre depressa, decide em ≈ 0,3 s em vez de ficar parado, a bola voa a ≈ 30 m/s), sem nunca pedir
a ninguém mais do que ≈ 24 m/s em média (`visual.RITMO`; picos até ≈ 34 m/s nos arranques). A ordem e o resultado de tudo ficam iguais; o relógio do marcador acompanha o jogo
(`rel`). **Medido:** «Jogo completo» a ×1 ≈ 8 a 10 minutos no total (cerca de 4 a 5 por parte), a ×2 cerca de metade; «Lances principais»
≈ 2 minutos por parte; o intervalo dura ≈ 3 s de filme.

**Comandos**: ▶/⏸ (barra de espaços), velocidades ×1 ×2 ×4 ×10, **«Lances principais»** (cerca de 2 minutos por parte: todos os
ataques com perigo, os golos, as defesas difíceis, os remates, livres e cantos, com um corte rápido entre lances) ou **«Jogo completo»**
(os 50 minutos do jogo), «Próximo lance» (tecla N), barra de tempo que **só mostra o intervalo** (os golos já não são marcados na barra,
para não estragar a surpresa; clicar, arrastar ou setas), **pausa automática no intervalo** («Segunda parte» continua), letreiro
«GOLO!», relato por baixo do campo e marcador com relógio.
No fim: «Ver o resultado» ou «Ver outra vez». Depois de ver, F5 mostra logo o resultado e deixa «Rever a simulação».
A página nunca recarrega, por isso **a música de fundo não pára**.

**Como funciona por dentro**

1. `visual.py` (o *realizador*) lê os eventos e constrói o **filme**: uma trajetória suave (PCHIP) para cada um dos 14 jogadores, a
   bola em «peças» contíguas (conduzida por um jogador, rasteira, em arco, remate, a rolar, escondida), animações (remate, desarme,
   queda, voo, cabeceamento, festejo…), comentários, o marcador e os lances principais. É determinístico: o mesmo jogo dá sempre o
   mesmo filme.
2. `GET /jogar/online/sala/<id>/filme` entrega o filme (JSON deflate, uns 55 KB) **de quem pede**: cada um vê-se sempre à esquerda a
   atacar para a direita (o campo é espelhado para o lugar B, e as escolhas ao acaso — por exemplo o canto da baliza onde entra a bola —
   são as mesmas nos dois lados: os dois veem o mesmo jogo). Só quem tem lugar na sala, só depois do jogo; fica guardado em memória.
3. `static/js/filme.js` dá a posição de cada jogador e da bola em qualquer instante (a mesma conta do Python: testado em Node);
   `static/js/cena.js` desenha esse instante num `<canvas>` com perspetiva a sério; `static/js/jogo_visual.js` trata do tempo e dos botões.
   `sala.js` volta a ligar a simulação sempre que o painel é redesenhado, sem a reiniciar.

**Testes**: `test_passo8_filme.py` (invariantes do filme em 28 jogos nos dois lados, a rota, privacidade, o espelho, o relógio, o resumo,
o JavaScript contra o Python) e `e2e_passo8.py` (Chromium em PC, telemóvel e telemóvel estreito: sem spoilers, botões, golo, intervalo, fim, F5, a música não
reinicia, sem scroll horizontal, botões com pelo menos 44 px).

### Notas dos jogadores e MVP (pedido a 8 nov)

No «Fim do jogo», depois das estatísticas, aparece **«Notas dos jogadores»**: o **MVP do jogo** em destaque (cartão amarelo, com a nota e
os feitos) e a nota (3,0 a 10,0) de cada um dos 14 jogadores, equipa por equipa (a tua à esquerda), com a posição, a função e até três
destaques («2 golos · 1 assistência · 5 defesas…»). A nota **só conta o que cada um fez** (golos, assistências, passes para remate,
passes certos, dribles, desarmes, interceções, cortes, defesas, faltas, remates falhados) e o que a equipa sofreu e marcou; **nunca
os atributos**. Um jogo normal dá cerca de 6,5, acima de 8 é um grande jogo e o 9 é raro (≈ 1 % dos jogadores). O MVP é quem tem a nota
mais alta (desempata por golos e assistências); quase sempre é de quem ganhou. Os dois veem as mesmas notas e o mesmo MVP.

### Limites conhecidos (Passo 8)

- É uma representação: o motor decide *o que* acontece e o filme inventa *como se vê* (por exemplo o canto da baliza onde entra um golo,
  o sítio exato de um desarme ou a trajetória dos jogadores entre dois eventos). Os resultados e as estatísticas são sempre os do motor.
- A vista é de televisão (de lado): os voos do guarda-redes são ao longo da linha de baliza, por isso aparecem em perspetiva.
- O filme está acelerado: os jogadores movem-se depressa (como o antigo ×4) e tudo se passa mais depressa do que na vida real. Quem quiser
  ver o jogo todo ao ritmo de um comentador usa «Jogo completo» a ×1; quem quiser só o essencial usa «Lances principais».
- Não há som de jogo (só a música de fundo), nem cartões nem substituições (o motor não os tem).
- O filme vive em memória, como a sala: se o Render reiniciar, perde-se (o resultado também).

### Números do motor (equipas aleatórias, 400 jogos)

| | por equipa | | por equipa |
|---|---|---|---|
| Golos | 2,5 (4,9 por jogo) | Desarmes | 16 |
| Remates / à baliza | 11,3 / 6,2 | Interceções | 29 |
| Defesas do GR | 3,7 | Passes tentados / certos | 246 / 181 (73 %) |
| Posse de bola | 50 % (23 % a 77 %) | Cantos / livres perigosos | 3,2 / 0,75 |

Empates: 14 %. A diferença de golos é de 0 ou 1 em 37 % dos jogos e de 5 ou mais em 16 % (plantéis muito diferentes).

### Revisão das combinações tática × estilo (8 nov, depois de um 13-0)

Um jogo 2-2-2 «contra-ataque» contra 2-3-1 «pelas alas» (equipas parecidas) acabou 13-0. Reproduzido e corrigido:

- **Causa**: o motor não tinha *gestão do resultado* (quem ganha por muitos golos continuava a atacar ao mesmo ritmo e quem perde não
  arriscava mais), a desorganização defensiva (`esp`) saturava e alimentava-se a si própria, e «pelas alas» criava mais espaço do que
  deveria. Em futebol real, quem vai a ganhar por 3 ou 4 baixa linhas e gere o tempo, e quem tem 3 defesas fecha melhor o corredor central.
- **Correção** (`match_engine.py`, `funcoes.py`): `K_GESTAO` (a equipa que vence por mais golos ganha menos espaço e remata menos; a que
  perde arrisca um pouco mais), `K_SOLIDEZ` (cada defesa além de dois fecha o espaço), `K_LARGURA` (as alas deixam de criar espaço sem
  limite) e o peso da tática no plano de jogo desceu de 0,30 para 0,18 (a tática que não encaixa no estilo custa, mas não decide o jogo).
- **Resultado** (as 20 combinações tática × estilo, 210 pares × 16 jogos, plantéis iguais; 3 360 jogos): média de 4,5 golos por jogo;
  diferenças de 7 ou mais golos em 0,2 % dos jogos (antes 2,7 %) e de 9 ou mais em 0,1 % (o máximo é 9). Todas as combinações ficam
  entre ≈ 31 % e 58 % dos pontos (empates valem 1). As melhores: 2-3-1 «posse» (58 %), 3-1-2 «park the bus» (56 %), 3-1-2 «contra-ataque»
  (55 %); as mais fracas: 3-2-1 com «bola longa» (31 %), «contra-ataque» (35 %) e «alas» (36 %) — com **um só avançado** os estilos
  ofensivos têm pouca saída, o que também se vê no futebol — e 2-2-2 com «alas» (39 %). Com plantéis realistas (jogadores nas
  posições naturais) o caso do 13-0 deu, em 300 jogos, a maior diferença de 8 golos e 1,7 % de goleadas de 7 ou mais.
- Dois «alas» juntos é o par que mais golos dá (≈ 6,6 por jogo); dois «park the bus», o que menos (≈ 2,3).

### Limites conhecidos (Passo 7)

- Os coeficientes do motor foram **calibrados por simulação** (números plausíveis para futebol de 7), não com dados reais.
- As formações não estão perfeitamente equilibradas entre si: a 3-2-1 (só 1 avançado) é a mais fraca e a 2-2-2 a seguir, uns 8 pontos percentuais abaixo da 2-3-1 e da 3-1-2 (ver o documento do Passo 7); o equilíbrio entre estilos é bem
  melhor, mas nenhum estilo é «igual» a outro, por desenho.
- As tabelas de ajuste (`AJUSTE_TATICA`, `SINERGIA_FUNCAO`) e os metros que cada função desloca o jogador (`_MOVIMENTO`) são **juízos de
  realismo** meus, calibrados por simulação. Os metros são pequenos de propósito: o motor reage muito à posição dos avançados e uma
  função não pode decidir um jogo só por onde põe o jogador; a identidade de cada função vem dos atributos que pede e do ajuste ao estilo.
- O resultado vive em memória, tal como a sala: perde-se se o Render reiniciar.
