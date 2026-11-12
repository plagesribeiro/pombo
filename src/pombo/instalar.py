"""Deixa o serviço rodando sozinho (Linux: systemd do usuário; Mac: LaunchAgent; Windows: tarefa agendada),
publica o painel no Tailscale e instala a skill do Claude."""
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time

from . import config

NOME = "pombo"
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(RAIZ, "pombo")


def _rodar(cmd, checar=True, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if checar and r.returncode != 0:
        raise config.ErroConfig(f"falhou: {' '.join(cmd)}\n{(r.stderr or r.stdout).strip()}")
    return r


def _path_do_servico():
    """O PATH de quem instalou, com a pasta do claude na frente: o que funciona no seu terminal funciona no bot."""
    partes = []
    claude = shutil.which(config.carregar_geral().get("claude") or "claude")
    if claude:
        partes.append(os.path.dirname(claude))
    partes += [os.path.expanduser("~/.local/bin")] + os.environ.get("PATH", "").split(os.pathsep)
    vistos, saida = set(), []
    for p in partes:
        if p and p not in vistos:
            vistos.add(p)
            saida.append(p)
    return os.pathsep.join(saida)


def _aviso_claude():
    if not shutil.which(config.carregar_geral().get("claude") or "claude"):
        print("Aviso: não achei o 'claude' no PATH. Instale o Claude Code e faça login (rode 'claude') antes.")


# ---------------------------------------------------------------- Linux

UNIT = os.path.expanduser(f"~/.config/systemd/user/{NOME}.service")


def _linux_instalar():
    os.makedirs(os.path.dirname(UNIT), exist_ok=True)
    texto = f"""[Unit]
Description=Pombo: bots do Telegram que rodam o Claude Code
After=network-online.target

[Service]
ExecStart={sys.executable} {SCRIPT} rodar
WorkingDirectory={RAIZ}
Restart=always
RestartSec=20
Environment=PATH={_path_do_servico()}
Environment=LANG=C.UTF-8
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    with open(UNIT, "w") as f:
        f.write(texto)
    _rodar(["systemctl", "--user", "daemon-reload"])
    _rodar(["systemctl", "--user", "enable", NOME])
    _rodar(["systemctl", "--user", "restart", NOME])
    linger = _rodar(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"], checar=False).stdout.strip()
    if linger != "Linger=yes":
        print("Aviso: sem 'linger', o serviço só roda com você logado. Para rodar sempre: sudo loginctl enable-linger $USER")


def _linux_remover():
    _rodar(["systemctl", "--user", "disable", "--now", NOME], checar=False)
    if os.path.exists(UNIT):
        os.remove(UNIT)
    _rodar(["systemctl", "--user", "daemon-reload"], checar=False)


# ---------------------------------------------------------------- Mac
# O macOS não deixa serviço de fundo entrar em Documentos sem autorização. Por isso o serviço roda dentro de um
# app pequeno, que recebe uma vez o "Acesso Total ao Disco"; o python3 e o claude abertos por ele herdam a permissão.

APP = os.path.expanduser("~/Applications/Pombo.app")
EXE = os.path.join(APP, "Contents", "MacOS", NOME)
RECURSOS = os.path.join(APP, "Contents", "Resources")
ROTULO_PADRAO = "io.github.plagesribeiro.pombo"


def _mac_rotulo():
    """Reaproveita o identificador de um app já instalado: assim a permissão dada no macOS continua valendo."""
    try:
        with open(os.path.join(APP, "Contents", "Info.plist"), "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier") or ROTULO_PADRAO
    except (OSError, ValueError):
        return ROTULO_PADRAO


def _mac_plist(rotulo):
    return os.path.expanduser(f"~/Library/LaunchAgents/{rotulo}.plist")


def mac_copiar_codigo():
    """O código vai dentro do app (o python consegue abrir sem permissão extra). Também usado pelo `pombo atualizar`."""
    os.makedirs(RECURSOS, exist_ok=True)
    shutil.copy2(SCRIPT, os.path.join(RECURSOS, "pombo"))
    destino_pkg = os.path.join(RECURSOS, "src", "pombo")
    novo = destino_pkg + ".novo"
    if os.path.isdir(novo):
        shutil.rmtree(novo)
    shutil.copytree(os.path.join(RAIZ, "src", "pombo"), novo, ignore=shutil.ignore_patterns("__pycache__"))
    if os.path.isdir(destino_pkg):
        shutil.rmtree(destino_pkg)
    os.replace(novo, destino_pkg)


def _mac_instalar():
    rotulo = _mac_rotulo()
    uid = str(os.getuid())
    _rodar(["launchctl", "bootout", f"gui/{uid}/{rotulo}"], checar=False)
    os.makedirs(os.path.dirname(EXE), exist_ok=True)
    mac_copiar_codigo()
    novo = tempfile.mktemp()
    _rodar(["clang", "-O2", "-o", novo, f'-DBOT_PY="{os.path.join(RECURSOS, "pombo")}"', os.path.join(RAIZ, "mac", "lancador.c")])
    assinar = False
    if not os.path.exists(EXE) or open(novo, "rb").read() != open(EXE, "rb").read():
        shutil.move(novo, EXE)
        os.chmod(EXE, 0o755)
        assinar = True
    else:
        os.remove(novo)
    with open(os.path.join(APP, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleIdentifier": rotulo, "CFBundleName": "Pombo",
                       "CFBundleDisplayName": "Pombo", "CFBundleExecutable": NOME,
                       "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "LSUIElement": True,
                       "LSBackgroundOnly": True}, f)
    if assinar:
        _rodar(["codesign", "--force", "--sign", "-", "--identifier", rotulo, APP], checar=False)
        print("Na 1ª vez (ou depois de mudar o lançador): Ajustes do Sistema → Privacidade e Segurança → "
              "Acesso Total ao Disco → + → ~/Applications/Pombo.app")
    base = config.base()
    os.makedirs(base, exist_ok=True)
    plist = {"Label": rotulo, "ProgramArguments": [EXE], "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 20,
             "EnvironmentVariables": {"PATH": _path_do_servico(), "LANG": "pt_BR.UTF-8", "PYTHONUNBUFFERED": "1"},
             "StandardOutPath": os.path.join(base, "launchd.log"), "StandardErrorPath": os.path.join(base, "launchd.log")}
    os.makedirs(os.path.dirname(_mac_plist(rotulo)), exist_ok=True)
    with open(_mac_plist(rotulo), "wb") as f:
        plistlib.dump(plist, f)
    _rodar(["launchctl", "bootstrap", f"gui/{uid}", _mac_plist(rotulo)])


def _mac_remover():
    rotulo = _mac_rotulo()
    _rodar(["launchctl", "bootout", f"gui/{os.getuid()}/{rotulo}"], checar=False)
    if os.path.exists(_mac_plist(rotulo)):
        os.remove(_mac_plist(rotulo))
    if os.path.isdir(APP):
        shutil.rmtree(APP)


# ---------------------------------------------------------------- Windows

TAREFA = "Pombo"


def _win_instalar():
    py = shutil.which("pythonw.exe") or sys.executable
    ps = f"""
$ErrorActionPreference = "Stop"
Unregister-ScheduledTask -TaskName "{TAREFA}" -Confirm:$false -ErrorAction SilentlyContinue
$a = New-ScheduledTaskAction -Execute "{py}" -Argument '"{SCRIPT}" rodar' -WorkingDirectory "{RAIZ}"
$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName "{TAREFA}" -Action $a -Trigger $t -Settings $s -Description "Pombo: bots do Telegram que rodam o Claude Code" | Out-Null
Start-ScheduledTask -TaskName "{TAREFA}"
"""
    _rodar(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps])


def _win_remover():
    _rodar(["powershell", "-NoProfile", "-Command",
            f'Unregister-ScheduledTask -TaskName "{TAREFA}" -Confirm:$false -ErrorAction SilentlyContinue'], checar=False)


# ---------------------------------------------------------------- comando `pombo` no PATH

LINK = os.path.expanduser("~/.local/bin/pombo")


def ligar_comando():
    """Põe o comando `pombo` em ~/.local/bin (Linux e Mac)."""
    if os.name == "nt":
        return
    os.chmod(SCRIPT, 0o755)
    os.makedirs(os.path.dirname(LINK), exist_ok=True)
    if os.path.islink(LINK) or os.path.exists(LINK):
        if os.path.realpath(LINK) == os.path.realpath(SCRIPT):
            return
        os.remove(LINK)
    os.symlink(SCRIPT, LINK)
    if os.path.dirname(LINK) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Aviso: {os.path.dirname(LINK)} não está no seu PATH. Acrescente para usar só `pombo`.")


def desligar_comando():
    if os.path.islink(LINK) and os.path.realpath(LINK) == os.path.realpath(SCRIPT):
        os.remove(LINK)


# ---------------------------------------------------------------- comum

def instalar():
    config.garantir_pastas()
    _aviso_claude()
    ligar_comando()
    if sys.platform.startswith("linux"):
        _linux_instalar()
    elif sys.platform == "darwin":
        _mac_instalar()
    elif os.name == "nt":
        _win_instalar()
    else:
        raise config.ErroConfig(f"sistema não suportado: {sys.platform}. Rode 'pombo rodar' do jeito que preferir.")
    time.sleep(4)
    from .registro import ler_log
    print(ler_log(None, 4), end="")
    print(f"Serviço instalado. Painel: http://127.0.0.1:{config.carregar_geral()['painel_porta']}")


def remover():
    if sys.platform.startswith("linux"):
        _linux_remover()
    elif sys.platform == "darwin":
        _mac_remover()
    elif os.name == "nt":
        _win_remover()
    desligar_comando()
    print("Serviço removido. A configuração continua em " + config.base())


def reiniciar():
    if sys.platform.startswith("linux"):
        _rodar(["systemctl", "--user", "restart", NOME])
    elif sys.platform == "darwin":
        _rodar(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{_mac_rotulo()}"])
    elif os.name == "nt":
        _rodar(["powershell", "-NoProfile", "-Command", f'Stop-ScheduledTask "{TAREFA}"; Start-ScheduledTask "{TAREFA}"'])
    print("Serviço reiniciado.")


def status():
    from .servico import pid_rodando
    pid = pid_rodando()
    print(f"Serviço: {'rodando (pid ' + str(pid) + ')' if pid else 'parado'}")
    if sys.platform.startswith("linux"):
        print(_rodar(["systemctl", "--user", "is-enabled", NOME], checar=False).stdout.strip() or "não instalado")


# ---------------------------------------------------------------- Tailscale

def _tailscale_nome():
    r = _rodar(["tailscale", "status", "--json"])
    return (json.loads(r.stdout).get("Self") or {}).get("DNSName", "").rstrip(".")


def publicar(porta_ts=10004):
    """Painel no celular: o Tailscale repassa https://<máquina>.<tailnet>.ts.net:<porta> para o painel local."""
    if not shutil.which("tailscale"):
        raise config.ErroConfig("o Tailscale não está instalado neste computador")
    g = config.carregar_geral()
    status = json.loads(_rodar(["tailscale", "serve", "status", "--json"]).stdout or "{}")
    for host, h in (status.get("Web") or {}).items():
        dono = ((h.get("Handlers") or {}).get("/") or {}).get("Proxy", "")
        if host.endswith(f":{porta_ts}") and dono and dono != f"http://127.0.0.1:{g['painel_porta']}":
            raise config.ErroConfig(f"a porta {porta_ts} do Tailscale já é de outro app ({dono}). Use --porta-tailscale.")
    _rodar(["tailscale", "serve", "--bg", f"--https={porta_ts}", f"http://127.0.0.1:{g['painel_porta']}"])
    host = f"{_tailscale_nome()}:{porta_ts}"
    if host not in g["hosts_permitidos"]:
        g["hosts_permitidos"].append(host)
        config.salvar_geral(g)
    print(f"Painel no celular: https://{host}  (só aparelhos da sua tailnet)")


def despublicar(porta_ts=10004):
    _rodar(["tailscale", "serve", f"--https={porta_ts}", "off"], checar=False)
    g = config.carregar_geral()
    g["hosts_permitidos"] = [h for h in g["hosts_permitidos"] if not h.endswith(f":{porta_ts}")]
    config.salvar_geral(g)
    print("Painel tirado do Tailscale.")


# ---------------------------------------------------------------- skill do Claude

def skill(remover=False):
    destino = os.path.expanduser("~/.claude/skills/pombo")
    origem = os.path.join(RAIZ, "skills", "pombo")
    if os.path.islink(destino) or os.path.isfile(destino):
        os.remove(destino)
    elif os.path.isdir(destino):
        shutil.rmtree(destino)
    if remover:
        print("Skill pombo removida.")
        return
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    try:
        os.symlink(origem, destino)
    except OSError:
        shutil.copytree(origem, destino)
    print(f"Skill instalada em {destino}. O Claude Code (inclusive dentro dos bots) já sabe configurar os bots.")
