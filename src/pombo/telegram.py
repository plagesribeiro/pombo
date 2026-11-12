"""Cliente mínimo da API de bots do Telegram (só biblioteca padrão)."""
import datetime as dt
import html
import json
import mimetypes
import os
import re
import time
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
