"""Testes rápidos, sem rede e sem Claude. Rode: python3 -m unittest discover tests"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(RAIZ, "src"), RAIZ]
os.environ["POMBO_DIR"] = tempfile.mkdtemp(prefix="pombo-unidade-")

from pombo import config, motores, rotinas  # noqa: E402
from pombo.telegram import para_html, pedacos  # noqa: E402


class Config(unittest.TestCase):
    def test_bot_padrao_valida(self):
        cfg = config.validar_bot({"pasta": "~/x"})
        self.assertEqual(cfg["permissoes"], "total")
        self.assertEqual(cfg["rotinas"], [])

    def test_campo_desconhecido(self):
        with self.assertRaises(config.ErroConfig):
            config.validar_bot({"pasta": "~", "pastaa": "x"})

    def test_usuarios_viram_numero(self):
        self.assertEqual(config.validar_bot({"pasta": "~", "usuarios_permitidos": ["12", 3]})["usuarios_permitidos"], [12, 3])

    def test_mcp_precisa_comando_ou_url(self):
        with self.assertRaises(config.ErroConfig):
            config.validar_bot({"pasta": "~", "mcps": {"x": {"args": []}}})
        config.validar_bot({"pasta": "~", "mcps": {"x": {"type": "http", "url": "https://exemplo"}}})

    def test_rotina_normaliza(self):
        r = config.validar_rotina({"nome": "Triagem do E-mail", "horarios": "7:00, 17:30 7:00", "dias": "sex,Seg", "prompt": "x"})
        self.assertEqual(r["id"], "triagem-do-e-mail")
        self.assertEqual(r["horarios"], ["07:00", "17:30"])
        self.assertEqual(r["dias"], ["seg", "sex"])

    def test_rotina_invalida(self):
        for ruim in ({"horarios": ["24:00"], "prompt": "x"}, {"dias": ["xyz"], "prompt": "x"}, {"prompt": " "},
                     {"prompt": "x", "conversa": "talvez"}, {"prompt": "x", "id": "Com Espaço"}):
            with self.assertRaises(config.ErroConfig, msg=ruim):
                config.validar_rotina({"nome": "r", **ruim})

    def test_rotinas_com_mesmo_id(self):
        with self.assertRaises(config.ErroConfig):
            config.validar_bot({"pasta": "~", "rotinas": [{"id": "a", "prompt": "x"}, {"id": "a", "prompt": "y"}]})

    def test_aplicar_campos(self):
        d = config.aplicar_campos({"env": {"A": "1"}}, ["nome=Meu bot", "ativo=false", 'plugin_dirs=["a"]', "env.B=2", "env.A="])
        self.assertEqual(d, {"env": {"B": 2}, "nome": "Meu bot", "ativo": False, "plugin_dirs": ["a"]})

    def test_salvar_e_carregar(self):
        config.salvar_bot("unidade", {"pasta": "/tmp", "rotinas": [{"nome": "R", "prompt": "p", "horarios": ["08:00"]}]})
        cfg = config.carregar_bot("unidade")
        self.assertEqual(cfg["nome"], "unidade")
        self.assertEqual(cfg["rotinas"][0]["id"], "r")
        self.assertIn("unidade", config.listar_ids())
        with self.assertRaises(config.ErroConfig):
            config.salvar_bot("Id Ruim", {"pasta": "/tmp"})

    def test_bot_novo_nasce_liberado_para_o_dono(self):
        g = config.carregar_geral()
        config.salvar_geral({**g, "meu_id_telegram": 0})
        self.assertEqual(config.usuarios_iniciais(), [])
        config.anotar_dono(777)
        config.anotar_dono(888)  # o primeiro fica
        self.assertEqual(config.usuarios_iniciais(), [777])
        from pombo.painel import criar_bot
        criar_bot({"nome": "Novo Dono", "pasta": "/tmp"})
        self.assertEqual(config.carregar_bot("novo-dono")["usuarios_permitidos"], [777])

    def test_token_fica_fora_do_bot(self):
        config.salvar_bot("tok", {"pasta": "/tmp"})
        config.gravar_token("tok", "123456:" + "A" * 35)
        self.assertEqual(config.token_do_bot("tok", config.carregar_bot("tok")), "123456:" + "A" * 35)
        self.assertNotIn("AAAA", open(config.arq_bot("tok")).read())
        if os.name != "nt":
            self.assertEqual(os.stat(config.caminho("segredos.json")).st_mode & 0o777, 0o600)
        config.remover_bot("tok")
        self.assertNotIn("tok", config.ler_json(config.caminho("segredos.json"), {}))


class Rotinas(unittest.TestCase):
    R = {"ativa": True, "horarios": ["07:00", "17:00"], "dias": [], "tolerancia_min": 90}

    def t(self, s):
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")

    def test_rotina_nova_nao_roda_na_hora(self):
        self.assertEqual(rotinas.decidir(self.R, self.t("2026-11-11 08:00"), None), ("iniciar", "2026-11-11 07:00"))

    def test_roda_no_horario(self):
        self.assertEqual(rotinas.decidir(self.R, self.t("2026-11-11 17:00"), "2026-11-11 07:00"), ("rodar", "2026-11-11 17:00"))

    def test_nao_repete(self):
        self.assertEqual(rotinas.decidir(self.R, self.t("2026-11-11 17:05"), "2026-11-11 17:00")[0], None)

    def test_perdida_depois_da_tolerancia(self):
        self.assertEqual(rotinas.decidir(self.R, self.t("2026-11-11 19:00"), "2026-11-11 07:00"), ("perdida", "2026-11-11 17:00"))

    def test_atrasada_dentro_da_tolerancia(self):
        self.assertEqual(rotinas.decidir(self.R, self.t("2026-11-11 18:00"), "2026-11-11 07:00")[0], "rodar")

    def test_dias_da_semana(self):
        r = {**self.R, "dias": ["seg"]}  # 2026-11-09 é segunda
        self.assertEqual(rotinas.ultimo_horario(r, self.t("2026-11-11 12:00")), self.t("2026-11-09 17:00"))
        self.assertEqual(rotinas.proximo_horario(r, self.t("2026-11-11 12:00")), self.t("2026-11-16 07:00"))

    def test_pausada_e_sem_horario(self):
        self.assertEqual(rotinas.decidir({**self.R, "ativa": False}, self.t("2026-11-11 17:00"), None)[0], None)
        self.assertEqual(rotinas.decidir({**self.R, "horarios": []}, self.t("2026-11-11 17:00"), None)[0], None)


class Telegram(unittest.TestCase):
    def test_html(self):
        self.assertEqual(para_html("**oi** `x<y` [site](https://a.b) [arq](/tmp/x)"),
                         '<b>oi</b> <code>x&lt;y</code> <a href="https://a.b">site</a> arq')

    def test_pedacos(self):
        partes = pedacos("a" * 9000)
        self.assertTrue(all(len(p) <= 3800 for p in partes))
        self.assertEqual("".join(partes), "a" * 9000)


class Motor(unittest.TestCase):
    def cmd(self, **kw):
        cfg = config.validar_bot({"pasta": "/tmp", **kw})
        return motores.comando_claude(cfg, config.carregar_geral(), "m", "SIS", "sessao-1")

    def test_total(self):
        cmd, env = self.cmd()
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], "sessao-1")
        self.assertNotIn("ENABLE_CLAUDEAI_MCP_SERVERS", env)

    def test_lista_e_conectores(self):
        cmd, env = self.cmd(permissoes="lista", ferramentas_permitidas=["Read", "Grep"], ferramentas_negadas=["Bash"],
                            conectores_claude_ai=False, modelo="haiku")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1:cmd.index("--allowedTools") + 3], ["Read", "Grep"])
        self.assertIn("--disallowedTools", cmd)
        self.assertEqual(env["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
        self.assertEqual(cmd[cmd.index("--model") + 1], "haiku")

    def test_mcps_do_bot(self):
        cmd, _ = self.cmd(mcps={"x": {"command": "echo"}}, so_mcps_do_bot=True)
        arq = cmd[cmd.index("--mcp-config") + 1]
        self.assertEqual(json.load(open(arq)), {"mcpServers": {"x": {"command": "echo"}}})
        self.assertIn("--strict-mcp-config", cmd)

    def test_chrome(self):
        self.assertNotIn("--chrome", self.cmd()[0])
        self.assertIn("--chrome", self.cmd(chrome=True)[0])

    def test_env_do_bot(self):
        _, env = self.cmd(env={"CLAUDE_CONFIG_DIR": "~/outra"})
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], os.path.expanduser("~/outra"))
        self.assertTrue(env["POMBO_BOT"])  # `pombo atualizar` sabe de qual bot veio o pedido


class Atualizar(unittest.TestCase):
    def setUp(self):
        from pombo import atualizar
        self.a = atualizar
        atualizar.apagar()

    def test_decidir(self):
        d = self.a.decidir
        self.assertEqual(d(None, 100, True), "nada")
        self.assertEqual(d({"quando": 50}, 100, False), "avisar")  # gravado antes de o processo subir
        self.assertEqual(d({"quando": 150}, 100, False), "esperar")
        self.assertEqual(d({"quando": 150}, 100, True), "reiniciar")

    def test_mensagem(self):
        m = self.a.mensagem({"antes": "a1 velho", "depois": "b2 novo"}, "Note")
        self.assertIn("atualizado e reiniciado com sucesso em Note", m)
        self.assertIn("b2 novo", m)
        self.assertNotIn("Antes", self.a.mensagem({"antes": "b2", "depois": "b2"}, "Note"))
        self.assertIn("pombo servico instalar", self.a.mensagem({"antes": "a", "depois": "b", "reinstalar": True}, "Note"))

    def test_mudou_instalador(self):
        import subprocess
        repo = tempfile.mkdtemp()
        git = lambda *x: subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *x],
                                        check=True, capture_output=True)
        git("init", "-q")
        for nome in ("README.md", "src/pombo/instalar.py"):
            os.makedirs(os.path.dirname(os.path.join(repo, nome)), exist_ok=True)
            open(os.path.join(repo, nome), "w").write("1")
        git("add", "README.md"); git("commit", "-qm", "a")
        c1 = self.a.commit(repo)
        open(os.path.join(repo, "README.md"), "w").write("2")
        git("commit", "-qam", "b")
        c2 = self.a.commit(repo)
        git("add", "src"); git("commit", "-qm", "c")
        c3 = self.a.commit(repo)
        self.assertTrue(self.a.eh_git(repo))
        self.assertFalse(self.a.mudou_instalador(repo, c1, c2))
        self.assertTrue(self.a.mudou_instalador(repo, c2, c3))
        self.assertEqual(self.a.versao(repo), self.a.versao(repo, c3))
        self.assertTrue(self.a.versao(repo).endswith(" c"))

    def test_servico_espera_ficar_parado_e_avisa(self):
        import time
        from unittest import mock
        from pombo import servico
        s = servico.Servico()
        ocupado = mock.Mock(ocupado=True, fila=mock.Mock(empty=lambda: True))
        s.runners = {"b": ocupado}
        self.a.gravar(self.a.novo_marcador("a1", "b2", False, "b"))
        with mock.patch.object(self.a, "reiniciar_processo") as reiniciar:
            s.conferir_atualizacao()  # ocupado: espera
            ocupado.ocupado = False
            s.conferir_atualizacao()  # 1ª vez parado: ainda espera (pode ter acabado de sair da fila)
            reiniciar.assert_not_called()
            s.conferir_atualizacao()
            reiniciar.assert_called_once()
        # o processo novo sobe depois do aviso: manda o ✅ pelo bot que pediu e apaga o aviso
        novo = servico.Servico()
        novo.inicio = time.time() + 1
        bot = mock.Mock(id="b", tg=object(), dono=lambda: 7)
        novo.runners = {"b": bot}
        with mock.patch("pombo.telegram.responder") as responder:
            novo.conferir_atualizacao()
        self.assertEqual(responder.call_args[0][1], 7)
        self.assertIn("b2", responder.call_args[0][2])
        self.assertIsNone(self.a.ler())


class Migrar(unittest.TestCase):
    def test_migrar_config_antiga(self):
        from pombo.migrar import migrar
        antigo = os.path.join(tempfile.mkdtemp(), "config.json")
        json.dump({"nome_maquina": "Mac", "token_keychain": "svc", "usuarios_permitidos": [7], "pasta_trabalho": "/tmp",
                   "permissoes": "bypassPermissions", "instrucoes_extra": "seja breve", "plugin_dirs": ["p"],
                   "transcricao_cmd": ["x", "{arquivo}"], "chrome": True}, open(antigo, "w"))
        json.dump({"offset": 55, "sessoes": {"7": {"id": "s", "ultima": 1}}}, open(os.path.join(os.path.dirname(antigo), "estado.json"), "w"))
        migrar(antigo, "migrado", "Ana")
        cfg = config.carregar_bot("migrado")
        self.assertEqual((cfg["pasta"], cfg["permissoes"], cfg["instrucoes"], cfg["token_keychain"]), ("/tmp", "total", "seja breve", "svc"))
        self.assertTrue(cfg["chrome"])
        self.assertEqual(config.Estado("migrado").ler()["offset"], 55)
        self.assertEqual(config.carregar_geral()["usuario_nome"], "Ana")
        self.assertTrue(os.path.exists(antigo + ".migrado"))


if __name__ == "__main__":
    unittest.main()
