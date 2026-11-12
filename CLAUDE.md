# Pombo

Um bot do Telegram por pasta, rodando o Claude Code (`claude -p`) no computador do usuário. Um serviço único liga
todos os bots, com rotinas agendadas, painel web e linha de comando. Python 3.8+ só com a biblioteca padrão.

Notas da sua instalação (máquinas, pendências) ficam no `CLAUDE.local.md`, que não vai para o Git.

## Estrutura

- `pombo`: entrada (`pombo --help`). Sem argumentos e sem terminal, roda o serviço (é o que o app do Mac faz).
- `src/pombo/config.py`: caminhos, leitura/gravação e **validação** da configuração (todo campo novo passa por aqui).
- `src/pombo/execucao.py`: um bot rodando (`BotRunner`): escuta o Telegram, fila, roda o agente, responde, rotinas.
- `src/pombo/motores.py`: monta o comando do `claude -p` (permissões, MCPs, plugins, env). Outro motor (Codex) entra aqui.
- `src/pombo/servico.py`: liga/desliga bots conforme os arquivos (recarrega a cada 2 s) e o agendador (a cada 20 s).
- `src/pombo/rotinas.py`: quando uma rotina deve rodar (funções puras, testadas).
- `src/pombo/painel.py` + `painel.html`: painel web (127.0.0.1) e a API que ele usa.
- `src/pombo/cli.py`: linha de comando. `src/pombo/instalar.py`: systemd/launchd/Windows, comando no PATH, Tailscale e skill.
- `src/pombo/migrar.py`: converte a configuração da versão antiga (um bot só) para `bots/<id>.json`.
- `skills/pombo/`: skill que ensina o Claude a configurar (instalada com `pombo skill instalar`).
- `mac/lancador.c`: lançador do app no Mac (para o macOS dar acesso a Documentos uma vez só).
- `tests/`: unidade (rápidos) e ponta a ponta (`telegram_falso.py` simula a API do Telegram).

## Regras

- Nada de dependência externa: só biblioteca padrão, compatível com Python 3.8 (o Mac usa `/usr/bin/python3`).
- Token nunca vai para `bots/*.json`, log, API do painel ou chat: só `segredos.json` (600), Keychain ou variável.
- Toda mudança de configuração passa por `config.validar_bot`, que dá mensagem clara em português.
- Painel: só 127.0.0.1, confere o `Host` e exige o cabeçalho `X-Pombo: 1` em toda mudança.
- Textos para o usuário em português simples (painel, Telegram, erros).
- Nada pessoal no repositório (nomes, IDs, endereços, caminhos de máquinas): exemplos genéricos ("Ana", "~/trabalho").
- Mudou algo? Rode os testes:
  - `python3 -m unittest discover -s tests -p "test_unidade.py"`
  - `POMBO_E2E=1 python3 -m unittest tests.test_ponta_a_ponta -v` (Claude de verdade com haiku + Telegram falso)
- Depois de mudar o código, `pombo servico reiniciar` (no Mac, `pombo servico instalar` de novo, porque o código vai
  copiado para dentro do app). Reiniciar interrompe um pedido em andamento: confira com `pombo status` antes.
