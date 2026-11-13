# Contribuindo

PRs de features, correções e melhorias são bem-vindos. Algumas coisas para manter em mente:

## Nada pessoal no commit
Seus dados (nome, cidade, chaves de API, pasta de projetos) ficam em arquivos que o `.gitignore` já exclui:
`memoria/*.md` (menos os `*.exemplo.md`), `app/config.json`, `config/elevenlabs.json`,
`.claude/settings.local.json`, `app/dados/`, `tarefas/*`, `.venv/`, `app/node_modules/`.

Antes de `git add`, dê uma olhada em `git status` — se aparecer algum desses (ou qualquer arquivo com seu nome,
e-mail ou caminho de pasta), é sinal de que ele não deveria estar ali. Se você criar um novo tipo de arquivo que
guarda dado pessoal, adicione o padrão correspondente ao `.gitignore` no mesmo PR.

## Onde mexer para adicionar uma feature
- **Personalidade/instruções:** `CLAUDE.md`, `.claude/skills/`, `.claude/agents/`.
- **Voz e bandeja:** `app/bandeja.py`, `app/vozes.py`, `app/rapido.py`.
- **Painel web:** `app/painel.py` (servidor) e `app/painel.html` (interface, tudo numa página só).
- **Funções que o painel e os fluxos usam:** `app/recursos.py`.
- **Ligação com o Claude:** `app/cerebro.py` (processo) e `app/cerebro.mjs` (SDK).

Se a feature depender de algo específico de quem está usando (nome de conta, nome de banco no Notion, caminho de
pasta…), siga o padrão já usado: um campo novo em `app/config.json` (com valor padrão vazio ou genérico, nunca um
valor seu), não um texto fixo no código.

## Lembre que isso roda em cima do Claude Code
Não é um app genérico de IA — ele usa o Claude Agent SDK, skills e subagentes do Claude Code diretamente. Se a sua
ideia depende de outro motor de IA, veja a seção "Importante" do [README.md](README.md) antes de começar.

## Testando
Não há suíte de testes automatizados ainda. Pelo menos: rode `python -m py_compile` nos arquivos `.py` que você
mexeu, `node --check` nos `.mjs`, e, se puder, abra o Sêneca (`Instalar.bat` ou `pythonw app/seneca_app.pyw`) pra
ver que a parte que você mudou ainda funciona.
