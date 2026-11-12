"""Teste de ponta a ponta: o serviço de verdade, o Claude Code de verdade (modelo haiku) e um Telegram falso.

Custa alguns centavos e leva 1 a 3 minutos. Só roda com POMBO_E2E=1:
  POMBO_E2E=1 python3 -m unittest tests.test_ponta_a_ponta -v
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(RAIZ, "src"), RAIZ]


def porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@unittest.skipUnless(os.environ.get("POMBO_E2E") == "1", "defina POMBO_E2E=1 para rodar (usa o Claude de verdade)")
class PontaAPonta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["POMBO_DIR"] = tempfile.mkdtemp(prefix="pombo-e2e-")
        from pombo import config
        from tests.telegram_falso import TelegramFalso
        cls.config = config
        cls.tg = TelegramFalso()
        cls.porta = porta_livre()
        cls.pasta = tempfile.mkdtemp(prefix="pombo-e2e-pasta-")
        with open(os.path.join(cls.pasta, "segredo.txt"), "w") as f:
            f.write("abacaxi\n")
        config.garantir_pastas()
        config.salvar_geral({**config.carregar_geral(), "nome_maquina": "Teste", "usuario_nome": "Fulano",
                             "painel_porta": cls.porta, "telegram_api": cls.tg.url})
        config.salvar_bot("e2e", {"nome": "Bot E2E", "pasta": cls.pasta, "usuarios_permitidos": [42], "modelo": "haiku",
                                  "conectores_claude_ai": False})
        config.gravar_token("e2e", "123456:" + "A" * 35)
        from pombo.servico import Servico
        cls.servico = Servico()
        threading.Thread(target=cls.servico.rodar, daemon=True).start()
        fim = time.time() + 20
        while time.time() < fim and not any(c[0] == "getUpdates" for c in cls.tg.chamadas):
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        for r in list(cls.servico.runners.values()):
            r.parar()
        cls.tg.fechar()

    def api(self, metodo, caminho, corpo=None, cabecalho=True, host=None):
        h = {"Content-Type": "application/json"}
        if cabecalho:
            h["X-Pombo"] = "1"
        if host:
            h["Host"] = host
        req = urllib.request.Request(f"http://127.0.0.1:{self.porta}{caminho}", method=metodo, headers=h,
                                     data=None if corpo is None else json.dumps(corpo).encode())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_1_pedido_e_continuacao(self):
        self.tg.mandar(42, "Leia o arquivo segredo.txt e responda só com a palavra que está nele, nada mais.")
        r = self.tg.esperar(lambda e: e.get("chat_id") == 42 and "abacaxi" in e.get("text", "").lower())
        self.assertIsNotNone(r, f"não chegou a resposta. Enviadas: {self.tg.enviadas}")
        # respondendo à mensagem do bot, a conversa continua
        self.tg.mandar(42, "Qual palavra você me respondeu na mensagem anterior? Responda só a palavra.", responder_a=r["message_id"])
        r2 = self.tg.esperar(lambda e: e.get("chat_id") == 42 and "abacaxi" in e.get("text", "").lower() and e.get("reply_to"))
        self.assertIsNotNone(r2, f"a conversa não continuou. Enviadas: {self.tg.enviadas}")
        from pombo.registro import ler_execucoes
        fim = time.time() + 10  # o histórico é gravado logo depois da resposta
        while len(ler_execucoes("e2e")) < 2 and time.time() < fim:
            time.sleep(0.3)
        execs = ler_execucoes("e2e")
        self.assertGreaterEqual(len(execs), 2)
        self.assertTrue(all(x["ok"] for x in execs))

    def test_2_desconhecido_nao_roda(self):
        antes = len(self.tg.enviadas)
        self.tg.mandar(99, "oi, me deixa usar?", nome="Estranho")
        time.sleep(3)
        est = self.config.Estado("e2e").ler()
        self.assertIn(99, [d["id"] for d in est.get("desconhecidos", [])])
        self.assertFalse(any(e.get("chat_id") == 99 for e in self.tg.enviadas[antes:]), "respondeu a um desconhecido")

    def test_3_painel_e_rotina(self):
        st, d = self.api("GET", "/api/estado")
        self.assertEqual(st, 200)
        bot = next(b for b in d["bots"] if b["id"] == "e2e")
        self.assertEqual(bot["estado"]["situacao"], "ligado")
        self.assertTrue(bot["token_definido"])
        self.assertNotIn("AAAA", json.dumps(d))  # o token nunca sai pela API
        cfg = bot["cfg"]
        cfg["rotinas"] = [{"nome": "Contar arquivos", "horarios": ["06:00"], "prompt": "Diga quantos arquivos .txt existem nesta pasta. Responda no formato: TOTAL=N"}]
        st, d = self.api("PUT", "/api/bots/e2e", {"cfg": cfg})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["cfg"]["rotinas"][0]["id"], "contar-arquivos")
        time.sleep(3)  # o serviço percebe a mudança
        st, d = self.api("POST", "/api/bots/e2e/rotinas/contar-arquivos/rodar", {})
        self.assertEqual(st, 200, d)
        r = self.tg.esperar(lambda e: e.get("chat_id") == 42 and "Contar arquivos" in e.get("text", "") and "TOTAL=1" in e.get("text", ""))
        self.assertIsNotNone(r, f"a rotina não respondeu. Enviadas: {self.tg.enviadas[-3:]}")

    def test_4_seguranca_do_painel(self):
        self.assertEqual(self.api("PUT", "/api/geral", {"usuario_nome": "x"}, cabecalho=False)[0], 403)
        self.assertEqual(self.api("GET", "/api/estado", host="evil.example:80")[0], 403)
        self.assertEqual(self.api("PUT", "/api/bots/e2e", {"cfg": {"pasta": "/tmp", "permissoes": "xyz"}})[0], 400)

    def test_6_agenda_e_silenciosa(self):
        import datetime as dt
        agora = dt.datetime.now()
        hora = agora.strftime("%H:%M")
        cfg = self.config.carregar_bot("e2e")
        cfg["rotinas"] = [
            {"id": "no-horario", "nome": "No horário", "horarios": [hora], "prompt": "Responda exatamente: AGENDADA_OK"},
            {"id": "quieta", "nome": "Quieta", "horarios": [hora], "silenciosa": True, "prompt": "Não há nada de novo hoje."},
        ]
        self.config.salvar_bot("e2e", cfg)
        ontem = (agora - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        self.config.Estado("e2e").atualizar(lambda d: d.setdefault("rotinas", {}).update(
            {"no-horario": {"marca": ontem}, "quieta": {"marca": ontem}}))
        time.sleep(3)  # o serviço recarrega a configuração
        self.servico.agendar()
        r = self.tg.esperar(lambda e: e.get("chat_id") == 42 and "AGENDADA_OK" in e.get("text", ""))
        self.assertIsNotNone(r, "a rotina agendada não rodou")
        from pombo.registro import ler_execucoes
        fim = time.time() + 120
        while time.time() < fim and not any(x.get("rotina") == "quieta" for x in ler_execucoes("e2e")):
            time.sleep(1)
        quieta = next((x for x in ler_execucoes("e2e") if x.get("rotina") == "quieta"), None)
        self.assertIsNotNone(quieta, "a rotina silenciosa não rodou")
        self.assertIn("nada enviado", quieta["resposta"])
        self.assertFalse(any("Quieta" in e.get("text", "") for e in self.tg.enviadas), "a rotina silenciosa mandou mensagem")
        # não roda de novo no mesmo horário
        self.servico.agendar()
        time.sleep(2)
        self.assertEqual(self.servico.runners["e2e"].fila.qsize(), 0)

    def test_5_comandos(self):
        self.tg.mandar(42, "/rotinas")
        self.assertIsNotNone(self.tg.esperar(lambda e: e.get("chat_id") == 42 and "/rodar N" in e.get("text", ""), 15))
        self.tg.mandar(42, "/status")
        self.assertIsNotNone(self.tg.esperar(lambda e: e.get("chat_id") == 42 and "Bot E2E" in e.get("text", ""), 15))


if __name__ == "__main__":
    unittest.main()
