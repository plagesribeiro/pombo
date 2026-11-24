"""Linha de comando. Tudo o que o painel faz, dá para fazer por aqui (e o Claude também consegue)."""
import argparse
import contextlib
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

from . import VERSAO, config, registro, rotinas

AJUDA = """Pombo: um bot do Telegram (ou do WhatsApp) para cada pasta, rodando o Claude Code neste computador.

Configuração: {base}

Uso comum:
  pombo servico instalar            deixa o serviço rodando sozinho (liga com o computador)
  pombo atualizar                   baixa a versão nova, reinicia sozinho e avisa no Telegram
  pombo painel                      endereço do painel (ou abre um, se o serviço estiver parado)
  pombo status                      como está cada bot

  pombo bots                        lista os bots
  pombo bots criar ID --pasta P     cria um bot do Telegram (depois: token)
  pombo bots criar ID --pasta P --canal whatsapp [--numero-separado] [--grupo "🎓 Nome"]
                                    cria um bot do WhatsApp (depois: pombo whatsapp parear). Com --grupo,
                                    cria um grupo só seu para ele (uma pasta por grupo, como no Telegram)
  pombo bots token ID               grava o token do @BotFather (pergunta sem mostrar)
  pombo bots liberar ID USUARIO     libera um ID do Telegram (ou número de WhatsApp) para falar com o bot
  pombo bots ver ID                 mostra a configuração (JSON, sem token)
  pombo bots editar ID campo=valor  muda qualquer campo (valores em JSON: true, 10, ["a","b"])
  pombo bots pausar|ligar|remover ID

  pombo rotinas ID                  lista as rotinas do bot
  pombo rotinas criar ID --nome N --horarios 07:00,17:00 --prompt "..."
  pombo rotinas editar ID ROTINA campo=valor
  pombo rotinas rodar ID ROTINA     roda agora (o resultado vai para o Telegram)
  pombo rotinas remover ID ROTINA

  pombo whatsapp parear [--numero pombo] [--telefone +55...] [--historico 3] [--de-novo]
                                    conecta o WhatsApp neste computador (QR ou código), com pouco histórico
  pombo whatsapp status             os WhatsApps deste computador (pareados ou não) e os bots de cada um
  pombo whatsapp grupos --numero N  os grupos daquele número (para ligar um grupo a um bot)
  pombo whatsapp grupo criar --bot ID [--nome N]     cria um grupo só seu e liga ao bot (sem gatilho)
  pombo whatsapp grupo ligar --bot ID --nome N|JID   liga ao bot um grupo que já existe

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
                tok = ("WhatsApp" if cfg["canal"] == "whatsapp" else
                       "com token" if (cfg.get("token_keychain") or config.token_do_bot(b, cfg)) else "SEM TOKEN")
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
        canal = a.canal or "telegram"
        cfg.update({"nome": a.nome or a.id, "pasta": a.pasta, "canal": canal,
                    "usuarios_permitidos": a.usuario or config.usuarios_iniciais(canal),
                    "permissoes": a.permissoes or "total"})
        if canal == "whatsapp":
            cfg["whatsapp"] = whatsapp_inicial(a)
            if a.numero_separado and not a.usuario:
                from .whatsapp import meu_telefone
                if meu_telefone():
                    cfg["usuarios_permitidos"] = [meu_telefone()]  # quem chama o bot: você
                    print(f"Liberado para chamar o bot: +{meu_telefone()} (o seu número). Outros: pombo bots liberar")
            if a.grupo:
                cfg["whatsapp"]["conversas"] = [criar_grupo(cfg["whatsapp"], a.grupo)]
        cfg = config.salvar_bot(a.id, cfg)
        print(f'Bot "{a.id}" criado em {config.arq_bot(a.id)}.')
        if canal == "whatsapp":
            return explicar_whatsapp(a.id, cfg)
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
            sair(f"faltou quem liberar: pombo bots liberar {a.id} 123456789 (ID do Telegram ou número de WhatsApp)")
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
    if cfg["canal"] == "telegram" and not token:
        sair(f'o bot "{a.id}" não tem token')
    r = BotRunner(a.id, cfg, config.carregar_geral(), token)
    chat = r.dono()
    if not chat:
        sair(f'o bot "{a.id}" não tem para quem responder (libere alguém ou, no WhatsApp, pareie o número)')
    de = "eu" if cfg["canal"] == "whatsapp" and cfg["whatsapp"]["meu_numero"] else (cfg["usuarios_permitidos"] or [chat])[0]
    r.processar_mensagem({"chat": chat, "id": None, "de": de, "texto": " ".join(a.texto) or "oi"})


def whatsapp_inicial(a):
    """Bot novo do WhatsApp. No seu número: só a conversa com você mesmo e o gatilho "pombo".
    Num número só do bot: todas as conversas de quem estiver liberado; na conversa direta sem gatilho, nos grupos
    marcando @ o bot (ou com o gatilho)."""
    from .whatsapp import NOME_NUMERO, pasta_numero
    wa = dict(config.WHATSAPP_PADRAO)
    if a.numero_separado:
        wa.update({"meu_numero": False, "conversas": ["todas"], "gatilho_sempre": False, "prefixo": ""})
    if getattr(a, "numero", None):
        if not NOME_NUMERO.match(a.numero):
            sair('o nome do número é uma palavra curta, como "pombo" (letras minúsculas, números e hífen)')
        wa["pasta_dados"] = pasta_numero(a.numero)
    elif a.conta:
        wa["conta"] = a.conta
    from .whatsapp import achar_wacli
    wa["wacli"] = achar_wacli()  # o serviço roda sem o PATH do terminal: guarda o caminho de agora
    return wa


def bots_do_mesmo_whatsapp(wa):
    from .whatsapp import bots_do_numero
    return bots_do_numero(wa)


@contextlib.contextmanager
def bots_pausados(wa):
    """Para o que precisa do banco do wacli só para si (criar grupo, parear): pausa os bots deste WhatsApp (o sync
    deles para), espera o banco ficar livre e, no fim, religa."""
    from .whatsapp import ErroWhatsApp, Wacli, esperar_banco_livre, pausar_para, religar_de
    w = Wacli(wa)
    pausados = pausar_para(wa)  # anotados: se este comando morrer no meio, o serviço religa ao subir
    try:
        if pausados:
            print(f"Pausando enquanto isso: {', '.join(pausados)}…")
        try:
            esperar_banco_livre(w)
        except ErroWhatsApp as e:
            sair(f"Erro: {e}. Pare o outro wacli e tente de novo.")
        yield w
    finally:
        religar_de(wa)


def criar_grupo(wa, nome):
    """Cria um grupo só com você (o wacli precisa do banco livre: os bots deste WhatsApp pausam por uns segundos).
    Devolve o JID."""
    from .whatsapp import ErroWhatsApp
    with bots_pausados(wa) as w:
        try:
            jid = w.criar_grupo(nome)
        except ErroWhatsApp as e:
            sair(f"Não consegui criar o grupo: {e}\nDá para criar no celular (um grupo só com você) e ligar com: "
                 f'pombo whatsapp grupo ligar --bot ID --nome "{nome}"')
    print(f'Grupo "{nome}" criado ({jid}).')
    return jid


def explicar_whatsapp(bot_id, cfg):
    wa = cfg["whatsapp"]
    if any(c.endswith("@g.us") for c in wa["conversas"]):
        print("Ele conversa no grupo só seu que acabou de ser criado: escreva lá direto, sem gatilho.")
    if not wa["wacli"]:
        print("Falta instalar o wacli: brew install openclaw/tap/wacli  (ou github.com/openclaw/wacli)\n"
              f"Depois guarde o caminho: pombo bots editar {bot_id} whatsapp.wacli=$(which wacli)")
    onde = f" --bot {bot_id}" if (wa["pasta_dados"] or wa["conta"]) else ""
    print("Próximo passo (se o número ainda não estiver pareado): pombo whatsapp parear" + onde +
          "   (lê o QR no celular: WhatsApp > Aparelhos conectados)")
    if wa["meu_numero"] and "eu" in wa["conversas"]:
        print(f'Depois, na conversa com você mesmo no WhatsApp, mande: {wa["gatilho"]}, oi')
    else:
        print(f"Depois libere quem pode falar com ele: pombo bots liberar {bot_id} +55DDDNUMERO")
    print("Atenção: o wacli não é oficial, e o WhatsApp pode bloquear números que usam clientes não oficiais.")


def cmd_whatsapp(a):
    import subprocess
    from .whatsapp import NOME_NUMERO, ErroWhatsApp, Wacli, achar_wacli, numeros_locais, pasta_numero
    wa = {"wacli": a.wacli or "", "conta": a.conta or "", "pasta_dados": ""}
    a.numero = getattr(a, "numero", None)
    if a.numero:
        if not NOME_NUMERO.match(a.numero):
            sair('o nome do número é uma palavra curta, como "pombo" (letras minúsculas, números e hífen)')
        wa.update({"conta": "", "pasta_dados": pasta_numero(a.numero)})
    if a.bot:
        cfg = config.validar_bot(config.carregar_bot(a.bot))
        if cfg["canal"] != "whatsapp":
            sair(f'o bot "{a.bot}" não é do WhatsApp')
        wa = cfg["whatsapp"]
    w = Wacli(wa)
    if not w.bin:
        sair("Não achei o wacli. Instale com: brew install openclaw/tap/wacli  (ou veja github.com/openclaw/wacli)")
    if a.acao == "grupo":
        return cmd_whatsapp_grupo(a, w)
    if a.acao == "status":
        if a.bot or a.numero or a.conta:
            try:
                st = w.status()
            except ErroWhatsApp as e:
                sair(f"Erro: {e}")
            if st.get("authenticated"):
                print(f"Pareado: +{st.get('phone') or ''} ({st.get('linked_jid')})  ·  wacli em {w.bin}")
            else:
                print("Não está pareado. Rode: pombo whatsapp parear" + (f" --numero {a.numero}" if a.numero else ""))
            return
        for n in numeros_locais():
            nome = n["numero"] or "padrão"
            situacao = f"+{n['telefone']}" if n["pareado"] else "não pareado"
            bots = ", ".join(b["id"] + ("" if b["ativo"] else " (pausado)") for b in n["bots"]) or "nenhum bot"
            print(f"- {nome:<10} {situacao:<16} {n['pasta_dados'] or '(pasta padrão do wacli)'}  ·  {bots}")
        return
    if a.acao == "grupos":
        try:
            grupos = w.grupos()
        except ErroWhatsApp as e:
            sair(f"Erro: {e}")
        for g in grupos:
            if isinstance(g, dict):
                print(f"- {g.get('Name') or '(sem nome)':<30} {g.get('JID')}")
        if not grupos:
            print("Nenhum grupo ainda (o número precisa estar pareado e no grupo).")
        return
    cmd = w.base() + ["auth"] + comando_parear(a)
    with bots_pausados(wa):
        if a.de_novo:
            print("Desfazendo o pareamento atual (o aparelho some de Aparelhos conectados no celular)…")
            subprocess.call(w.base() + ["auth", "logout"])
        print("No celular: WhatsApp > Configurações > Aparelhos conectados > Conectar um aparelho." +
              (" Toque em \"Conectar com número de telefone\" e digite o código que aparecer aqui." if a.telefone else
               " Leia o QR que vai aparecer aqui."))
        print(("Histórico: " + (f"só os últimos {a.historico} dia(s)" if a.historico else "o que o celular quiser mandar") +
               (f", até {a.por_conversa} mensagens por conversa" if a.por_conversa else "") +
               ". O Pombo não precisa de histórico: quanto menos, mais rápido e menos peso no celular.\n"))
        subprocess.call(cmd)
        if not pareado(w):
            # sessão velha presa (o aparelho foi removido no celular): o wacli tenta com ela, leva um "logged out" e
            # ainda escreve "Authenticated". Limpa a sessão e tenta mais uma vez, agora pedindo um código novo
            print("\nA sessão antiga estava presa (o aparelho tinha sido removido no celular). Limpando e tentando de novo…")
            subprocess.call(w.base() + ["auth", "logout"])
            subprocess.call(cmd)
    if not pareado(w):
        sair("\nNão pareou. Rode de novo: pombo whatsapp parear" + (f" --bot {a.bot}" if a.bot else "") + " --de-novo")
    print("\nPronto. O serviço do Pombo liga o bot do WhatsApp em alguns segundos (pombo status).")
    sys.exit(0)


def pareado(w):
    """O wacli às vezes diz "Authenticated" sem ter pareado: confere pelo auth status."""
    from .whatsapp import ErroWhatsApp
    try:
        return bool(w.status().get("authenticated"))
    except ErroWhatsApp:
        return False


def comando_parear(a):
    """O resto do `wacli auth`. Por padrão pede pouco histórico: o celular manda o histórico em pedaços, por horas,
    para o aparelho novo (a janela padrão é de uns 3 meses), e o Pombo só precisa das mensagens que chegam depois."""
    args = ["--phone", a.telefone] if a.telefone else []
    if a.historico:
        args += ["--history-days", str(a.historico)]
    if a.por_conversa:
        args += ["--history-max-per-chat", str(a.por_conversa)]
    return args


def cmd_whatsapp_grupo(a, w):
    from .whatsapp import ErroWhatsApp
    if not a.bot or a.grupo_acao not in ("criar", "ligar"):
        sair('use: pombo whatsapp grupo criar --bot ID [--nome "🎓 Nome"]  ou  pombo whatsapp grupo ligar --bot ID --nome N')
    cfg = config.validar_bot(config.carregar_bot(a.bot))
    wa = cfg["whatsapp"]
    if a.grupo_acao == "criar":
        jid = criar_grupo(wa, a.nome or f"🐦 {cfg['nome']}")
    else:
        if not a.nome:
            sair("faltou --nome (o nome do grupo, ou o JID ...@g.us)")
        if a.nome.endswith("@g.us"):
            jid = a.nome
        else:
            try:
                achados = [g for g in w.grupos(a.nome) if isinstance(g, dict)]
            except ErroWhatsApp as e:
                sair(f"Erro: {e}")
            exatos = [g for g in achados if (g.get("Name") or "").strip().lower() == a.nome.strip().lower()]
            achados = exatos or achados
            if len(achados) != 1:
                nomes = ", ".join(f'{g.get("Name")} ({g.get("JID")})' for g in achados[:10]) or "nenhum"
                sair(f'Achei {len(achados)} grupo(s) com "{a.nome}": {nomes}. Use o JID: --nome 1203...@g.us')
            jid = achados[0].get("JID")
    cfg = config.carregar_bot(a.bot)
    conversas = [c for c in cfg["whatsapp"].get("conversas") or [] if c != jid]
    if a.so_o_grupo:
        conversas = []
    cfg["whatsapp"]["conversas"] = conversas + [jid]
    config.salvar_bot(a.bot, cfg)
    print(f'Pronto: o bot "{a.bot}" conversa no grupo {jid}. Num grupo só seu, é só escrever, sem gatilho; '
          "se entrar mais alguém, ele volta a exigir o gatilho.")


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
    s.add_argument("pares", nargs="*", help="campo=valor (editar), token (token) ou ID do Telegram/número (liberar)")
    s.add_argument("--pasta")
    s.add_argument("--nome")
    s.add_argument("--canal", choices=list(config.CANAIS), help="telegram (padrão) ou whatsapp")
    s.add_argument("--numero-separado", action="store_true",
                   help="com --canal whatsapp: o WhatsApp pareado é um número só do bot (não o seu)")
    s.add_argument("--conta", help="com --canal whatsapp: conta do wacli (--account), para ter mais de um WhatsApp")
    s.add_argument("--numero", help='com --canal whatsapp: o número a mais que ele usa (ex.: pombo, pareado com '
                                    'pombo whatsapp parear --numero pombo)')
    s.add_argument("--grupo", help='com --canal whatsapp: cria um grupo só seu com este nome para o bot (ex.: "🎓 Mestrado")')
    s.add_argument("--usuario", action="append", help="ID do Telegram (ou número de WhatsApp) liberado (pode repetir)")
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

    s = sub.add_parser("whatsapp", help="conectar o WhatsApp (wacli) neste computador")
    s.add_argument("acao", choices=["parear", "status", "grupo", "grupos"])
    s.add_argument("grupo_acao", nargs="?", choices=["criar", "ligar"], help="com grupo: criar ou ligar")
    s.add_argument("--bot", help="usa a conta do wacli deste bot")
    s.add_argument("--nome", help="com grupo: nome do grupo (ou o JID, em ligar)")
    s.add_argument("--so-o-grupo", action="store_true", help="com grupo: o bot passa a escutar só esse grupo")
    s.add_argument("--conta", help="conta do wacli (--account)")
    s.add_argument("--numero", help='um número a mais, só do bot (ex.: pombo): fica em ~/.wacli-NOME')
    s.add_argument("--telefone", help="parear por código, sem QR (ex.: +55 31 99999-0000)")
    s.add_argument("--historico", type=int, default=3,
                   help="parear: dias de histórico que o celular manda (padrão 3; 0 = o que o celular quiser, ~3 meses)")
    s.add_argument("--por-conversa", type=int, default=50,
                   help="parear: no máximo quantas mensagens por conversa (padrão 50; 0 = sem limite)")
    s.add_argument("--de-novo", action="store_true", help="parear: desfaz o pareamento atual e pareia outra vez")
    s.add_argument("--wacli", help="caminho do wacli, se não estiver no PATH")
    s.set_defaults(fn=cmd_whatsapp)

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
