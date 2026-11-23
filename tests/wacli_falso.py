#!/usr/bin/env python3
"""Um wacli de mentira para os testes: responde aos comandos que o Pombo usa e guarda tudo em <store>/falso.json.

Os testes usam as funções `preparar`, `chegar` e `enviadas` daqui para simular o WhatsApp.
O formato das respostas imita o do wacli de verdade (envelope {"success", "data", "error"}, campos do Message em Go).
"""
import contextlib
import datetime as dt
import fcntl
import json
import os
import sys
import time

ARQ = "falso.json"


# ---------------------------------------------------------------- para os testes

def preparar(store, eu="5531900000000"):
    os.makedirs(store, exist_ok=True)
    _salvar(store, {"eu": eu, "mensagens": [], "diario": [], "enviadas": [], "reacoes": [], "seq": 0, "grupos": {}})
    return f"{eu}@s.whatsapp.net"


def chegar(store, chat, texto="", de_mim=True, remetente=None, nome="", midia="", citada="", idade_s=0, legenda="",
           encaminhada=False):
    """Simula uma mensagem que o wacli sync acabou de gravar. Devolve o id."""
    with _trava(store):
        return _chegar(store, chat, texto, de_mim, remetente, nome, midia, citada, idade_s, legenda, encaminhada)


def _chegar(store, chat, texto, de_mim, remetente, nome, midia, citada, idade_s, legenda, encaminhada):
    d = _carregar(store)
    d["seq"] += 1
    mid = f"MSG{d['seq']}"
    m = _mensagem(d, chat, mid, texto, de_mim, remetente, nome, midia, citada, idade_s, legenda)
    m["IsForwarded"] = encaminhada
    d["mensagens"].append(m)
    d["diario"].append({"operation": "upsert", "chat_jid": chat, "msg_id": mid})
    _salvar(store, d)
    return mid


def grupo(store, nome, outros=()):
    """Cria um grupo com você (e os números em `outros`). Devolve o JID."""
    with _trava(store):
        return _grupo(store, nome, outros)


def _grupo(store, nome, outros):
    d = _carregar(store)
    d["seq"] += 1
    jid = f"120363{d['seq']:06d}@g.us"
    d.setdefault("grupos", {})[jid] = {"nome": nome, "participantes": [d["eu"]] + list(outros)}
    _salvar(store, d)
    return jid


def entrar_no_grupo(store, jid, numero):
    with _trava(store):
        d = _carregar(store)
        d["grupos"][jid]["participantes"].append(numero)
        _salvar(store, d)


def enviadas(store):
    return _carregar(store)["enviadas"]


def reacoes(store):
    return _carregar(store)["reacoes"]


# ---------------------------------------------------------------- por dentro

