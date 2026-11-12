"""Linha de comando. Tudo o que o painel faz, dá para fazer por aqui (e o Claude também consegue)."""
import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

from . import VERSAO, config, registro, rotinas

AJUDA = """Pombo: um bot do Telegram para cada pasta, rodando o Claude Code neste computador.

Configuração: {base}

Uso comum:
  pombo servico instalar            deixa o serviço rodando sozinho (liga com o computador)
  pombo atualizar                   baixa a versão nova, reinicia sozinho e avisa no Telegram
  pombo painel                      endereço do painel (ou abre um, se o serviço estiver parado)
  pombo status                      como está cada bot

  pombo bots                        lista os bots
  pombo bots criar ID --pasta P     cria um bot (depois: token)
  pombo bots token ID               grava o token do @BotFather (pergunta sem mostrar)
  pombo bots liberar ID USUARIO     libera um ID do Telegram para falar com o bot
  pombo bots ver ID                 mostra a configuração (JSON, sem token)
  pombo bots editar ID campo=valor  muda qualquer campo (valores em JSON: true, 10, ["a","b"])
  pombo bots pausar|ligar|remover ID

  pombo rotinas ID                  lista as rotinas do bot
  pombo rotinas criar ID --nome N --horarios 07:00,17:00 --prompt "..."
  pombo rotinas editar ID ROTINA campo=valor
  pombo rotinas rodar ID ROTINA     roda agora (o resultado vai para o Telegram)
  pombo rotinas remover ID ROTINA

  pombo geral [campo=valor]         nome do computador, como os bots chamam você, seu ID do Telegram
  pombo log [ID] [-n 80]            últimas linhas do log
  pombo testar ID "texto"           roda um pedido como se fosse você (resposta no Telegram)
  pombo migrar                      converte a configuração de uma versão antiga
  pombo servico publicar            painel no celular, pelo Tailscale
  pombo skill instalar              ensina o Claude a configurar os bots (skill pombo)
  pombo rodar                       roda o serviço neste terminal (o instalador faz isso por você)

Sem o comando instalado no PATH, use: python3 /caminho/do/pombo ...
Mudanças valem em até ~2 s, sem reiniciar o serviço."""


def sair(msg, codigo=1):
    print(msg, file=sys.stderr)
    sys.exit(codigo)


