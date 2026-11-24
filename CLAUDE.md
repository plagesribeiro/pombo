# Pombo

Um bot do Telegram (ou do WhatsApp, pelo `wacli`) por pasta, rodando o Claude Code (`claude -p`) no computador do
usuário. Um serviço único liga todos os bots, com rotinas agendadas, painel web e linha de comando. Python 3.8+ só
com a biblioteca padrão.

Notas da sua instalação (máquinas, pendências) ficam no `CLAUDE.local.md`, que não vai para o Git.

## Estrutura

- `pombo`: entrada (`pombo --help`). Sem argumentos e sem terminal, roda o serviço (é o que o app do Mac faz).
- `src/pombo/config.py`: caminhos, leitura/gravação e **validação** da configuração (todo campo novo passa por aqui).
- `src/pombo/execucao.py`: um bot rodando (`BotRunner`): fila, roda o agente, responde, rotinas. Fala com o canal do
  bot (`canal`), que recebe e manda as mensagens; as mensagens chegam num formato só (`CanalTelegram.normalizar`).
- `src/pombo/telegram.py`: cliente da API do Telegram e `CanalTelegram` (getUpdates, andamento editando a mensagem).
- `src/pombo/whatsapp.py`: `CanalWhatsApp`, pelo programa `wacli` (github.com/openclaw/wacli): `Sincronizador` deixa
  o `wacli sync --follow` rodando, o diário `messages changes` faz o papel do offset, e `avaliar` decide o que é para o
  bot (conversa, quem mandou, gatilho ou menção, prefixo das próprias respostas). Um número a mais (o de um bot) fica
  em `~/.wacli-NOME` (`--store`); `numeros_locais` lista os números do computador e `Pareamento` pareia pelo painel.
- `src/pombo/motores.py`: monta o comando do `claude -p` (permissões, MCPs, plugins, env). Outro motor (Codex) entra aqui.
- `src/pombo/servico.py`: liga/desliga bots conforme os arquivos (recarrega a cada 2 s) e o agendador (a cada 20 s).
- `src/pombo/rotinas.py`: quando uma rotina deve rodar (funções puras, testadas).
- `src/pombo/painel.py` + `painel.html`: painel web (127.0.0.1) e a API que ele usa.
- `src/pombo/cli.py`: linha de comando. `src/pombo/instalar.py`: systemd/launchd/Windows, comando no PATH, Tailscale e skill.
- `src/pombo/atualizar.py`: `pombo atualizar` (git pull + aviso em `atualizacao.json`); o serviço reinicia a si mesmo
  quando nenhum bot está ocupado (`os.execv`; no Windows sai com código 75 e a tarefa religa) e avisa no Telegram.
- Vários computadores no mesmo WhatsApp (`geral.outros_computadores`, em `whatsapp.py`): cada um pergunta ao painel
  dos outros (`GET /api/whatsapp/computador`) quais bots estão ligados lá e guarda em `estado/_outros_computadores.json`;
  `liberacao`, `_de_outro_bot` e `_numeros_de_bot` levam isso em conta.
- `src/pombo/migrar.py`: converte a configuração da versão antiga (um bot só) para `bots/<id>.json`.
- `INSTALAR.md`: roteiro que o Claude Code segue para instalar o Pombo (o prompt do README aponta para ele).
  Mudou a instalação, um comando ou um campo usado lá? Atualize o roteiro junto.
- `skills/pombo/`: skill que ensina o Claude a configurar (instalada com `pombo skill instalar`).
- `mac/lancador.c`: lançador do app no Mac (para o macOS dar acesso a Documentos uma vez só).
- `tests/`: unidade (rápidos) e ponta a ponta (`telegram_falso.py` simula a API do Telegram e `wacli_falso.py`, o
  programa `wacli`).

## Regras

- Nada de dependência externa: só biblioteca padrão, compatível com Python 3.8 (o Mac usa `/usr/bin/python3`).
- Token nunca vai para `bots/*.json`, log, API do painel ou chat: só `segredos.json` (600), Keychain ou variável.
- Canal novo: implemente a mesma interface do `CanalTelegram` (ouvir, responder, aviso, enviar_arquivo, andamento,
  baixar, chat_do_dono, eh_dono, parar) e registre em `execucao.criar_canal` e `config.CANAIS`.
- Toda mudança de configuração passa por `config.validar_bot`, que dá mensagem clara em português.
- Painel: só 127.0.0.1, confere o `Host` e exige o cabeçalho `X-Pombo: 1` em toda mudança.
- Textos para o usuário em português simples (painel, Telegram, erros).
- Nada pessoal no repositório (nomes, IDs, endereços, caminhos de máquinas): exemplos genéricos ("Ana", "~/trabalho").
- Mudou algo? Rode os testes:
  - `python3 -m unittest discover -s tests -p "test_unidade.py"`
  - `POMBO_E2E=1 python3 -m unittest tests.test_ponta_a_ponta -v` (Claude de verdade com haiku + Telegram falso)
- Para colocar código novo no ar (seu ou de um `git pull`): `pombo atualizar` (ou `pombo atualizar --sem-baixar` para
  um código que você mudou aqui). Ele copia o código para o app no Mac, espera os bots ficarem parados, reinicia e
  avisa no Telegram. Atualizar sem reiniciar não adianta. `pombo servico reiniciar`/`instalar` reiniciam na hora e
  matam o pedido em andamento, inclusive a conversa de onde foram chamados: só pelo terminal.
