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
            url = urllib.parse.urlparse(self.path)
            # mudanças, e tudo do WhatsApp (que roda o wacli), só com o cabeçalho que a página manda
            if (metodo != "GET" or url.path.startswith("/api/whatsapp")) and self.headers.get("X-Pombo") != "1":
                return self._resp(403, {"erro": "pedido sem o cabeçalho do painel"})
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
    if p[:1] == ["whatsapp"]:
        return rota_whatsapp(metodo, p[1:], q, corpo)
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
        "token_definido": (cfg.get("canal") == "whatsapp" or bool(cfg.get("token_keychain"))
                           or bool(config.token_do_bot(bot_id, cfg))),
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
    for k in ("nome", "pasta", "usuarios_permitidos", "permissoes", "canal"):
        if corpo.get(k) not in (None, ""):
            cfg[k] = corpo[k]
    if not cfg["nome"]:
        cfg["nome"] = bot_id
    if not cfg["usuarios_permitidos"]:
        cfg["usuarios_permitidos"] = config.usuarios_iniciais(cfg["canal"])
    if cfg["canal"] == "whatsapp":
        from .whatsapp import NOME_NUMERO, achar_wacli, pasta_numero
        from .whatsapp import meu_telefone
        wa = dict(config.WHATSAPP_PADRAO, wacli=achar_wacli())
        numero = (corpo.get("numero") or "").strip()
        if corpo.get("chave") is not None:
            n = numero_pela_chave(corpo.get("chave"))
            wa.update({"pasta_dados": n["pasta_dados"], "conta": n["conta"], "wacli": n["wacli"] or wa["wacli"]})
        elif numero:
            if not NOME_NUMERO.match(numero):
                raise Erro(400, 'o nome do número é uma palavra curta, como "pombo"')
            wa["pasta_dados"] = pasta_numero(numero)
        if corpo.get("numero_separado"):
            wa.update({"meu_numero": False, "conversas": ["todas"], "gatilho_sempre": False, "prefixo": ""})
            if not corpo.get("usuarios_permitidos") and meu_telefone():
                cfg["usuarios_permitidos"] = [meu_telefone()]  # quem chama o bot: você
        cfg["whatsapp"] = wa
    config.salvar_bot(bot_id, cfg)
    return {"id": bot_id}


def rota_whatsapp(metodo, p, q, corpo):
    """Números do WhatsApp deste computador, os grupos de cada um e o pareamento pelo código de telefone."""
    from . import whatsapp
    if p == [] and metodo == "GET":
        return {"numeros": whatsapp.numeros_locais(), "casa": os.path.expanduser("~")}
    if p == ["computador"] and metodo == "GET":  # o que os outros computadores com o mesmo WhatsApp perguntam
        return whatsapp.descrever_computador()
    if p == ["outros-computadores"] and metodo == "GET":
        return {"computadores": whatsapp.atualizar_outros_computadores() if q.get("agora") else
                (config.ler_json(config.arq_outros_computadores(), {}).get("computadores") or {})}
    if p == ["grupos"] and metodo == "GET":
        # o número vem pela chave e é procurado aqui: nada da URL (caminho de programa, pasta) vai para o wacli
        n = numero_pela_chave(q.get("chave"))
        try:
            grupos = whatsapp.Wacli(n).grupos()
        except whatsapp.ErroWhatsApp as e:
            raise Erro(400, f"não consegui listar os grupos: {e}")
        donos = {}
        for b in config.listar_ids():
            try:
                c = config.carregar_bot(b)
            except config.ErroConfig:
                continue
            if c.get("canal") == "whatsapp":
                for conv in (c.get("whatsapp") or {}).get("conversas") or []:
                    if str(conv).endswith("@g.us"):
                        donos[str(conv).lower()] = b
        lista = [{"jid": g.get("JID"), "nome": g.get("Name") or "(sem nome)", "bot": donos.get(str(g.get("JID")).lower())}
                 for g in grupos if isinstance(g, dict) and g.get("JID")]
        return {"grupos": sorted(lista, key=lambda g: g["nome"].lower())}
    if p == ["parear"]:
        dados = corpo if metodo == "POST" else q
        novo = (dados.get("novo") or "").strip()
        if novo:  # um número novo: fica em ~/.wacli-NOME
            if not whatsapp.NOME_NUMERO.match(novo):
                raise Erro(400, 'o nome do número é uma palavra curta, como "pombo" (letras minúsculas, números e hífen)')
            wa = {"pasta_dados": whatsapp.pasta_numero(novo), "conta": "", "wacli": whatsapp.achar_wacli()}
        else:
            n = numero_pela_chave(dados.get("chave"))
            wa = {"pasta_dados": n["pasta_dados"], "conta": n["conta"], "wacli": n["wacli"] or whatsapp.achar_wacli()}
        if metodo == "GET":
            atual = whatsapp.pareamento(wa)
            return atual.resumo() if atual else {"estado": "nenhum"}
        if metodo == "POST":
            telefone = re.sub(r"[^\d+]", "", str(corpo.get("telefone") or ""))
            if len(re.sub(r"\D", "", telefone)) < 10:
                raise Erro(400, "digite o telefone com DDI e DDD, como +55 31 99999-0000")
            if not wa["wacli"]:
                raise Erro(400, "não achei o wacli neste computador: brew install openclaw/tap/wacli")
            atual = whatsapp.identidade_em_cache(wa, segundos=0)
            if atual and not (whatsapp.variantes(atual["telefone"]) & whatsapp.variantes(telefone)):
                raise Erro(409, f"esse lugar já tem o +{atual['telefone']} pareado. Para outro telefone, escolha "
                                "\"número novo…\" (senão ele desfaria o pareamento do +" + atual["telefone"] + ")")
            if atual and not corpo.get("de_novo"):
                raise Erro(409, f"o +{atual['telefone']} já está pareado aqui. Para parear de novo, marque "
                                "\"Desfazer o pareamento atual antes\"")
            return whatsapp.parear(wa, telefone, de_novo=bool(corpo.get("de_novo"))).resumo()
    raise Erro(404, "não encontrado")


def numero_pela_chave(chave):
    """Um dos números deste computador (numeros_locais), pela chave que o painel recebeu de /api/whatsapp."""
    from . import whatsapp
    for n in whatsapp.numeros_locais_rapido(segundos=5):
        if n["chave"] == chave:
            return n
    raise Erro(404, "não conheço esse número do WhatsApp (atualize a página)")


def liberar(bot_id, usuario, remover=False):
    cfg = config.carregar_bot(bot_id)
    whatsapp = cfg.get("canal") == "whatsapp"
    try:
        usuario = config.normalizar_numero(usuario) if whatsapp else int(usuario)
    except config.ErroConfig as e:
        raise Erro(400, str(e))
    except (TypeError, ValueError):
        raise Erro(400, "usuário precisa ser o número do ID do Telegram")
    lista = [u for u in cfg["usuarios_permitidos"] if u != usuario]
    if not remover:
        lista.append(usuario)
    cfg["usuarios_permitidos"] = lista
    config.salvar_bot(bot_id, cfg)
    if not remover and not whatsapp:
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
