"""Cliente mínimo da API de bots do Telegram (só biblioteca padrão)."""
import datetime as dt
import html
import json
import mimetypes
import os
import re
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ErroTelegram(RuntimeError):
    def __init__(self, metodo, codigo, descricao):
        super().__init__(f"{metodo}: {codigo} {descricao}")
        self.codigo = codigo
        self.descricao = descricao


class Telegram:
    def __init__(self, token, api="https://api.telegram.org", log=None):
        api = (api or "https://api.telegram.org").rstrip("/")
        self.base = f"{api}/bot{token}/"
        self.arquivos = f"{api}/file/bot{token}/"
        self.log = log or (lambda m: None)

    def call(self, metodo, _timeout=30, _tentativas=None, **params):
        dados = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
        # rede instável: tenta de novo antes de desistir. O getUpdates não repete, porque o laço já repete.
        tentativas = _tentativas or (1 if metodo == "getUpdates" else 5)
        d = None
        for n in range(tentativas):
            req = urllib.request.Request(self.base + metodo, data=dados)
            try:
                with urllib.request.urlopen(req, timeout=_timeout) as r:
                    d = json.load(r)
                break
            except urllib.error.HTTPError as e:
                try:
                    d = json.load(e)
                except ValueError:
                    raise ErroTelegram(metodo, e.code, "resposta inválida")
                break
            except (urllib.error.URLError, OSError) as e:
                if n == tentativas - 1:
                    raise
                self.log(f"{metodo} falhou ({e}); tentando de novo ({n + 2}/{tentativas})")
                time.sleep([2, 5, 10, 20][min(n, 3)])
        if not d.get("ok"):
            raise ErroTelegram(metodo, d.get("error_code"), d.get("description"))
        return d["result"]

    def enviar_arquivo(self, chat, caminho, legenda=None):
        limite = "----pombo" + uuid.uuid4().hex
        nome = os.path.basename(caminho)
        tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
        partes = []
        for k, v in (("chat_id", str(chat)), ("caption", legenda)):
            if v:
                partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        with open(caminho, "rb") as f:
            conteudo = f.read()
        ext = os.path.splitext(nome)[1].lower()
        metodo, campo = (("sendVoice", "voice") if ext in (".ogg", ".oga", ".opus")
                         else ("sendAudio", "audio") if ext in (".mp3", ".m4a")
                         else ("sendPhoto", "photo") if ext in (".jpg", ".jpeg", ".png", ".webp")
                         else ("sendDocument", "document"))
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{campo}"; filename="{nome}"\r\n'
                      f'Content-Type: {tipo}\r\n\r\n'.encode() + conteudo + b"\r\n")
        corpo = b"".join(partes) + f"--{limite}--\r\n".encode()
        req = urllib.request.Request(self.base + metodo, data=corpo,
                                     headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)

    def baixar(self, file_id, pasta):
        f = self.call("getFile", file_id=file_id)
        os.makedirs(pasta, exist_ok=True)
        destino = os.path.join(pasta, f"{dt.datetime.now():%Y%m%d-%H%M%S}-{os.path.basename(f['file_path'])}")
        urllib.request.urlretrieve(self.arquivos + f["file_path"], destino)
        return destino


