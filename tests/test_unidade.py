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
os.environ["HOME"] = tempfile.mkdtemp(prefix="pombo-casa-")  # nada de ler o ~/.wacli de verdade de quem roda os testes

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

    def test_lista_le_os_anexos_do_bot(self):
        cmd, _ = self.cmd(permissoes="lista", ferramentas_permitidas=["Read(./**)"])
        regra = cmd[cmd.index("--allowedTools") + 2]
        self.assertTrue(regra.startswith("Read(//") and regra.endswith(os.path.join("anexos", "m") + "/**)"), regra)

    def test_so_manda_arquivo_da_pasta_quando_restrito(self):
        from unittest import mock
        from pombo import execucao
        pasta = tempfile.mkdtemp()
        dentro = os.path.join(pasta, "ok.txt")
        fora = os.path.join(tempfile.mkdtemp(), "segredo.txt")
        atalho = os.path.join(pasta, "atalho.txt")
        for a in (dentro, fora):
            open(a, "w").write("x")
        os.symlink(fora, atalho)  # um atalho dentro da pasta apontando para fora também não vale
        resposta = f"Aqui:\nENVIAR_ARQUIVO: {dentro}\nENVIAR_ARQUIVO: {fora}\nENVIAR_ARQUIVO: {atalho}"
        for perm, restrito, esperado in (("lista", False, [dentro]), ("total", True, [dentro]),
                                         ("total", False, [dentro, fora, atalho])):
            cfg = config.validar_bot({"pasta": pasta, "usuarios_permitidos": [7], "permissoes": perm})
            r = execucao.BotRunner("b", cfg, config.carregar_geral(), "t")
            with mock.patch.object(r.canal, "responder", return_value=[]), \
                    mock.patch.object(r.canal, "enviar_arquivo", return_value=1) as env:
                r.enviar_resultado(7, resposta, None, {}, None, restrito=restrito)
            self.assertEqual([c[0][1] for c in env.call_args_list], esperado, (perm, restrito))

    def test_pedido_de_acesso_avisa_o_dono(self):
        from unittest import mock
        from pombo import execucao
        r = execucao.BotRunner("b", config.validar_bot({"pasta": "~", "usuarios_permitidos": [7, 8]}), config.carregar_geral(), "t")
        ze = {"de": 8, "nome_de": "Zé (+5531944443333)", "convidado": True}
        with mock.patch.object(r.canal, "chat_do_dono", return_value=7), mock.patch.object(r.canal, "aviso") as aviso:
            self.assertEqual(r.pedido_de_acesso(ze, "quero acesso completo", "Vou avisar o Pedro.\nSOLICITAR_ACESSO"),
                             "Vou avisar o Pedro.")
            self.assertEqual(aviso.call_args[0][0], 7)
            self.assertIn("Zé (+5531944443333)", aviso.call_args[0][1])
            self.assertIn("quero acesso completo", aviso.call_args[0][1])
            r.pedido_de_acesso(ze, "de novo", "ok\nSOLICITAR_ACESSO")  # a mesma pessoa: um aviso a cada 12 horas
            self.assertEqual(aviso.call_count, 1)
            dono = {"de": 7, "convidado": False}  # do dono, a linha some e nada é avisado
            self.assertEqual(r.pedido_de_acesso(dono, "x", "oi\nSOLICITAR_ACESSO"), "oi")
            self.assertEqual(aviso.call_count, 1)
            self.assertEqual(r.pedido_de_acesso(ze, "x", "sem pedido"), "sem pedido")

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

    def test_comando_atualizar(self):
        from unittest import mock
        from pombo import execucao
        r = execucao.BotRunner("b", config.validar_bot({"pasta": "~", "usuarios_permitidos": [7, 8]}), config.carregar_geral(), "t")
        feito = mock.Mock(stdout="Atualizado: a → b.", stderr="", returncode=0)
        with mock.patch.object(r.canal, "responder") as resp, mock.patch.object(execucao.subprocess, "run", return_value=feito) as run:
            self.assertTrue(r.comando("/atualizar", 8, 1))  # liberado, mas não é o dono
            run.assert_not_called()
            self.assertIn("Só o dono", resp.call_args[0][1])
            r.comando("/atualizar@meu_bot", 7, 2)
        self.assertEqual(run.call_args[0][0][2:], ["atualizar", "--bot", "b"])
        self.assertIn("Atualizado: a → b.", resp.call_args[0][1])

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
        bot = mock.Mock(id="b", dono=lambda: 7)
        novo.runners = {"b": bot}
        novo.conferir_atualizacao()
        responder = bot.canal.responder
        self.assertEqual(responder.call_args[0][0], 7)
        self.assertIn("b2", responder.call_args[0][1])
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


class ConfigWhatsApp(unittest.TestCase):
    def test_padrao_e_numeros(self):
        cfg = config.validar_bot({"canal": "whatsapp", "usuarios_permitidos": ["+55 (31) 99999-0000"]})
        self.assertEqual(cfg["usuarios_permitidos"], ["5531999990000"])
        self.assertEqual(cfg["whatsapp"]["conversas"], ["eu"])
        self.assertEqual(cfg["whatsapp"]["gatilho"], "pombo")
        self.assertEqual(config.validar_bot({})["canal"], "telegram")

    def test_validacoes(self):
        ruins = [
            {"canal": "sms"},
            {"canal": "whatsapp", "usuarios_permitidos": ["123"]},
            {"canal": "whatsapp", "whatsapp": {"nada": 1}},
            {"canal": "whatsapp", "whatsapp": {"prefixo": "  "}},  # no seu número, o prefixo é o que evita responder a si mesmo
            {"canal": "whatsapp", "whatsapp": {"gatilho": "", "gatilho_sempre": False, "conversas": ["eu", "privadas"]}},
            {"canal": "whatsapp", "whatsapp": {"meu_numero": False, "conversas": ["eu"]}},
            {"canal": "whatsapp", "whatsapp": {"conversas": ["grupo-sem-arroba@x"]}},
            {"canal": "whatsapp", "whatsapp": {"gatilho": "dois termos"}},
            {"canal": "whatsapp", "whatsapp": {"espaco_entre_envios": "rápido"}},
        ]
        for c in ruins:
            with self.assertRaises(config.ErroConfig, msg=c):
                config.validar_bot(c)
        cfg = config.validar_bot({"canal": "whatsapp", "whatsapp": {"conversas": "eu, +55 31 98888-7777, 120363@g.us",
                                                                     "gatilho": "@Pombo"}})
        self.assertEqual(cfg["whatsapp"]["conversas"], ["eu", "5531988887777", "120363@g.us"])
        self.assertEqual(cfg["whatsapp"]["gatilho"], "Pombo")
        sep = config.validar_bot({"canal": "whatsapp", "whatsapp": {"meu_numero": False, "conversas": ["privadas"],
                                                                     "gatilho_sempre": False, "gatilho": "", "prefixo": ""}})
        self.assertFalse(sep["whatsapp"]["meu_numero"])

    def test_sem_token_e_credencial(self):
        from pombo.servico import Servico
        cfg = config.validar_bot({"canal": "whatsapp"})
        self.assertEqual(config.token_do_bot("x", cfg), "")
        self.assertTrue(Servico()._token("x", cfg).startswith("wacli:"))


class FuncoesWhatsApp(unittest.TestCase):
    def test_gatilho(self):
        from pombo.whatsapp import tirar_gatilho
        self.assertEqual(tirar_gatilho("Pombo, marca isso", "pombo"), (True, "marca isso"))
        self.assertEqual(tirar_gatilho("  @pombo: oi", "pombo"), (True, "oi"))
        self.assertEqual(tirar_gatilho("POMBO — /novo", "pombo"), (True, "/novo"))
        self.assertEqual(tirar_gatilho("pombos são aves", "pombo"), (False, "pombos são aves"))
        self.assertEqual(tirar_gatilho("oi pombo", "pombo"), (False, "oi pombo"))

    def test_formatacao(self):
        from pombo.whatsapp import para_whatsapp
        t = para_whatsapp("## Título\n**negrito**, *itálico*, ~~riscado~~ e `a *b* c`\n[site](https://a.com) [https://b.com](https://b.com)")
        self.assertEqual(t, "*Título*\n*negrito*, _itálico_, ~riscado~ e `a *b* c`\nsite (https://a.com) https://b.com")

    def test_numero_tipo_e_data(self):
        from pombo.whatsapp import numero, quando, tipo_de_conversa
        self.assertEqual(numero("5531999990000:12@s.whatsapp.net"), "5531999990000")
        self.assertEqual(tipo_de_conversa("120363@g.us"), "grupo")
        self.assertEqual(tipo_de_conversa("123@lid"), "privada")
        self.assertIsNone(tipo_de_conversa("status@broadcast"))
        self.assertIsNone(tipo_de_conversa("123@newsletter"))
        self.assertEqual(quando({"Timestamp": "2026-07-25T10:00:00Z"}), quando({"Timestamp": "2026-07-25T07:00:00-03:00"}))
        self.assertAlmostEqual(quando({"Timestamp": "2026-07-25T10:00:00.123456789Z"}) % 1, 0.123456789, places=5)


