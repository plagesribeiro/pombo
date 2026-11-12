# Como contribuir

Obrigado por querer ajudar o Pombo! Toda ajuda conta: contar um problema, sugerir uma ideia, melhorar o texto ou
mandar código.

## Contar um problema ou dar uma ideia

Abra uma [issue](https://github.com/plagesribeiro/pombo/issues/new/choose). Para problemas, mande:

- o sistema (Mac, Linux ou Windows) e a versão do Python;
- o que você fez, o que esperava e o que aconteceu;
- as últimas linhas de `pombo log ID -n 40`.

**Nunca cole o token do bot, IDs do Telegram ou conteúdo pessoal.** Apague esses trechos do log antes de mandar.

Falha de segurança não vai em issue pública: veja o [SECURITY.md](SECURITY.md).

## Mandar código

1. Faça um fork e crie um branch a partir do `main`.
2. Leia o [CLAUDE.md](CLAUDE.md): ele explica a estrutura do código e as regras. As principais:
   - só a biblioteca padrão do Python, compatível com a 3.8;
   - o token nunca aparece em arquivo de bot, log, painel ou chat;
   - todo campo novo de configuração passa por `config.validar_bot`;
   - textos para o usuário em português simples;
   - nada pessoal no código ou nos exemplos (use "Ana", `~/trabalho`).
3. Rode os testes:

   ```bash
   python3 -m unittest discover -s tests -p "test_unidade.py"         # rápido, sem rede
   POMBO_E2E=1 python3 -m unittest tests.test_ponta_a_ponta -v        # opcional: Claude de verdade + Telegram falso
   ```

   Use `POMBO_DIR=/outra/pasta` para testar sem mexer na sua configuração.
4. Abra o pull request explicando o que muda e por quê. Mudança grande? Abra uma issue antes para conversar.

Usar o Claude Code para contribuir é bem-vindo: o `CLAUDE.md` já é o guia dele.

## Ideias em aberto

- aprovar ações pelo celular, com botões no Telegram;
- retomar um pedido interrompido por um reinício;
- outros agentes, como o Codex;
- outros canais, como o WhatsApp;
- interface em inglês.

## Convivência

Seja gentil e respeitoso. Este projeto segue o [Código de Conduta](CODE_OF_CONDUCT.md).

---

**English:** issues and pull requests in English are welcome too. Read [CLAUDE.md](CLAUDE.md) for the code rules
(stdlib only, Python 3.8, never log tokens) and run `python3 -m unittest discover -s tests -p "test_unidade.py"`.
