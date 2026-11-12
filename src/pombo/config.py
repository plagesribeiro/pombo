"""Onde ficam as coisas e como ler e gravar a configuração.

Tudo fica numa pasta de configuração por máquina (fora de qualquer repositório), ~/.config/pombo
(no Windows, %APPDATA%\\pombo; a variável POMBO_DIR muda o lugar):

  geral.json            nome da máquina, como o bot chama você, porta do painel
  bots/<id>.json        um arquivo por bot (sem token)
  segredos.json         tokens dos bots (permissão só do usuário)
  estado/<id>.json      offset do Telegram, conversas, último horário de cada rotina
  execucoes/<id>.jsonl  histórico de pedidos e rotinas
  logs/<id>.log         log de cada bot (logs/geral.log para o serviço)
  anexos/<id>/          fotos, áudios e arquivos recebidos
  mcp/<id>.json         MCPs extras do bot, gerado a partir do bots/<id>.json
"""
import copy
import json
import os
import re
import socket
import subprocess
import sys
import threading

APP = "pombo"
PORTA_PAINEL = 47940

DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
PERMISSOES = {
    "total": "faz qualquer coisa sem perguntar (--dangerously-skip-permissions)",
    "auto": "o Claude Code decide o que é seguro; o arriscado é negado (--permission-mode auto)",
    "lista": "só as ferramentas da lista 'ferramentas_permitidas'; o resto é negado (--permission-mode dontAsk)",
}
MOTORES = ["claude"]

GERAL_PADRAO = {
    "nome_maquina": "",
    "usuario_nome": "",
    "meu_id_telegram": 0,
    "claude": "claude",
    "painel_porta": PORTA_PAINEL,
    "hosts_permitidos": [],
    "telegram_api": "https://api.telegram.org",
}

BOT_PADRAO = {
    "nome": "",
    "ativo": True,
    "usuarios_permitidos": [],
    "pasta": "~",
    "motor": "claude",
    "modelo": "",
    "esforco": "",
    "permissoes": "total",
    "ferramentas_permitidas": [],
    "ferramentas_negadas": [],
    "conectores_claude_ai": True,
    "mcps": {},
    "so_mcps_do_bot": False,
    "plugin_dirs": [],
    "instrucoes": "",
    "instrucoes_arquivo": "",
    "env": {},
    "nova_sessao_apos_horas": 6,
    "tempo_maximo_min": 25,
    "transcricao_cmd": [],
    "token_keychain": "",
    "rotinas": [],
}

ROTINA_PADRAO = {
    "id": "",
    "nome": "",
    "ativa": True,
    "horarios": [],
    "dias": [],
    "prompt": "",
    "conversa": "nova",
    "silenciosa": False,
    "tolerancia_min": 90,
}

ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
HORA_VALIDA = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ErroConfig(ValueError):
    """Configuração inválida. A mensagem diz o que corrigir."""


# ---------------------------------------------------------------- caminhos

def base():
    if os.environ.get("POMBO_DIR"):
        return os.path.expanduser(os.environ["POMBO_DIR"])
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP)
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), APP)


def caminho(*partes):
    return os.path.join(base(), *partes)


def arq_bot(bot_id):
    return caminho("bots", bot_id + ".json")


def garantir_pastas():
    for p in ("bots", "estado", "execucoes", "logs", "anexos", "mcp"):
        os.makedirs(caminho(p), exist_ok=True)


def restringir(arquivo):
    if os.name != "nt":
        try:
            os.chmod(arquivo, 0o600)
        except OSError:
            pass


# ---------------------------------------------------------------- json