def chamar_servico(metodo, caminho, corpo=None, timeout=15):
    """Fala com o serviço rodando (pela API do painel). Devolve None se ele não estiver no ar."""
    porta = config.carregar_geral()["painel_porta"]
    req = urllib.request.Request(f"http://127.0.0.1:{porta}{caminho}", method=metodo,
                                 data=None if corpo is None else json.dumps(corpo).encode(),
                                 headers={"X-Pombo": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("erro")
        except ValueError:
            msg = str(e)
        raise config.ErroConfig(msg)
    except (urllib.error.URLError, OSError):
        return None


def mostrar_json(d):
    print(json.dumps(d, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- comandos

def cmd_status(a):
    from .servico import pid_rodando
    estado = chamar_servico("GET", "/api/estado") if pid_rodando() else None
    if a.json:
        return mostrar_json(estado or {"servico": False, "bots": config.listar_ids()})
    print(f"Serviço: {'ligado' if estado else 'parado'}  ·  configuração em {config.base()}")
    if estado:
        bots = estado["bots"]
    else:
        bots = []
        for b in config.listar_ids():
            try:
                cfg = config.carregar_bot(b)
                bots.append({"id": b, "cfg": cfg, "estado": {"situacao": "parado" if cfg["ativo"] else "pausado", "detalhe": ""}})
            except config.ErroConfig as e:
                bots.append({"id": b, "cfg": None, "estado": {"situacao": "erro", "detalhe": str(e)}})
    if not bots:
        print("Nenhum bot. Crie com: pombo bots criar ID --pasta CAMINHO")
    for b in bots:
        cfg = b.get("cfg") or {}
        e = b["estado"]
        linha = f"- {b['id']:<14} {e['situacao']:<10} {cfg.get('pasta', '')}"
        if e.get("username"):
            linha += f"  @{e['username']}"
        if e.get("detalhe"):
            linha += f"  ({e['detalhe']})"
        print(linha)
        for r in cfg.get("rotinas") or []:
            print(f"    ⏰ {r['id']}: {rotinas.descrever_agenda(r)}{'' if r['ativa'] else ' (pausada)'}")


def cmd_bots(a):
    acao = a.acao or "listar"
    if acao == "listar":
        ids = config.listar_ids()
        if a.json:
            return mostrar_json(ids)
        if not ids:
            print("Nenhum bot. Crie com: pombo bots criar ID --pasta CAMINHO")
        for b in ids:
            try:
                cfg = config.carregar_bot(b)
                tok = "com token" if (cfg.get("token_keychain") or config.token_do_bot(b, cfg)) else "SEM TOKEN"
                print(f"- {b:<14} {cfg['nome']:<20} {cfg['pasta']}  [{'ativo' if cfg['ativo'] else 'pausado'}, {tok}, "
                      f"{len(cfg['usuarios_permitidos'])} usuário(s), {len(cfg['rotinas'])} rotina(s)]")
            except config.ErroConfig as e:
                print(f"- {b:<14} ERRO: {e}")
        return
    if not a.id:
        sair(f"faltou o id do bot: pombo bots {acao} ID")
    if acao == "criar":
        if config.existe(a.id):
            sair(f'já existe um bot "{a.id}"')
        if not a.pasta:
            sair("faltou --pasta (a pasta onde o bot trabalha)")
        cfg = dict(config.BOT_PADRAO)
        cfg.update({"nome": a.nome or a.id, "pasta": a.pasta, "usuarios_permitidos": a.usuario or config.usuarios_iniciais(),
                    "permissoes": a.permissoes or "total"})
        config.salvar_bot(a.id, cfg)
        print(f'Bot "{a.id}" criado em {config.arq_bot(a.id)}.')
        if not config.token_do_bot(a.id, cfg):
            print(f"Próximo passo: pombo bots token {a.id}   (cole o token do @BotFather)")
        if not cfg["usuarios_permitidos"]:
            print(f"Depois mande uma mensagem para o bot e libere seu ID: pombo bots liberar {a.id} SEU_ID "
                  "(o painel mostra o ID de quem tentou falar)")
        return
    if acao == "ver":
        cfg = config.carregar_bot(a.id)
        return mostrar_json({"id": a.id, **cfg,
                             "_token_definido": bool(cfg.get("token_keychain") or config.token_do_bot(a.id, cfg)),
                             "_desconhecidos": config.Estado(a.id).ler().get("desconhecidos") or []})
    if acao == "editar":
        cfg = config.carregar_bot(a.id)
        config.aplicar_campos(cfg, a.pares)
        cfg = config.salvar_bot(a.id, cfg)
        print(f'Bot "{a.id}" atualizado.')
        return
    if acao == "token":
        valor = a.pares[0] if a.pares else None
        if not valor or valor == "-":
            valor = getpass.getpass("Token do @BotFather (não aparece na tela): ") if sys.stdin.isatty() and valor != "-" else sys.stdin.read()
        config.carregar_bot(a.id)
        config.gravar_token(a.id, valor)
        print(f'Token do bot "{a.id}" salvo em {config.caminho("segredos.json")} (só seu usuário lê).')
        return
    if acao == "liberar":
        if not a.pares:
            sair(f"faltou o ID do Telegram: pombo bots liberar {a.id} 123456789")
        from .painel import liberar
        r = liberar(a.id, a.pares[0], remover=a.tirar)
        print(f"Usuários liberados: {', '.join(str(x) for x in r['usuarios_permitidos']) or 'nenhum'}")
        return
    if acao in ("pausar", "ligar"):
        cfg = config.carregar_bot(a.id)
        cfg["ativo"] = acao == "ligar"
        config.salvar_bot(a.id, cfg)
        print(f'Bot "{a.id}" {"ligado" if cfg["ativo"] else "pausado"}.')
        return
    if acao == "remover":
        if not a.sim:
            sair(f'Isso apaga a configuração e o token do bot "{a.id}" (a pasta de trabalho não é tocada). '
                 f"Para confirmar: pombo bots remover {a.id} --sim")
        config.remover_bot(a.id)
        print(f'Bot "{a.id}" removido.')
        return
    sair(f"ação desconhecida: {acao}")


def cmd_rotinas(a):
    cfg = config.carregar_bot(a.id)
    acao = a.acao or "listar"
    if acao == "listar":
        if a.json:
            return mostrar_json(cfg["rotinas"])
        if not cfg["rotinas"]:
            print(f'O bot "{a.id}" não tem rotinas. Crie com: pombo rotinas criar {a.id} --nome ... --horarios 07:00 --prompt "..."')
        est = (config.Estado(a.id).ler().get("rotinas") or {})
        for r in cfg["rotinas"]:
            e = est.get(r["id"]) or {}
            print(f"- {r['id']}: {r['nome']}  [{rotinas.descrever_agenda(r)}]{'' if r['ativa'] else ' (pausada)'}"
                  f"  última: {e.get('ultima_execucao') or 'nunca'}")
            print(f"    {r['prompt'][:160]}")
        return
    if acao == "criar":
        if not a.prompt:
            sair('faltou --prompt "o que a rotina faz"')
        r = {"id": a.rotina or "", "nome": a.nome or "", "horarios": a.horarios or "", "dias": a.dias or "",
             "prompt": a.prompt, "conversa": a.conversa or "nova", "silenciosa": a.silenciosa, "ativa": not a.pausada}
        r = config.validar_rotina(r)
        if any(x["id"] == r["id"] for x in cfg["rotinas"]):
            sair(f'já existe a rotina "{r["id"]}" neste bot (use --id para outro id)')
        cfg["rotinas"].append(r)
        config.salvar_bot(a.id, cfg)
        print(f'Rotina "{r["id"]}" criada: {rotinas.descrever_agenda(r)}.')
        return
    if not a.rotina:
        sair(f"faltou o id da rotina: pombo rotinas {acao} {a.id} ROTINA")
    idx = next((i for i, r in enumerate(cfg["rotinas"]) if r["id"] == a.rotina), None)
    if idx is None:
        sair(f'o bot "{a.id}" não tem a rotina "{a.rotina}". Rotinas: {", ".join(r["id"] for r in cfg["rotinas"]) or "nenhuma"}')
    if acao == "editar":
        config.aplicar_campos(cfg["rotinas"][idx], a.pares)
        config.salvar_bot(a.id, cfg)
        print(f'Rotina "{a.rotina}" atualizada.')
    elif acao == "remover":
        cfg["rotinas"].pop(idx)
        config.salvar_bot(a.id, cfg)
        print(f'Rotina "{a.rotina}" removida.')
    elif acao == "rodar":
        r = chamar_servico("POST", f"/api/bots/{a.id}/rotinas/{a.rotina}/rodar", {})
        if r is None:
            sair("o serviço não está rodando. Ligue com: pombo servico instalar")
        print("Rotina na fila. O resultado chega no Telegram.")
    else:
        sair(f"ação desconhecida: {acao}")


def cmd_geral(a):
    g = config.carregar_geral()
    if a.pares:
        config.aplicar_campos(g, a.pares)
        g = config.salvar_geral(g)
        print("Configuração geral atualizada.")
    mostrar_json(g)


def cmd_log(a):
    print(registro.ler_log(a.id, a.n), end="")


def cmd_painel(a):
    from .servico import pid_rodando
    g = config.carregar_geral()
    porta = a.porta or g["painel_porta"]
    if pid_rodando() and not a.porta:
        print(f"Painel: http://127.0.0.1:{porta}")
        for h in g.get("hosts_permitidos") or []:
            print(f"No celular (Tailscale): https://{h}")
        return
    from . import painel
    print(f"O serviço está parado; abrindo um painel só para configurar em http://127.0.0.1:{porta} (Ctrl+C para fechar).")
    painel.iniciar(None, porta=porta, bloquear=True)


def cmd_testar(a):
    from .execucao import BotRunner
    cfg = config.validar_bot(config.carregar_bot(a.id))
    token = config.token_do_bot(a.id, cfg)
    if not token:
        sair(f'o bot "{a.id}" não tem token')
    if not cfg["usuarios_permitidos"]:
        sair(f'o bot "{a.id}" não tem nenhum usuário liberado')
    r = BotRunner(a.id, cfg, config.carregar_geral(), token)
    uid = cfg["usuarios_permitidos"][0]
    r.processar_mensagem({"chat": {"id": uid, "type": "private"}, "from": {"id": uid}, "message_id": None,
                          "text": " ".join(a.texto) or "oi"})


def cmd_migrar(a):
    from .migrar import migrar
    bot_id = migrar(a.de, a.id, a.usuario or "")
    print(f'Pronto: a configuração antiga virou o bot "{bot_id}" ({config.arq_bot(bot_id)}).')


def cmd_servico(a):
    from . import instalar
    acoes = {"instalar": instalar.instalar, "remover": instalar.remover, "status": instalar.status,
             "reiniciar": instalar.reiniciar, "publicar": lambda: instalar.publicar(a.porta_tailscale),
             "despublicar": lambda: instalar.despublicar(a.porta_tailscale)}
    acoes[a.acao]()


def cmd_atualizar(a):
    from . import atualizar, instalar
    from .servico import pid_rodando
    raiz = instalar.RAIZ
    if not atualizar.eh_git(raiz):
        origem = instalar.clone_de_origem()
        if origem:  # no Mac o serviço roda a cópia de dentro do app: quem atualiza é o clone de onde ela veio
            import subprocess
            sys.exit(subprocess.run([sys.executable, os.path.join(origem, "pombo")] + sys.argv[1:]).returncode)
        sair(f"esta cópia do Pombo ({raiz}) não é um clone do git, então não sei baixar a versão nova. "
             "Baixe à mão e rode: pombo servico instalar")
    de, antes = atualizar.commit(raiz), atualizar.versao(raiz)
    if a.sem_baixar:
        a.reiniciar = True
    else:
        ok, erro = atualizar.baixar(raiz)
        if not ok:
            sair(f"Não consegui baixar a versão nova (git pull). Nada foi reiniciado.\n{erro}")
    para, depois = atualizar.commit(raiz), atualizar.versao(raiz)
    if de == para and not a.reiniciar:
        print(f"Já está na versão mais recente: {depois}. Nada para reiniciar.")
        return
    reinstalar = atualizar.mudou_instalador(raiz, de, para)
    if sys.platform == "darwin" and os.path.isdir(instalar.APP):
        instalar.mac_copiar_codigo()  # no Mac o serviço roda a cópia que fica dentro do app
    resumo = f"{antes} → {depois}" if de != para else depois
    if not pid_rodando():
        print(f"Atualizado: {resumo}. O serviço está parado; ligue com: pombo servico instalar")
        return
    atualizar.gravar(atualizar.novo_marcador(antes, depois, reinstalar, a.bot))
    print(f"Atualizado: {resumo}.\n"
          "O serviço reinicia sozinho assim que nenhum bot estiver com pedido rodando (inclusive este) "
          "e avisa no Telegram quando voltar. Se o aviso não chegar em alguns minutos: pombo status / pombo log")
    if reinstalar:
        print(atualizar.AVISO_REINSTALAR)


def cmd_skill(a):
    from . import instalar
    instalar.skill(remover=a.acao == "remover")


def cmd_rodar(a):
    from .servico import Servico
    Servico().rodar()


# ---------------------------------------------------------------- argparse

def montar():
    p = argparse.ArgumentParser(prog="pombo", add_help=True, formatter_class=argparse.RawDescriptionHelpFormatter,
                                description=AJUDA.format(base=config.base()))
    p.add_argument("--versao", action="version", version=VERSAO)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("rodar", help="roda o serviço neste terminal")
    s.set_defaults(fn=cmd_rodar)

    s = sub.add_parser("status", help="como está cada bot")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("painel", help="endereço do painel")
    s.add_argument("--porta", type=int)
    s.set_defaults(fn=cmd_painel)

    s = sub.add_parser("bots", help="criar, ver, editar e remover bots")
    s.add_argument("acao", nargs="?", choices=["listar", "criar", "ver", "editar", "token", "liberar", "pausar", "ligar", "remover"])
    s.add_argument("id", nargs="?")
    s.add_argument("pares", nargs="*", help="campo=valor (editar), token (token) ou ID do Telegram (liberar)")
    s.add_argument("--pasta")
    s.add_argument("--nome")
    s.add_argument("--usuario", type=int, action="append", help="ID do Telegram liberado (pode repetir)")
    s.add_argument("--permissoes", choices=list(config.PERMISSOES))
    s.add_argument("--tirar", action="store_true", help="com liberar: tira o usuário da lista")
    s.add_argument("--sim", action="store_true", help="com remover: confirma")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_bots)

    s = sub.add_parser("rotinas", help="rotinas agendadas de um bot")
    s.add_argument("acao", nargs="?", choices=["listar", "criar", "editar", "remover", "rodar"])
    s.add_argument("id", nargs="?")
    s.add_argument("rotina", nargs="?")
    s.add_argument("pares", nargs="*")
    s.add_argument("--nome")
    s.add_argument("--horarios", help="ex.: 07:00,11:00,17:00")
    s.add_argument("--dias", help="ex.: seg,ter,qua,qui,sex (vazio = todos)")
    s.add_argument("--prompt")
    s.add_argument("--id", dest="rotina_id")
    s.add_argument("--conversa", choices=["nova", "continuar"])
    s.add_argument("--silenciosa", action="store_true", help="não manda nada quando não houver novidade")
    s.add_argument("--pausada", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_rotinas)

    s = sub.add_parser("geral", help="configuração geral deste computador")
    s.add_argument("pares", nargs="*")
    s.set_defaults(fn=cmd_geral)

    s = sub.add_parser("log", help="últimas linhas do log")
    s.add_argument("id", nargs="?")
    s.add_argument("-n", type=int, default=80)
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("testar", help="roda um pedido como se fosse você")
    s.add_argument("id")
    s.add_argument("texto", nargs="*")
    s.set_defaults(fn=cmd_testar)

    s = sub.add_parser("migrar", help="converte a configuração antiga")
    s.add_argument("--de", help="caminho do config.json antigo")
    s.add_argument("--id", default="principal")
    s.add_argument("--usuario", help="como o bot chama você")
    s.set_defaults(fn=cmd_migrar)

    s = sub.add_parser("servico", help="instalar, remover ou publicar o serviço")
    s.add_argument("acao", choices=["instalar", "remover", "status", "reiniciar", "publicar", "despublicar"])
    s.add_argument("--porta-tailscale", type=int, default=10004)
    s.set_defaults(fn=cmd_servico)

    s = sub.add_parser("atualizar", help="baixa a versão nova, reinicia sozinho e avisa no Telegram")
    s.add_argument("--reiniciar", action="store_true", help="reinicia (e avisa) mesmo sem versão nova")
    s.add_argument("--sem-baixar", action="store_true", help="não roda o git pull (só reinicia e avisa)")
    s.add_argument("--bot", default="", help="bot que manda o aviso (padrão: o bot desta conversa)")
    s.set_defaults(fn=cmd_atualizar)

    s = sub.add_parser("skill", help="instala a skill pombo no Claude Code")
    s.add_argument("acao", choices=["instalar", "remover"])
    s.set_defaults(fn=cmd_skill)
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    p = montar()
    if not argv:
        # sem argumentos: num terminal mostra a ajuda; como serviço (sem terminal), roda
        if sys.stdin is not None and sys.stdin.isatty():
            p.print_help()
            return
        argv = ["rodar"]
    if argv[0] == "rotinas" and len(argv) > 1 and argv[1] not in ("listar", "criar", "editar", "remover", "rodar") \
            and not argv[1].startswith("-"):
        argv = ["rotinas", "listar"] + argv[1:]  # "rotinas ID" = listar
    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        p.print_help()
        return
    if a.cmd == "rotinas":
        if not a.id:
            sair("faltou o id do bot: pombo rotinas ID")
        if a.acao == "criar":  # o id da rotina, se vier, vem de --id
            a.rotina = a.rotina_id or a.rotina
            if a.rotina and "=" in a.rotina:
                sair("use --nome, --horarios e --prompt para criar uma rotina")
    try:
        a.fn(a)
    except config.ErroConfig as e:
        sair(f"Erro: {e}")
