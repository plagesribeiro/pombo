"""Converte a configuração da versão antiga (telegram-claude-bot, um bot só: config.json + estado.json) para o
formato do Pombo (bots/<id>.json)."""
import os

from . import config


def origem_antiga():
    """Onde a versão antiga guardava a configuração."""
    candidatos = [config.caminho("config.json")]
    if os.name == "nt":
        candidatos.append(os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "telegram-claude-bot", "config.json"))
    else:
        candidatos.append(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                                       "telegram-claude-bot", "config.json"))
    return next((c for c in candidatos if os.path.isfile(c)), candidatos[-1])


def migrar(origem=None, bot_id="principal", usuario_nome=""):
    origem = origem or origem_antiga()
    if not os.path.isfile(origem):
        raise config.ErroConfig(f"não achei a configuração antiga em {origem}")
    if config.existe(bot_id):
        raise config.ErroConfig(f'já existe um bot "{bot_id}". Escolha outro id com --id')
    old = config.ler_json(origem, {})
    config.garantir_pastas()

    geral = config.carregar_geral()
    if old.get("nome_maquina"):
        geral["nome_maquina"] = old["nome_maquina"]
    if usuario_nome:
        geral["usuario_nome"] = usuario_nome
    if old.get("claude"):
        geral["claude"] = old["claude"]
    config.salvar_geral(geral)

    perm = old.get("permissoes") or "bypassPermissions"
    cfg = dict(config.BOT_PADRAO)
    cfg.update({
        "nome": old.get("nome_maquina") or bot_id,
        "usuarios_permitidos": old.get("usuarios_permitidos") or [],
        "pasta": old.get("pasta_trabalho") or "~",
        "modelo": old.get("modelo") or "",
        "permissoes": "total" if perm == "bypassPermissions" else "auto",
        "plugin_dirs": old.get("plugin_dirs") or [],
        "instrucoes": old.get("instrucoes_extra") or "",
        "instrucoes_arquivo": old.get("instrucoes_arquivo") or "",
        "nova_sessao_apos_horas": old.get("nova_sessao_apos_horas") or 6,
        "tempo_maximo_min": old.get("tempo_maximo_min") or 25,
        "transcricao_cmd": old.get("transcricao_cmd") or [],
        "token_keychain": old.get("token_keychain") or "",
    })
    config.salvar_bot(bot_id, cfg)
    if old.get("token"):
        config.gravar_token(bot_id, old["token"])

    arq_estado = os.path.join(os.path.dirname(origem), "estado.json")
    est = config.ler_json(arq_estado, {})
    if est:
        config.Estado(bot_id).atualizar(lambda d: d.update(
            {"offset": est.get("offset"), "sessoes": est.get("sessoes") or {}}))
    os.replace(origem, origem + ".migrado")
    if os.path.isfile(arq_estado):
        os.replace(arq_estado, arq_estado + ".migrado")
    return bot_id
