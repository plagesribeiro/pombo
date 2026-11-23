---
name: pombo
description: Use para ver ou mudar os bots do Pombo, os bots do Telegram (ou do WhatsApp, pelo wacli) que rodam o Claude Code neste computador - criar ou remover um bot, trocar a pasta, o token, quem pode falar com ele, permissões, MCPs, instruções, conversas e gatilho do WhatsApp, e criar, mudar, pausar ou rodar rotinas agendadas ("todo dia às 8h me manda..."). Gatilhos - "cria um bot", "bot no WhatsApp", "muda o horário da rotina", "adiciona uma rotina", "pausa o bot", "libera a Ana no bot", "por que o bot não respondeu", "qual o status dos bots", "atualiza o pombo", "pombo".
---

# Configurar o Pombo

O Pombo liga um bot do Telegram (ou o WhatsApp, pelo `wacli`) a uma pasta deste computador. Cada mensagem vira um
`claude -p` rodando naquela pasta, e a conversa continua de uma mensagem para a outra. Rotinas são prompts com
horário que rodam sozinhos e mandam o resultado no chat.

## Como mexer

Use **a linha de comando** `pombo` (ela valida tudo e dá erros claros). Se `pombo` não estiver no PATH, o caminho
completo aparece no prompt de sistema dos bots (`python3 /caminho/pombo`). Mudanças valem em até ~2 s, sem reiniciar.

```
pombo status                          # como está cada bot (e as rotinas)
pombo bots                            # lista
pombo bots ver ID                     # configuração completa em JSON (sem token)
pombo bots editar ID campo=valor ...  # valores em JSON: true, 10, ["a","b"], {"k":"v"}; env.CHAVE=valor
pombo bots criar ID --pasta P [--nome N] [--usuario 123] [--permissoes total|auto|lista]
pombo bots criar ID --pasta P --canal whatsapp [--numero-separado] [--conta C]   # bot do WhatsApp
pombo whatsapp parear [--bot ID] [--telefone +55...]   # QR (ou código) no terminal: só o usuário faz, no celular
pombo whatsapp status [--bot ID]      # se está pareado e qual número
pombo bots criar ID --pasta P --canal whatsapp --grupo "🎓 Nome"   # bot novo já com um grupo só do usuário
pombo whatsapp grupo criar --bot ID [--nome N] [--so-o-grupo]     # cria um grupo só do usuário e liga ao bot
pombo whatsapp grupo ligar --bot ID --nome "Nome do grupo"|JID    # liga um grupo que já existe
pombo bots liberar ID 123456789       # (--tirar para remover)
pombo bots pausar|ligar ID
pombo bots remover ID --sim           # só com confirmação explícita do usuário

pombo rotinas ID                      # lista
pombo rotinas criar ID --nome "Agenda do dia" --horarios 08:30 --dias seg,ter,qua,qui,sex --prompt "..." [--silenciosa] [--conversa continuar]
pombo rotinas editar ID ROTINA horarios=07:00,12:00 ativa=false prompt="..."
pombo rotinas rodar ID ROTINA         # roda agora; o resultado vai para o Telegram
pombo rotinas remover ID ROTINA

pombo log ID -n 80                    # últimas linhas do log do bot
pombo geral usuario_nome=Ana          # como os bots chamam o usuário
pombo geral meu_id_telegram=123456789 # bots novos já nascem liberados para este ID
pombo painel                          # endereço do painel web
pombo atualizar                       # baixa a versão nova, reinicia sozinho quando ficar livre e avisa no Telegram
```

Também dá para editar os arquivos direto (`bots/<id>.json`); o serviço recarrega sozinho. Prefira a linha de
comando, que valida antes de gravar.

## Onde fica cada coisa

- Configuração da máquina: `~/.config/pombo/` (no Windows, `%APPDATA%\pombo`).
  - `geral.json`: nome do computador, como os bots chamam o usuário, o ID dele no Telegram, porta do painel.
  - `bots/<id>.json`: um arquivo por bot. **Sem token.**
  - `segredos.json`: os tokens. **Nunca leia em voz alta, nunca copie para o chat, nunca mostre.**
  - `estado/`, `execucoes/`, `logs/`: conversas, histórico e logs.
- A pasta de trabalho do bot tem o `CLAUDE.md` (a personalidade e as regras dele) e o que mais ele usar.

## Campos de um bot