class CanalWhatsApp(unittest.TestCase):
    """O canal de verdade conversando com o tests/wacli_falso.py (sem rede e sem Claude)."""

    def montar(self, transcricao=True, **wa):
        from pombo import execucao
        from tests import wacli_falso
        self.f = wacli_falso
        self.store = tempfile.mkdtemp(prefix="wacli-falso-")
        self.eu = wacli_falso.preparar(self.store)
        script = os.path.join(RAIZ, "tests", "wacli_falso.py")
        usuarios = wa.pop("usuarios", [])
        cfg = config.validar_bot({"canal": "whatsapp", "pasta": self.store, "usuarios_permitidos": usuarios,
                                  "transcricao_cmd": ["echo", "{arquivo}"] if transcricao else [],
                                  "whatsapp": {"wacli": script, "pasta_dados": self.store, **wa}})
        bot_id = "wa" + str(abs(hash(self.store)) % 10000)
        self.r = execucao.BotRunner(bot_id, cfg, config.carregar_geral(), "")
        self.recebidas = []
        self.r.chegou = self.recebidas.append
        self.c = self.r.canal
        self.assertTrue(self.c.conhecer_numero())
        self.desde = __import__("time").time() - 5
        return self.c

    def chegar(self, chat, texto="", **kw):
        mid = self.f.chegar(self.store, chat, texto, **kw)
        n = len(self.recebidas)
        self.c.examinar(chat, mid, self.desde)
        return self.recebidas[-1] if len(self.recebidas) > n else None

    def test_conversa_comigo_mesmo(self):
        c = self.montar()
        self.assertEqual(c.chat_do_dono(), self.eu)
        self.assertTrue(c.eh_dono("eu"))
        m = self.chegar(self.eu, "Pombo, o que tem hoje?")
        self.assertEqual((m["texto"], m["de"], m["chat"]), ("o que tem hoje?", "eu", self.eu))
        self.assertIsNone(self.chegar(self.eu, "lembrete: comprar pão"))  # anotação, sem gatilho
        self.assertEqual(self.chegar(self.eu, "/novo")["texto"], "/novo")  # comando dispensa o gatilho
        self.assertIsNone(self.chegar(self.eu, "pombo, de ontem", idade_s=3 * 86400))  # velha demais
        self.assertIsNone(self.chegar(self.eu, "/Users/ana/notas.md"))  # parece comando, mas não é
        self.assertIsNone(self.chegar(self.eu, "pombo, apaga tudo", encaminhada=True))  # conteúdo de outra pessoa
        # a resposta sai com o prefixo, formatada, citando a mensagem e com --allow-self (é a conversa "eu")
        ids = c.responder(self.eu, "**Pronto**, Pombo atualizado", responder_a=m["id"])
        e = self.f.enviadas(self.store)[-1]
        self.assertEqual((e["text"], e["reply-to"], e["allow-self"]), ("🐦 *Pronto*, Pombo atualizado", m["id"], True))
        # o diário mostra a resposta do próprio Pombo: não pode virar pedido (mesmo começando com "Pombo")
        n = len(self.recebidas)
        c.examinar(self.eu, ids[0], self.desde)
        self.assertEqual(len(self.recebidas), n)
        self.assertIsNone(self.chegar(self.eu, "🐦 pombo, resposta antiga sem id anotado"))

    def test_sem_gatilho_na_conversa_eu(self):
        self.montar(gatilho_sempre=False)
        self.assertEqual(self.chegar(self.eu, "qualquer coisa")["texto"], "qualquer coisa")

    def test_conversas_dos_outros_no_meu_numero(self):
        self.montar(conversas=["eu", "privadas", "120363@g.us"], usuarios=["5531911112222"])
        ana = "5531911112222@s.whatsapp.net"
        self.assertIsNone(self.chegar(ana, "marca isso", de_mim=True))  # sem gatilho
        m = self.chegar(ana, "pombo, faz algo", de_mim=False, nome="Ana")
        self.assertEqual((m["de"], m["nome_de"], m["texto"]), ("5531911112222", "Ana", "faz algo"))  # liberada, com gatilho
        self.assertIsNone(self.chegar("5531933334444@s.whatsapp.net", "pombo, me ajuda", de_mim=False))  # não liberado
        self.f.chegar(self.store, "120363@g.us", "a reunião é 15h", de_mim=False, remetente="5531955556666@s.whatsapp.net", nome="Beto")
        m = self.chegar("120363@g.us", "pombo, põe na agenda")
        self.assertIn("Beto: a reunião é 15h", m["contexto"])
        self.assertIn("nunca ordem", m["contexto"])
        self.assertIsNone(self.chegar("120399@g.us", "pombo, oi"))  # grupo não liberado
        # responder à mensagem do bot dispensa o gatilho
        bot = self.c.responder("120363@g.us", "Marquei.")[0]
        self.assertEqual(self.chegar("120363@g.us", "muda pra 16h", citada=bot)["texto"], "muda pra 16h")
        # comando no grupo não vale como comando (mostraria o que o dono está fazendo)
        self.assertFalse(self.chegar("120363@g.us", "pombo /status")["pode_comando"])
        self.assertIsNone(self.chegar("120363@g.us", "/status"))
        self.assertTrue(self.chegar(self.eu, "/status")["pode_comando"])

    def test_numero_do_bot(self):
        self.montar(meu_numero=False, conversas=["privadas"], gatilho_sempre=False, usuarios=["5531911112222"])
        ana = "5531911112222@s.whatsapp.net"
        self.assertEqual(self.c.chat_do_dono(), ana)
        self.assertTrue(self.c.eh_dono("5531911112222"))
        m = self.chegar(ana, "oi", de_mim=False)
        self.assertEqual(m["de"], "5531911112222")
        self.c.andamento(ana, m["id"]).fim()  # reação em mensagem de outra pessoa leva o --sender
        self.c.responder(ana, "oi!", responder_a=m["id"])
        self.assertEqual({x["sender"] for x in self.f.reacoes(self.store)}, {ana})
        self.assertIsNone(self.chegar(ana, "resposta do bot", de_mim=True))
        self.assertIsNone(self.chegar("5531977778888@s.whatsapp.net", "oi", de_mim=False, nome="Estranho"))
        desc = self.r.estado.ler()["desconhecidos"][-1]
        self.assertEqual((desc["id"], desc["nome"]), ("5531977778888", "Estranho"))

    def test_audio_e_reacao(self):
        self.montar(reacoes="etapas")
        m = self.chegar(self.eu, midia="audio")  # áudio sem legenda: o gatilho pode estar falado
        self.assertTrue(m["exigir_gatilho"])
        self.assertEqual(m["audio"], (self.eu, m["id"]))
        self.assertTrue(self.c.baixar(m["audio"], os.path.join(self.store, "anexos")).endswith(".ogg"))
        from unittest import mock
        with mock.patch("pombo.whatsapp.Reacao.INTERVALO", 0):
            andamento = self.c.andamento(self.eu, m["id"])
            for etapa in ("🎧 Ouvindo seu áudio…", "🧠 Pensando…", "📖 Lendo notas.md…", "⚙️ git status", "💭 Achei"):
                andamento.mostrar(etapa)
                __import__("time").sleep(0.4)
            andamento.fim()
            emojis = [x["emoji"] for x in self.f.reacoes(self.store)]
            self.assertNotIn("✅", emojis)  # o ✅ espera a resposta sair
            self.c.responder(self.eu, "pronto", responder_a=m["id"])
        emojis = [x["emoji"] for x in self.f.reacoes(self.store)]
        self.assertEqual((emojis[0], emojis[-1]), ("👀", "✅"))
        self.assertTrue({"🎧", "🧠", "🛠️"} <= set(emojis), emojis)
        # sem pausa de teste: as trocas rápidas viram uma só (no máximo uma a cada 3 s)
        r2 = self.c.andamento(self.eu, m["id"])
        for etapa in ("🧠 Pensando…", "📖 Lendo", "🧠 x", "⚙️ y"):
            r2.mostrar(etapa)
        r2.fim()
        self.c.responder(self.eu, "pronto de novo", responder_a=m["id"])
        self.assertLessEqual(len(self.f.reacoes(self.store)) - len(emojis), 3)
        n = len(self.recebidas)
        for x in self.f.reacoes(self.store):  # as reações aparecem no diário e são ignoradas
            self.c.examinar(self.eu, x["id"], self.desde)
        self.assertEqual(len(self.recebidas), n)

    def test_audio_sem_transcricao_e_ignorado(self):
        self.montar(transcricao=False)
        self.assertIsNone(self.chegar(self.eu, midia="audio"))
        self.assertIsNotNone(self.chegar(self.eu, midia="audio", legenda="pombo, ouve isso"))

    def test_midia_mandada_pelo_bot_nao_vira_pedido(self):
        from unittest import mock
        self.montar(gatilho_sempre=False)
        arq = os.path.join(self.store, "resposta.ogg")
        open(arq, "wb").close()
        original = self.c.wa.enviar_arquivo

        def enviar_e_o_diario_mostra_antes(chat, caminho):
            mid = original(chat, caminho)
            self.c.examinar(chat, mid, self.desde)  # o diário mostra o áudio antes de o id voltar
            return mid
        with mock.patch.object(self.c.wa, "enviar_arquivo", side_effect=enviar_e_o_diario_mostra_antes):
            self.c.enviar_arquivo(self.eu, arq)
        self.assertEqual(self.recebidas, [])
        self.assertIsNotNone(self.chegar(self.eu, midia="audio"))  # um áudio seu, depois, vale

    def test_aviso_calado_para_audio_nao_conferido(self):
        from unittest import mock
        self.montar()
        del self.r.chegou  # usa o chegou de verdade
        self.r.ocupado = True
        with mock.patch.object(self.r.canal, "aviso") as aviso:
            self.r.chegou({"chat": self.eu, "id": "X", "de": "eu", "texto": "", "audio": (self.eu, "X"), "exigir_gatilho": True})
            aviso.assert_not_called()
            self.r.chegou({"chat": self.eu, "id": "Y", "de": "eu", "texto": "oi"})
            aviso.assert_called_once()

    def test_erro_do_wacli_vem_legivel(self):
        from pombo.whatsapp import ErroWhatsApp
        self.montar()
        with self.assertRaises(ErroWhatsApp) as e:
            self.c.wa.mensagem(self.eu, "NAO-EXISTE")
        self.assertEqual(str(e.exception), "sql: no rows in result set")

    def test_audio_longo_transcreve_so_o_comeco(self):
        from unittest import mock
        from pombo import execucao
        self.montar()
        m = self.chegar(self.eu, midia="audio")
        trecho = os.path.join(self.store, "trecho.wav")
        open(trecho, "wb").close()
        with mock.patch.object(execucao, "duracao_audio", return_value=300.0), \
                mock.patch.object(execucao, "trecho_audio", return_value=trecho) as cortar, \
                mock.patch.object(self.r, "transcrever", return_value=("Oi, lembra de comprar pão", None)) as tr, \
                mock.patch.object(self.r, "rodar_agente") as agente:
            self.r.processar_mensagem(m)
        cortar.assert_called_once()
        self.assertEqual([c[0][0] for c in tr.call_args_list], [trecho])  # só o começo; o áudio inteiro não
        agente.assert_not_called()
        self.assertFalse(os.path.exists(trecho))  # o trecho é apagado
        respostas = iter([("Pombo, me lembra", None), ("Pombo, me lembra de ligar pro Geraldo amanhã às 10h", None)])
        with mock.patch.object(execucao, "duracao_audio", return_value=300.0), \
                mock.patch.object(execucao, "trecho_audio", side_effect=lambda c, s: open(trecho, "wb").close() or trecho), \
                mock.patch.object(self.r, "transcrever", side_effect=lambda c: next(respostas)) , \
                mock.patch.object(self.r, "rodar_agente", return_value=("Anotado.", "s1", None, {})) as agente:
            self.r.processar_mensagem(m)
        self.assertIn("me lembra de ligar pro Geraldo amanhã às 10h", agente.call_args[0][0])
        # áudio curto (ou sem ffmpeg): uma transcrição só, do áudio inteiro
        with mock.patch.object(execucao, "duracao_audio", return_value=4.0), \
                mock.patch.object(execucao, "trecho_audio") as cortar, \
                mock.patch.object(self.r, "transcrever", return_value=("Pombo, oi", None)) as tr, \
                mock.patch.object(self.r, "rodar_agente", return_value=("Oi!", "s1", None, {})):
            self.r.processar_mensagem(m)
        cortar.assert_not_called()
        self.assertEqual(tr.call_count, 1)

    def test_processar_audio_sem_gatilho_fica_quieto(self):
        from unittest import mock
        self.montar()
        m = self.chegar(self.eu, midia="audio")
        with mock.patch.object(self.r, "transcrever", return_value=("comprar pão amanhã", None)), \
                mock.patch.object(self.r, "rodar_agente") as agente:
            self.r.processar_mensagem(m)
        agente.assert_not_called()
        self.assertEqual(self.f.enviadas(self.store), [])
        with mock.patch.object(self.r, "transcrever", return_value=("Pombo, que horas são?", None)), \
                mock.patch.object(self.r, "rodar_agente", return_value=("São 10h.", "s1", None, {})) as agente:
            self.r.processar_mensagem(m)
        self.assertIn("(Mensagem de áudio, transcrita) que horas são?", agente.call_args[0][0])
        self.assertEqual(self.f.enviadas(self.store)[-1]["text"], "🐦 São 10h.")

    def test_grupo_so_meu_e_uma_pasta(self):
        from unittest import mock
        self.montar(conversas=["eu"])
        g = self.f.grupo(self.store, "🎓 Mestrado")
        cfg = self.r.cfg
        cfg["whatsapp"]["conversas"] = ["eu", g]
        # grupo só seu: escreve direto, sem gatilho; comando vale; nada de contexto dos outros
        m = self.chegar(g, "qual o prazo da ICEIS?")
        self.assertEqual((m["texto"], m["de"], m["pode_comando"]), ("qual o prazo da ICEIS?", "eu", True))
        self.assertNotIn("contexto", m)
        self.assertTrue(self.chegar(g, "/status")["pode_comando"])
        e = self.c.responder(g, "21/12.")
        self.assertFalse(self.f.enviadas(self.store)[-1]["allow-self"])  # grupo não é "mandar para si mesmo"
        n = len(self.recebidas)
        self.c.examinar(g, e[0], self.desde)  # a resposta do bot no grupo não vira pedido
        self.assertEqual(len(self.recebidas), n)
        # entrou mais alguém: volta a ser grupo comum, com gatilho
        self.f.entrar_no_grupo(self.store, g, "5531955556666")
        with mock.patch("pombo.whatsapp.CACHE_GRUPO_S", 0):
            self.assertIsNone(self.chegar(g, "e agora?"))
            self.assertEqual(self.chegar(g, "pombo, e agora?")["texto"], "e agora?")
        # grupo com outras pessoas desde o começo: só com gatilho
        g2 = self.f.grupo(self.store, "Família", outros=["5531911112222"])
        cfg["whatsapp"]["conversas"] = ["eu", g2]
        self.assertIsNone(self.chegar(g2, "oi"))


    def test_conversa_eu_pelo_lid(self):
        from unittest import mock
        self.montar()
        with mock.patch.object(self.c.wa, "_rodar", return_value={"id": "BOTX", "to": "55556666777788@lid", "sent": True}):
            self.c.responder(self.eu, "oi")
        self.assertTrue(self.c.eh_eu("55556666777788@lid"))
        self.assertEqual(self.c.conversa_liberada("55556666777788@lid"), "eu")

    def test_banco_ocupado_tenta_de_novo(self):
        from unittest import mock
        from pombo.whatsapp import ErroWhatsApp
        self.montar()
        respostas = [ErroWhatsApp("store is locked (another wacli is running?)"), {"id": "B1", "to": self.eu}]

        def falso(*a, **k):
            r = respostas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(self.c.wa, "_rodar", side_effect=falso), mock.patch("pombo.whatsapp.time.sleep"):
            self.assertEqual(self.c.wa.enviar_texto(self.eu, "oi", a_si=True), "B1")


    def test_reacoes_simples_e_nenhuma(self):
        from unittest import mock
        from pombo.whatsapp import SemReacao
        self.montar()  # padrão: só 👀 e ✅
        m = self.chegar(self.eu, "pombo, oi")
        with mock.patch("pombo.whatsapp.Reacao.INTERVALO", 0):
            r = self.c.andamento(self.eu, m["id"])
            for etapa in ("🧠 Pensando…", "📖 Lendo", "⚙️ git"):
                r.mostrar(etapa)
            r.fim()
            self.c.responder(self.eu, "oi!", responder_a=m["id"])
        self.assertEqual([x["emoji"] for x in self.f.reacoes(self.store)], ["👀", "✅"])
        self.r.cfg["whatsapp"]["reacoes"] = "nenhuma"
        self.assertIsInstance(self.c.andamento(self.eu, m["id"]), SemReacao)
        with self.assertRaises(config.ErroConfig):
            config.validar_bot({"canal": "whatsapp", "whatsapp": {"reacoes": "muitas"}})

    def test_reacao_no_grupo_leva_o_remetente(self):
        self.montar()
        g = self.f.grupo(self.store, "🎓 Mestrado")
        self.r.cfg["whatsapp"]["conversas"] = ["eu", g]
        m = self.chegar(g, "oi")
        r = self.c.andamento(g, m["id"])
        r.fim()
        self.c.responder(g, "oi!", responder_a=m["id"])
        self.assertEqual({x["sender"] for x in self.f.reacoes(self.store)}, {self.eu})  # sem isso o wacli recusa


