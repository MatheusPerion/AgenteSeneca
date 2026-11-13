# Sêneca

O Sêneca é o Claude Code rodando na sua assinatura, como assistente pessoal. Esta pasta contém tudo: personalidade, memória, ferramentas, voz e painel.
Primeira vez aqui? Veja [README.md](README.md) para instalar e adaptar o projeto para você.

## Como usar
- **Programa "Sêneca"** (área de trabalho e menu Iniciar): abre o Centro de Comando e liga a voz.
- **Liga sozinho com o Windows** (voz e bandeja, sem abrir janela). Para desligar isso: Gerenciador de Tarefas → Aplicativos de inicialização.
- **Voz:** segure o Ctrl direito, fale e solte.
- **Trocar a voz:** clique no microfone da lateral. Perfis em `app\vozes.py`; vozes locais (Piper) em `app\vozes\`.
- **Atualizar:** Núcleo de IA → "Atualizar o Sêneca" religa com o código novo, e a janela se recarrega sozinha.
- **Escrevendo:** seção Conversas do painel, ou uma sessão do Claude aberta nesta pasta.
- **Tarefas:** "Sêneca, crie uma tarefa para...". Enquanto roda, aparece ao vivo na barra lateral do app do Claude como "Sêneca · ..." (somente leitura); relatório em `tarefas\` e aviso por voz no fim. Depois de terminar, "Abrir no Claude" importa a sessão. Importar enquanto roda congela a cópia, por isso o painel só faz isso no fim.

## Pastas
| Caminho | O que é |
|---|---|
| `CLAUDE.md` | Personalidade e instruções do Sêneca |
| `.claude\settings.json` | Permissões (permitido, bloqueado, pastas liberadas), agentes e habilidades |
| `memoria\` | Cofre Obsidian |
| `tarefas\` | Relatórios das tarefas |
| `scripts\` | Mãos no computador: abrir, pesquisar, fechar, clima, tarefa |
| `app\` | Bandeja, painel, ligação com o Claude e dados |

## Como funciona
A bandeja (`app\bandeja.py`) ouve e transcreve (Whisper na placa de vídeo). Comandos simples de abrir e pesquisar rodam na hora (`app\rapido.py`).
O resto vai para uma sessão contínua do Claude Code (`app\cerebro.py` + `cerebro.mjs`), que já fica aberta e lembra da conversa.
Depois de 8 horas parada, ela começa uma conversa nova. Em "Abrir conversa no Claude" dá para ver essa sessão no app.

## Limites
Bloqueados em `.claude\settings.json`: `git push --force`, apagar arquivos, `taskkill` e WhatsApp. O Notion é só leitura.
Commit, push, pull e instalação de programas (pelo winget) acontecem só quando você pede.
Tarefas em segundo plano não conseguem alterar `.claude\`.

Dados de execução: `app\dados\` e `app\log.txt`.