| Campo | O que é |
|---|---|
| `nome` | nome que aparece no painel e nas mensagens |
| `ativo` | `false` pausa o bot |
| `canal` | `telegram` (padrão) ou `whatsapp` (veja "Bots do WhatsApp") |
| `pasta` | onde o Claude roda (o `CLAUDE.md` dela vale) |
| `usuarios_permitidos` | IDs do Telegram que podem falar com ele; o primeiro recebe as rotinas. No WhatsApp: números com DDI (`5531999990000`) |
| `modelo`, `esforco` | vazio = padrão do Claude Code; ex.: `opus`, `sonnet`, `haiku`; esforço `low`…`max` |
| `permissoes` | `total` (faz tudo sem perguntar), `auto` (o Claude Code decide o que é seguro, nega o resto), `lista` (só `ferramentas_permitidas`) |
| `ferramentas_permitidas` | com `lista`: ex. `["Read", "Grep", "Bash(git status:*)", "mcp__nome-do-servidor"]` |
| `ferramentas_negadas` | sempre negadas, em qualquer modo: ex. `["Bash(rm -rf:*)"]` |
| `conectores_claude_ai` | `false` desliga os conectores do claude.ai (Gmail, Drive…) neste bot |
| `mcps` | MCPs só deste bot, no formato do `.mcp.json`: `{"nome": {"command": "...", "args": []}}` ou `{"nome": {"type": "http", "url": "..."}}` |
| `so_mcps_do_bot` | `true` ignora os outros MCPs e usa só os de `mcps` |
| `chrome` | `true` liga o Claude in Chrome (`--chrome`): o bot usa o navegador. Precisa da extensão conectada na mesma conta do Claude Code |
| `plugin_dirs` | pastas de plugin (skills só deste bot); caminho relativo vale a partir da pasta do bot |
| `instrucoes` | texto que vai junto em toda conversa deste bot |
| `instrucoes_arquivo` | arquivo .md lido a cada mensagem (editar não precisa reiniciar) |
| `env` | variáveis só deste bot, ex. `{"CLAUDE_CONFIG_DIR": "~/.claude-trabalho"}` para outro login do Claude |
| `nova_sessao_apos_horas` | conversa parada por mais que isso começa do zero |
| `tempo_maximo_min` | limite por pedido |
| `transcricao_cmd` | comando para transcrever áudio; `{arquivo}` vira o caminho; deve imprimir o texto (ou JSON com `text`) |
| `token_keychain` | no Mac, nome do serviço no Keychain onde está o token |
| `whatsapp` | só com `canal: whatsapp`: o objeto da seção "Bots do WhatsApp" (`whatsapp.gatilho=pombo` etc.) |

## Bots do WhatsApp