def para_html(texto):
    """Markdown simples do Claude -> HTML do Telegram."""
    guardados = []

    def guarda(s):
        guardados.append(s)
        return f"\x00{len(guardados) - 1}\x00"

    t = re.sub(r"```[^\n]*\n(.*?)```", lambda m: guarda(f"<pre>{html.escape(m.group(1).rstrip())}</pre>"), texto, flags=re.S)
    t = re.sub(r"`([^`\n]+)`", lambda m: guarda(f"<code>{html.escape(m.group(1))}</code>"), t)

    def link(m):
        rotulo, url = m.group(1), m.group(2).strip()
        if url.startswith(("http://", "https://")):
            return guarda(f'<a href="{html.escape(url, quote=True)}">{html.escape(rotulo)}</a>')
        return guarda(html.escape(rotulo))

    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
    t = html.escape(t, quote=False)
    t = re.sub(r"(?m)^#{1,6}\s*(.+)$", r"<b>\1</b>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"(?<![\w/])_(?!\s)(.+?)(?<!\s)_(?![\w/])", r"<i>\1</i>", t)
    for _ in range(2):
        t = re.sub(r"\x00(\d+)\x00", lambda m: guardados[int(m.group(1))], t)
    return t


def pedacos(texto, limite=3800):
    blocos, atual = [], ""
    for par in texto.split("\n\n"):
        while len(par) > limite:
            blocos.append(par[:limite])
            par = par[limite:]
        if atual and len(atual) + len(par) + 2 > limite:
            blocos.append(atual)
            atual = par
        else:
            atual = f"{atual}\n\n{par}" if atual else par
    if atual:
        blocos.append(atual)
    return blocos or ["(sem texto)"]


def responder(tg, chat, texto, responder_a=None, log=None, silencioso=False):
    """Manda o texto (em partes, se for longo). Devolve os message_id enviados."""
    ids = []
    for i, p in enumerate(pedacos(texto)):
        extra = dict(reply_to_message_id=responder_a if i == 0 else None, allow_sending_without_reply="true",
                     disable_web_page_preview="true", disable_notification="true" if silencioso else None)
        try:
            r = tg.call("sendMessage", chat_id=chat, text=para_html(p), parse_mode="HTML", **extra)
        except ErroTelegram as e:
            if log:
                log(f"HTML recusado ({e}); mandando sem formatação")
            r = tg.call("sendMessage", chat_id=chat, text=p, **extra)
        ids.append(r.get("message_id"))
    return ids


# ---------------------------------------------------------------- o canal (o que o BotRunner usa)

FORMATO = ('Formato da resposta: só **negrito**, listas com "-", `código` e [rótulo](link). Nada de tabelas nem títulos '
           'com #. Nome de arquivo, pasta ou caminho sempre em `código` (ex.: `Pombo.app`, `notas.md`): solto, o Telegram '
           'transforma em link de site.')

# /novo apaga o contexto: fica longe do topo do menu, onde é fácil tocar sem querer
COMANDOS = [
    {"command": "status", "description": "mostra se estou ocupado"},
    {"command": "rotinas", "description": "lista as rotinas agendadas"},
    {"command": "atualizar", "description": "atualiza o Pombo e reinicia"},
    {"command": "parar", "description": "interrompe o que estiver rodando"},
    {"command": "novo", "description": "esquece a conversa e começa outra"},
    {"command": "ajuda", "description": "o que eu sei fazer"},
]


class Andamento:
    """A mensagem "👀 Recebi!" que vai sendo editada com o que o agente está fazendo e some no fim."""

    def __init__(self, tg, chat, responder_a, inicio="👀 Recebi! Tô vendo aqui…", prefixo=""):
        self.tg, self.chat, self.prefixo = tg, chat, prefixo
        self.texto, self.ultimo_envio, self.mid = "", 0.0, None
        self.ativo = True
        self._lock = threading.Lock()
        try:
            r = tg.call("sendMessage", chat_id=chat, text=inicio, reply_to_message_id=responder_a,
                        allow_sending_without_reply="true", disable_notification="true")
            self.mid, self.texto = r["message_id"], inicio
        except Exception:
            pass
        threading.Thread(target=self._digitando, daemon=True).start()

    def _digitando(self):
        while self.ativo:
            try:
                self.tg.call("sendChatAction", chat_id=self.chat, action="typing", _tentativas=1)
            except Exception:
                pass
            for _ in range(9):
                if not self.ativo:
                    return
                time.sleep(0.5)

    def mostrar(self, texto, forcar=False):
        texto = (self.prefixo + texto.strip())[:300]
        with self._lock:
            if not self.mid or not texto or texto == self.texto:
                return
            if not forcar and time.time() - self.ultimo_envio < 3:
                return
            try:
                self.tg.call("editMessageText", chat_id=self.chat, message_id=self.mid, text=texto, _tentativas=1)
                self.texto, self.ultimo_envio = texto, time.time()
            except Exception:
                pass

    def fim(self):
        self.ativo = False
        if self.mid:
            try:
                self.tg.call("deleteMessage", chat_id=self.chat, message_id=self.mid, _tentativas=2)
            except Exception:
                pass


class CanalTelegram:
    """Um bot do Telegram: escuta pelo getUpdates e responde pela API de bots."""

    nome = "Telegram"
    formato = FORMATO
    limite_arquivo = 49_000_000
    dica = "Responder a uma mensagem minha continua a conversa daquela mensagem."

    def __init__(self, runner, token):
        self.r = runner
        self.tg = Telegram(token, runner.geral.get("telegram_api"), log=runner.log)

    # ---- quem é quem

    def chat_do_dono(self):
        u = self.r.cfg["usuarios_permitidos"]
        return u[0] if u else None  # numa conversa privada do Telegram, o chat é o próprio ID da pessoa

    def eh_dono(self, de):
        return de is not None and de == self.chat_do_dono()

    # ---- mandar

    def responder(self, chat, texto, responder_a=None, silencioso=False):
        return responder(self.tg, chat, texto, responder_a, log=self.r.log, silencioso=silencioso)

    def aviso(self, chat, texto, responder_a=None):
        try:
            self.tg.call("sendMessage", chat_id=chat, text=texto, reply_to_message_id=responder_a,
                         disable_notification="true")
        except Exception:
            pass

    def enviar_arquivo(self, chat, caminho):
        r = self.tg.enviar_arquivo(chat, caminho)
        return ((r or {}).get("result") or {}).get("message_id")

    def andamento(self, chat, responder_a, inicio="👀 Recebi! Tô vendo aqui…", prefixo=""):
        return Andamento(self.tg, chat, responder_a, inicio=inicio, prefixo=prefixo)

    def baixar(self, anexo, pasta):
        return self.tg.baixar(anexo, pasta)

    def parar(self):
        pass

    # ---- receber

    def ouvir(self):
        r = self.r
        espera = r.parar_evento.wait
        while not r.parar_evento.is_set():
            try:
                me = self.tg.call("getMe", _tentativas=1)
                r.username = me.get("username", "")
                break
            except ErroTelegram as e:
                r.erro = ("o Telegram recusou o token (401). Confira o token no painel."
                          if e.codigo in (401, 404) else f"Telegram: {e}")
                r.log(r.erro)
                espera(60)
            except Exception as e:
                r.erro = f"sem conexão com o Telegram ainda ({e})"
                espera(5)
        if r.parar_evento.is_set():
            return
        for metodo, params in (("deleteWebhook", {}), ("setMyCommands", {"commands": json.dumps(COMANDOS)})):
            try:
                self.tg.call(metodo, _tentativas=2, **params)
            except Exception as e:
                r.log(f"{metodo} falhou: {e}")
        r.anunciar_ligado(f"@{r.username}")
        while not r.parar_evento.is_set():
            offset = r.estado.ler().get("offset")
            try:
                ups = self.tg.call("getUpdates", _timeout=35, offset=offset, timeout=25,
                                   allowed_updates=json.dumps(["message"]))
            except ErroTelegram as e:
                if e.codigo == 409:
                    r.erro = "outro computador está lendo este mesmo bot (erro 409). Cada máquina precisa do seu bot."
                elif e.codigo in (401, 404):
                    r.erro = "o Telegram recusou o token (401). Confira o token no painel."
                else:
                    r.erro = f"Telegram: {e}"
                r.log(r.erro)
                espera(30)
                continue
            except Exception as e:
                r.erro = f"sem conexão com o Telegram ({e})"
                espera(5)
                continue
            if r.erro.startswith(("outro computador", "sem conexão", "Telegram:")):
                r.erro = ""
            for u in ups:
                r.estado.atualizar(lambda d: d.__setitem__("offset", u["update_id"] + 1))
                if r.parar_evento.is_set():
                    break
                try:
                    self.receber(u.get("message") or {})
                except Exception:
                    r.log("erro ao receber:\n" + traceback.format_exc())

    def receber(self, m):
        de = (m.get("from") or {}).get("id")
        chat = m.get("chat") or {}
        if chat.get("type") != "private" or chat.get("id") != de:
            self.r.log(f"ignorado: mensagem fora de conversa privada ({chat.get('type')})")
            return
        if de not in self.r.cfg["usuarios_permitidos"]:
            self.desconhecido(m)
            return
        self.r.chegou(self.normalizar(m))

    @staticmethod
    def normalizar(m):
        """Mensagem do Telegram -> o formato que o BotRunner entende (o mesmo do WhatsApp)."""
        audio = m.get("voice") or m.get("audio")
        doc = m.get("document")
        citada = m.get("reply_to_message") or {}
        return {
            "chat": (m.get("chat") or {}).get("id"),
            "id": m.get("message_id"),
            "de": (m.get("from") or {}).get("id"),
            "texto": m.get("text") or m.get("caption") or "",
            "pode_comando": bool(m.get("text")),
            "audio": audio["file_id"] if audio else None,
            "fotos": [m["photo"][-1]["file_id"]] if m.get("photo") else [],
            "arquivos": [{"nome": doc.get("file_name"), "anexo": doc["file_id"]}] if doc else [],
            "citada": {"id": citada.get("message_id"), "texto": citada.get("text") or ""} if citada else {},
        }

    def desconhecido(self, m):
        r = self.r
        de = m.get("from") or {}
        nome = " ".join(x for x in (de.get("first_name"), de.get("last_name")) if x)
        r.log(f"ignorado: mensagem de {de.get('id')} ({de.get('username')}), que não está liberado")
        r.anotar_desconhecido(de.get("id"), nome, de.get("username") or "", m.get("text") or "")
        if not r.cfg["usuarios_permitidos"]:
            try:
                responder(self.tg, de.get("id"), (
                    f"Este bot ainda não tem dono. Seu ID do Telegram é `{de.get('id')}`.\n\n"
                    f"Para liberar você, abra o painel no computador e toque em **Liberar**, ou rode:\n"
                    f"`{r.cli()} bots liberar {r.id} {de.get('id')}`"), log=r.log)
            except Exception:
                pass