class VariosBotsNoMesmoWhatsApp(unittest.TestCase):
    def setUp(self):
        from tests import wacli_falso
        self.f = wacli_falso
        self.store = tempfile.mkdtemp(prefix="wacli-falso-")
        self.f.preparar(self.store)
        self.script = os.path.join(RAIZ, "tests", "wacli_falso.py")
        for b in config.listar_ids():
            config.remover_bot(b)

    def bot(self, bot_id, **wa):
        return config.salvar_bot(bot_id, {"canal": "whatsapp", "pasta": self.store,
                                          "whatsapp": {"wacli": self.script, "pasta_dados": self.store, **wa}})

    def test_cada_conversa_com_um_bot(self):
        self.bot("pessoal-zap")
        with self.assertRaises(config.ErroConfig) as e:
            self.bot("mestrado-zap")  # também quer a conversa "eu"
        self.assertIn("pombo whatsapp grupo criar", str(e.exception))
        self.bot("mestrado-zap", conversas=["120363000001@g.us"])
        # outro WhatsApp (outro número, noutra pasta do wacli) pode usar a conversa "eu" dele
        self.bot("trabalho-zap", pasta_dados=tempfile.mkdtemp(prefix="outro-numero-"))
        # pausado não conta
        cfg = config.carregar_bot("pessoal-zap")
        cfg["ativo"] = False
        config.salvar_bot("pessoal-zap", cfg)
        self.bot("outro-zap")

    def test_um_sync_por_numero(self):
        from pombo import whatsapp
        w = whatsapp.Wacli({"wacli": self.script, "pasta_dados": self.store})
        a = whatsapp.obter_sincronizador(w, "", "bot-a")
        b = whatsapp.obter_sincronizador(whatsapp.Wacli({"wacli": self.script, "pasta_dados": self.store}), "", "bot-b")
        self.assertIs(a, b)
        whatsapp.soltar_sincronizador(a, "bot-a")
        self.assertFalse(a.parar_evento.is_set())  # o bot-b ainda usa
        whatsapp.soltar_sincronizador(a, "bot-b")
        self.assertTrue(a.parar_evento.is_set())
        a.thread.join(10)
        self.assertFalse(a.vivo())
        c = whatsapp.obter_sincronizador(w, "", "bot-a")  # liga outro depois
        self.assertIsNot(c, a)
        whatsapp.soltar_sincronizador(c, "bot-a")

    def test_criar_e_ligar_grupo_pela_linha_de_comando(self):
        import argparse
        import contextlib
        import io
        from pombo import cli
        self.bot("pessoal-zap")
        self.bot("mestrado-zap", conversas=["5531988887777"])
        args = argparse.Namespace(acao="grupo", grupo_acao="criar", bot="mestrado-zap", nome="🎓 Mestrado",
                                  so_o_grupo=True, wacli=None, conta=None, telefone=None)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_whatsapp(args)
        cfg = config.carregar_bot("mestrado-zap")
        (jid,) = cfg["whatsapp"]["conversas"]
        self.assertTrue(jid.endswith("@g.us"))
        self.assertTrue(cfg["ativo"] and config.carregar_bot("pessoal-zap")["ativo"])  # religou quem pausou
        # ligar um grupo que já existe, pelo nome
        g = self.f.grupo(self.store, "🏠 Casa")
        args = argparse.Namespace(acao="grupo", grupo_acao="ligar", bot="pessoal-zap", nome="🏠 casa",
                                  so_o_grupo=False, wacli=None, conta=None, telefone=None)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_whatsapp(args)
        self.assertEqual(config.carregar_bot("pessoal-zap")["whatsapp"]["conversas"], ["eu", g])
        # criar o bot já com o grupo
        args = argparse.Namespace(acao="criar", id="casa-zap", pasta=self.store, nome=None, canal="whatsapp",
                                  numero_separado=False, conta=None, grupo="🏡 Obra", usuario=None, permissoes=None,
                                  pares=[], json=False)
        from unittest import mock
        with mock_wacli(self.script), mock.patch.dict(os.environ, {"WACLI_STORE_DIR": self.store}), \
                contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_bots(args)
        conversas = config.carregar_bot("casa-zap")["whatsapp"]["conversas"]
        self.assertEqual(len(conversas), 1)
        self.assertTrue(conversas[0].endswith("@g.us"))


