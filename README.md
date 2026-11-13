# Sêneca

Um assistente pessoal que roda inteiramente sobre o [Claude Code](https://claude.com/claude-code) — não existe um
"motor" separado: a personalidade, a memória e as ferramentas são tudo arquivos de texto nesta pasta. Tem voz (atalho
ou palavra de ativação, Whisper local), um painel web local (tarefas, agenda, memória, delegar trabalho longo em
segundo plano) e lê o que você conectar no Claude Code (Notion, Google Agenda etc.).

Windows apenas (bandeja, atalhos de teclado, caminhos). Feito para ser **adaptado**: fork, configure os pontos abaixo
com os seus dados e o Sêneca passa a falar com você, não com quem o escreveu.

## Pré-requisitos
- [Claude Code](https://claude.com/claude-code), com uma assinatura Claude ativa. Só funciona com Claude — veja
  "Importante" mais abaixo.
- Windows 10/11, Python 3.12+ e [Node.js](https://nodejs.org) 18+ instalados (o instalador abaixo confere isso).

## Instalação (um comando)
```bash
git clone https://github.com/<seu-usuario>/seneca.git
cd seneca
```
Depois, dê **duplo-clique em `Instalar.bat`** (ou rode `scripts/instalar.ps1`). Ele confere Python e Node, cria o
ambiente (`uv` se tiver, senão `venv`/`pip`), roda `npm install`, pergunta seu nome, apelido, cidade e a pasta onde
ficam seus projetos — e já deixa tudo escrito em `memoria/perfil.md` e `app/config.json` por você. No fim, oferece
pra abrir o Sêneca.

Se ainda não entrou no Claude Code nesta máquina, rode `claude` (ou `npx claude`) uma vez dentro da pasta e faça
login com a sua conta — é a única parte que o instalador não faz por você.

Vozes locais (Piper, offline) são opcionais — sem elas o Sêneca usa vozes online (edge-tts) normalmente:
```bash
powershell -File scripts/baixar-vozes.ps1
```

## Importante: só funciona com Claude
O Sêneca é construído em cima do Claude Code (`CLAUDE.md`, os skills em `.claude/skills/`, os subagentes em
`.claude/agents/` e o cérebro em `app/cerebro.mjs` usam o [Claude Agent SDK](https://www.npmjs.com/package/@anthropic-ai/claude-agent-sdk)
diretamente). Hoje **não dá pra trocar por Codex, Llama ou outro modelo** sem reescrever essa camada inteira — não é
uma chave de configuração, é arquitetura. Se você quiser outro motor de IA, esse é um projeto à parte.

## Ajustando depois (sem o instalador)
O instalador cobre o essencial, mas estes pontos continuam editáveis a qualquer momento:

| Onde | Para quê |
|---|---|
| `memoria/perfil.md` | nome, apelido, cidade, fuso horário (criado pelo instalador; `*.exemplo.md` é o modelo) |
| `app/config.json` → `nome` | como ele te chama na notificação de boas-vindas |
| `app/config.json` → `cidade_clima` | cidade usada no clima do painel e em `scripts/clima.ps1` |
| `app/config.json` → `workspace` | pasta onde ficam seus projetos |
| `app/config.json` → `notion_banco` | nome do seu banco de tarefas no Notion (vazio = "Development Tracker") |
| `app/config.json` → `notion_eu` | seu nome na conta do Notion, para o filtro "Só minhas" em Tarefas |
| [.claude/settings.json](.claude/settings.json) → `additionalDirectories` | precisa bater com `workspace` acima |
| `config/elevenlabs.json` (opcional) | chave da ElevenLabs, para voz premium — copie de `config/elevenlabs.exemplo.json` |
| `scripts/abrir.ps1`, `scripts/fechar.ps1`, `app/rapido.py` (`SITES`) | apelidos de apps e sites — os de exemplo são meus hábitos, troque pelos seus |

Conectores (Notion, Google Agenda etc.) são ligados no próprio Claude Code; o Sêneca só lê o que você conectar.
Depois de conectar, volte em `memoria/perfil.md` e `app/config.json` com o nome do banco/conta.

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
