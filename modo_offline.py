"""
modo_offline.py — rotas do MODO OFFLINE (Passos 2 e 3: sorteio, tática e posições)
===================================================================================

Separação dos modos: este ficheiro só importa funções *_offline() do data_loader.

Rotas:
    GET  /jogar/offline                sorteio: 5 jogadores, o utilizador escolhe 1 (7 vezes)
    POST /jogar/offline/escolher       regista a escolha e volta ao sorteio
    GET  /jogar/offline/tatica         escolher a tática (4 opções)
    POST /jogar/offline/tatica         guarda a tática e coloca os jogadores no campo
    GET  /jogar/offline/equipa         a equipa no campo (trocar jogadores de posição)
    POST /jogar/offline/equipa/trocar  troca dois jogadores de posição (JSON, chamado pelo JavaScript)
    POST /jogar/offline/liga           simula a liga (uma só vez) e guarda o resultado
    GET  /jogar/offline/liga           os 22 jogos do utilizador, a aparecerem um a um
    GET  /jogar/offline/liga/classificacao   tabela final das 12 equipas + melhores marcadores
    GET  /jogar/offline/liga/top10     top 10 de todos os utilizadores (e a posição do utilizador)
    POST /jogar/offline/novo           começa um jogo novo (com o mesmo nome)

Estado do jogo, na sessão (cookie assinado, o utilizador não o consegue alterar):
    session["offline"] = {
        "equipa":   [nomes, por ordem de escolha],
        "sorteio":  [os 5 nomes que estão em jogo agora],
        "tatica":   1 a 4 (ou ausente),
        "escalacao": {"p1": nome, … "p7": nome},   # posição -> jogador
        "liga":     token da liga simulada (ou ausente),
    }
Depois de a liga ser simulada o resultado fica guardado no servidor (armazem.py) e a equipa já
não se pode mexer: senão bastava repetir a liga até sair um bom resultado.
O sorteio atual fica guardado para que atualizar a página NÃO volte a sortear
(senão bastava carregar em F5 até sair uma boa equipa).

O cookie é legível pelo utilizador (só não o consegue alterar), por isso NUNCA guarda
atributos nem a força da equipa. Estes só existem no servidor, quando são calculados
(forca.py). Para as páginas só vão o nome, a posição natural e se está "fora de posição".
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

import data_loader as dados
import draft
import forca
import liga
import taticas

bp = Blueprint("offline", __name__, url_prefix="/jogar/offline")

CHAVE_SESSAO = "offline"


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #

def reiniciar() -> None:
    """Apaga o jogo offline em curso (usado quando alguém entra com o nome no ecrã inicial)."""
    session.pop(CHAVE_SESSAO, None)


def _ler_estado() -> dict:
    guardado = session.get(CHAVE_SESSAO) or {}
    tatica = taticas.obter_tatica(guardado.get("tatica"))
    escalacao = guardado.get("escalacao")
    return {
        "equipa": list(guardado.get("equipa", [])),
        "sorteio": list(guardado.get("sorteio", [])),
        "tatica": tatica.id if tatica else None,
        "escalacao": dict(escalacao) if isinstance(escalacao, dict) else {},
        "liga": guardado.get("liga") if isinstance(guardado.get("liga"), str) else None,
    }


def _guardar_estado(estado: dict) -> None:
    guardar = {"equipa": estado["equipa"], "sorteio": estado["sorteio"]}
    if estado.get("tatica"):
        guardar["tatica"] = estado["tatica"]
        guardar["escalacao"] = estado["escalacao"]
    if estado.get("liga"):
        guardar["liga"] = estado["liga"]
    session[CHAVE_SESSAO] = guardar


def _armazem():
    return current_app.extensions["armazem"]


def _liga_atual() -> dict | None:
    """A liga já simulada neste jogo (id, nome, dados), ou None se ainda não foi simulada.

    Se o token da sessão já não existe na base de dados (por exemplo o disco do servidor foi
    apagado), esquece-o: o utilizador volta à equipa e pode simular outra vez.
    """
    estado = _ler_estado()
    if not estado["liga"]:
        return None
    encontrada = _armazem().obter_liga(estado["liga"])
    if encontrada is None:
        estado["liga"] = None
        _guardar_estado(estado)
    return encontrada


def _posicoes() -> dict[str, str]:
    """Nome -> posição de todos os jogadores do Excel OFFLINE (só isto vai para as páginas)."""
    jogadores = dados.carregar_jogadores_offline()
    return dict(zip(jogadores["Nome"], jogadores["Posição"]))


def _estado_da_equipa(posicoes: dict[str, str]) -> dict:
    """Lê o estado e deita fora nomes que já não existem no Excel (se foi alterado a meio do jogo)."""
    estado = _ler_estado()
    estado["equipa"] = [nome for nome in estado["equipa"] if nome in posicoes]
    return estado


def _exige_nome(vista):
    """Sem nome na sessão (não passou pelo ecrã inicial), volta ao início."""
    @wraps(vista)
    def envolvida(*args, **kwargs):
        if not session.get("nome"):
            return redirect(url_for("inicio"))
        return vista(*args, **kwargs)
    return envolvida


@bp.after_request
def sem_cache(resposta):
    # O botão "Voltar" do browser não deve mostrar um sorteio ou uma equipa antigos.
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


# --------------------------------------------------------------------------- #
# Sorteio
# --------------------------------------------------------------------------- #

@bp.get("")
@_exige_nome
def sorteio():
    posicoes = _posicoes()
    estado = _estado_da_equipa(posicoes)

    if draft.equipa_completa(estado["equipa"]):
        return redirect(url_for("offline.equipa" if estado["tatica"] else "offline.tatica"))

    oferta_valida = bool(estado["sorteio"]) and all(
        nome in posicoes and nome not in estado["equipa"] for nome in estado["sorteio"]
    )
    if not oferta_valida:
        estado["sorteio"] = draft.sortear_opcoes(list(posicoes), estado["equipa"])
    _guardar_estado(estado)

    return render_template(
        "sorteio.html",
        opcoes=estado["sorteio"],
        equipa=estado["equipa"],
        posicoes=posicoes,
        numero=len(estado["equipa"]) + 1,
        tamanho=draft.TAMANHO_EQUIPA,
        nova_escolha=bool(estado["equipa"]),
    )


@bp.post("/escolher")
@_exige_nome
def escolher():
    estado = _ler_estado()
    jogador = request.form.get("jogador", "")

    # Só vale um jogador que esteja mesmo no sorteio atual (e ainda não escolhido).
    # Um clique repetido ou uma página antiga não faz nada: volta ao sorteio atual.
    if (
        jogador in estado["sorteio"]
        and jogador not in estado["equipa"]
        and not draft.equipa_completa(estado["equipa"])
    ):
        estado["equipa"].append(jogador)
        estado["sorteio"] = []          # o sorteio seguinte é feito ao abrir o ecrã
        _guardar_estado(estado)

    return redirect(url_for("offline.sorteio"))


# --------------------------------------------------------------------------- #
# Tática
# --------------------------------------------------------------------------- #

@bp.get("/tatica")
@_exige_nome
def tatica():
    if _liga_atual():
        return redirect(url_for("offline.liga_jogos"))
    posicoes = _posicoes()
    estado = _estado_da_equipa(posicoes)
    if not draft.equipa_completa(estado["equipa"]):
        return redirect(url_for("offline.sorteio"))

    return render_template(
        "tatica.html",
        taticas=list(taticas.TATICAS.values()),
        atual=estado["tatica"],
        equipa=estado["equipa"],
        posicoes=posicoes,
        tamanho=draft.TAMANHO_EQUIPA,
        nova_escolha=False,
    )


@bp.post("/tatica")
@_exige_nome
def escolher_tatica():
    if _liga_atual():
        return redirect(url_for("offline.liga_jogos"))
    posicoes = _posicoes()
    estado = _estado_da_equipa(posicoes)
    if not draft.equipa_completa(estado["equipa"]):
        return redirect(url_for("offline.sorteio"))

    nova = taticas.obter_tatica(request.form.get("tatica"))
    if nova is None:
        return redirect(url_for("offline.tatica"))

    antiga = taticas.obter_tatica(estado["tatica"])
    escalacao_atual = estado["escalacao"]
    atual_valida = antiga is not None and taticas.escalacao_valida(antiga, escalacao_atual, estado["equipa"])

    if atual_valida and antiga.id == nova.id:
        pass                                    # a mesma tática: tudo fica como estava
    elif atual_valida:
        # Mudar de tática: cada jogador tenta ficar no mesmo papel (GR, defesa, médio, avançado).
        papeis = taticas.papeis_da_escalacao(antiga, escalacao_atual)
        estado["escalacao"] = taticas.distribuir(nova, estado["equipa"], posicoes, papeis)
    else:
        estado["escalacao"] = taticas.distribuir(nova, estado["equipa"], posicoes)
    estado["tatica"] = nova.id
    _guardar_estado(estado)
    return redirect(url_for("offline.equipa"))


# --------------------------------------------------------------------------- #
# A equipa no campo
# --------------------------------------------------------------------------- #

def _equipa_pronta() -> tuple[dict, taticas.Tatica, dict[str, str]] | None:
    """(estado, tática, posições naturais) se há equipa completa, tática e escalação válida; senão None."""
    posicoes = _posicoes()
    estado = _estado_da_equipa(posicoes)
    tatica_ = taticas.obter_tatica(estado["tatica"])
    if (
        not draft.equipa_completa(estado["equipa"])
        or tatica_ is None
        or not taticas.escalacao_valida(tatica_, estado["escalacao"], estado["equipa"])
    ):
        return None
    return estado, tatica_, posicoes


def _lugares(tatica_: taticas.Tatica, escalacao: dict[str, str], posicoes: dict[str, str]) -> list[dict]:
    """O que as páginas precisam de saber de cada posição. Nada de atributos nem de força."""
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


@bp.get("/equipa")
@_exige_nome
def equipa():
    if _liga_atual():
        return redirect(url_for("offline.liga_jogos"))
    pronta = _equipa_pronta()
    if pronta is None:
        # Falta equipa completa (volta ao sorteio) ou tática (escolhe-se agora).
        estado = _estado_da_equipa(_posicoes())
        destino = "offline.tatica" if draft.equipa_completa(estado["equipa"]) else "offline.sorteio"
        return redirect(url_for(destino))
    estado, tatica_, posicoes = pronta

    return render_template(
        "equipa.html",
        nome=session["nome"],
        tatica=tatica_,
        lugares=_lugares(tatica_, estado["escalacao"], posicoes),
        adversarios=len(liga_equipas_adversarias()),     # só o número: as forças nunca saem do servidor
    )


@bp.post("/equipa/trocar")
@_exige_nome
def trocar():
    if _liga_atual():
        return jsonify(erro="liga_ja_jogada"), 409
    pronta = _equipa_pronta()
    if pronta is None:
        return jsonify(erro="sem_equipa"), 409
    estado, tatica_, posicoes = pronta

    pedido = request.get_json(silent=True)           # só aceita application/json
    if not isinstance(pedido, dict):
        return jsonify(erro="pedido_invalido"), 400
    a, b = pedido.get("a"), pedido.get("b")
    ids = {p.id for p in tatica_.posicoes}
    if not (isinstance(a, str) and isinstance(b, str) and a in ids and b in ids):
        return jsonify(erro="posicao_invalida"), 400

    estado["escalacao"] = taticas.trocar(estado["escalacao"], a, b)
    _guardar_estado(estado)
    return jsonify(lugares={l["id"]: l for l in _lugares(tatica_, estado["escalacao"], posicoes)})


# --------------------------------------------------------------------------- #
# A liga
# --------------------------------------------------------------------------- #

def liga_equipas_adversarias() -> dict[str, float]:
    """Equipas adversárias do Excel OFFLINE: nome -> força (só no servidor, nunca vai para as páginas)."""
    equipas = dados.carregar_equipas_offline()
    return dict(zip(equipas["Nome da Equipa"], equipas["Força da Equipa"].astype(float)))


@bp.post("/liga")
@_exige_nome
def comecar_liga():
    """Simula a liga. Só acontece UMA vez por jogo: pedir outra vez mostra a mesma liga."""
    if _liga_atual():
        return redirect(url_for("offline.liga_jogos"))
    pronta = _equipa_pronta()
    if pronta is None:
        return redirect(url_for("offline.equipa"))
    estado, tatica_, _posicoes_naturais = pronta

    jogadores = dados.carregar_jogadores_offline()
    forcas = liga_equipas_adversarias()
    forcas[liga.NOME_EQUIPA_UTILIZADOR] = forca.forca_equipa(tatica_, estado["escalacao"], jogadores)
    pesos = liga.pesos_de_golo(tatica_, estado["escalacao"], jogadores)

    resultado = liga.simular_liga_offline(forcas, pesos).para_dict()
    _id, token = _armazem().guardar_liga(session["nome"], resultado)

    estado["liga"] = token
    _guardar_estado(estado)
    return redirect(url_for("offline.liga_jogos"))


def _pagina_da_liga(modelo: str, **extra):
    """Mostra uma página dos resultados da liga, ou volta à equipa se a liga ainda não foi simulada."""
    guardada = _liga_atual()
    if guardada is None:
        return redirect(url_for("offline.equipa"))
    return render_template(modelo, nome=session["nome"], liga_id=guardada["id"], liga=guardada["dados"], **extra)


@bp.get("/liga")
@_exige_nome
def liga_jogos():
    return _pagina_da_liga("liga.html")


@bp.get("/liga/classificacao")
@_exige_nome
def classificacao():
    return _pagina_da_liga("classificacao.html")


@bp.get("/liga/top10")
@_exige_nome
def top10():
    guardada = _liga_atual()
    if guardada is None:
        return redirect(url_for("offline.equipa"))
    armazem = _armazem()
    top = armazem.top(10)
    minha = armazem.posicao(guardada["id"])
    return render_template(
        "top10.html",
        nome=session["nome"],
        liga_id=guardada["id"],
        top=top,
        minha=minha,
        fora_do_top=minha is not None and minha["id"] not in {linha["id"] for linha in top},
        total=armazem.total(),
    )


@bp.post("/novo")
@_exige_nome
def novo_jogo():
    """Jogar outra vez, com o mesmo nome: apaga o jogo atual e volta ao sorteio."""
    reiniciar()
    return redirect(url_for("offline.sorteio"))
