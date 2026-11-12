"""O serviço: liga e desliga os bots conforme a configuração, roda as rotinas na hora e serve o painel.

Mudanças na configuração (painel, linha de comando ou edição à mão) valem em até ~2 s, sem reiniciar.
"""
import datetime as dt
import os
import subprocess
import sys
import threading
import time
import traceback

from . import atualizar, config, registro, rotinas
from .execucao import BotRunner


def log(msg):
    registro.log(None, msg)


class Servico:
    def __init__(self):
        self.runners = {}
        self.parando = []
        self.geral = config.carregar_geral()
        self.erros_config = {}
        self._tokens = {}
        self._trava = threading.RLock()
        self.inicio = time.time()
        self._ocioso_antes = False

    # ---------------------------------------------------------------- bots

    def _token(self, bot_id, cfg):
        """O token só é lido de novo quando o arquivo do bot ou o segredos.json mudam (o Keychain é lento)."""
        chave = tuple(_mtime(p) for p in (config.arq_bot(bot_id), config.caminho("segredos.json")))
        guardado = self._tokens.get(bot_id)
        if guardado and guardado[0] == chave:
            return guardado[1]
        token = config.token_do_bot(bot_id, cfg)
        self._tokens[bot_id] = (chave, token)
        return token

    def reconciliar(self):
        with self._trava:
            self.geral = config.carregar_geral()
            ids = config.listar_ids()
            for bot_id in ids:
                try:
                    cfg = config.carregar_bot(bot_id)
                    cfg = config.validar_bot(cfg)
                    self.erros_config.pop(bot_id, None)
                except config.ErroConfig as e:
                    if self.erros_config.get(bot_id) != str(e):
                        log(f'configuração inválida do bot "{bot_id}": {e}')
                    self.erros_config[bot_id] = str(e)
                    continue
                token = self._token(bot_id, cfg) if cfg["ativo"] else ""
                r = self.runners.get(bot_id)
                if r and (not cfg["ativo"] or not token or r.token != token or r.geral.get("telegram_api") != self.geral.get("telegram_api")):
                    self._parar(bot_id)
                    r = None
                if r:
                    r.atualizar(cfg, self.geral)
                elif cfg["ativo"] and token and not any(p.id == bot_id and p.vivo() for p in self.parando):
                    novo = BotRunner(bot_id, cfg, self.geral, token)
                    self.runners[bot_id] = novo
                    novo.iniciar()
                    log(f'bot "{bot_id}" ligado')
            for bot_id in list(self.runners):
                if bot_id not in ids:
                    self._parar(bot_id)
            self.parando = [p for p in self.parando if p.vivo()]

    def _parar(self, bot_id):
        r = self.runners.pop(bot_id, None)
        if r:
            r.parar()
            self.parando.append(r)
            log(f'bot "{bot_id}" desligado')

    def rodar_rotina(self, bot_id, rotina_id):
        with self._trava:
            r = self.runners.get(bot_id)
        if not r:
            raise config.ErroConfig(f'o bot "{bot_id}" não está ligado agora (pausado, sem token ou com erro)')
        if not any(x["id"] == rotina_id for x in r.cfg["rotinas"]):
            raise config.ErroConfig(f'o bot "{bot_id}" não tem a rotina "{rotina_id}"')
        r.fila.put(("rotina", rotina_id, True))

    def mandar_teste(self, bot_id):
        with self._trava:
            r = self.runners.get(bot_id)
        if not r:
            raise config.ErroConfig(f'o bot "{bot_id}" não está ligado agora')
        dono = r.dono()
        if not dono:
            raise config.ErroConfig("libere pelo menos um usuário antes de mandar a mensagem de teste")
        from .telegram import responder
        responder(r.tg, dono, f"✅ Teste do painel: o bot **{r.cfg['nome']}** está ligado em {self.geral['nome_maquina']}.", log=r.log)

    def estado_bot(self, bot_id):
        with self._trava:
            r = self.runners.get(bot_id)
            erro_cfg = self.erros_config.get(bot_id)
        if erro_cfg:
            return {"situacao": "erro", "detalhe": "configuração inválida: " + erro_cfg}
        if r:
            situacao = "erro" if r.erro else ("ocupado" if r.ocupado else "ligado")
            return {"situacao": situacao, "detalhe": r.erro or r.atual, "username": r.username,
                    "fila": r.fila.qsize(), "desde": r.desde}
        try:
            cfg = config.carregar_bot(bot_id)
        except config.ErroConfig as e:
            return {"situacao": "erro", "detalhe": str(e)}
        if not cfg["ativo"]:
            return {"situacao": "pausado", "detalhe": ""}
        if not self._token(bot_id, cfg):
            return {"situacao": "sem_token", "detalhe": "falta o token do BotFather"}
        return {"situacao": "ligando", "detalhe": ""}

    # ---------------------------------------------------------------- rotinas

    def agendar(self):
        agora = dt.datetime.now()
        with self._trava:
            ativos = list(self.runners.items())
        for bot_id, r in ativos:
            if r.erro and "token" in r.erro:
                continue
            marcas = (r.estado.ler().get("rotinas") or {})
            for rot in r.cfg["rotinas"]:
                ultima = (marcas.get(rot["id"]) or {}).get("marca")
                acao, marca = rotinas.decidir(rot, agora, ultima)
                if not acao:
                    continue
                r.estado.atualizar(lambda d, rid=rot["id"], m=marca: d.setdefault("rotinas", {}).setdefault(rid, {}).__setitem__("marca", m))
                if acao == "rodar":
                    r.fila.put(("rotina", rot["id"], False))
                    r.log(f'rotina "{rot["nome"]}" agendada para agora ({marca})')
                elif acao == "perdida":
                    r.log(f'rotina "{rot["nome"]}" das {marca} não rodou: o serviço estava parado ou o computador dormindo '
                          f'(passou da tolerância de {rot["tolerancia_min"]} min)')

    def _laco_agenda(self):
        while True:
            try:
                self.agendar()
            except Exception:
                log("erro no agendador:\n" + traceback.format_exc())
            time.sleep(20)

    # ---------------------------------------------------------------- atualização (pombo atualizar)

    def ocioso(self):
        with self._trava:
            return all(not r.ocupado and r.fila.empty() for r in self.runners.values())

    def conferir_atualizacao(self):
        """Roda na thread principal, a cada ~2 s. Veja atualizar.py."""
        agora = self.ocioso()
        # duas conferências seguidas: um pedido que acabou de sair da fila ainda pode não estar marcado como ocupado
        ocioso, self._ocioso_antes = agora and self._ocioso_antes, agora
        marcador = atualizar.ler()
        acao = atualizar.decidir(marcador, self.inicio, ocioso)
        if acao == "reiniciar":
            log(f"atualização: reiniciando o serviço para carregar {marcador.get('depois')}")
            atualizar.reiniciar_processo()
        elif acao == "avisar":
            if self._avisar_atualizacao(marcador) or time.time() - self.inicio > 600:
                atualizar.apagar()

    def _avisar_atualizacao(self, marcador):
        """Manda o ✅ para o dono do bot que pediu (ou, sem pedido de bot, de quem for o dono do computador)."""
        with self._trava:
            runners = dict(self.runners)
        r = runners.get(marcador.get("bot") or "")
        if not r or not r.dono():
            meu = self.geral.get("meu_id_telegram")
            candidatos = [x for x in runners.values() if x.dono()]
            r = next((x for x in candidatos if x.dono() == meu), candidatos[0] if candidatos else None)
        if not r:
            log(f"atualização aplicada ({marcador.get('depois')}); nenhum bot ligado para avisar")
            return True
        from .telegram import responder
        try:
            responder(r.tg, r.dono(), atualizar.mensagem(marcador, self.geral["nome_maquina"]), log=r.log)
        except Exception as e:
            log(f"atualização aplicada, mas o aviso no Telegram falhou (tento de novo): {e}")
            return False
        log(f"atualização aplicada ({marcador.get('depois')}); aviso mandado pelo bot \"{r.id}\"")
        return True

    # ---------------------------------------------------------------- principal

    def rodar(self):
        config.garantir_pastas()
        trava_instancia()
        log(f"serviço ligado em \"{self.geral['nome_maquina']}\" (configuração em {config.base()})")
        from . import painel
        try:
            painel.iniciar(self)
        except OSError as e:
            log(f"o painel não abriu na porta {self.geral['painel_porta']}: {e}")
        threading.Thread(target=self._laco_agenda, name="agenda", daemon=True).start()
        while True:
            try:
                self.reconciliar()
            except Exception:
                log("erro ao conferir a configuração:\n" + traceback.format_exc())
            try:
                self.conferir_atualizacao()
            except Exception:
                log("erro ao conferir a atualização:\n" + traceback.format_exc())
            time.sleep(2)


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def arq_trava():
    return config.caminho("servico.pid")


def pid_rodando():
    """PID do serviço, se estiver rodando."""
    try:
        with open(arq_trava()) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return pid if _vivo(pid) and pid != os.getpid() else None


def trava_instancia():
    pid = pid_rodando()
    if pid:
        sys.exit(f"O serviço já está rodando neste computador (pid {pid}).")
    os.makedirs(config.base(), exist_ok=True)
    with open(arq_trava(), "w") as f:
        f.write(str(os.getpid()))


def _vivo(pid):
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
