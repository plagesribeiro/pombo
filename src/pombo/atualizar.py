"""Atualizar o Pombo sem derrubar ninguém, do mesmo jeito no Linux, no Mac e no Windows.

`pombo atualizar` baixa a versão nova (git pull) e deixa um aviso em atualizacao.json. O serviço confere esse aviso a
cada ~2 s: quando nenhum bot estiver com pedido rodando (inclusive o pedido de quem mandou atualizar), ele reinicia a si
mesmo. Ao subir de novo, avisa no Telegram que a atualização deu certo e apaga o aviso.

Reiniciar a si mesmo, em vez de chamar o systemd/launchd/Agendador de fora, é o que deixa isso igual em todo lugar e
seguro de pedir pelo próprio bot: um reinício de fora mataria a conversa que pediu antes da resposta chegar.
"""
import os
import subprocess
import sys
import time

from . import config

ARQ = "atualizacao.json"
CODIGO_REINICIAR = 75  # no Windows o processo sai com esse código e a tarefa agendada liga de novo
ARQUIVOS_DO_INSTALADOR = ("mac/", "src/pombo/instalar.py")
AVISO_REINSTALAR = ("O jeito de instalar mudou nesta versão: quando puder, rode `pombo servico instalar` no terminal "
                    "do computador (isso interrompe o que estiver rodando).")


def arquivo():
    return config.caminho(ARQ)


def ler():
    d = config.ler_json(arquivo(), None)
    return d if isinstance(d, dict) else None


def gravar(marcador):
    config.gravar_json(arquivo(), marcador)


def apagar():
    try:
        os.remove(arquivo())
    except OSError:
        pass


def decidir(marcador, inicio_processo, ocioso):
    """O que o serviço faz com o aviso: "nada", "esperar", "reiniciar" ou "avisar".

    Aviso gravado antes de este processo começar = o código novo já está carregado, só falta avisar.
    Aviso gravado depois = reiniciar, mas só com todos os bots parados (ocioso).
    """
    if not marcador:
        return "nada"
    if float(marcador.get("quando") or 0) < inicio_processo:
        return "avisar"
    return "reiniciar" if ocioso else "esperar"


def mensagem(marcador, maquina):
    antes, depois = marcador.get("antes") or "?", marcador.get("depois") or "?"
    if antes == depois:
        texto = f"✅ Pombo reiniciado com sucesso em {maquina}.\nVersão: {depois}"
    else:
        texto = f"✅ Pombo atualizado e reiniciado com sucesso em {maquina}.\nAntes: {antes}\nAgora: {depois}"
    if marcador.get("reinstalar"):
        texto += "\n\n⚠️ " + AVISO_REINSTALAR
    return texto


def reiniciar_processo():
    """Troca este processo por um novo, com o código novo. Só chamar da thread principal."""
    if os.name == "nt":
        os._exit(CODIGO_REINICIAR)  # a tarefa agendada liga de novo (RestartCount)
    os.execv(sys.executable, [sys.executable] + sys.argv)  # mesmo PID: systemd e launchd nem percebem


# ---------------------------------------------------------------- git

def _git(raiz, *args):
    return subprocess.run(["git", "-C", raiz, *args], capture_output=True, text=True)


def eh_git(raiz):
    return _git(raiz, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"


def commit(raiz):
    return _git(raiz, "rev-parse", "HEAD").stdout.strip()


def versao(raiz, ref="HEAD"):
    """'abc1234 Assunto do commit' (ou "" fora do git)."""
    r = _git(raiz, "log", "-1", "--format=%h %s", ref)
    return r.stdout.strip() if r.returncode == 0 else ""


def baixar(raiz):
    """git pull --ff-only. Devolve (ok, mensagem de erro)."""
    r = _git(raiz, "pull", "--ff-only")
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def mudou_instalador(raiz, de, para):
    if not de or not para or de == para:
        return False
    nomes = _git(raiz, "diff", "--name-only", de, para).stdout.split()
    return any(n.startswith(ARQUIVOS_DO_INSTALADOR) for n in nomes)


def novo_marcador(antes, depois, reinstalar, bot=""):
    return {"antes": antes, "depois": depois, "reinstalar": bool(reinstalar),
            "bot": bot or os.environ.get("POMBO_BOT", ""), "quando": time.time()}