def ler_json(arquivo, padrao):
    try:
        with open(arquivo, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return copy.deepcopy(padrao)


def gravar_json(arquivo, dados, privado=False):
    os.makedirs(os.path.dirname(arquivo), exist_ok=True)
    tmp = arquivo + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if privado:
        restringir(tmp)
    os.replace(tmp, arquivo)


def ler_texto(arquivo):
    try:
        with open(arquivo, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


# ---------------------------------------------------------------- geral

def carregar_geral():
    g = {**GERAL_PADRAO, **ler_json(caminho("geral.json"), {})}
    if not g["nome_maquina"]:
        g["nome_maquina"] = socket.gethostname()
    return g


def salvar_geral(g):
    limpo = {k: g.get(k, v) for k, v in GERAL_PADRAO.items()}
    try:
        limpo["painel_porta"] = int(limpo["painel_porta"])
    except (TypeError, ValueError):
        raise ErroConfig("painel_porta precisa ser um número")
    try:
        limpo["meu_id_telegram"] = int(limpo["meu_id_telegram"] or 0)
    except (TypeError, ValueError):
        raise ErroConfig("meu_id_telegram precisa ser o número do seu ID do Telegram")
    if not isinstance(limpo["hosts_permitidos"], list):
        raise ErroConfig("hosts_permitidos precisa ser uma lista")
    gravar_json(caminho("geral.json"), limpo)
    return limpo


# ---------------------------------------------------------------- bots

def listar_ids():
    try:
        nomes = os.listdir(caminho("bots"))
    except OSError:
        return []
    return sorted(n[:-5] for n in nomes if n.endswith(".json") and ID_VALIDO.match(n[:-5]))


def existe(bot_id):
    return os.path.isfile(arq_bot(bot_id))


def carregar_bot(bot_id):
    if not existe(bot_id):
        raise ErroConfig(f'não existe bot "{bot_id}". Bots: {", ".join(listar_ids()) or "nenhum"}')
    bruto = ler_json(arq_bot(bot_id), None)
    if not isinstance(bruto, dict):
        raise ErroConfig(f"{arq_bot(bot_id)} não é um JSON válido")
    return completar_bot(bruto, bot_id)


def completar_bot(bruto, bot_id=""):
    cfg = {**copy.deepcopy(BOT_PADRAO), **{k: v for k, v in bruto.items() if k != "id"}}
    if not cfg["nome"]:
        cfg["nome"] = bot_id
    cfg["rotinas"] = [{**ROTINA_PADRAO, **r} for r in cfg.get("rotinas") or [] if isinstance(r, dict)]
    return cfg


def validar_bot(cfg):
    """Confere e normaliza. Levanta ErroConfig com uma mensagem clara."""
    cfg = completar_bot(cfg)
    desconhecidos = set(cfg) - set(BOT_PADRAO)
    if desconhecidos:
        raise ErroConfig(f"campo desconhecido: {', '.join(sorted(desconhecidos))}. Campos: {', '.join(BOT_PADRAO)}")
    try:
        cfg["usuarios_permitidos"] = [int(x) for x in cfg["usuarios_permitidos"]]
    except (TypeError, ValueError):
        raise ErroConfig("usuarios_permitidos precisa ser uma lista de números (IDs do Telegram)")
    if cfg["motor"] not in MOTORES:
        raise ErroConfig(f"motor precisa ser um destes: {', '.join(MOTORES)}")
    if cfg["permissoes"] not in PERMISSOES:
        raise ErroConfig(f"permissoes precisa ser um destes: {', '.join(PERMISSOES)}")
    for campo in ("ferramentas_permitidas", "ferramentas_negadas", "plugin_dirs", "transcricao_cmd"):
        if not isinstance(cfg[campo], list) or not all(isinstance(x, str) for x in cfg[campo]):
            raise ErroConfig(f"{campo} precisa ser uma lista de textos")
    for campo in ("mcps", "env"):
        if not isinstance(cfg[campo], dict):
            raise ErroConfig(f"{campo} precisa ser um objeto JSON ({{...}})")
    if not all(isinstance(v, str) for v in cfg["env"].values()):
        raise ErroConfig("os valores de env precisam ser textos")
    for nome, srv in cfg["mcps"].items():
        if not isinstance(srv, dict) or not (srv.get("command") or srv.get("url")):
            raise ErroConfig(f'o MCP "{nome}" precisa de "command" (programa local) ou "url" (servidor remoto)')
    for campo in ("ativo", "conectores_claude_ai", "so_mcps_do_bot"):
        cfg[campo] = bool(cfg[campo])
    for campo in ("nova_sessao_apos_horas", "tempo_maximo_min"):
        try:
            cfg[campo] = float(cfg[campo])
            if cfg[campo] <= 0:
                raise ValueError
            if cfg[campo] == int(cfg[campo]):
                cfg[campo] = int(cfg[campo])
        except (TypeError, ValueError):
            raise ErroConfig(f"{campo} precisa ser um número maior que zero")
    if not str(cfg["pasta"]).strip():
        raise ErroConfig("pasta não pode ficar vazia")
    ids = set()
    rotinas = []
    for r in cfg["rotinas"]:
        r = validar_rotina(r)
        if r["id"] in ids:
            raise ErroConfig(f'há duas rotinas com o id "{r["id"]}"')
        ids.add(r["id"])
        rotinas.append(r)
    cfg["rotinas"] = rotinas
    return cfg


def validar_rotina(r):
    r = {**ROTINA_PADRAO, **r}
    desconhecidos = set(r) - set(ROTINA_PADRAO)
    if desconhecidos:
        raise ErroConfig(f"campo de rotina desconhecido: {', '.join(sorted(desconhecidos))}. Campos: {', '.join(ROTINA_PADRAO)}")
    if not r["id"]:
        r["id"] = gerar_id(r["nome"] or "rotina")
    if not ID_VALIDO.match(r["id"]):
        raise ErroConfig(f'id de rotina inválido: "{r["id"]}" (use letras minúsculas, números e hífen)')
    if not r["nome"]:
        r["nome"] = r["id"]
    if isinstance(r["horarios"], str):
        r["horarios"] = [h for h in re.split(r"[,\s]+", r["horarios"]) if h]
    horarios = []
    for h in r["horarios"]:
        m = HORA_VALIDA.match(str(h).strip())
        if not m:
            raise ErroConfig(f'horário inválido na rotina "{r["nome"]}": "{h}" (use HH:MM, como 07:00)')
        horarios.append(f"{int(m.group(1)):02d}:{m.group(2)}")
    r["horarios"] = sorted(set(horarios))
    if isinstance(r["dias"], str):
        r["dias"] = [d for d in re.split(r"[,\s]+", r["dias"]) if d]
    dias = []
    for d in r["dias"]:
        d = str(d).strip().lower()[:3].replace("sáb", "sab")
        if d not in DIAS:
            raise ErroConfig(f'dia inválido na rotina "{r["nome"]}": "{d}" (use {", ".join(DIAS)})')
        dias.append(d)
    r["dias"] = [d for d in DIAS if d in dias]
    if not str(r["prompt"]).strip():
        raise ErroConfig(f'a rotina "{r["nome"]}" precisa de um prompt')
    if r["conversa"] not in ("nova", "continuar"):
        raise ErroConfig('conversa precisa ser "nova" (cada rodada começa do zero) ou "continuar"')
    for campo in ("ativa", "silenciosa"):
        r[campo] = bool(r[campo])
    try:
        r["tolerancia_min"] = int(r["tolerancia_min"])
    except (TypeError, ValueError):
        raise ErroConfig("tolerancia_min precisa ser um número de minutos")
    return r


def usuarios_iniciais():
    """Bot novo já nasce liberado para o dono deste computador (geral.json: meu_id_telegram)."""
    meu = carregar_geral().get("meu_id_telegram")
    return [int(meu)] if meu else []


def anotar_dono(usuario):
    """A primeira pessoa liberada neste computador vira o dono (se ainda não houver um)."""
    g = carregar_geral()
    if not g.get("meu_id_telegram"):
        g["meu_id_telegram"] = int(usuario)
        salvar_geral(g)


def salvar_bot(bot_id, cfg):
    if not ID_VALIDO.match(bot_id or ""):
        raise ErroConfig(f'id inválido: "{bot_id}". Use letras minúsculas, números e hífen (ex.: pessoal, trabalho)')
    cfg = validar_bot(cfg)
    gravar_json(arq_bot(bot_id), cfg)
    return cfg


def remover_bot(bot_id):
    if not existe(bot_id):
        raise ErroConfig(f'não existe bot "{bot_id}"')
    os.remove(arq_bot(bot_id))
    seg = ler_json(caminho("segredos.json"), {})
    if seg.pop(bot_id, None) is not None:
        gravar_json(caminho("segredos.json"), seg, privado=True)


def gerar_id(texto):
    t = texto.lower()
    for a, b in (("áàâãä", "a"), ("éèêë", "e"), ("íìîï", "i"), ("óòôõö", "o"), ("úùûü", "u"), ("ç", "c")):
        for c in a:
            t = t.replace(c, b)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40]
    return t or "item"


# ---------------------------------------------------------------- caminhos de um bot

def pasta_do_bot(cfg):
    return os.path.abspath(os.path.expanduser(cfg["pasta"]))


def resolver(cfg, p):
    """Caminho relativo vale a partir da pasta do bot."""
    p = os.path.expanduser(p or "")
    if not p:
        return ""
    return p if os.path.isabs(p) else os.path.join(pasta_do_bot(cfg), p)


# ---------------------------------------------------------------- tokens

def token_do_bot(bot_id, cfg):
    """Ordem: segredos.json, Keychain do Mac (token_keychain), variável POMBO_TOKEN_<ID>."""
    t = ler_json(caminho("segredos.json"), {}).get(bot_id)
    if t:
        return t.strip()
    if cfg.get("token_keychain") and sys.platform == "darwin":
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", cfg["token_keychain"], "-w"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return (os.environ.get("POMBO_TOKEN_" + bot_id.upper().replace("-", "_")) or "").strip()


TOKEN_VALIDO = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")


def gravar_token(bot_id, token):
    token = (token or "").strip()
    if not TOKEN_VALIDO.match(token):
        raise ErroConfig("isso não parece um token do BotFather (formato 123456789:ABC...)")
    seg = ler_json(caminho("segredos.json"), {})
    seg[bot_id] = token
    gravar_json(caminho("segredos.json"), seg, privado=True)


# ---------------------------------------------------------------- estado de um bot

class Estado:
    """estado/<id>.json, lido e gravado com trava (várias threads mexem nele)."""

    _travas = {}
    _trava_global = threading.Lock()

    def __init__(self, bot_id):
        self.arquivo = caminho("estado", bot_id + ".json")
        with Estado._trava_global:
            self.trava = Estado._travas.setdefault(self.arquivo, threading.RLock())

    def ler(self):
        with self.trava:
            return ler_json(self.arquivo, {})

    def atualizar(self, fn):
        with self.trava:
            d = ler_json(self.arquivo, {})
            r = fn(d)
            gravar_json(self.arquivo, d)
            return r


# ---------------------------------------------------------------- editar por texto (CLI e Claude)

def interpretar_valor(texto):
    """'true' -> True, '[1,2]' -> lista, '{"a":1}' -> objeto, o resto fica texto."""
    try:
        return json.loads(texto)
    except ValueError:
        return texto


def aplicar_campos(alvo, pares):
    """pares: ["campo=valor", "env.CHAVE=valor"]. Altera alvo (dict) e devolve."""
    for par in pares:
        if "=" not in par:
            raise ErroConfig(f'use campo=valor (recebi "{par}")')
        chave, valor = par.split("=", 1)
        partes = chave.strip().split(".")
        d = alvo
        for p in partes[:-1]:
            if not isinstance(d.get(p), dict):
                d[p] = {}
            d = d[p]
        if valor == "" and partes[-1] in d and len(partes) > 1:
            d.pop(partes[-1])
        else:
            d[partes[-1]] = interpretar_valor(valor)
    return alvo