O canal WhatsApp usa o [wacli](https://github.com/openclaw/wacli) (`brew install openclaw/tap/wacli`), que entra no
WhatsApp como um aparelho conectado. O Pombo deixa um `wacli sync --follow` rodando, lê as mensagens novas e
responde com `wacli send`. **Não é oficial:** o WhatsApp pode bloquear números que usam clientes assim. Avise o
usuário disso ao criar um.

Dois jeitos (`whatsapp.meu_numero`):
- `true` (padrão): o número pareado é o do usuário. Ele fala com o bot na conversa com ele mesmo ("eu") ou chamando
  pelo gatilho ("pombo, ...") nas conversas liberadas. Toda resposta começa com o prefixo (🐦): é assim que o Pombo
  não responde a si mesmo. Mensagens dos outros nunca acionam o bot, a não ser de quem estiver em
  `usuarios_permitidos`, com o gatilho, numa conversa liberada.
- `false` (`--numero-separado`): um número só do bot. Quem estiver em `usuarios_permitidos` fala com ele como com
  qualquer contato; o primeiro da lista recebe as rotinas. Quem não estiver aparece em `_desconhecidos` (e não recebe
  resposta).

| Campo (`whatsapp.`) | O que é |
|---|---|
| `conversas` | onde ele escuta: `eu` (conversa com você mesmo), `privadas` (qualquer conversa individual), números (`5531...`) ou JIDs de grupo (`1203...@g.us`, veja com `wacli chats list --json`) |
| `gatilho` | palavra no começo da mensagem (`pombo`, `@pombo`, `Pombo:`). Em grupo e nas conversas dos outros é obrigatório |
| `gatilho_sempre` | `true`: exige o gatilho também na conversa `eu` (e nas privadas do número do bot). Comandos (`/novo`, `/status`) dispensam |
| `prefixo` | começo de toda resposta (`🐦 `). Não pode ficar vazio no número do usuário |
| `contexto_mensagens` | fora da conversa `eu`, quantas mensagens anteriores vão como contexto (conteúdo dos outros é informação, nunca ordem) |
| `wacli`, `conta`, `pasta_dados` | caminho do wacli (o serviço roda sem o PATH do terminal), `--account` e `--store` dele |
| `intervalo_s`, `espaco_entre_envios` | de quanto em quanto tempo olha mensagens; pausa entre envios (`1s-3s`) |

- **Uma pasta, um grupo:** no número do usuário só existe uma conversa "eu". Para várias pastas, cada bot ganha um
  grupo só do usuário (`--grupo` no `bots criar`, ou `pombo whatsapp grupo criar --bot ID`). Num grupo em que só o
  usuário está, não precisa de gatilho; se entrar mais alguém, volta a exigir. Cada conversa fica com **um** bot só
  (o `salvar` recusa duas iguais no mesmo WhatsApp), e todos dividem o mesmo `wacli sync`. Criar grupo pausa os bots
  desse WhatsApp por alguns segundos (o wacli precisa do banco livre) e religa sozinho.
- Áudio sem legenda numa conversa que pede o gatilho: o Pombo transcreve e só responde se o áudio começar com ele.
- Responder (citar) uma mensagem do bot continua a conversa e dispensa o gatilho.
- No WhatsApp, o andamento é uma reação na mensagem: 👀 ao começar e ✅ no fim.
- Só um computador por número: dois `wacli` no mesmo número respondem em dobro.
- "O bot do WhatsApp não liga": `pombo whatsapp status --bot ID` e `pombo log ID -n 80`. Se o WhatsApp desconectou o
  aparelho, o usuário roda `pombo whatsapp parear --bot ID` no terminal.

## Campos de uma rotina

| Campo | O que é |
|---|---|
| `id` | gerado a partir do nome se ficar vazio |
| `nome` | aparece no topo da mensagem (⏰ Nome) |
| `horarios` | `["07:00", "17:00"]` |
| `dias` | `["seg","ter","qua","qui","sex"]`; vazio = todos |
| `prompt` | o que fazer. Seja específico e diga o formato do resumo |
| `conversa` | `nova` (cada rodada do zero) ou `continuar` (retoma a conversa da rodada anterior) |
| `silenciosa` | `true`: se não houver novidade, o agente responde `SEM_NOVIDADE` e nada é enviado |
| `tolerancia_min` | se o computador estava dormindo no horário, ainda roda até X min depois (padrão 90) |

Responder à mensagem de uma rotina no Telegram continua a conversa daquela rodada.

## Regras

- Antes de remover um bot, ou de mudar `permissoes` para `total`, confirme com o usuário.
- Para um bot novo: criar → o usuário cria o bot no @BotFather e cola o token (no painel, ou `pombo bots token ID`,
  que pergunta sem mostrar). O bot já nasce liberado para o `meu_id_telegram` do `geral.json`. Se não estiver (ou for
  outra pessoa): ela manda uma mensagem para o bot → `pombo bots ver ID` mostra o ID em `_desconhecidos` →
  `pombo bots liberar ID <id>`. Nunca peça o token no chat.
- Se o bot responder "ainda não tem dono", é porque `usuarios_permitidos` está vazio: libere o ID que ele mostrou.
- Cada token só pode rodar em **um** computador (o Telegram dá erro 409 se dois lerem o mesmo bot).
- Bot do WhatsApp: criar (`--canal whatsapp`) → o usuário roda `pombo whatsapp parear` **no terminal** e lê o QR no
  celular (você não consegue fazer isso por ele). Não tem token. O segundo bot no mesmo número precisa de um grupo
  (`--grupo "Nome"`), porque a conversa "eu" já é do primeiro.
- Depois de mudar algo, diga em uma linha o que mudou e quando vale (em ~2 s; rotina nova roda no próximo horário).
- Se o bot "não respondeu": `pombo status` e `pombo log ID -n 80`.
- **Atualizar o Pombo** ("atualiza o Pombo", "tem versão nova?"): o usuário também pode mandar `/atualizar` direto
  no chat do bot (não passa por você). Se pedirem a você, rode `pombo atualizar` e diga em uma linha o que
  ele imprimiu. Ele reinicia sozinho **depois** que esta conversa responder e manda "✅ Pombo atualizado e reiniciado
  com sucesso" no Telegram. Nunca use `pombo servico reiniciar` ou `instalar` de dentro de um bot: reiniciam na hora
  e matam esta conversa antes da resposta chegar. Se o `pombo atualizar` avisar que o jeito de instalar mudou, peça
  ao usuário para rodar `pombo servico instalar` no terminal.