class Parear(unittest.TestCase):
    def test_pede_pouco_historico_e_pausa_os_bots(self):
        import argparse
        import contextlib
        import io
        from unittest import mock
        from pombo import cli
        from tests import wacli_falso
        store = tempfile.mkdtemp(prefix="wacli-falso-")
        wacli_falso.preparar(store)
        for b in config.listar_ids():
            config.remover_bot(b)
        script = os.path.join(RAIZ, "tests", "wacli_falso.py")
        config.salvar_bot("zap", {"canal": "whatsapp", "pasta": store,
                                  "whatsapp": {"wacli": script, "pasta_dados": store}})
        args = argparse.Namespace(acao="parear", grupo_acao=None, bot="zap", conta=None, wacli=None, nome=None,
                                  so_o_grupo=False, telefone="+55 31 99999-0000", historico=3, por_conversa=50,
                                  de_novo=True)
        chamadas, ativo_durante = [], []

        def chamar(cmd):
            chamadas.append(cmd)
            ativo_durante.append(config.carregar_bot("zap")["ativo"])
            return 0
        with mock.patch("subprocess.call", side_effect=chamar), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(cli, "pareado", return_value=True), self.assertRaises(SystemExit) as saida:
            cli.cmd_whatsapp(args)
        self.assertEqual(saida.exception.code, 0)
        self.assertEqual(chamadas[0][-2:], ["auth", "logout"])  # --de-novo desfaz o pareamento antes
        self.assertEqual(chamadas[1][-7:], ["auth", "--phone", "+55 31 99999-0000", "--history-days", "3",
                                            "--history-max-per-chat", "50"])
        self.assertEqual(ativo_durante, [False, False])  # o sync parado enquanto pareia
        self.assertTrue(config.carregar_bot("zap")["ativo"])  # e religado no fim
        # sessão velha presa: o wacli diz "Authenticated" sem parear; o Pombo limpa e tenta de novo, e confere no fim
        chamadas.clear()
        estados = iter([False, True, True])
        args.de_novo = False
        with mock.patch("subprocess.call", side_effect=chamar), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(cli, "pareado", side_effect=lambda w: next(estados)), \
                self.assertRaises(SystemExit) as saida:
            cli.cmd_whatsapp(args)
        self.assertEqual(saida.exception.code, 0)
        self.assertEqual([c[-1] if c[-2] != "auth" else c[-2] + " " + c[-1] for c in chamadas][1], "auth logout")
        self.assertEqual(len(chamadas), 3)  # auth, logout, auth
        with mock.patch("subprocess.call", return_value=0), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()), mock.patch.object(cli, "pareado", return_value=False), \
                self.assertRaises(SystemExit) as saida:
            cli.cmd_whatsapp(args)
        self.assertEqual(saida.exception.code, 1)  # não diz "Pronto" sem ter pareado
        sem_limite = argparse.Namespace(telefone=None, historico=0, por_conversa=0)
        self.assertEqual(cli.comando_parear(sem_limite), [])


def mock_wacli(script):
    """O `bots criar` procura o wacli no PATH: aqui ele acha o falso."""
    from unittest import mock
    return mock.patch("pombo.whatsapp.achar_wacli", lambda caminho="": caminho or script)


