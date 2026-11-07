"""
modo_online.py — rotas do MODO ONLINE (Passos 5 a 7: salas, convite, sorteio à vez, tática, funções, estilo, bolas paradas, jogo)
========================================================================================

Separação dos modos: este ficheiro só usa a função *_online() do data_loader (nunca os Excel offline).

Rotas:
    GET  /jogar/online                          início: criar uma sala (e voltar às salas em curso)
    POST /jogar/online/criar                    cria a sala e leva para ela
    GET  /jogar/online/convite/<id>             o link que se envia ao adversário (confirma a entrada)
    POST /jogar/online/convite/<id>             entra na sala (lugar B)
    GET  /jogar/online/sala/<id>                a sala (a página toda; depois atualiza-se sozinha)
    GET  /jogar/online/sala/<id>/estado?a=…     JSON: o painel atual (HTML) só se mudou desde a assinatura `a`
    POST /jogar/online/sala/<id>/acao           JSON: escolher, tatica, mudar_tatica, cancelar_mudar, funcao, estilo,
                                                livres, cantos, pronto, editar, sair
    POST /jogar/online/sala/<id>/trocar         JSON: troca dois jogadores no campo (como no offline)
    GET  /jogar/online/sala/<id>/eventos        os eventos do jogo (JSON comprimido, com as posições)
    GET  /jogar/online/sala/<id>/filme          o «filme» do jogo para a simulação visual (Passo 8; JSON comprimido, visto do lugar de quem pede)

Como se mantém tudo sincronizado: o servidor devolve o «painel» (um bocado de HTML) já desenhado para
QUEM está a pedir — cada jogador só recebe o que pode ver. O browser guarda a «assinatura» do painel
que está a mostrar e só o substitui quando muda. Quem avisa o browser de que algo mudou é o SocketIO
(tempo_real.py); sem ele, o browser pergunta de 2 em 2 segundos.

O cookie de sessão só guarda, por sala, o token secreto do lugar do utilizador (ver salas.py).
Nunca há atributos nem forças nas páginas: só nomes e posições.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

import data_loader as dados
import draft
import funcoes as fun
import match_engine
import taticas
import tempo_real
from salas import ABANDONADA, ESPERA, ErroSala

bp = Blueprint("online", __name__, url_prefix="/jogar/online")

# No Excel online as posições vêm abreviadas (GR, D, D/M, M, M/A, A). Nas páginas usam-se as palavras
# inteiras, como no modo offline, e é com elas que o `taticas.py` calcula quem está «fora de posição».
PALAVRA = {"GR": "Guarda-redes", "D": "Defesa", "M": "Médio", "A": "Avançado"}
SALAS_NA_SESSAO = 5          # quantas salas o cookie se lembra (as mais recentes)
STATUS_ERRO = {"sala_inexistente": 404, "sem_lugar": 403, "sala_cheia": 409, "abandonada": 409,
               "cheio": 503, "dados_mudaram": 409, "jogo_nao_pronto": 409, "erro_motor": 500}

# Como se escreve a origem de um golo no ecrã do fim do jogo
ORIGEM_GOLO = {"canto": "de canto", "livre": "de livre", "contra": "em contra-ataque", "cruzamento": "após cruzamento",
               "ressalto": "no ressalto", "cabeceamento": "de cabeça", "penalti": "de penálti"}


# --------------------------------------------------------------------------- #
# Dados e sessão
# --------------------------------------------------------------------------- #

def posicoes_online() -> dict[str, str]:
    """Nome -> posição natural (em palavras) de todos os jogadores do Excel ONLINE."""
    jogadores = dados.carregar_jogadores_online()
    resultado = {}
    for nome, bruta in zip(jogadores["Nome"], jogadores["Posição(ões)"]):
        partes = [p.strip() for p in str(bruta).split("/")]
        desconhecidas = [p for p in partes if p not in PALAVRA]
        if desconhecidas:
            raise ValueError(f"Posição desconhecida no Excel online para {nome!r}: {bruta!r}")
        resultado[nome] = "/".join(PALAVRA[p] for p in partes)
    return resultado


def validar_funcoes() -> None:
    """Falhar cedo: as funções e os estilos só podem citar atributos que existem no Excel ONLINE."""
    fun.validar(list(dados.carregar_jogadores_online().columns))


def _salas():
    return current_app.extensions["salas"]


def _tokens() -> dict[str, str]:
    """sala -> token, da mais antiga para a mais recente.

    No cookie fica uma LISTA de pares [sala, token]: o Flask ordena as chaves dos dicionários ao
    gravar o cookie, e aqui a ordem conta (para esquecer as salas mais antigas primeiro).
    """
    guardado = session.get("salas")
    tokens: dict[str, str] = {}
    if isinstance(guardado, list):
        for par in guardado:
            if isinstance(par, (list, tuple)) and len(par) == 2 and all(isinstance(x, str) for x in par):
                tokens[par[0]] = par[1]
    return tokens


def _guardar(tokens: dict[str, str]) -> None:
    session["salas"] = [[sala_id, token] for sala_id, token in tokens.items()]


def token_da_sessao(sala_id) -> str | None:
    """O token do lugar que o utilizador tem nesta sala (None se não tem). Também usado pelo SocketIO."""
    return _tokens().get(sala_id) if isinstance(sala_id, str) else None


def _lembrar(sala_id: str, token: str) -> None:
    tokens = _tokens()
    tokens.pop(sala_id, None)
    tokens[sala_id] = token
    while len(tokens) > SALAS_NA_SESSAO:
        tokens.pop(next(iter(tokens)))
    _guardar(tokens)


def _esquecer(sala_id: str) -> None:
    tokens = _tokens()
    if tokens.pop(sala_id, None) is not None:
        _guardar(tokens)


def id_valido(sala_id: str) -> bool:
    try:
        return str(uuid.UUID(sala_id)) == sala_id
    except (ValueError, AttributeError, TypeError):
        return False


def _exige_nome(vista):
    @wraps(vista)
    def envolvida(*args, **kwargs):
        if not session.get("nome"):
            # Quem chega por um convite sem nome: guarda o convite e pede o nome primeiro.
            sala_id = kwargs.get("sala_id")
            if sala_id and id_valido(sala_id):
                session["convite"] = sala_id
            return redirect(url_for("inicio"))
        return vista(*args, **kwargs)
    return envolvida


@bp.after_request
def sem_cache(resposta):
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


# --------------------------------------------------------------------------- #
# O painel: o que cada jogador vê (HTML pronto a mostrar)
# --------------------------------------------------------------------------- #

def _lugares(tatica_: taticas.Tatica, escalacao: dict[str, str], posicoes: dict[str, str]) -> list[dict]:
    """O que o desenho do campo precisa de cada posição. Nada de atributos nem de força."""
    lugares = []
    for p in tatica_.posicoes:
        jogador = escalacao[p.id]
        lugares.append({
            "id": p.id,
            "sigla": taticas.SIGLA_PAPEL[p.papel],
            "posicao": p.nome,
            "x": p.x,
            "y": p.y,
            "jogador": jogador,
            "natural": posicoes[jogador],
            "fora": taticas.fora_de_posicao(posicoes[jogador], p),
        })
    return lugares


def _opcoes(tatica_: taticas.Tatica, lugares: list[dict], tatica_vista: dict) -> dict:
    """O que o ecrã mostra para escolher funções, estilo e bolas paradas: só nomes e descrições.

    Os multiplicadores (`pesos`) e as tendências ficam em funcoes.py e nunca chegam aqui.
    """
    por_id = {p.id: p for p in tatica_.posicoes}
    funcoes = []
    for lugar in lugares:
        posicao = por_id[lugar["id"]]
        lista = fun.funcoes_da_posicao(tatica_, posicao)
        escolhida = next(f for f in lista if f.id == tatica_vista["funcoes"][posicao.id])
        funcoes.append({
            "posicao": posicao.id, "sigla": lugar["sigla"], "nome_posicao": posicao.nome, "jogador": lugar["jogador"],
            "opcoes": [{"id": f.id, "nome": f.nome, "descricao": f.descricao} for f in lista],
            "escolhida": {"id": escolhida.id, "nome": escolhida.nome, "descricao": escolhida.descricao},
        })
    estilo = fun.obter_estilo(tatica_vista["estilo"])          # None enquanto o treinador não escolher
    return {
        "estilos": [{"id": e.id, "nome": e.nome, "descricao": e.descricao} for e in fun.ESTILOS],
        "estilo": {"id": estilo.id, "nome": estilo.nome, "descricao": estilo.descricao} if estilo else None,
        "funcoes": funcoes,
        "marcadores": [{"nome": l["jogador"], "posicao": l["posicao"]} for l in lugares if l["sigla"] != "GR"],
        "livres": tatica_vista["livres"],
        "cantos": tatica_vista["cantos"],
    }


def _simular(config_a: dict, config_b: dict, semente: int) -> dict:
    """Corre o motor do Passo 7 com os jogadores do Excel ONLINE (os atributos nunca saem daqui)."""
    fichas = match_engine.fichas_de(dados.carregar_jogadores_online())
    return match_engine.match_engine_online(config_a, config_b, fichas, semente=semente)


def _resultado(sala_id: str, token: str) -> dict:
    """O resultado público do jogo (calculado uma só vez por sala; ver Salas.resultado)."""
    try:
        return _salas().resultado(sala_id, token, _simular)
    except ErroSala:
        raise
    except Exception:                                   # um erro do motor não pode deitar abaixo a sala
        current_app.logger.exception("Falha ao simular o jogo da sala %s", sala_id)
        raise ErroSala("erro_motor", "Não foi possível simular o jogo. Tenta outra vez dentro de instantes.")


def _fim_do_jogo(res: dict, lugar: str) -> dict:
    """O ecrã do fim do jogo, visto de quem o pede: «eu» à esquerda, o adversário à direita."""
    i = 0 if lugar == "A" else 1
    j = 1 - i
    e = res["estatisticas"]
    gols = res["placar"]

    def linha(rotulo, chave, sufixo="", barra=None):
        a_, b_ = e[i][chave], e[j][chave]
        return {"rotulo": rotulo, "eu": f"{a_}{sufixo}", "adv": f"{b_}{sufixo}",
                "pc_eu": _percentagem(e[i][barra or chave], e[j][barra or chave])}

    def par(rotulo, ok, total, pc):
        return {"rotulo": rotulo, "eu": f"{e[i][ok]} / {e[i][total]}", "adv": f"{e[j][ok]} / {e[j][total]}",
                "pc_eu": _percentagem(e[i][ok], e[j][ok])}

    principais = [
        linha("Golos", "golos"),
        linha("Posse de bola", "posse", " %"),
        linha("Remates", "remates"),
        linha("Remates à baliza", "remates_baliza"),
        linha("Defesas do guarda-redes", "defesas"),
        par("Passes completos / tentados", "passes_ok", "passes", "passes_pc"),
        linha("Passes completos (%)", "passes_pc", " %"),
        linha("Desarmes", "desarmes"),
        linha("Interceções", "intercecoes"),
    ]
    extras = [
        linha("Cantos", "cantos"), linha("Livres perigosos", "livres"), linha("Faltas", "faltas"),
        linha("Cruzamentos", "cruzamentos"), linha("Passes longos", "passes_longos"),
        par("Dribles certos / tentados", "dribles_ok", "dribles", None),
        linha("Contra-ataques", "contra_ataques"), linha("Remates bloqueados", "remates_bloqueados"),
        linha("Golos de bola parada", "golos_bola_parada"),
    ]
    marcadores = [[{"minuto": g["minuto"], "jogador": g["jogador"], "assistencia": g.get("assistencia"),
                    "como": ORIGEM_GOLO.get(g.get("origem"), "")} for g in res["marcadores"][k]] for k in (i, j)]
    if gols[i] > gols[j]:
        resultado = "vitoria"
    elif gols[i] < gols[j]:
        resultado = "derrota"
    else:
        resultado = "empate"
    return {"resultado": resultado, "placar": [gols[i], gols[j]], "equipas": [res["equipas"][i], res["equipas"][j]],
            "principais": principais, "extras": extras, "marcadores": marcadores, "relato": res["relato"]}


def _percentagem(a, b) -> int:
    """Que parte do traço pertence a quem pede (para as barras; 50 se não há nada para comparar)."""
    total = a + b
    return 50 if not total else round(100 * a / total)


def _contexto(sala_id: str, token: str) -> dict:
    """A vista da sala para este lugar + o que os templates precisam. Levanta ErroSala se não houver sala/lugar."""
    salas = _salas()
    vista = salas.vista(sala_id, token)
    fim = None
    if vista["estado"] == "pronta":                     # os dois estão prontos: o jogo faz-se agora (uma só vez)
        res = _resultado(sala_id, token)
        vista = salas.vista(sala_id, token)             # já traz «calculado»: a assinatura do painel não muda a seguir
        fim = _fim_do_jogo(res, vista["lugar"])
    posicoes = posicoes_online()
    if (set(vista["equipa"]) | set(vista["equipa_adversario"])) - set(posicoes):
        raise ErroSala("dados_mudaram", "Os dados do jogo mudaram durante a partida. Cria uma sala nova.")
    contexto = {
        "v": vista,
        "nome": vista["nome"],
        "posicoes": posicoes,
        "tamanho": draft.TAMANHO_EQUIPA,
        "taticas": list(taticas.TATICAS.values()),
        "url_trocar": url_for("online.trocar", sala_id=sala_id),
        "url_convite": url_for("online.convite", sala_id=sala_id),
        "convite_externo": url_for("online.convite", sala_id=sala_id, _external=True),
    }
    if fim is not None:
        contexto["fim"] = fim
        contexto["url_eventos"] = url_for("online.eventos", sala_id=sala_id)
        contexto["url_filme"] = url_for("online.filme", sala_id=sala_id)
    tatica_ = taticas.obter_tatica(vista["tatica"]["escolhida"])
    escalacao = vista["tatica"]["escalacao"]
    if tatica_ is not None and taticas.escalacao_valida(tatica_, escalacao, vista["equipa"]):
        contexto["tatica_atual"] = tatica_
        contexto["lugares"] = _lugares(tatica_, escalacao, posicoes)
        contexto["o"] = _opcoes(tatica_, contexto["lugares"], vista["tatica"])
    return contexto


def _assinatura(vista: dict) -> str:
    """Uma «impressão digital» do que o painel mostra: muda se, e só se, o painel muda."""
    return hashlib.sha1(json.dumps(vista, sort_keys=True).encode("utf8")).hexdigest()[:12]


def _painel(sala_id: str, token: str, assinatura_cliente: str | None = None, forcar: bool = False) -> dict:
    """O JSON do estado: assinatura, html (None se o cliente já tem este painel) e presença do adversário."""
    contexto = _contexto(sala_id, token)
    assinatura = _assinatura(contexto["v"])
    html = None
    if forcar or assinatura_cliente != assinatura:
        html = render_template("online/_painel.html", **contexto)
    return {
        "assinatura": assinatura,
        "html": html,
        "estado": contexto["v"]["estado"],
        "presenca": _salas().presenca(sala_id, token),
    }


def _erro_json(erro: ErroSala, sala_id: str | None = None, token: str | None = None):
    """Resposta de erro; sempre que possível leva o estado atual para o browser se pôr em dia."""
    corpo = {"erro": erro.codigo, "mensagem": erro.mensagem}
    if erro.codigo in ("sala_inexistente", "sem_lugar", "dados_mudaram"):
        corpo["destino"] = url_for("online.lobby")
    elif sala_id and token:
        try:
            corpo.update(_painel(sala_id, token, forcar=True))
        except ErroSala:
            pass
    return jsonify(corpo), STATUS_ERRO.get(erro.codigo, 409)


def _pagina_de_erro(titulo: str, mensagem: str, status: int):
    return render_template("online/erro.html", titulo=titulo, mensagem=mensagem), status


# --------------------------------------------------------------------------- #
# Início, criar sala, convite
# --------------------------------------------------------------------------- #

@bp.get("")
@_exige_nome
def lobby():
    salas = _salas()
    em_curso = []
    for sala_id, token in _tokens().items():
        try:
            vista = salas.vista(sala_id, token)
        except ErroSala:
            _esquecer(sala_id)
            continue
        if vista["estado"] != ABANDONADA:
            em_curso.append({"id": sala_id, "adversario": vista["adversario"], "espera": vista["estado"] == ESPERA})
    return render_template("online/lobby.html", nome=session["nome"], em_curso=em_curso[::-1])


@bp.post("/criar")
@_exige_nome
def criar():
    try:
        sala_id, token = _salas().criar(session["nome"], list(posicoes_online()))
    except ErroSala as erro:
        return _pagina_de_erro("Não foi possível criar a sala", erro.mensagem, STATUS_ERRO.get(erro.codigo, 409))
    _lembrar(sala_id, token)
    return redirect(url_for("online.sala", sala_id=sala_id))


@bp.get("/convite/<sala_id>")
@_exige_nome
def convite(sala_id):
    salas = _salas()
    token = token_da_sessao(sala_id)
    if token and salas.lugar_de(sala_id, token):
        return redirect(url_for("online.sala", sala_id=sala_id))          # já estás nesta sala
    info = salas.convite(sala_id) if id_valido(sala_id) else None
    if info is None:
        return _pagina_de_erro("Esta sala já não existe",
                               "O link pode estar errado ou a sala já fechou. Pede um link novo ao teu amigo, "
                               "ou cria tu uma sala.", 404)
    if info["fechada"]:
        return _pagina_de_erro("Esta sala já fechou",
                               "O jogo desta sala terminou. Podes criar uma sala tua e convidar um amigo.", 409)
    if not info["livre"]:
        return _pagina_de_erro("Esta sala já está cheia",
                               "Já há dois jogadores nesta sala. Podes criar uma sala tua e convidar um amigo.", 409)
    return render_template("online/convite.html", nome=session["nome"], anfitriao=info["anfitriao"], sala_id=sala_id)


@bp.post("/convite/<sala_id>")
@_exige_nome
def entrar(sala_id):
    try:
        token = _salas().entrar(sala_id, session["nome"]) if id_valido(sala_id) else None
        if token is None:
            raise ErroSala("sala_inexistente", "Esta sala já não existe.")
    except ErroSala as erro:
        return _pagina_de_erro("Não foi possível entrar na sala", erro.mensagem, STATUS_ERRO.get(erro.codigo, 409))
    _lembrar(sala_id, token)
    tempo_real.avisar(sala_id)
    return redirect(url_for("online.sala", sala_id=sala_id))


# --------------------------------------------------------------------------- #
# A sala
# --------------------------------------------------------------------------- #

@bp.get("/sala/<sala_id>")
def sala(sala_id):
    token = token_da_sessao(sala_id)
    salas = _salas()
    if not token or salas.lugar_de(sala_id, token) is None:
        if token:
            _esquecer(sala_id)
        if id_valido(sala_id) and salas.existe(sala_id):
            return redirect(url_for("online.convite", sala_id=sala_id))
        return _pagina_de_erro("Esta sala já não existe",
                               "A sala fechou ou o link está errado. Podes criar uma sala nova.", 404)
    try:
        contexto = _contexto(sala_id, token)
    except ErroSala as erro:
        if erro.codigo != "erro_motor":                 # se foi o motor que falhou, o lugar continua teu
            _esquecer(sala_id)
        return _pagina_de_erro("Não foi possível abrir a sala", erro.mensagem, STATUS_ERRO.get(erro.codigo, 409))
    painel = render_template("online/_painel.html", **contexto)
    return render_template(
        "online/sala.html", painel=painel, assinatura=_assinatura(contexto["v"]),
        sala_id=sala_id, nome=contexto["nome"], presenca=_salas().presenca(sala_id, token),
        tempo_real=tempo_real.disponivel(),
        url_estado=url_for("online.estado", sala_id=sala_id), url_acao=url_for("online.acao", sala_id=sala_id),
    )


@bp.get("/sala/<sala_id>/estado")
def estado(sala_id):
    token = token_da_sessao(sala_id)
    try:
        if not token:
            raise ErroSala("sem_lugar", "Não tens lugar nesta sala.")
        return jsonify(_painel(sala_id, token, request.args.get("a")))
    except ErroSala as erro:
        return _erro_json(erro, sala_id, token)


@bp.get("/sala/<sala_id>/eventos")
def eventos(sala_id):
    """Os eventos do jogo (com a posição de todos) para o Passo 8. Só quem tem lugar na sala, e só depois do jogo."""
    token = token_da_sessao(sala_id)
    try:
        if not token:
            raise ErroSala("sem_lugar", "Não tens lugar nesta sala.")
        corpo = _salas().eventos(sala_id, token)
    except ErroSala as erro:
        return _erro_json(erro)
    return current_app.response_class(corpo, mimetype="application/json", headers={"Content-Encoding": "deflate"})


@bp.get("/sala/<sala_id>/filme")
def filme(sala_id):
    """O filme do jogo (trajetórias, bola, animações, comentários) para a simulação visual: ver `visual.py`.
    Só quem tem lugar na sala, e só depois do jogo. Cada um recebe o seu (com ele próprio à esquerda)."""
    token = token_da_sessao(sala_id)
    try:
        if not token:
            raise ErroSala("sem_lugar", "Não tens lugar nesta sala.")
        corpo = _salas().filme(sala_id, token)
    except ErroSala as erro:
        return _erro_json(erro)
    return current_app.response_class(corpo, mimetype="application/json",
                                      headers={"Content-Encoding": "deflate", "Cache-Control": "private, max-age=3600"})


def _tatica_valida(valor):
    return valor if isinstance(valor, (int, str)) and not isinstance(valor, bool) else None


@bp.post("/sala/<sala_id>/acao")
def acao(sala_id):
    token = token_da_sessao(sala_id)
    pedido = request.get_json(silent=True)
    if not isinstance(pedido, dict) or not isinstance(pedido.get("acao"), str):
        return jsonify(erro="pedido_invalido", mensagem="Pedido inválido."), 400
    nome_acao = pedido["acao"]
    salas = _salas()
    try:
        if not token:
            raise ErroSala("sem_lugar", "Não tens lugar nesta sala.")
        if nome_acao == "escolher":
            salas.escolher(sala_id, token, pedido.get("jogador"))
        elif nome_acao == "tatica":
            salas.escolher_tatica(sala_id, token, _tatica_valida(pedido.get("tatica")), posicoes_online())
        elif nome_acao == "mudar_tatica":
            salas.mudar_tatica(sala_id, token, True)
        elif nome_acao == "cancelar_mudar":
            salas.mudar_tatica(sala_id, token, False)
        elif nome_acao == "funcao":
            salas.escolher_funcao(sala_id, token, pedido.get("posicao"), pedido.get("funcao"))
        elif nome_acao == "estilo":
            salas.escolher_estilo(sala_id, token, pedido.get("estilo"))
        elif nome_acao in ("livres", "cantos"):
            salas.escolher_marcador(sala_id, token, nome_acao, pedido.get("jogador"))
        elif nome_acao == "pronto":
            salas.pronto(sala_id, token, True)
        elif nome_acao == "editar":
            salas.pronto(sala_id, token, False)
        elif nome_acao == "sair":
            salas.sair(sala_id, token)
            _esquecer(sala_id)
            tempo_real.avisar(sala_id)
            return jsonify(saiu=True, destino=url_for("online.lobby"))
        else:
            return jsonify(erro="acao_desconhecida", mensagem="Ação desconhecida."), 400
        resposta = _painel(sala_id, token, forcar=True)
    except ErroSala as erro:
        return _erro_json(erro, sala_id, token)
    tempo_real.avisar(sala_id)
    return jsonify(resposta)


@bp.post("/sala/<sala_id>/trocar")
def trocar(sala_id):
    token = token_da_sessao(sala_id)
    pedido = request.get_json(silent=True)
    if not isinstance(pedido, dict):
        return jsonify(erro="pedido_invalido", mensagem="Pedido inválido."), 400
    try:
        if not token:
            raise ErroSala("sem_lugar", "Não tens lugar nesta sala.")
        _salas().trocar(sala_id, token, pedido.get("a"), pedido.get("b"))
        contexto = _contexto(sala_id, token)
    except ErroSala as erro:
        status = 400 if erro.codigo == "posicao_invalida" else None
        resposta, codigo = _erro_json(erro, sala_id, token)
        return resposta, status or codigo
    return jsonify(lugares={l["id"]: l for l in contexto["lugares"]}, assinatura=_assinatura(contexto["v"]),
                   opcoes=render_template("online/_opcoes.html", **contexto))
