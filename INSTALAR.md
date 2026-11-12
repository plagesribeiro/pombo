# Instalar o Pombo (roteiro para o Claude Code)

> **Para quem está lendo:** este arquivo é o roteiro que o Claude Code segue quando você cola o prompt de instalação
> do [README](README.md#instalar-com-o-claude-em-1-minuto). Você não precisa ler: o Claude faz os passos e só para
> quando precisar de você (criar o bot no Telegram, colar o token, mandar um "oi").

**Claude, o seu objetivo:** deixar o Pombo instalado e rodando neste computador, com um primeiro bot do Telegram
ligado a uma pasta e respondendo à pessoa. Siga os passos em ordem. Fale em português simples, explique em uma frase
o que cada passo faz e pare para pedir só o que depende da pessoa. Não pule a verificação no final.

## Regras

- **Pergunte antes** de: instalar programas (Python, Git), escolher a pasta do bot e escolher o modo de permissão.
- **O token do Telegram é uma senha.** Nunca escreva o token em arquivo, log ou comando que fique no histórico. Grave
  com `pombo bots token ID -` lendo da entrada padrão (veja o passo 6). Não repita o token na resposta.
- Se algo falhar, leia a mensagem de erro, rode `pombo status` e `pombo log ID -n 40`, e consulte "Problemas comuns"
  no [README](README.md#problemas-comuns) antes de tentar de novo.
- No **Windows**, troque `pombo ...` por `python pombo ...` dentro da pasta do repositório, até o passo 3 criar o
  comando.

## 1. Conferir o que é preciso

Rode e confira:

- `python3 --version` (Windows: `python --version`): precisa ser 3.8 ou mais novo.
- `git --version`.
- `claude --version`: o Claude Code precisa estar instalado e **logado** no terminal (é o login que os bots usam).
  Se você está rodando dentro do Claude Code, ele já está.

Se faltar Python ou Git, diga como instalar (Mac: `xcode-select --install`; Linux: o gerenciador de pacotes; Windows:
[python.org](https://www.python.org) e [git-scm.com](https://git-scm.com)) e pergunte se pode instalar.

## 2. Baixar o Pombo

Se o repositório ainda não estiver aqui:

```bash
git clone https://github.com/plagesribeiro/pombo.git ~/pombo
cd ~/pombo
```

Se a pessoa já clonou em outro lugar, use essa pasta. **Não mova a pasta depois de instalar**: o serviço aponta
para ela.

## 3. Ligar o serviço e ensinar o Claude

```bash
python3 pombo servico instalar
python3 pombo skill instalar
```

- O primeiro deixa o Pombo rodando sozinho e ligando junto com o computador, e cria o comando `pombo` em
  `~/.local/bin`. Se `pombo` não for encontrado depois, use `~/.local/bin/pombo` ou `python3 ~/pombo/pombo`.
- O segundo instala a skill `pombo` no Claude Code, para a pessoa poder pedir mudanças em português depois
  ("cria uma rotina às 8h que...").
- **Mac:** avise que, se a pasta do bot ficar em Documentos, Mesa ou Downloads, ela vai precisar liberar o
  **Acesso Total ao Disco** para `~/Applications/Pombo.app` (Ajustes do Sistema → Privacidade e Segurança → Acesso
  Total ao Disco → **+**). Uma pasta fora delas (ex.: `~/pessoal`) não precisa disso.
- **Linux:** se `loginctl show-user $USER -p Linger` disser `Linger=no`, sugira
  `sudo loginctl enable-linger $USER`, para o bot continuar rodando quando ela sair da sessão.

Depois, `pombo status` deve dizer `Serviço: ligado`.

## 4. Perguntar o nome e a pasta

Pergunte, numa mensagem só:

1. Como os bots devem chamar a pessoa (ex.: "Ana").
2. Em qual pasta o primeiro bot vai trabalhar. Sugira criar `~/pessoal` (um `CLAUDE.md` lá dentro vira a memória do
   bot). Pode ser uma pasta que já existe.
3. O modo de permissão. Explique em uma linha cada: `auto` (recomendado: o Claude Code decide o que é seguro e nega
   o arriscado), `total` (faz tudo sem perguntar; só para pasta e ferramentas de total confiança), `lista` (só as
   ferramentas liberadas).

Então:

```bash
pombo geral usuario_nome="Ana"
mkdir -p ~/pessoal
pombo bots criar pessoal --pasta ~/pessoal --nome "Pessoal" --permissoes auto
```

## 5. Criar o bot no Telegram (a pessoa faz)

Mande este passo a passo:

1. No Telegram, abra o **[@BotFather](https://t.me/BotFather)** e mande `/newbot`.
2. Escolha um nome de exibição (ex.: *Meu Pombo*) e um nome de usuário que termine em `bot`
   (ex.: `ana_pombo_bot`).
3. O BotFather responde com um **token**, parecido com `123456789:AAH...`. Ele é uma senha.

Ofereça dois jeitos de entregar o token e espere a resposta:

- **Mais simples:** colar o token aqui na conversa.
- **Mais reservado:** rodar ela mesma, no terminal, `pombo bots token pessoal` e colar lá (não aparece na tela).

## 6. Gravar o token

Se ela colou o token na conversa, grave lendo da entrada padrão, sem deixar o token na linha de comando:

```bash
pombo bots token pessoal - <<'FIM'
COLE_O_TOKEN_AQUI
FIM
```

Em poucos segundos o bot liga. Confira com `pombo status` (o bot deve aparecer como `ligado`). Se aparecer erro 401,
o token está errado: peça de novo.

## 7. Liberar a pessoa

1. Peça para ela abrir o bot no Telegram (o link é `https://t.me/<nome_de_usuario_do_bot>`) e mandar **"oi"**.
   Como ninguém foi liberado ainda, o bot responde com o ID do Telegram dela.
2. Rode `pombo bots ver pessoal --json` e procure em `_desconhecidos` a pessoa que acabou de escrever (`nome`,
   `username`, `texto`). Confirme com ela que é ela.
3. Libere e guarde o ID para os próximos bots já nascerem liberados:

```bash
pombo bots liberar pessoal ID_DO_TELEGRAM
pombo geral meu_id_telegram=ID_DO_TELEGRAM
```

## 8. Verificar e entregar

1. Peça para ela mandar **"oi"** de novo. O Claude deve responder no Telegram em alguns segundos. Se não responder,
   veja `pombo log pessoal -n 40`.
2. Rode `pombo painel` e passe o endereço (normalmente <http://127.0.0.1:47940>).
3. Termine com um resumo curto:
   - o bot, a pasta e o modo de permissão;
   - comandos do Telegram: `/novo` (conversa do zero), `/parar`, `/status`, `/rotinas`, `/atualizar`;
   - que dá para pedir ao Claude, em qualquer sessão: *"cria uma rotina no bot pessoal todo dia às 8h que me manda
     a agenda"*;
   - que o computador precisa estar ligado e acordado para o bot responder;
   - onde dar retorno: [issues do Pombo](https://github.com/plagesribeiro/pombo/issues).