class PastaPadrao(unittest.TestCase):
    """Conversas dos outros ("todas"): o bot da pasta padrão atende o gatilho onde nenhum outro bot foi ligado."""

    def setUp(self):
        from pombo import execucao
        from tests import wacli_falso
        self.f = wacli_falso
        self.store = tempfile.mkdtemp(prefix="wacli-falso-")
        self.eu = self.f.preparar(self.store)
        script = os.path.join(RAIZ, "tests", "wacli_falso.py")
        for b in config.listar_ids():
            config.remover_bot(b)
        self.grupo_mestrado = self.f.grupo(self.store, "🎓 Mestrado")
        wa = {"wacli": script, "pasta_dados": self.store}
        config.salvar_bot("mestrado-zap", {"canal": "whatsapp", "pasta": self.store,
                                           "whatsapp": dict(wa, conversas=[self.grupo_mestrado], prefixo="🎓 ")})
        cfg = config.salvar_bot("zap", {"canal": "whatsapp", "pasta": self.store,
                                        "whatsapp": dict(wa, conversas=["eu", "todas"])})
        self.r = execucao.BotRunner("zap", cfg, config.carregar_geral(), "")
        self.recebidas = []
        self.r.chegou = self.recebidas.append
        self.c = self.r.canal
        self.c.conhecer_numero()
        self.desde = __import__("time").time() - 5

    def chegar(self, chat, texto="", **kw):
        mid = self.f.chegar(self.store, chat, texto, **kw)
        n = len(self.recebidas)
        self.c.examinar(chat, mid, self.desde)
        return self.recebidas[-1] if len(self.recebidas) > n else None

    def test_atende_conversas_dos_outros_com_gatilho(self):
        familia = self.f.grupo(self.store, "Família", outros=["5531911112222"])
        self.f.chegar(self.store, familia, "o almoço é domingo", de_mim=False,
                      remetente="5531911112222@s.whatsapp.net", nome="Mãe")
        self.assertIsNone(self.chegar(familia, "vou sim"))  # sem gatilho: conversa normal
        m = self.chegar(familia, "pombo, põe o almoço na agenda")
        self.assertEqual(m["texto"], "põe o almoço na agenda")
        self.assertFalse(m["pode_comando"])
        self.assertIn("vai aparecer lá", m["contexto"])  # o agente sabe que a resposta é pública
        self.assertIn("Mãe: o almoço é domingo", m["contexto"])
        ana = "5531933334444@s.whatsapp.net"
        self.assertEqual(self.chegar(ana, "pombo, resume isso")["texto"], "resume isso")
        self.assertIsNone(self.chegar(ana, "pombo, faz", de_mim=False))  # só as suas mensagens chamam o bot

    def test_audio_seu_nas_conversas_dos_outros(self):
        self.r.cfg["transcricao_cmd"] = ["echo", "{arquivo}"]
        ana = "5531933334444@s.whatsapp.net"
        self.assertTrue(self.chegar(ana, midia="audio")["exigir_gatilho"])  # o seu: transcreve e confere o "Pombo"
        self.assertIsNone(self.chegar(ana, midia="audio", de_mim=False))  # o dos outros nunca chama o bot
        self.assertFalse(self.chegar(ana, midia="audio", legenda="pombo, transcreve")["exigir_gatilho"])

    def test_conversa_de_outra_pasta_e_dela(self):
        self.assertEqual(self.c.liberacao(self.grupo_mestrado), (None, False))
        self.assertIsNone(self.chegar(self.grupo_mestrado, "pombo, oi"))
        # um grupo só seu que não é de nenhuma pasta: pela pasta padrão, ainda precisa do gatilho
        notas = self.f.grupo(self.store, "Notas")
        self.assertEqual(self.c.liberacao(notas), ("grupo", True))
        self.assertIsNone(self.chegar(notas, "comprar pão"))
        self.assertEqual(self.chegar(notas, "pombo, oi")["texto"], "oi")

    def test_uma_pasta_padrao_por_whatsapp(self):
        with self.assertRaises(config.ErroConfig) as e:
            config.salvar_bot("outro", {"canal": "whatsapp", "pasta": self.store,
                                        "whatsapp": {"wacli": "x", "pasta_dados": self.store, "conversas": ["grupos"]}})
        self.assertIn("pasta padrão", str(e.exception))


