"""
app.py — AC Travanca (fundação, modo offline e modo online)
===========================================================

Correr no PC:      python app.py            -> http://127.0.0.1:5000
Correr no Render:  gunicorn app:app         (ver render.yaml)

Rotas:
    /                  ecrã inicial (nome obrigatório + botões Offline / Online)
    POST /entrar       valida o nome NO SERVIDOR, guarda-o na sessão e redireciona
    /jogar/offline...  modo offline: sorteio e escolha dos 7 jogadores (modo_offline.py;
                       usa SÓ os Excel do modo offline)
    /jogar/online...   modo online: salas privadas com link de convite, sorteio à vez e tática
                       (modo_online.py, salas.py, tempo_real.py; usa SÓ o Excel do modo online)
    /healthz           verificação de saúde (Render)
"""

from __future__ import annotations

import logging
import os
import secrets
import unicodedata
from datetime import timedelta
from pathlib import Path

from flask import Flask, abort, make_response, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import data_loader as dados
import modo_offline
import modo_online
import tempo_real
from armazem import Armazem, ArmazemIndisponivel
from salas import Salas

# --------------------------------------------------------------------------- #
# Regras do nome do jogador (a mesma regra é aplicada no browser, em static/js/home.js)
# --------------------------------------------------------------------------- #
NOME_MIN = 2
NOME_MAX = 20
NOME_SIMBOLOS_PERMITIDOS = " .'’-_"   # além de letras e números

MENSAGENS_NOME = {
    "curto": f"Escreve o teu nome (mínimo {NOME_MIN} caracteres) para continuar.",
    "caracteres": "Usa só letras, números e espaços no nome.",
}

MODOS = ("offline", "online")

# Para onde vai cada modo depois de o nome ser aceite (nome da rota no Flask).
DESTINOS = {"offline": "offline.sorteio", "online": "online.lobby"}


def validar_nome(bruto: str | None) -> tuple[str, str | None]:
    """Limpa e valida o nome. Devolve (nome_limpo, mensagem_de_erro | None)."""
    # NFC: junta letra+acento separados; " ".join(split()): tira espaços a mais.
    nome = " ".join(unicodedata.normalize("NFC", bruto or "").split())

    if len(nome) < NOME_MIN:
        return nome, MENSAGENS_NOME["curto"]
    if len(nome) > NOME_MAX:
        return nome[:NOME_MAX], f"O nome pode ter no máximo {NOME_MAX} caracteres."
    if not any(c.isalnum() for c in nome) or not all(
        c.isalnum() or c in NOME_SIMBOLOS_PERMITIDOS for c in nome
    ):
        return nome, MENSAGENS_NOME["caracteres"]
    return nome, None


