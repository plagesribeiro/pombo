# Segurança

O Pombo roda o Claude Code no seu computador e guarda tokens de bots do Telegram, então falhas de segurança importam.

## Como relatar

**Não abra uma issue pública.** Use o
[relato privado do GitHub](https://github.com/plagesribeiro/pombo/security/advisories/new) e conte:

- o que a falha permite (ex.: alguém não liberado fazer o bot rodar algo, o token vazar, o painel aceitar pedidos de
  fora);
- como reproduzir;
- a versão (`git log --oneline -1`) e o sistema.

A resposta vem em até 7 dias. A correção sai o quanto antes, e você recebe o crédito se quiser.

## O que é esperado (não é falha)

- Um bot no modo `total` faz qualquer coisa que o seu usuário faz no computador: é o que esse modo promete.
- Um bot que lê conteúdo de terceiros (e-mails, páginas) pode sofrer *prompt injection*. O Pombo reduz o risco, mas
  não elimina. Prefira os modos `auto` ou `lista` nesses bots.