class NumeroDoBot(unittest.TestCase):
    """O número próprio do Pombo: entra nos grupos, responde quando marcado e o seu número sai da frente."""

    def setUp(self):
        from pombo import execucao, whatsapp
        from tests import wacli_falso
        self.w, self.f = whatsapp, wacli_falso
        whatsapp._numeros_cache = (0.0, [])
        whatsapp._identidades.clear()
        for b in config.listar_ids():
            config.remover_bot(b)
        script = os.path.join(RAIZ, "tests", "wacli_falso.py")
        # o seu número (sem o 9, como os números antigos ficaram no WhatsApp) e o número do bot
        self.meu = tempfile.mkdtemp(prefix="wacli-meu-")
        self.eu = wacli_falso.preparar(self.meu, "553188887777", lid="55556666777788")
        self.dobot = tempfile.mkdtemp(prefix="wacli-bot-")
        self.bot_jid = wacli_falso.preparar(self.dobot, "5531977776666", lid="11112222333344")
        self.grupo = wacli_falso.grupo(self.meu, "Mestrado", outros=["5531977776666"])
        wacli_falso.grupo(self.dobot, "Mestrado", outros=["553188887777"], jid=self.grupo)  # o mesmo grupo
        self.familia = wacli_falso.grupo(self.meu, "Família", outros=["5531911112222"])
        self.wa_meu = {"wacli": script, "pasta_dados": self.meu}
        self.wa_bot = {"wacli": script, "pasta_dados": self.dobot}
        cfg_meu = config.salvar_bot("zap", {"canal": "whatsapp", "pasta": self.meu,
                                            "whatsapp": dict(self.wa_meu, conversas=["eu", "todas"])})
        cfg_bot = config.salvar_bot("pombo-zap", {"canal": "whatsapp", "pasta": self.dobot,
                                                  "usuarios_permitidos": ["+55 31 98888-7777"],
                                                  "whatsapp": dict(self.wa_bot, meu_numero=False, conversas=["todas"],
                                                                   gatilho_sempre=False, prefixo="")})
        self.meu_r = execucao.BotRunner("zap", cfg_meu, config.carregar_geral(), "")
        self.bot_r = execucao.BotRunner("pombo-zap", cfg_bot, config.carregar_geral(), "")
        self.recebidas = {"zap": [], "pombo-zap": []}
        for r in (self.meu_r, self.bot_r):
            r.chegou = self.recebidas[r.id].append
            self.assertTrue(r.canal.conhecer_numero())
        self.desde = __import__("time").time() - 5

    def chegar(self, r, store, chat, texto="", **kw):
        mid = self.f.chegar(store, chat, texto, **kw)
        n = len(self.recebidas[r.id])
        r.canal.examinar(chat, mid, self.desde)
        return self.recebidas[r.id][-1] if len(self.recebidas[r.id]) > n else None

    def test_identidade_com_lid(self):
        self.assertEqual((self.bot_r.canal.meu_numero, self.bot_r.canal.meu_lid), ("5531977776666", "11112222333344"))
        numeros = {n["telefone"]: n for n in self.w.numeros_locais()}
        self.assertEqual(numeros["553188887777"]["lid"], "55556666777788")
        self.assertEqual([b["id"] for b in numeros["5531977776666"]["bots"]], ["pombo-zap"])

    def test_variantes_e_mencao(self):
        self.assertEqual(self.w.variantes("5531988887777"), {"5531988887777", "553188887777"})
        self.assertEqual(self.w.variantes("553188887777"), {"5531988887777", "553188887777"})
        self.assertEqual(self.w.tirar_mencao("@5531977776666 qual o prazo?", {"5531977776666"}), (True, "qual o prazo?"))
        self.assertEqual(self.w.tirar_mencao("oi @11112222333344, tudo?", {"11112222333344"}), (True, "oi tudo?"))
        self.assertEqual(self.w.tirar_mencao("fala com @5531900000000", {"5531977776666"}), (False, "fala com @5531900000000"))

    def test_no_grupo_marcando_o_pombo(self):
        dono = "553188887777@s.whatsapp.net"  # chega sem o 9, e o liberado foi escrito com o 9
        m = self.chegar(self.bot_r, self.dobot, self.grupo, "@5531977776666 qual o prazo da ICEIS?", de_mim=False,
                        remetente=dono, nome="Ana")
        self.assertEqual((m["texto"], m["de"]), ("qual o prazo da ICEIS?", "5531988887777"))
        self.assertTrue(self.chegar(self.bot_r, self.dobot, self.grupo, "pombo, e agora?", de_mim=False, remetente=dono))
        self.assertIsNone(self.chegar(self.bot_r, self.dobot, self.grupo, "conversa normal", de_mim=False, remetente=dono))
        # marcado pelo LID, vindo do seu LID (o WhatsApp esconde o número em grupos novos)
        m = self.chegar(self.bot_r, self.dobot, self.grupo, "@11112222333344 oi", de_mim=False,
                        remetente="55556666777788@lid")
        self.assertEqual((m["texto"], m["de"]), ("oi", "5531988887777"))
        self.assertTrue(self.bot_r.canal.eh_dono(m["de"]))
        # outra pessoa marcando o Pombo: nada
        self.assertIsNone(self.chegar(self.bot_r, self.dobot, self.grupo, "@5531977776666 me ajuda", de_mim=False,
                                      remetente="5531955556666@s.whatsapp.net"))
        # conversa direta com o número do bot: tudo, sem marcar; e as rotinas vão para lá (com o JID sem o 9)
        m = self.chegar(self.bot_r, self.dobot, dono, "oi", de_mim=False, nome="Eu")
        self.assertEqual(m["texto"], "oi")
        self.assertIsNone(m["nome_de"])  # o dono é chamado pelo nome do Pombo, não pelo do contato ("Eu")
        self.assertNotIn("contexto", m)  # a conversa direta é só vocês dois
        self.assertEqual(self.bot_r.canal.chat_do_dono(), dono)

    def test_seu_numero_sai_da_frente(self):
        c = self.meu_r.canal
        self.assertEqual(c.liberacao(self.grupo), (None, False))  # o número do Pombo está no grupo: é dele
        self.assertIsNone(self.chegar(self.meu_r, self.meu, self.grupo, "pombo, oi"))
        self.assertEqual(c.liberacao(self.bot_jid), (None, False))  # a conversa direta com o Pombo também
        self.assertEqual(c.liberacao(self.familia), ("grupo", True))  # onde o Pombo não está, continua como antes
        self.assertEqual(self.chegar(self.meu_r, self.meu, self.familia, "pombo, oi")["texto"], "oi")
        self.assertEqual(c.liberacao(self.eu), ("eu", False))

    def test_grupo_ligado_a_bot_de_outro_numero(self):
        outro = self.f.grupo(self.meu, "Obra")  # o Pombo ainda não aparece nos participantes
        cfg = config.carregar_bot("pombo-zap")
        cfg["whatsapp"]["conversas"] = ["todas", outro]
        config.salvar_bot("pombo-zap", cfg)
        self.meu_r.canal._reivindicadas = (0.0, set())
        self.assertEqual(self.meu_r.canal.liberacao(outro), (None, False))
        with self.assertRaises(config.ErroConfig) as e:  # o mesmo grupo em dois bots, mesmo em números diferentes
            config.salvar_bot("obra-meu", {"canal": "whatsapp", "pasta": self.meu,
                                           "whatsapp": dict(self.wa_meu, conversas=[outro])})
        self.assertIn("outro número", str(e.exception))

    def test_parear_pelo_painel(self):
        import time
        from pombo import painel
        script = os.path.join(RAIZ, "tests", "wacli_falso.py")
        novo = tempfile.mkdtemp(prefix="wacli-novo-")
        os.rmdir(novo)
        wa = {"wacli": script, "pasta_dados": novo}
        self.assertFalse(self.w.Wacli(wa).status().get("authenticated"))
        p = self.w.parear(wa, "+55 31 96666-5555")
        fim, vistos = time.time() + 20, set()
        while time.time() < fim and p.estado not in ("pareado", "erro"):
            vistos.add((p.estado, p.codigo))
            time.sleep(0.05)
        self.assertEqual(p.estado, "pareado", p.mensagem)
        self.assertIn(("codigo", "ABCD-EFGH"), vistos)
        self.assertEqual(self.w.Wacli(wa).identidade()["telefone"], "5531966665555")
        # a API do painel: os números (com a chave) e os grupos de um número, pela chave
        self.w.esquecer_caches()
        r = painel.rota(None, "GET", "/api/whatsapp", {}, {})
        do_bot = next(n for n in r["numeros"] if n["telefone"] == "5531977776666")
        g = painel.rota(None, "GET", "/api/whatsapp/grupos", {"chave": do_bot["chave"]}, {})
        self.assertEqual([x["nome"] for x in g["grupos"]], ["Mestrado"])

    def test_painel_nao_roda_programa_da_url(self):
        from pombo import painel
        marca = os.path.join(tempfile.mkdtemp(), "rodou")
        programa = os.path.join(tempfile.mkdtemp(), "x.sh")
        with open(programa, "w") as f:
            f.write(f"#!/bin/sh\ntouch {marca}\n")
        os.chmod(programa, 0o755)
        with self.assertRaises(painel.Erro):  # sem chave conhecida, nada roda
            painel.rota(None, "GET", "/api/whatsapp/grupos", {"wacli": programa, "pasta_dados": "/etc"}, {})
        self.assertFalse(os.path.exists(marca))
        with self.assertRaises(painel.Erro):
            painel.rota(None, "POST", "/api/whatsapp/parear", {}, {"novo": "Nome Ruim", "telefone": "+5531999990000"})

    def test_painel_nao_pareia_o_chip_por_cima_do_seu_numero(self):
        from pombo import painel
        self.w.esquecer_caches()
        meu = next(n for n in painel.rota(None, "GET", "/api/whatsapp", {}, {})["numeros"] if n["telefone"] == "553188887777")
        with self.assertRaises(painel.Erro) as e:
            painel.rota(None, "POST", "/api/whatsapp/parear", {}, {"chave": meu["chave"], "telefone": "+5531966665555",
                                                                   "de_novo": True})
        self.assertIn("número novo", str(e.exception))
        with self.assertRaises(painel.Erro) as e:  # o mesmo telefone, sem marcar "desfazer"
            painel.rota(None, "POST", "/api/whatsapp/parear", {}, {"chave": meu["chave"], "telefone": "+5531988887777"})
        self.assertIn("Desfazer", str(e.exception))

    def test_bots_pausados_voltam_se_o_pareamento_morrer(self):
        self.w.pausar_para(self.wa_bot)
        self.assertFalse(config.carregar_bot("pombo-zap")["ativo"])
        arq = self.w._arq_pausa(self.wa_bot)
        d = config.ler_json(arq, {})
        d["pid"] = 999999  # o processo que pausou morreu
        config.gravar_json(arq, d)
        self.w.restaurar_pausas()
        self.assertTrue(config.carregar_bot("pombo-zap")["ativo"])
        self.assertFalse(os.path.exists(arq))
        # pausa feita à mão durante o pareamento fica
        self.w.pausar_para(self.wa_bot)
        import time
        time.sleep(0.02)
        cfg = config.carregar_bot("pombo-zap")
        cfg["instrucoes"] = "mexi aqui"
        config.gravar_json(config.arq_bot("pombo-zap"), cfg)
        self.w.religar_de(self.wa_bot)
        self.assertFalse(config.carregar_bot("pombo-zap")["ativo"])

    def test_sai_da_frente_so_onde_o_pombo_atende(self):
        # o bot do número do Pombo escuta só o Mestrado; ele também está no grupo Família, mas não atende lá
        familia_bot = self.f.grupo(self.dobot, "Família", outros=["553188887777"], jid=self.familia)
        self.assertTrue(familia_bot)
        cfg = config.carregar_bot("pombo-zap")
        cfg["whatsapp"]["conversas"] = [self.grupo]
        config.salvar_bot("pombo-zap", cfg)
        self.w.esquecer_caches()
        self.meu_r.canal._outros = (0.0, [])
        self.assertEqual(self.meu_r.canal.liberacao(self.familia), ("grupo", True))  # o seu número responde
        self.assertEqual(self.meu_r.canal.liberacao(self.grupo), (None, False))  # no Mestrado, o Pombo
        # sem você liberado no bot do Pombo, ele não te atende: o seu número continua no Mestrado também
        cfg["usuarios_permitidos"] = ["5531911112222"]
        config.salvar_bot("pombo-zap", cfg)
        self.meu_r.canal._outros, self.meu_r.canal._reivindicadas = (0.0, []), (0.0, set())
        self.assertEqual(self.meu_r.canal.liberacao(self.grupo), ("grupo", True))

    def test_pombo_ganha_de_grupo_ligado_no_seu_numero(self):
        config.salvar_bot("mestrado-meu", {"canal": "whatsapp", "pasta": self.meu,
                                           "whatsapp": dict(self.wa_meu, conversas=[self.grupo])})
        self.bot_r.canal._reivindicadas = (0.0, set())
        m = self.chegar(self.bot_r, self.dobot, self.grupo, "@5531977776666 oi", de_mim=False,
                        remetente="553188887777@s.whatsapp.net")
        self.assertEqual(m["texto"], "oi")  # o Pombo atende (antes ficava sem resposta)
        from pombo import execucao
        r = execucao.BotRunner("mestrado-meu", config.carregar_bot("mestrado-meu"), config.carregar_geral(), "")
        r.canal.conhecer_numero()
        self.assertEqual(r.canal.liberacao(self.grupo), (None, False))  # e o bot do seu número sai da frente

    def test_lid_casa_com_lid_e_telefone_com_telefone(self):
        c = self.bot_r.canal
        self.assertEqual(c.liberado("55556666777788@lid"), "5531988887777")  # o seu LID, de um número pareado aqui
        self.assertEqual(c.liberado("553188887777@s.whatsapp.net"), "5531988887777")
        self.assertIsNone(c.liberado("5531988887777@lid"))  # um LID com os dígitos do seu telefone não é você

    def test_grupo_aberto_qualquer_pessoa_marcando(self):
        cfg = config.carregar_bot("pombo-zap")
        cfg["whatsapp"].update({"conversas": [self.grupo], "qualquer_pessoa": True})
        config.salvar_bot("pombo-zap", cfg)
        self.bot_r.cfg = config.carregar_bot("pombo-zap")
        ze = "5531955556666@s.whatsapp.net"
        m = self.chegar(self.bot_r, self.dobot, self.grupo, "@5531977776666 qual o prazo?", de_mim=False,
                        remetente=ze, nome="Zé")
        self.assertEqual((m["texto"], m["de"], m["nome_de"], m["pode_comando"]),
                         ("qual o prazo?", "5531955556666", "Zé (+5531955556666)", False))
        self.assertIn("e não", m["contexto"])  # o agente sabe que não foi o dono quem pediu
        self.assertFalse(self.bot_r.canal.eh_dono(m["de"]))
        self.assertIsNone(self.chegar(self.bot_r, self.dobot, self.grupo, "conversa normal", de_mim=False, remetente=ze))
        self.bot_r.cfg["transcricao_cmd"] = ["echo", "{arquivo}"]
        self.assertIsNone(self.chegar(self.bot_r, self.dobot, self.grupo, midia="audio", de_mim=False, remetente=ze))
        # o dono continua sendo o dono
        m = self.chegar(self.bot_r, self.dobot, self.grupo, "pombo, oi", de_mim=False, remetente="553188887777@s.whatsapp.net")
        self.assertTrue(self.bot_r.canal.eh_dono(m["de"]))
        self.assertIsNone(m["nome_de"])

    def test_conversa_direta_de_outra_pessoa_liberada(self):
        # uma lista de números que podem falar com o número do bot: atendidos sem marcar, mas como convidados
        cfg = config.carregar_bot("pombo-zap")
        cfg["usuarios_permitidos"] = ["+55 31 98888-7777", "5531955556666"]
        config.salvar_bot("pombo-zap", cfg)
        self.bot_r.cfg = config.carregar_bot("pombo-zap")
        bia = "5531955556666@s.whatsapp.net"
        m = self.chegar(self.bot_r, self.dobot, bia, "me explica o que é um CDB", de_mim=False, nome="Bia")
        self.assertEqual((m["texto"], m["nome_de"], m["convidado"]), ("me explica o que é um CDB", "Bia (+5531955556666)", True))
        self.assertIn("e não", m["contexto"])
        self.assertFalse(m["pode_comando"])
        # comandos: só o /novo (o /status e o /parar mostrariam ou parariam o pedido de outra pessoa)
        self.assertFalse(self.chegar(self.bot_r, self.dobot, bia, "/status", de_mim=False)["pode_comando"])
        self.assertFalse(self.chegar(self.bot_r, self.dobot, bia, "/parar", de_mim=False)["pode_comando"])
        self.assertTrue(self.chegar(self.bot_r, self.dobot, bia, "/novo", de_mim=False)["pode_comando"])
        # o dono continua com tudo
        dono = "553188887777@s.whatsapp.net"
        m = self.chegar(self.bot_r, self.dobot, dono, "/status", de_mim=False)
        self.assertTrue(m["pode_comando"])
        self.assertFalse(m["convidado"])
        # quem não está na lista continua sem resposta
        self.assertIsNone(self.chegar(self.bot_r, self.dobot, "5531944443333@s.whatsapp.net", "oi", de_mim=False))

    def test_conversa_pelo_numero_com_e_sem_o_9(self):
        # o número escrito com o 9 casa com a conversa que o WhatsApp guardou sem ele (e a pasta padrão sai da frente)
        config.salvar_bot("convidados", {"canal": "whatsapp", "pasta": self.dobot,
                                         "usuarios_permitidos": ["5531988887777", "5531976543210"],
                                         "whatsapp": dict(self.wa_bot, meu_numero=False, conversas=["5531976543210"],
                                                          prefixo="")})
        from pombo import execucao
        r = execucao.BotRunner("convidados", config.carregar_bot("convidados"), config.carregar_geral(), "")
        r.canal.conhecer_numero()
        self.assertEqual(r.canal.liberacao("553176543210@s.whatsapp.net"), ("privada", False))
        self.bot_r.canal._reivindicadas = (0.0, set())
        self.assertEqual(self.bot_r.canal.liberacao("553176543210@s.whatsapp.net"), (None, False))

    def test_desconhecidos_o_ultimo_da_fila(self):
        # bot aberto para quem não está liberado: você fica no bot com "todas", o convidado no bot dele
        config.salvar_bot("publico", {"canal": "whatsapp", "pasta": self.dobot, "usuarios_permitidos": ["5531988887777"],
                                      "whatsapp": dict(self.wa_bot, meu_numero=False, conversas=["desconhecidos"],
                                                       qualquer_pessoa=True, prefixo="", limite_por_pessoa_dia=2,
                                                       gatilho_sempre=False)})
        config.salvar_bot("convidados", {"canal": "whatsapp", "pasta": self.dobot,
                                         "usuarios_permitidos": ["5531988887777", "5531976543210"],
                                         "whatsapp": dict(self.wa_bot, meu_numero=False, conversas=["5531976543210"],
                                                          prefixo="")})
        from pombo import execucao
        pub = execucao.BotRunner("publico", config.carregar_bot("publico"), config.carregar_geral(), "")
        pub.canal.conhecer_numero()
        self.recebidas["publico"] = []
        pub.chegou = self.recebidas["publico"].append
        ze = "5531944443333@s.whatsapp.net"
        self.assertEqual(pub.canal.liberacao(ze), ("privada", True))
        self.assertEqual(pub.canal.liberacao("553188887777@s.whatsapp.net"), (None, False))  # você: o bot com "todas"
        self.assertEqual(pub.canal.liberacao("553176543210@s.whatsapp.net"), (None, False))  # o convidado: o bot dele
        m = self.chegar(pub, self.dobot, ze, "oi, quem é você?", de_mim=False, nome="Zé")
        self.assertEqual((m["de"], m["nome_de"], m["convidado"], m["pode_comando"]),
                         ("5531944443333", "Zé (+5531944443333)", True, False))
        self.assertIn("não está entre os liberados", m["contexto"])
        self.assertIsNone(self.chegar(self.bot_r, self.dobot, ze, "oi", de_mim=False))  # o bot com "todas" não atende o Zé
        # limite por dia: a 2ª passa, a 3ª ganha o aviso, a 4ª nem isso
        self.assertTrue(self.chegar(pub, self.dobot, ze, "e agora?", de_mim=False))
        self.assertIsNone(self.chegar(pub, self.dobot, ze, "mais uma", de_mim=False))
        self.assertIn("Por hoje deu", self.f.enviadas(self.dobot)[-1]["text"])
        n = len(self.f.enviadas(self.dobot))
        self.assertIsNone(self.chegar(pub, self.dobot, ze, "e mais", de_mim=False))
        self.assertEqual(len(self.f.enviadas(self.dobot)), n)
        # sem nenhum outro bot que te atenda, o bot aberto atende você também (como dono)
        cfg = config.carregar_bot("pombo-zap")
        cfg["ativo"] = False
        config.salvar_bot("pombo-zap", cfg)
        self.assertEqual(pub.canal.liberacao("553188887777@s.whatsapp.net"), ("privada", True))

    def test_desconhecidos_so_com_qualquer_pessoa_no_numero_do_bot(self):
        base = {"canal": "whatsapp", "pasta": self.dobot}
        for wa in ({"meu_numero": False, "conversas": ["desconhecidos"], "prefixo": ""},
                   {"meu_numero": True, "conversas": ["desconhecidos"], "qualquer_pessoa": True}):
            with self.assertRaises(config.ErroConfig, msg=wa):
                config.validar_bot(dict(base, whatsapp=wa))
        wa = dict(self.wa_bot, meu_numero=False, conversas=["desconhecidos"], qualquer_pessoa=True, prefixo="")
        config.salvar_bot("publico", dict(base, whatsapp=wa))
        with self.assertRaises(config.ErroConfig):  # um número, um bot dos desconhecidos
            config.salvar_bot("publico2", dict(base, whatsapp=wa))

    def test_grupo_aberto_so_em_grupo_escolhido_e_no_numero_do_bot(self):
        base = {"canal": "whatsapp", "pasta": self.dobot}
        for wa in ({"meu_numero": True, "conversas": [self.grupo], "qualquer_pessoa": True},
                   {"meu_numero": False, "conversas": ["todas"], "qualquer_pessoa": True, "gatilho_sempre": False, "prefixo": ""},
                   {"meu_numero": False, "conversas": [self.grupo, "privadas"], "qualquer_pessoa": True, "prefixo": ""}):
            with self.assertRaises(config.ErroConfig, msg=wa):
                config.validar_bot(dict(base, whatsapp=wa))


