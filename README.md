# Sêneca

Um assistente pessoal que roda inteiramente sobre o [Claude Code](https://claude.com/claude-code) — não existe um
"motor" separado: a personalidade, a memória e as ferramentas são tudo arquivos de texto nesta pasta. Tem voz (atalho
ou palavra de ativação, Whisper local), um painel web local (tarefas, agenda, memória, delegar trabalho longo em
segundo plano) e lê o que você conectar no Claude Code (Notion, Google Agenda etc.).

Windows apenas (bandeja, atalhos de teclado, caminhos). Feito para ser **adaptado**: fork, configure os pontos abaixo
com os seus dados e o Sêneca passa a falar com você, não com quem o escreveu.

## Pré-requisitos
- [Claude Code](https://claude.com/claude-code) com uma assinatura ativa, autenticado nesta máquina.
- Windows 10/11, Python 3.12+, [Node.js](https://nodejs.org) 18+.
- [uv](https://docs.astral.sh/uv/) (recomendado) para o ambiente Python: `winget install astral-sh.uv`.

## Instalação
```bash
git clone https://github.com/<seu-usuario>/seneca.git
cd seneca
uv venv
uv pip install -r requirements.txt
```
```bash
cd app && npm install
```

Vozes locais (Piper, offline) são opcionais — sem elas o Sêneca usa vozes online (edge-tts) normalmente:
```bash
powershell -File scripts/baixar-vozes.ps1
```

## Adapte para você
Nada aqui tem seu nome, sua cidade ou suas contas: é tudo configuração, nos lugares abaixo.

1. **Quem é você.** Copie cada `memoria/*.exemplo.md` para o mesmo nome sem `.exemplo` (ex.: `memoria/perfil.exemplo.md`
   → `memoria/perfil.md`) e preencha nome, apelido, cidade e fuso horário em `memoria/perfil.md`. Esses arquivos ficam
   só na sua máquina (estão no `.gitignore`).
2. **`app/config.json`** — é criado automaticamente na primeira vez que o Sêneca liga, com os padrões de
   `app/bandeja.py` (`PADRAO`). Edite (ou peça ao Sêneca para editar) os campos que fizerem sentido:
   | Campo | Para quê |
   |---|---|
   | `nome` | como ele te chama na notificação de boas-vindas |
   | `cidade_clima` | cidade usada no clima do painel e em `scripts/clima.ps1` |
   | `workspace` | pasta onde ficam seus projetos (vazio = a pasta acima desta) |
   | `notion_banco` | nome do seu banco de tarefas no Notion (vazio = "Development Tracker") |
   | `notion_eu` | seu nome na conta do Notion, para o filtro "Só minhas" em Tarefas |
3. **Pasta de projetos.** Ajuste `additionalDirectories` em [.claude/settings.json](.claude/settings.json) para a
   mesma pasta que você colocou em `workspace` — é o que dá ao Claude Code permissão de editar arquivos fora desta
   pasta.
4. **Conectores.** Notion, Google Agenda etc. são conectados no próprio Claude Code (não há chave de API aqui para
   isso); o Sêneca só lê o que você conectar. Depois de conectar, edite `memoria/perfil.md` e `app/config.json` com o
   nome do banco/conta.
5. **Vozes online** já funcionam sem configurar nada (edge-tts, grátis). Para ElevenLabs (opcional, pago): copie
   `config/elevenlabs.exemplo.json` para `config/elevenlabs.json` e cole sua chave — este arquivo também fica de fora
   do git.
6. **Apelidos de apps e sites.** `scripts/abrir.ps1`, `scripts/fechar.ps1` e `app/rapido.py` (dicionário `SITES`) têm
   alguns apelidos de exemplo (navegador, vscode, lol…) — edite à vontade para os seus.

## Como usar
Depois de configurado, veja [LEIA-ME.md](LEIA-ME.md): atalho de voz, palavra de ativação, cores da bandeja, o painel e
como criar tarefas em segundo plano.

## Segurança
- `config/elevenlabs.json`, `app/config.json`, `.claude/settings.local.json` e tudo em `memoria/` (exceto os
  `.exemplo.md`) ficam fora do git por padrão — confira o `.gitignore` antes de publicar um fork.
- O Sêneca não cria, edita nem apaga nada no Notion; não envia e-mail ou mensagens; nunca apaga arquivos dos seus
  projetos; só faz `git commit/push/pull` ou instala programas quando você pede explicitamente. Veja `CLAUDE.md` e
  `.claude/settings.json` para a lista completa de permissões e bloqueios.
- Revise sempre o que vai no `git add` antes de um commit, principalmente se você criou novos arquivos de
  configuração.

## Licença
[MIT](LICENSE).
