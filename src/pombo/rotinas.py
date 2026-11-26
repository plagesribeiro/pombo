"""Quando cada rotina deve rodar."""
import datetime as dt

from .config import DIAS

FORMATO = "%Y-%m-%d %H:%M"


def _horarios_do_dia(rotina, dia):
    if rotina["dias"] and DIAS[dia.weekday()] not in rotina["dias"]:
        return []
    saida = []
    for h in rotina["horarios"]:
        hh, mm = (int(x) for x in h.split(":"))
        saida.append(dt.datetime.combine(dia, dt.time(hh, mm)))
    return sorted(saida)


def ultimo_horario(rotina, agora):
    """O horário agendado mais recente que já passou (até 8 dias para trás), ou None."""
    for delta in range(0, 9):
        dia = (agora - dt.timedelta(days=delta)).date()
        passados = [t for t in _horarios_do_dia(rotina, dia) if t <= agora]
        if passados:
            return passados[-1]
    return None


def proximo_horario(rotina, agora):
    for delta in range(0, 9):
        dia = (agora + dt.timedelta(days=delta)).date()
        futuros = [t for t in _horarios_do_dia(rotina, dia) if t > agora]
        if futuros:
            return futuros[0]
    return None


def decidir(rotina, agora, ultima_marca):
    """Devolve (acao, marca).

    acao: "rodar" (horário novo dentro da tolerância), "perdida" (passou da tolerância, por exemplo com o
    computador dormindo), "iniciar" (rotina nova: marca o último horário sem rodar) ou None (nada a fazer).
    marca: o horário ("AAAA-MM-DD HH:MM") que deve ser gravado como o último tratado.
    """
    if not rotina.get("ativa") or not rotina.get("horarios"):
        return None, ultima_marca
    t = ultimo_horario(rotina, agora)
    if t is None:
        return None, ultima_marca
    marca = t.strftime(FORMATO)
    if not ultima_marca:
        return "iniciar", marca
    if marca <= ultima_marca:
        return None, ultima_marca
    if (agora - t).total_seconds() > rotina.get("tolerancia_min", 90) * 60:
        return "perdida", marca
    return "rodar", marca


def descrever_agenda(rotina):
    dias = rotina.get("dias") or []
    quando = ", ".join(rotina.get("horarios") or []) or "sem horário (só manual)"
    if dias and len(dias) < 7:
        quando += " (" + ", ".join(dias) + ")"
    return quando


def interpretar_checagem(codigo, saida):
    """O que fazer com o resultado do `checar` de uma rotina. codigo None = nem rodou (saida diz o motivo).

    Devolve (acao, texto): ("novidades", o que ele achou) roda o agente com isso; ("pular", motivo) não roda nesta vez;
    ("erro", motivo) roda o agente normalmente (melhor rodar à toa do que perder alguma coisa).
    """
    if codigo is None:
        return "erro", f"o checador não rodou ({saida})"
    if codigo == 0 and (saida or "").strip():
        return "novidades", saida.strip()
    if codigo == 0:
        return "pular", "o checador não achou nada (saída vazia)"
    if codigo == 1:
        return "pular", "o checador disse que não há nada (código 1)"
    return "erro", f"o checador falhou (código {codigo}{': ' + saida.strip()[-200:] if (saida or '').strip() else ''})"
