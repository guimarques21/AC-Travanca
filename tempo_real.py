"""
tempo_real.py — a «campainha» em tempo real (Flask-SocketIO), OPCIONAL
=====================================================================

O enunciado pede WebSockets (Flask-SocketIO) para sincronizar o sorteio entre os dois jogadores.
Aqui o SocketIO faz só uma coisa: quando algo muda numa sala, TOCA A CAMPAINHA («mudou») a quem está
nessa sala. Ao ouvir a campainha, o browser pede ao servidor o estado atual (pedido normal, que passa
sempre pelas mesmas validações e só mostra a cada jogador o que ele pode ver).

Vantagens deste desenho:
  - Se o SocketIO não estiver instalado, ou o WebSocket for bloqueado (redes de empresas, alguns
    telemóveis), o jogo continua a funcionar: o browser pergunta ao servidor de 2 em 2 segundos.
  - Nada importante passa pelo WebSocket: a campainha não leva dados.

Pacotes (ver requirements.txt): flask-socketio e simple-websocket. No Render o servidor tem de ser
UM processo com várias threads (ver README): as salas vivem na memória desse processo.
"""

from __future__ import annotations

import logging

try:
    from flask_socketio import SocketIO, join_room
except ImportError:                      # pacote não instalado: sem campainha, só consulta periódica
    SocketIO = None
    join_room = None

log = logging.getLogger(__name__)

socketio = None                          # fica definido por iniciar(), se o pacote existir


def disponivel() -> bool:
    return socketio is not None


def iniciar(app, salas, token_da_sessao) -> bool:
    """Liga o SocketIO à aplicação (se o pacote estiver instalado). Devolve True se ficou ligado.

    `token_da_sessao(sala_id)` devolve o token do lugar que o utilizador (cookie de sessão) tem nessa sala.
    """
    global socketio
    if SocketIO is None:
        app.logger.warning(
            "flask-socketio não está instalado: o modo online funciona, mas sincroniza por consulta "
            "de 2 em 2 segundos (sem tempo real). Instala com: pip install flask-socketio simple-websocket"
        )
        return False

    # threading + simple-websocket: serve com gunicorn -k gthread (sem eventlet/gevent).
    # cors "*": a campainha não leva dados e quem entra numa sala é validado pelo cookie de sessão
    # (SameSite=Lax: não vai em pedidos de outros sites).
    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*",
                        logger=False, engineio_logger=False)

    @socketio.on("entrar_sala")
    def entrar_sala(dados=None):
        sala_id = dados.get("sala") if isinstance(dados, dict) else None
        token = token_da_sessao(sala_id) if isinstance(sala_id, str) else None
        if token and salas.lugar_de(sala_id, token):
            join_room(sala_id)
            return {"ok": True}
        return {"ok": False}

    return True


def avisar(sala_id: str) -> None:
    """Toca a campainha a todos os que estão nesta sala. Sem SocketIO não faz nada (há a consulta periódica)."""
    if socketio is not None:
        try:
            socketio.emit("mudou", {}, to=sala_id)
        except Exception:                # a campainha nunca pode estragar uma jogada
            log.exception("Falhou o aviso em tempo real da sala %s", sala_id)


def executar(app, host: str, port: int, debug: bool) -> None:
    """Arranca o servidor de desenvolvimento (com WebSocket, se o SocketIO existir)."""
    if socketio is not None:
        socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=debug)
