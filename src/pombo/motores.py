"""Como chamar o agente. Hoje só o Claude Code (`claude -p`); outro motor entra aqui com o mesmo formato."""
import json
import os
import shutil

from . import config


def comando_claude(cfg, geral, bot_id, sistema, sessao):
    """Monta o comando e as variáveis de ambiente para um `claude -p` deste bot. O prompt vai pelo stdin."""
    claude = shutil.which(geral.get("claude") or "claude") or geral.get("claude") or "claude"
    cmd = [claude, "-p", "--output-format", "stream-json", "--verbose", "--append-system-prompt", sistema]
    if sessao:
        cmd += ["--resume", sessao]
    perm = cfg["permissoes"]
    if perm == "total":
        cmd += ["--dangerously-skip-permissions"]
    elif perm == "auto":
        cmd += ["--permission-mode", "auto"]
    elif perm == "lista":
        cmd += ["--permission-mode", "dontAsk"]
        if cfg["ferramentas_permitidas"]:
            cmd += ["--allowedTools", *cfg["ferramentas_permitidas"]]
    if cfg["ferramentas_negadas"]:
        cmd += ["--disallowedTools", *cfg["ferramentas_negadas"]]
    if cfg.get("modelo"):
        cmd += ["--model", cfg["modelo"]]
    if cfg.get("esforco"):
        cmd += ["--effort", cfg["esforco"]]
    if cfg.get("chrome"):  # Claude in Chrome: precisa da extensão instalada e conectada no navegador
        cmd += ["--chrome"]
    for p in cfg.get("plugin_dirs") or []:
        p = config.resolver(cfg, p)
        if os.path.isdir(p):
            cmd += ["--plugin-dir", p]
    if cfg["mcps"] or cfg["so_mcps_do_bot"]:
        arq = config.caminho("mcp", bot_id + ".json")
        config.gravar_json(arq, {"mcpServers": cfg["mcps"]}, privado=True)
        cmd += ["--mcp-config", arq]
        if cfg["so_mcps_do_bot"]:
            cmd += ["--strict-mcp-config"]
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)  # o bot pode ter sido iniciado de dentro de uma sessão do Claude Code
    if not cfg["conectores_claude_ai"]:
        env["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
    for k, v in (cfg.get("env") or {}).items():
        env[k] = os.path.expanduser(v)
    return cmd, env


def ler_evento(linha):
    """Uma linha do stream-json -> dict, ou None."""
    try:
        d = json.loads(linha)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None
