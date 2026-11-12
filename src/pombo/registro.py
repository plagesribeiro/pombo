"""Logs e histórico de execuções."""
import collections
import datetime as dt
import json
import os
import threading

from . import config

_trava = threading.Lock()
LIMITE_LOG = 5_000_000
LIMITE_HISTORICO = 2_000_000


def _arq_log(bot_id):
    return config.caminho("logs", (bot_id or "geral") + ".log")


def log(bot_id, msg):
    linha = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    arq = _arq_log(bot_id)
    with _trava:
        try:
            os.makedirs(os.path.dirname(arq), exist_ok=True)
            if os.path.exists(arq) and os.path.getsize(arq) > LIMITE_LOG:
                os.replace(arq, arq + ".1")
            with open(arq, "a", encoding="utf-8") as f:
                f.write(linha + "\n")
        except OSError:
            pass
    print(f"[{bot_id or 'geral'}] {linha}", flush=True)


def ultimas_linhas(arquivo, n=200):
    try:
        with open(arquivo, encoding="utf-8", errors="replace") as f:
            return list(collections.deque(f, maxlen=n))
    except OSError:
        return []


def ler_log(bot_id, n=200):
    return "".join(ultimas_linhas(_arq_log(bot_id), n))


def registrar_execucao(bot_id, dados):
    arq = config.caminho("execucoes", bot_id + ".jsonl")
    with _trava:
        try:
            os.makedirs(os.path.dirname(arq), exist_ok=True)
            if os.path.exists(arq) and os.path.getsize(arq) > LIMITE_HISTORICO:
                linhas = ultimas_linhas(arq, 2000)
                with open(arq, "w", encoding="utf-8") as f:
                    f.writelines(linhas)
            with open(arq, "a", encoding="utf-8") as f:
                f.write(json.dumps(dados, ensure_ascii=False) + "\n")
        except OSError:
            pass


def ler_execucoes(bot_id, n=30):
    saida = []
    for linha in ultimas_linhas(config.caminho("execucoes", bot_id + ".jsonl"), n):
        try:
            saida.append(json.loads(linha))
        except ValueError:
            pass
    return list(reversed(saida))
