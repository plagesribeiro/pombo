"""Onde ficam as coisas e como ler e gravar a configuração.

Tudo fica numa pasta de configuração por máquina (fora de qualquer repositório), ~/.config/pombo
(no Windows, %APPDATA%\\pombo; a variável POMBO_DIR muda o lugar):

  geral.json            nome da máquina, como o bot chama você, porta do painel
  bots/<id>.json        um arquivo por bot (sem token)
  segredos.json         tokens dos bots (permissão só do usuário)
  estado/<id>.json      offset do Telegram (ou checkpoint do WhatsApp), conversas, último horário de cada rotina
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
CANAIS = {
    "telegram": "um bot do Telegram (token do @BotFather)",
    "whatsapp": "o WhatsApp, pelo wacli (github.com/openclaw/wacli), pareado como aparelho conectado",
}

GERAL_PADRAO = {
    "nome_maquina": "",
    "usuario_nome": "",
    "meu_id_telegram": 0,
    "claude": "claude",
    "painel_porta": PORTA_PAINEL,
    "hosts_permitidos": [],
    "telegram_api": "https://api.telegram.org",
    # painéis do Pombo nos outros computadores com o mesmo WhatsApp (ex.: "https://mac.sua-tailnet.ts.net:10004"):
    # a pasta padrão daqui deixa para eles as conversas que os bots de lá pegaram pelo nome (veja whatsapp.py)
    "outros_computadores": [],
}

BOT_PADRAO = {
    "nome": "",
    "ativo": True,
    "canal": "telegram",
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
    "chrome": False,
    "plugin_dirs": [],
    "instrucoes": "",
    "instrucoes_arquivo": "",
    "env": {},
    "nova_sessao_apos_horas": 6,
    "tempo_maximo_min": 25,
    # texto de até 3 caracteres (".", "ok") ou só um anexo sem legenda não é respondido: vai como contexto do próximo
    # pedido da mesma pessoa (em até 10 min). Áudio e chamar pelo gatilho ("pombo, oi") sempre valem
    "ignorar_triviais": True,
    "transcricao_cmd": [],
    "token_keychain": "",
    "whatsapp": {},
    "rotinas": [],
}

# Só para bots com "canal": "whatsapp". Veja whatsapp.py.
WHATSAPP_PADRAO = {
    "wacli": "",                    # caminho do wacli; vazio = procura no PATH e nos lugares de sempre
    "conta": "",                    # --account do wacli (para ter mais de um WhatsApp no mesmo computador)
    "pasta_dados": "",              # --store do wacli; vazio = o padrão dele (~/.wacli)
    "meu_numero": True,             # o WhatsApp pareado é o seu número (False: um número só do bot)
    "conversas": ["eu"],            # "eu", números, JIDs de grupo (...@g.us) ou "privadas", "grupos", "todas"
    "gatilho": "pombo",             # a mensagem começa com isso ("pombo, ..." ou "@pombo ...")
    "gatilho_sempre": True,         # exige o gatilho também na conversa "eu" e nas privadas do número do bot
    "prefixo": "🐦 ",               # começo de toda resposta (no seu número, é como o Pombo se reconhece)
    "contexto_mensagens": 20,       # quantas mensagens anteriores da conversa vão junto, como contexto (0 = nenhuma)
    "intervalo_s": 1,               # de quanto em quanto tempo olha se chegou mensagem
    "espaco_entre_envios": "1s-3s",  # pausa entre envios (--send-spacing do wacli); vazio = sem pausa
    "reacoes": "simples",           # na sua mensagem, enquanto trabalha: "simples" (👀), "etapas" (👀 🎧 🧠 🛠️) ou
                                    # "nenhuma"; quando a resposta sai, a reação some (deu erro: fica ⚠️)
    "qualquer_pessoa": False,       # nos grupos deste bot, qualquer pessoa que marcar o bot (ou usar o gatilho) é atendida
    "limite_por_pessoa_dia": 0,     # quem não está liberado: até quantas mensagens por dia são respondidas (0 = sem limite)
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
CURINGAS = ("privadas", "grupos", "todas")  # conversas liberadas por tipo (a pasta padrão), não pelo nome
# no número do bot, com qualquer_pessoa: a conversa direta de quem nenhum outro bot do número atende (o último da fila)
DESCONHECIDOS = "desconhecidos"
JID_VALIDO = re.compile(r"^[0-9a-z.:_-]+@(s\.whatsapp\.net|g\.us|lid)$")


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
    limpo["outros_computadores"] = validar_outros_computadores(limpo["outros_computadores"])
    gravar_json(caminho("geral.json"), limpo)
    return limpo


def validar_outros_computadores(lista):
    if isinstance(lista, str):
        lista = [x for x in re.split(r"[,\s]+", lista) if x]
    if not isinstance(lista, list):
        raise ErroConfig("outros_computadores precisa ser uma lista de endereços do painel, "
                         'como ["https://mac.sua-tailnet.ts.net:10004"]')
    limpa = []
    for u in lista:
        u = str(u).strip().rstrip("/")
        if not re.match(r"^https?://[^/\s]+$", u):
            raise ErroConfig(f'"{u}" não parece o endereço do painel de outro computador '
                             "(ex.: https://mac.sua-tailnet.ts.net:10004, sem nada depois da porta)")
        if u not in limpa:
            limpa.append(u)
    return limpa


def arq_outros_computadores():
    """O que os outros computadores disseram da última vez (fica guardado: computador dormindo não muda nada)."""
    return caminho("estado", "_outros_computadores.json")


def bots_de_outros_computadores():
    """[(nome do computador, número, bot)] dos bots de WhatsApp ligados nos outros computadores (última resposta
    guardada de cada um). Número: {"telefone", "lid", "grupos"}; bot: {"id", "nome", "usuarios_permitidos",
    "whatsapp": {"meu_numero", "conversas"}}."""
    lista = []
    for maq in (ler_json(arq_outros_computadores(), {}).get("computadores") or {}).values():
        for n in maq.get("numeros") or []:
            for b in n.get("bots") or []:
                if b.get("ativo"):
                    lista.append((maq.get("nome_maquina") or maq.get("url") or "?", n, b))
    return lista


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
    if cfg.get("canal") == "whatsapp" and isinstance(cfg.get("whatsapp"), dict):
        cfg["whatsapp"] = {**copy.deepcopy(WHATSAPP_PADRAO), **cfg["whatsapp"]}
    cfg["rotinas"] = [{**ROTINA_PADRAO, **r} for r in cfg.get("rotinas") or [] if isinstance(r, dict)]
    return cfg


def validar_bot(cfg):
    """Confere e normaliza. Levanta ErroConfig com uma mensagem clara."""
    cfg = completar_bot(cfg)
    desconhecidos = set(cfg) - set(BOT_PADRAO)
    if desconhecidos:
        raise ErroConfig(f"campo desconhecido: {', '.join(sorted(desconhecidos))}. Campos: {', '.join(BOT_PADRAO)}")
    if cfg["canal"] not in CANAIS:
        raise ErroConfig(f"canal precisa ser um destes: {', '.join(CANAIS)}")
    if not isinstance(cfg["usuarios_permitidos"], list):
        raise ErroConfig("usuarios_permitidos precisa ser uma lista")
    if cfg["canal"] == "whatsapp":
        cfg["usuarios_permitidos"] = [normalizar_numero(x) for x in cfg["usuarios_permitidos"]]
        cfg["whatsapp"] = validar_whatsapp(cfg["whatsapp"], cfg["usuarios_permitidos"])
    else:
        try:
            cfg["usuarios_permitidos"] = [int(x) for x in cfg["usuarios_permitidos"]]
        except (TypeError, ValueError):
            raise ErroConfig("usuarios_permitidos precisa ser uma lista de números (IDs do Telegram)")
        if not isinstance(cfg["whatsapp"], dict):
            raise ErroConfig("whatsapp precisa ser um objeto JSON ({...})")
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
    for campo in ("ativo", "conectores_claude_ai", "so_mcps_do_bot", "chrome", "ignorar_triviais"):
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


def normalizar_numero(x):
    """'+55 (31) 99999-0000' -> '5531999990000' (número com DDI, só dígitos)."""
    n = re.sub(r"\D", "", str(x if x is not None else ""))
    if not 8 <= len(n) <= 15:
        raise ErroConfig(f'"{x}" não parece um número de WhatsApp. Use o número com DDI e DDD, como +55 31 99999-0000')
    return n


def validar_whatsapp(wa, usuarios):
    if not isinstance(wa, dict):
        raise ErroConfig("whatsapp precisa ser um objeto JSON ({...})")
    wa = {**copy.deepcopy(WHATSAPP_PADRAO), **wa}
    desconhecidos = set(wa) - set(WHATSAPP_PADRAO)
    if desconhecidos:
        raise ErroConfig(f"campo desconhecido em whatsapp: {', '.join(sorted(desconhecidos))}. "
                         f"Campos: {', '.join(WHATSAPP_PADRAO)}")
    for campo in ("wacli", "conta", "pasta_dados", "gatilho", "prefixo", "espaco_entre_envios"):
        if not isinstance(wa[campo], str):
            raise ErroConfig(f"whatsapp.{campo} precisa ser um texto")
    for campo in ("meu_numero", "gatilho_sempre", "qualquer_pessoa"):
        wa[campo] = bool(wa[campo])
    wa["gatilho"] = wa["gatilho"].strip().lstrip("@").strip()
    if wa["gatilho"] and not re.match(r"^\w[\w-]*$", wa["gatilho"]):
        raise ErroConfig('whatsapp.gatilho precisa ser uma palavra só, como "pombo"')
    if wa["espaco_entre_envios"] and not re.match(r"^\d+(ms|s)(-\d+(ms|s))?$", wa["espaco_entre_envios"].strip()):
        raise ErroConfig('whatsapp.espaco_entre_envios fica assim: "2s", "500ms" ou "1s-3s" (vazio = sem pausa)')
    wa["espaco_entre_envios"] = wa["espaco_entre_envios"].strip()
    if wa["reacoes"] not in ("simples", "etapas", "nenhuma"):
        raise ErroConfig('whatsapp.reacoes precisa ser "simples" (👀), "etapas" (👀 🎧 🧠 🛠️) ou "nenhuma"')
    if wa["conta"] and not re.match(r"^[A-Za-z0-9_.-]+$", wa["conta"]):
        raise ErroConfig("whatsapp.conta é o nome de uma conta do wacli (letras, números, ponto, hífen)")
    if wa["conta"] and wa["pasta_dados"]:
        raise ErroConfig("use whatsapp.conta ou whatsapp.pasta_dados, não os dois (o wacli não aceita --account com --store)")
    for campo, minimo, maximo in (("contexto_mensagens", 0, 50), ("intervalo_s", 1, 60), ("limite_por_pessoa_dia", 0, 1000)):
        try:
            wa[campo] = int(wa[campo])
            if not minimo <= wa[campo] <= maximo:
                raise ValueError
        except (TypeError, ValueError):
            raise ErroConfig(f"whatsapp.{campo} precisa ser um número de {minimo} a {maximo}")
    if isinstance(wa["conversas"], str):
        wa["conversas"] = [c.strip() for c in re.split(r"[,;\n]+", wa["conversas"]) if c.strip()]
    if not isinstance(wa["conversas"], list) or not wa["conversas"]:
        raise ErroConfig('whatsapp.conversas precisa ter pelo menos uma conversa (ex.: ["eu"])')
    conversas = []
    for c in wa["conversas"]:
        c = str(c).strip().lower()
        if c == "eu" or c in CURINGAS or c == DESCONHECIDOS:
            pass
        elif "@" in c:
            if not JID_VALIDO.match(c):
                raise ErroConfig(f'conversa inválida: "{c}" (use "eu", um número, um JID como 1203...@g.us, '
                                 '"privadas", "grupos" ou "todas")')
        else:
            c = normalizar_numero(c)
        if c not in conversas:
            conversas.append(c)
    wa["conversas"] = conversas
    grupos = any(c.endswith("@g.us") for c in conversas) or "grupos" in conversas or "todas" in conversas
    if wa["meu_numero"]:
        if not wa["prefixo"].strip():
            raise ErroConfig("whatsapp.prefixo não pode ficar vazio no seu número: é por ele que o Pombo não responde "
                             "a si mesmo (o padrão é 🐦)")
        fora_do_eu = [c for c in conversas if c != "eu"]
        if fora_do_eu and not wa["gatilho"]:
            raise ErroConfig("sem gatilho, o bot responderia toda mensagem sua nessas conversas. Defina whatsapp.gatilho "
                             '(ex.: "pombo") ou deixe só a conversa "eu"')
    else:
        if "eu" in conversas:
            raise ErroConfig('a conversa "eu" só existe quando o WhatsApp pareado é o seu número (whatsapp.meu_numero)')
        if not usuarios:
            pass  # sem ninguém liberado, ninguém fala com o bot (quem tentar aparece no painel)
    if wa["qualquer_pessoa"]:
        # outras pessoas chamando um agente: só num número de bot e só em grupos escolhidos um a um (nunca na pasta
        # padrão, na conversa direta ou no seu número, onde ele responderia por você)
        if wa["meu_numero"]:
            raise ErroConfig("whatsapp.qualquer_pessoa só vale num número só do bot (whatsapp.meu_numero = false): no seu "
                             "número, outras pessoas estariam mandando mensagens em seu nome")
        soltas = [c for c in conversas if not c.endswith("@g.us") and c != DESCONHECIDOS]
        if soltas:
            raise ErroConfig("com whatsapp.qualquer_pessoa, o bot só pode escutar grupos escolhidos um a um (JIDs ...@g.us) "
                             f'e "{DESCONHECIDOS}" (a conversa direta de quem nenhum outro bot atende); tire: {", ".join(soltas)}')
    elif DESCONHECIDOS in conversas:
        raise ErroConfig(f'"{DESCONHECIDOS}" é para atender qualquer pessoa: ligue whatsapp.qualquer_pessoa (só num número '
                         "do bot, numa pasta isolada)")
    if (grupos or wa["gatilho_sempre"]) and not wa["gatilho"]:
        raise ErroConfig("defina whatsapp.gatilho: " + ("em grupo, o bot só responde quando chamado"
                                                       if grupos else "gatilho_sempre está ligado"))
    return wa


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


def usuarios_iniciais(canal="telegram"):
    """Bot novo já nasce liberado para o dono deste computador (geral.json: meu_id_telegram).
    No WhatsApp com o seu número, o dono é o próprio número pareado: a lista começa vazia."""
    if canal != "telegram":
        return []
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
    conferir_conversas(bot_id, cfg)
    gravar_json(arq_bot(bot_id), cfg)
    return cfg


def chave_whatsapp(cfg):
    """Bots com a mesma chave usam o mesmo WhatsApp (a mesma conta e pasta do wacli)."""
    wa = cfg.get("whatsapp") or {}
    pasta = wa.get("pasta_dados") or ""
    return f"{wa.get('conta') or ''}|{os.path.abspath(os.path.expanduser(pasta)) if pasta else ''}"


def conferir_conversas(bot_id, cfg):
    """No mesmo WhatsApp, cada conversa fica com um bot só (senão os dois respondem)."""
    if cfg.get("canal") != "whatsapp" or not cfg.get("ativo"):
        return
    minhas = set(cfg["whatsapp"]["conversas"])

    def cobre(cs):  # "todas" cobre "privadas" e "grupos"
        return set(cs) | ({"privadas", "grupos"} if "todas" in cs else set())
    # grupo já ligado pelo nome a um bot de outro computador: é dele (o JID do grupo é o mesmo em qualquer número)
    for maquina, _n, o in bots_de_outros_computadores():
        comum = sorted({c for c in minhas & set((o.get("whatsapp") or {}).get("conversas") or []) if c.endswith("@g.us")})
        if comum:
            raise ErroConfig(f'o grupo {comum[0]} já é do bot "{o.get("id")}" no computador "{maquina}": cada grupo fica '
                             "com um bot só. Tire o grupo de lá antes")
    for outro in listar_ids():
        if outro == bot_id:
            continue
        try:
            o = validar_bot(carregar_bot(outro))
        except ErroConfig:
            continue
        if o["canal"] != "whatsapp" or not o["ativo"]:
            continue
        if chave_whatsapp(o) != chave_whatsapp(cfg):
            # outro número: só os grupos batem (o JID do grupo é o mesmo em qualquer número)
            comum = sorted({c for c in minhas & set(o["whatsapp"]["conversas"]) if c.endswith("@g.us")})
            if comum:
                raise ErroConfig(f'o grupo {comum[0]} já é do bot "{outro}" (em outro número): cada grupo fica com um bot '
                                 "só. Tire o grupo de lá antes, ou pause aquele bot")
            continue
        comum = sorted((minhas & set(o["whatsapp"]["conversas"])) |
                       (cobre(minhas) & cobre(o["whatsapp"]["conversas"]) & {"privadas", "grupos"}))
        if comum:
            nome = ("a conversa com você mesmo" if comum[0] == "eu" else
                    "a conversa direta de quem não está liberado (desconhecidos)" if comum[0] == DESCONHECIDOS else
                    f'"{comum[0]}" (a pasta padrão das conversas dos outros)' if comum[0] in CURINGAS else
                    f"a conversa {comum[0]}")
            raise ErroConfig(f'{nome} já é do bot "{outro}" neste mesmo WhatsApp: cada conversa fica com um bot só. '
                             "Para outra pasta, crie um grupo só seu: pombo whatsapp grupo criar --bot " + bot_id)


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
    """Ordem: segredos.json, Keychain do Mac (token_keychain), variável POMBO_TOKEN_<ID>.
    Bot do WhatsApp não tem token: a sessão fica no wacli."""
    if cfg.get("canal") == "whatsapp":
        return ""
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