class VariosComputadores(unittest.TestCase):
    """O mesmo número do Pombo pareado em dois computadores: a pasta padrão fica num, e os grupos ligados pelo nome
    a um bot do outro computador são de lá (ninguém responde em dobro). Usa o mesmo cenário do NumeroDoBot."""
    chegar = NumeroDoBot.chegar

    def setUp(self):
        NumeroDoBot.setUp(self)
        self.geral = {**config.carregar_geral(), "nome_maquina": "Ubuntu"}
        for r in (self.meu_r, self.bot_r):
            r.geral = self.geral
        self.obra = self.f.grupo(self.dobot, "Obra", outros=["553188887777"])

    def tearDown(self):
        try:
            os.remove(config.arq_outros_computadores())
        except OSError:
            pass

    def outro(self, bots, telefone="5531977776666", grupos=(), nome="Mac"):
        config.gravar_json(config.arq_outros_computadores(), {"computadores": {"https://mac:10004": {
            "url": "https://mac:10004", "nome_maquina": nome, "numeros": [
                {"telefone": telefone, "lid": "", "grupos": list(grupos), "bots": bots}]}}})
        for r in (self.meu_r, self.bot_r):
            r.canal._reivindicadas, r.canal._outros = (0.0, set()), (0.0, [])

    def bot(self, conversas, id="obra-zap", meu_numero=False, usuarios=("5531988887777",)):
        return {"id": id, "nome": id, "ativo": True, "usuarios_permitidos": list(usuarios),
                "whatsapp": {"meu_numero": meu_numero, "conversas": conversas}}

    def test_conversa_direta_ligada_nos_dois_computadores_responde_um(self):
        config.salvar_bot("convidados", {"canal": "whatsapp", "pasta": self.dobot,
                                         "usuarios_permitidos": ["5531988887777", "5531976543210"],
                                         "whatsapp": dict(self.wa_bot, meu_numero=False, conversas=["5531976543210"],
                                                          prefixo="")})
        from pombo import execucao
        r = execucao.BotRunner("convidados", config.carregar_bot("convidados"), self.geral, "")
        r.canal.conhecer_numero()
        bia = "553176543210@s.whatsapp.net"
        self.assertEqual(r.canal.liberacao(bia), ("privada", False))
        # o mesmo convidado na lista do Mac: responde só o de nome menor ("Mac" < "Ubuntu"), e avisa no log
        self.outro([self.bot(["553176543210"], id="convidados", usuarios=("5531988887777", "553176543210"))])
        self.assertEqual(r.canal.liberacao(bia), (None, False))
        self.assertTrue(any("tire de um dos dois" in a for a in r.canal._avisos_dobrados))
        self.outro([self.bot(["553176543210"], id="convidados")], nome="Zeta")  # agora o daqui é o de nome menor
        self.assertEqual(r.canal.liberacao(bia), ("privada", False))

    def test_grupo_de_um_bot_do_outro_computador_e_dele(self):
        c = self.bot_r.canal
        self.assertEqual(c.liberacao(self.obra), ("grupo", True))  # antes: a pasta padrão daqui atende
        self.outro([self.bot([self.obra])])
        self.assertEqual(c.liberacao(self.obra), (None, False))  # agora é do Mac
        self.assertIsNone(self.chegar(self.bot_r, self.dobot, self.obra, "@5531977776666 oi", de_mim=False,
                                      remetente="553188887777@s.whatsapp.net"))
        self.assertEqual(c.liberacao(self.grupo), ("grupo", True))  # o resto continua aqui
        self.assertEqual(c.liberacao("553188887777@s.whatsapp.net"), ("privada", True))  # e a conversa direta também
        # bot pausado no Mac não pega nada
        b = self.bot([self.obra])
        b["ativo"] = False
        self.outro([b])
        self.assertEqual(c.liberacao(self.obra), ("grupo", True))

    def test_duas_pastas_padrao_so_uma_responde(self):
        self.outro([self.bot(["todas"], id="pombo-zap")], nome="Mac")  # "Mac" < "Ubuntu": o Mac ganha
        self.assertEqual(self.bot_r.canal.liberacao(self.grupo), (None, False))
        self.assertIn("Mac", self.bot_r.canal.aviso_padrao)
        self.outro([self.bot(["todas"], id="pombo-zap")], nome="Windows")  # "Ubuntu" < "Windows": aqui ganha
        self.assertEqual(self.bot_r.canal.liberacao(self.grupo), ("grupo", True))
        # outro número com pasta padrão no outro computador não conta
        self.outro([self.bot(["todas"], id="x")], telefone="5531900001111", nome="Mac")
        self.assertEqual(self.bot_r.canal.liberacao(self.grupo), ("grupo", True))

    def test_seu_numero_sai_da_frente_do_pombo_do_outro_computador(self):
        config.remover_bot("pombo-zap")  # o número do Pombo não tem bot ligado neste computador
        self.w.esquecer_caches()
        c = self.meu_r.canal
        self.outro([])
        self.assertEqual(c.liberacao(self.grupo), ("grupo", True))
        # no outro computador, a pasta padrão do Pombo te atende, e ele está no Mestrado (mas não na Família)
        self.outro([self.bot(["todas"], id="pombo-zap")], grupos=[self.grupo])
        self.assertEqual(c.liberacao(self.grupo), (None, False))
        self.assertEqual(c.liberacao(self.familia), ("grupo", True))
        self.assertEqual(c.liberacao(self.bot_jid), (None, False))  # a conversa direta com o Pombo também é dele

    def test_nao_deixa_ligar_grupo_que_ja_e_de_outro_computador(self):
        self.outro([self.bot([self.obra])])
        cfg = config.carregar_bot("pombo-zap")
        cfg["whatsapp"]["conversas"] = ["todas", self.obra]
        with self.assertRaises(config.ErroConfig) as e:
            config.salvar_bot("pombo-zap", cfg)
        self.assertIn('computador "Mac"', str(e.exception))

    def test_descrever_e_perguntar_ao_outro_computador(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from pombo import painel
        self.w.esquecer_caches()
        eu = painel.rota(None, "GET", "/api/whatsapp/computador", {}, {})
        self.assertEqual(eu["nome_maquina"], config.carregar_geral()["nome_maquina"])
        do_bot = next(n for n in eu["numeros"] if n["telefone"] == "5531977776666")
        self.assertIn(self.grupo, do_bot["grupos"])
        self.assertEqual([b["id"] for b in do_bot["bots"]], ["pombo-zap"])
        self.assertEqual(do_bot["bots"][0]["whatsapp"]["conversas"], ["todas"])
        meu = next(n for n in eu["numeros"] if n["telefone"] == "553188887777")
        self.assertEqual(meu["grupos"], [])  # os grupos do seu número não saem daqui

        resposta = {"nome_maquina": "Mac", "versao": "x", "numeros": [{"telefone": "5531977776666", "bots": []}]}
        cabecalhos = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                cabecalhos.append((self.path, self.headers.get("X-Pombo")))
                dados = json.dumps(resposta).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        g = config.carregar_geral()
        try:
            config.salvar_geral({**g, "outros_computadores": [url + "/"]})
            m = self.w.atualizar_outros_computadores(timeout=3)[url]
            self.assertEqual((m["nome_maquina"], m["erro"]), ("Mac", ""))
            self.assertEqual(cabecalhos, [("/api/whatsapp/computador", "1")])
            srv.shutdown()
            srv.server_close()
            m = self.w.atualizar_outros_computadores(timeout=2)[url]  # desligado: fica a última resposta
            self.assertTrue(m["erro"])
            self.assertEqual(m["nome_maquina"], "Mac")
        finally:
            config.salvar_geral(g)

    def test_endereco_do_outro_computador(self):
        with self.assertRaises(config.ErroConfig):
            config.validar_outros_computadores(["mac.tailnet:10004"])
        with self.assertRaises(config.ErroConfig):
            config.validar_outros_computadores(["https://mac:10004/api"])
        self.assertEqual(config.validar_outros_computadores("https://a:1/ https://a:1"), ["https://a:1"])