@contextlib.contextmanager
def _trava(store):
    """Como o banco do wacli de verdade: um processo de cada vez mexe no estado."""
    os.makedirs(store, exist_ok=True)
    with open(os.path.join(store, "falso.lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _carregar(store):
    with open(os.path.join(store, ARQ), encoding="utf-8") as f:
        return json.load(f)


def _salvar(store, d):
    tmp = os.path.join(store, f"{ARQ}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(store, ARQ))


def _agora(idade_s=0):
    t = dt.datetime.utcfromtimestamp(time.time() - idade_s)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _mensagem(d, chat, mid, texto, de_mim, remetente, nome, midia, citada, idade_s, legenda):
    eu = d["eu"] + "@s.whatsapp.net"
    return {"ChatJID": chat, "ChatName": "", "MsgID": mid, "SenderJID": eu if de_mim else (remetente or chat),
            "SenderName": "" if de_mim else nome, "Timestamp": _agora(idade_s), "FromMe": de_mim,
            "Text": texto if not midia else "[Audio]" if midia == "audio" else texto, "DisplayText": texto,
            "quoted_msg_id": citada or None, "ReactionToID": "", "ReactionEmoji": "", "MediaType": midia,
            "MediaCaption": legenda, "Filename": "arquivo.pdf" if midia == "document" else "", "Revoked": False,
            "DeletedForMe": False}


def _saida(data=None, erro=None):
    # como o de verdade: o envelope vai para o stdout quando dá certo e para o stderr quando dá erro
    print(json.dumps({"success": erro is None, "data": data, "error": erro}, ensure_ascii=False),
          file=sys.stdout if erro is None else sys.stderr)
    sys.exit(0 if erro is None else 1)


def _opcoes(args):
    """['--to', 'x', '--allow-self', 'sobra'] -> ({'to': 'x', 'allow-self': True}, ['sobra'])."""
    op, resto, i = {}, [], 0
    sem_valor = {"allow-self", "no-preview", "json", "read-only", "events", "follow", "checkpoint"}
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            nome = a[2:]
            if nome in sem_valor:
                op[nome] = True
            else:
                op[nome] = args[i + 1] if i + 1 < len(args) else ""
                i += 1
        else:
            resto.append(a)
        i += 1
    return op, resto


def _registrar_envio(d, chat, texto, extra):
    d["seq"] += 1
    mid = f"BOT{d['seq']}"
    m = _mensagem(d, chat, mid, texto, True, None, "", extra.get("midia", ""), extra.get("reply-to", ""), 0, "")
    d["mensagens"].append(m)
    d["diario"].append({"operation": "upsert", "chat_jid": chat, "msg_id": mid})
    d["enviadas"].append({"id": mid, "to": chat, "text": texto, **extra})
    return mid


def main(argv):
    op, pos = _opcoes(argv)
    store = op.get("store") or os.environ.get("WACLI_STORE_DIR") or os.path.expanduser("~/.wacli-falso")
    if pos[:1] != ["sync"]:  # o sync fica rodando para sempre: não pode segurar a trava
        with _trava(store):
            return _main(op, pos, store)
    return _main(op, pos, store)


def _main(op, pos, store):
    try:
        d = _carregar(store)
    except OSError:
        d = None
    cmd = pos[:2]
    if cmd[:1] == ["sync"]:
        if d is None:
            sys.stderr.write(json.dumps({"event": "error", "data": {"message": "not authenticated; run `wacli auth`"}}) + "\n")
            sys.exit(0)
        sys.stderr.write(json.dumps({"event": "connected", "data": {}}) + "\n")
        sys.stderr.flush()
        while True:
            time.sleep(3600)
    if d is None:
        _saida({"authenticated": False} if cmd == ["auth", "status"] else None,
               None if cmd == ["auth", "status"] else "not authenticated; run `wacli auth`")
    eu = d["eu"] + "@s.whatsapp.net"
    if cmd == ["auth", "status"]:
        _saida({"authenticated": True, "linked_jid": eu, "phone": d["eu"]})
    if cmd == ["messages", "changes"]:
        if op.get("checkpoint"):
            _saida({"store_id": "falso", "changes": [], "has_more": False, "next_checkpoint": str(len(d["diario"]))})
        try:
            pos_ = int(op.get("since") or "")
        except ValueError:
            _saida(erro="malformed cursor/checkpoint; restart the read")
        limite = int(op.get("limit") or 100)
        trecho = d["diario"][pos_:pos_ + limite]
        _saida({"store_id": "falso", "changes": trecho, "has_more": pos_ + limite < len(d["diario"]),
                "next_checkpoint": str(pos_ + len(trecho))})
    if cmd == ["messages", "show"]:
        for m in d["mensagens"]:
            if m["ChatJID"] == op.get("chat") and m["MsgID"] == op.get("id"):
                _saida(m)
        _saida(erro="sql: no rows in result set")
    if cmd == ["messages", "context"]:
        da_conversa = [m for m in d["mensagens"] if m["ChatJID"] == op.get("chat") and not m["ReactionEmoji"]]
        ids = [m["MsgID"] for m in da_conversa]
        if op.get("id") not in ids:
            _saida(erro="message not found")
        i = ids.index(op["id"])
        _saida({"messages": da_conversa[max(0, i - int(op.get("before") or 0)):i + 1]})
    if cmd == ["send", "text"]:
        para = op.get("to", "")
        if para == eu and not op.get("allow-self"):
            _saida(erro="refusing to send to the linked account itself; pass --allow-self")
        if op.get("reply-to") and not any(m["MsgID"] == op["reply-to"] for m in d["mensagens"]):
            _saida(erro="reply target not found in local store; run wacli sync first")
        mid = _registrar_envio(d, para, op.get("message", ""), {"reply-to": op.get("reply-to", ""),
                                                                  "allow-self": bool(op.get("allow-self"))})
        _salvar(store, d)
        _saida({"sent": True, "to": para, "id": mid})
    if cmd and cmd[0] == "send" and cmd[1] in ("file", "voice"):
        if not os.path.isfile(op.get("file", "")):
            _saida(erro="file not found")
        mid = _registrar_envio(d, op.get("to", ""), "", {"arquivo": op["file"], "tipo": cmd[1],
                                                         "midia": "audio" if cmd[1] == "voice" else "document"})
        _salvar(store, d)
        _saida({"sent": True, "to": op.get("to"), "id": mid})
    if cmd == ["send", "react"]:
        d["seq"] += 1
        mid = f"REA{d['seq']}"
        d["reacoes"].append({"id": mid, "to": op.get("to"), "alvo": op.get("id"), "emoji": op.get("reaction"),
                             "sender": op.get("sender", "")})
        m = _mensagem(d, op.get("to"), mid, "", True, None, "", "", "", 0, "")
        m.update({"ReactionToID": op.get("id"), "ReactionEmoji": op.get("reaction")})
        d["mensagens"].append(m)
        d["diario"].append({"operation": "upsert", "chat_jid": op.get("to"), "msg_id": mid})
        _salvar(store, d)
        _saida({"sent": True, "to": op.get("to"), "id": mid, "target": op.get("id"), "reaction": op.get("reaction")})
    if cmd == ["groups", "participants"] and pos[2:3] == ["list"]:
        g = d.get("grupos", {}).get(op.get("jid"))
        _saida([{"group_jid": op.get("jid"), "user_jid": f"{n}@s.whatsapp.net", "role": "admin" if i == 0 else "member"}
                for i, n in enumerate(g["participantes"])] if g else [])
    if cmd == ["groups", "list"]:
        busca = (op.get("query") or "").lower()
        _saida([{"JID": j, "Name": g["nome"]} for j, g in d.get("grupos", {}).items() if busca in g["nome"].lower()])
    if cmd == ["groups", "create"]:
        d["seq"] += 1
        jid = f"120363{d['seq']:06d}@g.us"
        d.setdefault("grupos", {})[jid] = {"nome": op.get("name"), "participantes": [d["eu"]]}
        _salvar(store, d)
        _saida({"JID": jid, "GroupName": {"Name": op.get("name")}, "Participants": [{"JID": eu}]})
    if cmd == ["doctor"]:
        _saida({"lock_held": False, "authenticated": True, "connection_state": "disconnected"})
    if cmd == ["media", "download"]:
        pasta = op.get("output") or store
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, f"{op.get('id')}.ogg")
        with open(caminho, "wb") as f:
            f.write(b"OggS falso")
        _saida({"chat": op.get("chat"), "id": op.get("id"), "path": caminho, "downloaded": True})
    _saida(erro=f"comando não existe no falso: {' '.join(pos)}")


if __name__ == "__main__":
    main(sys.argv[1:])
