"""Painel web: uma página para ver e configurar os bots. Só abre na própria máquina (127.0.0.1).

Para usar no celular, publique pelo Tailscale (`pombo servico publicar`): ele repassa a tailnet para cá.
Toda mudança grava nos mesmos arquivos da pasta de configuração, então painel, linha de comando e edição à mão
são equivalentes.
"""
import json
import os
import re
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSAO, config, motores, registro, rotinas

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "painel.html")
ICONE = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#2457a8"/>'
         b'<path d="M7 16l17-7-4 16-5-5-3 4v-6l9-7-11 6z" fill="#fff"/></svg>')


class Erro(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def iniciar(servico=None, porta=None, bloquear=False):
    geral = config.carregar_geral()
    porta = int(porta or geral["painel_porta"])
    srv = ThreadingHTTPServer(("127.0.0.1", porta), _handler(servico, porta))
    srv.daemon_threads = True
    registro.log(None, f"painel em http://127.0.0.1:{porta}")
    if bloquear:
        srv.serve_forever()
    else:
        threading.Thread(target=srv.serve_forever, name="painel", daemon=True).start()
    return srv


def _handler(servico, porta):
    class H(BaseHTTPRequestHandler):
        server_version = "pombo"

        def log_message(self, *a):
            pass

        # ---- segurança: só hosts conhecidos, e mudanças só com o cabeçalho que a página manda

        def _host_ok(self):
            host = (self.headers.get("Host") or "").lower()
            permitidos = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
            permitidos |= {h.lower() for h in config.carregar_geral().get("hosts_permitidos") or []}
            return host in permitidos

        def _resp(self, status, corpo, tipo="application/json; charset=utf-8"):
            dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(dados)

        def _corpo(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except ValueError:
                raise Erro(400, "corpo não é JSON")

        def _tratar(self, metodo):
            if not self._host_ok():
                return self._resp(403, {"erro": "host não permitido. Use http://127.0.0.1:%d" % porta})
            if metodo != "GET" and self.headers.get("X-Pombo") != "1":
                return self._resp(403, {"erro": "pedido sem o cabeçalho do painel"})
            url = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            try:
                if metodo == "GET" and url.path in ("/", "/index.html"):
                    with open(HTML, "rb") as f:
                        return self._resp(200, f.read(), "text/html; charset=utf-8")
                if metodo == "GET" and url.path == "/favicon.ico":
                    return self._resp(200, ICONE, "image/svg+xml")
                corpo = self._corpo() if metodo in ("POST", "PUT") else {}
                r = rota(servico, metodo, url.path, q, corpo)
                return self._resp(200, r if r is not None else {"ok": True})
            except Erro as e:
                return self._resp(e.status, {"erro": str(e)})
            except config.ErroConfig as e:
                return self._resp(400, {"erro": str(e)})
            except Exception as e:
                registro.log(None, f"erro no painel ({metodo} {url.path}): {e!r}")
                return self._resp(500, {"erro": f"erro interno: {e}"})

        def do_GET(self):
            self._tratar("GET")

        def do_POST(self):
            self._tratar("POST")

        def do_PUT(self):
            self._tratar("PUT")

        def do_DELETE(self):
            self._tratar("DELETE")

    return H


# ---------------------------------------------------------------- rotas

def rota(servico, metodo, caminho, q, corpo):
    partes = [urllib.parse.unquote(p) for p in caminho.strip("/").split("/")]
    if partes[:1] != ["api"]:
        raise Erro(404, "não encontrado")
    p = partes[1:]
    if p == ["estado"] and metodo == "GET":
        return estado_geral(servico)
    if p == ["geral"] and metodo == "PUT":
        g = {**config.carregar_geral(), **{k: v for k, v in corpo.items() if k in config.GERAL_PADRAO}}
        return config.salvar_geral(g)
    if p == ["bots"] and metodo == "POST":
        return criar_bot(corpo)
    if len(p) >= 2 and p[0] == "bots":
        bot_id = p[1]
        if not config.existe(bot_id):
            raise Erro(404, f'não existe bot "{bot_id}"')
        resto = p[2:]
        if not resto and metodo == "GET":
            return info_bot(servico, bot_id)
        if not resto and metodo == "PUT":
            cfg = corpo.get("cfg")
            if not isinstance(cfg, dict):
                raise Erro(400, "faltou cfg")
            config.salvar_bot(bot_id, cfg)
            return info_bot(servico, bot_id)
        if not resto and metodo == "DELETE":
            config.remover_bot(bot_id)
            return {"ok": True}
        if resto == ["token"] and metodo == "POST":
            config.gravar_token(bot_id, corpo.get("token"))
            return {"ok": True}
        if resto == ["liberar"] and metodo == "POST":
            return liberar(bot_id, corpo.get("usuario"), corpo.get("remover"))
        if resto == ["teste"] and metodo == "POST":
            _precisa(servico).mandar_teste(bot_id)
            return {"ok": True}
        if resto == ["log"] and metodo == "GET":
            return {"texto": registro.ler_log(bot_id, int(q.get("n") or 200))}
        if resto == ["execucoes"] and metodo == "GET":
            return {"execucoes": registro.ler_execucoes(bot_id, int(q.get("n") or 30))}
        if resto == ["instrucoes-arquivo"]:
            return arquivo_instrucoes(bot_id, metodo, corpo)
        if resto == ["mcps"] and metodo == "GET":
            return listar_mcps(bot_id)
        if len(resto) == 3 and resto[0] == "rotinas" and resto[2] == "rodar" and metodo == "POST":
            _precisa(servico).rodar_rotina(bot_id, resto[1])
            return {"ok": True}
    raise Erro(404, "não encontrado")


def _precisa(servico):
    if not servico:
        raise Erro(409, "o serviço não está rodando. Ligue com: pombo servico instalar (ou pombo rodar)")
    return servico


def estado_geral(servico):
    from .servico import pid_rodando
    return {
        "versao": VERSAO,
        "base": config.base(),
        "geral": config.carregar_geral(),
        "servico": bool(servico) or bool(pid_rodando()),
        "painel_do_servico": bool(servico),
        "opcoes": {"permissoes": config.PERMISSOES, "motores": config.MOTORES, "dias": config.DIAS},
        "bots": [resumo_bot(servico, b) for b in config.listar_ids()],
    }


def resumo_bot(servico, bot_id):
    try:
        cfg = config.carregar_bot(bot_id)
    except config.ErroConfig as e:
        return {"id": bot_id, "cfg": None, "estado": {"situacao": "erro", "detalhe": str(e)}}
    est = config.Estado(bot_id).ler()
    agora = __import__("datetime").datetime.now()
    rot = {}
    for r in cfg["rotinas"]:
        e = (est.get("rotinas") or {}).get(r["id"]) or {}
        prox = rotinas.proximo_horario(r, agora) if r["ativa"] else None
        rot[r["id"]] = {"ultima_execucao": e.get("ultima_execucao"), "ok": e.get("ok"),
                        "proxima": prox.strftime("%d/%m %H:%M") if prox else None}
    if servico:
        situacao = servico.estado_bot(bot_id)
    else:
        situacao = {"situacao": "parado", "detalhe": "o serviço não está rodando"} if cfg["ativo"] else {"situacao": "pausado", "detalhe": ""}
    return {
        "id": bot_id,
        "cfg": cfg,
        "token_definido": bool(config.token_do_bot(bot_id, cfg)) if not cfg.get("token_keychain") else True,
        "estado": situacao,
        "desconhecidos": est.get("desconhecidos") or [],
        "rotinas_estado": rot,
        "pasta_existe": os.path.isdir(config.pasta_do_bot(cfg)),
    }


def info_bot(servico, bot_id):
    return resumo_bot(servico, bot_id)


def criar_bot(corpo):
    bot_id = (corpo.get("id") or config.gerar_id(corpo.get("nome") or "")).strip()
    if config.existe(bot_id):
        raise Erro(409, f'já existe um bot "{bot_id}"')
    cfg = dict(config.BOT_PADRAO)
    for k in ("nome", "pasta", "usuarios_permitidos", "permissoes"):
        if corpo.get(k) not in (None, ""):
            cfg[k] = corpo[k]
    if not cfg["nome"]:
        cfg["nome"] = bot_id
    if not cfg["usuarios_permitidos"]:
        cfg["usuarios_permitidos"] = config.usuarios_iniciais()
    config.salvar_bot(bot_id, cfg)
    return {"id": bot_id}


def liberar(bot_id, usuario, remover=False):
    try:
        usuario = int(usuario)
    except (TypeError, ValueError):
        raise Erro(400, "usuário precisa ser o número do ID do Telegram")
    cfg = config.carregar_bot(bot_id)
    lista = [u for u in cfg["usuarios_permitidos"] if u != usuario]
    if not remover:
        lista.append(usuario)
    cfg["usuarios_permitidos"] = lista
    config.salvar_bot(bot_id, cfg)
    if not remover:
        config.anotar_dono(usuario)
        config.Estado(bot_id).atualizar(lambda d: d.__setitem__(
            "desconhecidos", [x for x in d.get("desconhecidos", []) if x.get("id") != usuario]))
    return {"usuarios_permitidos": lista}


def arquivo_instrucoes(bot_id, metodo, corpo):
    cfg = config.carregar_bot(bot_id)
    arq = config.resolver(cfg, cfg.get("instrucoes_arquivo"))
    if not arq:
        raise Erro(400, "este bot não tem arquivo de instruções (campo instrucoes_arquivo)")
    if metodo == "GET":
        return {"caminho": arq, "existe": os.path.isfile(arq), "texto": config.ler_texto(arq)}
    if metodo == "PUT":
        texto = corpo.get("texto")
        if not isinstance(texto, str):
            raise Erro(400, "faltou o texto")
        os.makedirs(os.path.dirname(arq), exist_ok=True)
        with open(arq, "w", encoding="utf-8") as f:
            f.write(texto)
        return {"ok": True}
    raise Erro(405, "método não suportado")


def listar_mcps(bot_id):
    """Roda `claude mcp list` na pasta do bot, com o ambiente do bot (mostra o que ele enxerga)."""
    cfg = config.validar_bot(config.carregar_bot(bot_id))
    geral = config.carregar_geral()
    cmd, env = motores.comando_claude(cfg, geral, bot_id, "", None)
    pasta = config.pasta_do_bot(cfg)
    if not os.path.isdir(pasta):
        raise Erro(400, f"a pasta {pasta} não existe")
    lista = [cmd[0], "mcp", "list"]
    try:
        r = subprocess.run(lista, cwd=pasta, env=env, capture_output=True, text=True, timeout=120,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Erro(500, f"não consegui rodar claude mcp list: {e}")
    texto = re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or "")).strip()
    obs = []
    if not cfg["conectores_claude_ai"]:
        obs.append("Os conectores do claude.ai estão desligados para este bot.")
    if cfg["so_mcps_do_bot"]:
        obs.append("Este bot usa só os MCPs da lista dele; os de cima não entram nas conversas.")
    if cfg["chrome"]:
        obs.append("O Claude in Chrome está ligado: nas conversas, o bot também usa o seu Chrome.")
    return {"texto": texto or "(nenhum MCP)", "obs": obs}
