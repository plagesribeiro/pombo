"""Um Telegram de mentira para testes: responde aos métodos que o bot usa e guarda o que ele mandou."""
import itertools
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class TelegramFalso:
    def __init__(self):
        self.updates = []
        self.enviadas = []
        self.chamadas = []
        self._ids = itertools.count(1000)
        self._upd = itertools.count(1)
        self._trava = threading.Condition()
        dono = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                corpo = self.rfile.read(n)
                tipo = self.headers.get("Content-Type", "")
                params = {} if "multipart" in tipo else dict(urllib.parse.parse_qsl(corpo.decode()))
                metodo = self.path.rsplit("/", 1)[-1]
                r = dono.tratar(metodo, params, corpo if "multipart" in tipo else None)
                dados = json.dumps(r).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def fechar(self):
        self.srv.shutdown()

    def tratar(self, metodo, p, arquivo):
        self.chamadas.append((metodo, p))
        if metodo == "getMe":
            return {"ok": True, "result": {"id": 1, "is_bot": True, "username": "bot_de_teste"}}
        if metodo == "getUpdates":
            offset = int(p.get("offset") or 0)
            fim = time.time() + min(float(p.get("timeout") or 0), 1.0)
            with self._trava:
                while True:
                    novos = [u for u in self.updates if u["update_id"] >= offset]
                    if novos or time.time() >= fim:
                        return {"ok": True, "result": novos}
                    self._trava.wait(0.1)
        if metodo == "sendMessage":
            mid = next(self._ids)
            with self._trava:
                self.enviadas.append({"message_id": mid, "chat_id": int(p["chat_id"]), "text": p.get("text", ""),
                                      "reply_to": p.get("reply_to_message_id")})
                self._trava.notify_all()
            return {"ok": True, "result": {"message_id": mid}}
        if metodo in ("editMessageText", "deleteMessage", "sendChatAction", "setMyCommands", "deleteWebhook"):
            return {"ok": True, "result": True}
        if metodo in ("sendDocument", "sendPhoto", "sendVoice", "sendAudio"):
            mid = next(self._ids)
            self.enviadas.append({"message_id": mid, "arquivo": True, "metodo": metodo})
            return {"ok": True, "result": {"message_id": mid}}
        return {"ok": False, "error_code": 400, "description": f"método {metodo} não existe no falso"}

    def mandar(self, de, texto, responder_a=None, nome="Teste"):
        """Simula uma mensagem privada de `de`."""
        m = {"message_id": next(self._ids), "from": {"id": de, "first_name": nome, "username": f"u{de}"},
             "chat": {"id": de, "type": "private"}, "date": int(time.time()), "text": texto}
        if responder_a:
            m["reply_to_message"] = {"message_id": responder_a, "text": "(mensagem do bot)"}
        with self._trava:
            self.updates.append({"update_id": next(self._upd), "message": m})
            self._trava.notify_all()
        return m["message_id"]

    def esperar(self, condicao, timeout=180):
        """Espera uma mensagem enviada que satisfaça a condição. Devolve a mensagem ou None."""
        fim = time.time() + timeout
        with self._trava:
            while time.time() < fim:
                for e in self.enviadas:
                    if not e.get("visto") and condicao(e):
                        e["visto"] = True
                        return e
                self._trava.wait(0.5)
        return None