# --------------------------------------------------------------------------- #
# Fábrica da aplicação
# --------------------------------------------------------------------------- #
def create_app() -> Flask:
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)

    # --- Configuração -------------------------------------------------------
    # SECRET_KEY assina o cookie de sessão (guarda o nome do jogador).
    # No Render define a variável de ambiente SECRET_KEY (o render.yaml já gera uma).
    # Sem ela, usa-se uma chave aleatória: funciona, mas as sessões perdem-se
    # sempre que a app reinicia (e não funcionaria com vários workers).
    chave = os.environ.get("SECRET_KEY")
    if not chave:
        chave = secrets.token_hex(32)
        app.logger.warning("SECRET_KEY não definida: a usar chave temporária (só para desenvolvimento).")

    app.config.update(
        SECRET_KEY=chave,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # o Render serve em HTTPS
        # Ficheiros estáticos (incluindo a música) ficam em cache 30 dias no browser.
        # É seguro porque os URLs levam ?v=<data do ficheiro> (ver static_v abaixo).
        SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=30),
    )

    # No Render há um proxy à frente da aplicação (HTTPS -> HTTP): sem isto o Flask pensaria que o site é
    # http e os links de convite saíam com o endereço errado.
    if os.environ.get("RENDER"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # --- Classificação geral: onde ficam guardadas as ligas e o Top 10 ---------
    #  - DATABASE_URL (postgresql://…): base de dados EXTERNA e gratuita (ex.: Neon). É o que faz o Top 10
    #    ficar guardado para sempre no Render gratuito, cujo disco é apagado a cada reinício (ver README).
    #  - senão, um ficheiro SQLite: DATABASE_PATH, ou instance/ranking.sqlite3 (é o que se usa no PC).
    url_bd = (os.environ.get("DATABASE_URL") or "").strip()
    caminho_bd = os.environ.get("DATABASE_PATH") or str(Path(app.instance_path) / "ranking.sqlite3")
    app.config["DATABASE_PATH"] = caminho_bd
    app.extensions["armazem"] = armazem = Armazem(url_bd or caminho_bd)
    if os.environ.get("RENDER") and armazem.tipo == "sqlite" and not os.environ.get("DATABASE_PATH"):
        app.logger.warning(
            "DATABASE_URL não definida no Render: as ligas ficam num ficheiro que o Render apaga sempre que o "
            "serviço reinicia, por isso o Top 10 também será apagado. Ver no README «Top 10 guardado para sempre»."
        )
    try:
        app.logger.info("Classificação geral em %s (%d ligas jogadas).", armazem.descricao(), armazem.total())
    except ArmazemIndisponivel as erro:
        # Não impede a app de arrancar (a base gratuita pode estar a acordar): tenta outra vez a cada pedido.
        app.logger.warning("Classificação geral em %s: ainda sem resposta (%s).", armazem.descricao(), erro)

    @app.errorhandler(ArmazemIndisponivel)
    def base_de_dados_indisponivel(erro):
        app.logger.error("Base de dados indisponível: %s", erro)
        resposta = make_response(render_template("indisponivel.html"), 503)
        resposta.headers["Retry-After"] = "10"
        resposta.headers["Cache-Control"] = "no-store"
        return resposta

    # --- Falhar cedo: valida os 3 Excel ao arrancar --------------------------
    app.logger.info(
        "Dados lidos: %d jogadores (offline), %d jogadores (online), %d equipas adversárias.",
        len(dados.carregar_jogadores_offline()),
        len(dados.carregar_jogadores_online()),
        len(dados.carregar_equipas_offline()),
    )

    # --- Modo online: salas (em memória) e SocketIO (opcional) ----------------
    # As salas vivem na memória DESTE processo: no servidor tem de correr um só processo (ver README).
    app.extensions["salas"] = Salas()
    modo_online.posicoes_online()          # falhar cedo se o Excel online tiver posições desconhecidas
    modo_online.validar_funcoes()          # e se as funções/estilos citarem atributos que não existem nele
    tempo_real.iniciar(app, app.extensions["salas"], modo_online.token_da_sessao)

    # --- Ajuda para os templates --------------------------------------------
    @app.context_processor
    def utilidades_templates():
        def static_v(ficheiro: str) -> str:
            """URL de um ficheiro estático com ?v=<data de modificação> (cache-busting)."""
            try:
                versao = int((Path(app.static_folder) / ficheiro).stat().st_mtime)
            except OSError:
                versao = 0
            return url_for("static", filename=ficheiro, v=versao)

        return {"static_v": static_v}

    # --- Rotas ---------------------------------------------------------------
    @app.get("/")
    def inicio():
        # O campo do nome começa SEMPRE vazio: sem sugestões nem nome guardado.
        return render_template(
            "index.html", nome="", erro=None, convite=bool(session.get("convite")),
            nome_min=NOME_MIN, nome_max=NOME_MAX, mensagens=MENSAGENS_NOME,
        )

    @app.post("/entrar")
    def entrar():
        modo = request.form.get("modo", "")
        if modo not in MODOS:
            abort(400)

        nome, erro = validar_nome(request.form.get("nome"))
        if erro:
            return render_template(
                "index.html", nome=nome, erro=erro, convite=bool(session.get("convite")),
                nome_min=NOME_MIN, nome_max=NOME_MAX, mensagens=MENSAGENS_NOME,
            ), 400

        session["nome"] = nome
        modo_offline.reiniciar()   # entrar com o nome é sempre um jogo novo
        # Quem chegou por um link de convite sem nome: depois do nome, «Jogar Online» leva ao convite.
        convite = session.pop("convite", None)
        if modo == "online" and convite and modo_online.id_valido(convite):
            return redirect(url_for("online.convite", sala_id=convite))
        return redirect(url_for(DESTINOS[modo]))

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    # Modo offline (sorteio, tática, equipa no campo e liga) e modo online (salas)
    app.register_blueprint(modo_offline.bp)
    app.register_blueprint(modo_online.bp)

    return app


# `app` ao nível do módulo é o que o gunicorn procura em "app:app".
app = create_app()

if __name__ == "__main__":
    tempo_real.executar(app, "127.0.0.1", int(os.environ.get("PORT", 5000)), debug=True)
