---
name: briefing
description: Briefing matinal do Sêneca — agenda, tarefas, e-mails, projetos e prioridades do dia. Use quando a pessoa disser "bom dia", "briefing" ou "o que tenho pra hoje".
---

# Briefing do dia

Monte um briefing curto e elegante, em português, no tom sereno e estoico do Sêneca.

## Coleta
1. Data/hora atual e dia da semana.
2. `memoria/tarefas.md`: tarefas de "Hoje" e atrasadas.
3. Diário de ontem em `memoria/diario/` (pendências que ficaram).
4. `memoria/objetivos.md`: lembre de 1 objetivo relevante.
5. `memoria/projetos.md`: status dos projetos ativos. Se algum tiver repositório git, rode `git -C <caminho> log --oneline -5` e `git -C <caminho> status -s` para ver o que mudou.
6. **Se estiverem conectados:** Google Agenda (eventos de hoje) e Gmail (não lidos importantes). Se não estiverem, pule sem reclamar.
7. Clima (opcional): busca rápida do tempo na cidade da pessoa, se ela estiver em `perfil.md`.

## Formato
```
Bom dia[, nome]. Hoje é <dia>, <data>.

📅 Agenda: ...
✅ Prioridades (máx. 3): ...
📬 E-mails que pedem atenção: ...
💻 Projetos: ...
⚠️ Pendências de ontem: ...
```
Use o nome (de `memoria/perfil.md`) só se fizer sentido, não em toda frase. Termine com **uma frase curta** (ela é lida em voz alta), por exemplo: "Três prioridades hoje. Comecemos pela primeira: X."

## Depois
Crie (ou complete) `memoria/diario/<hoje>.md` com a seção "Plano do dia".
