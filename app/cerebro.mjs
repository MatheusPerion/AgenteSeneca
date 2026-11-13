/**
 * Ligação entre a bandeja e o Claude: uma sessão contínua do Claude Code.
 *
 * Normal:   recebe uma linha JSON por pedido no stdin ({"id","prompt"}) e devolve {"id","ok","resposta","sessao"}.
 * --unico:  recebe o pedido inteiro no stdin, responde e sai (consultas internas do painel).
 * --uso:    grava em dados/uso.json o quanto da assinatura já foi usado e sai.
 * O que o Claude faz é registrado ao vivo em dados/atividade.jsonl, que o painel lê.
 */
import { query } from "@anthropic-ai/claude-agent-sdk";
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const APP = dirname(fileURLToPath(import.meta.url));
const RAIZ = dirname(APP);
const DADOS = join(APP, "dados");

function registrar(run, tipo, dados = {}) {
  try {
    mkdirSync(DADOS, { recursive: true });
    appendFileSync(join(DADOS, "atividade.jsonl"), JSON.stringify({ run, t: Date.now() / 1000, tipo, ...dados }) + "\n", "utf8");
  } catch {
    /* o painel é opcional */
  }
}

const curto = (v, n = 400) => {
  const s = typeof v === "string" ? v : JSON.stringify(v ?? "");
  return s.length > n ? s.slice(0, n) + "…" : s;
};

function permissoes() {
  // settings.json é compartilhado (vai pro git); settings.local.json é de cada um (additionalDirectories, por exemplo).
  const base = JSON.parse(readFileSync(join(RAIZ, ".claude", "settings.json"), "utf8")).permissions;
  let local = {};
  try { local = JSON.parse(readFileSync(join(RAIZ, ".claude", "settings.local.json"), "utf8")).permissions || {}; } catch { /* opcional */ }
  return {
    allow: base.allow,
    deny: base.deny,
    additionalDirectories: local.additionalDirectories || base.additionalDirectories || [],
  };
}

function opcoes() {
  const { allow, deny, additionalDirectories } = permissoes();
  return {
    cwd: RAIZ,
    settingSources: ["user", "project", "local"],
    systemPrompt: { type: "preset", preset: "claude_code" },
    permissionMode: "acceptEdits", // edita só dentro das pastas liberadas
    allowedTools: allow,
    disallowedTools: deny,
    additionalDirectories,
  };
}

function acompanhar(run, message) {
  const blocos = Array.isArray(message.message?.content) ? message.message.content : [];
  if (message.type === "assistant") {
    for (const b of blocos) {
      if (b.type === "text") registrar(run, "texto", { texto: curto(b.text, 800) });
      else if (b.type === "tool_use") registrar(run, "ferramenta", { id: b.id, nome: b.name, entrada: curto(b.input, 3000) });
    }
  } else if (message.type === "user") {
    for (const b of blocos) {
      if (b.type === "tool_result") registrar(run, "resultado", { id: b.tool_use_id, ok: !b.is_error, saida: curto(b.content, 300) });
    }
  }
}

function concluir(run, message) {
  const ok = message.subtype === "success" && !message.is_error;
  const resposta = ok ? message.result || "" : message.result || message.errors?.join("\n") || "O Claude não conseguiu responder.";
  registrar(run, "fim", { ok, resposta: curto(resposta, 1500) });
  return { id: run, ok, resposta, sessao: message.session_id };
}

// --uso: grava em dados/uso.json quanto da assinatura já foi usado (janelas de 5h e 7 dias) e sai.
// Não envia nenhum pedido ao modelo, então não gasta limite. A API do SDK é experimental e pode mudar.
async function soUso() {
  async function* semPedidos() {
    await new Promise(() => {}); // mantém a entrada aberta sem mandar nada
  }
  const consulta = query({ prompt: semPedidos(), options: { cwd: RAIZ, settingSources: [] } });
  const u = await consulta.usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET();
  if (!u?.rate_limits_available || !u.rate_limits) throw new Error("limites da assinatura indisponíveis");
  mkdirSync(DADOS, { recursive: true });
  writeFileSync(join(DADOS, "uso.json"), JSON.stringify({
    atualizado: Date.now() / 1000,
    assinatura: u.subscription_type,
    cinco_horas: u.rate_limits.five_hour ?? null,
    sete_dias: u.rate_limits.seven_day ?? null,
  }), "utf8");
  process.exit(0);
}

async function unico() {
  let prompt = "";
  process.stdin.setEncoding("utf-8");
  for await (const parte of process.stdin) prompt += parte;
  const run = randomUUID().slice(0, 8);
  registrar(run, "inicio", { pedido: curto(prompt, 600) });
  for await (const message of query({ prompt, options: opcoes() })) {
    acompanhar(run, message);
    if (message.type === "result") {
      console.log(JSON.stringify(concluir(run, message)));
      await new Promise((pronto) => process.stdout.write("", pronto));
      process.exit(0);
    }
  }
}

async function continuo() {
  const sessao = process.env.SENECA_SESSAO;
  const options = { ...opcoes(), ...(process.env.SENECA_RETOMAR === "1" ? { resume: sessao } : { sessionId: sessao }) };
  let atual = "";

  async function* pedidos() {
    for await (const linha of createInterface({ input: process.stdin })) {
      if (!linha.trim()) continue;
      const pedido = JSON.parse(linha);
      atual = pedido.id;
      registrar(atual, "inicio", { pedido: curto(pedido.prompt, 600) });
      yield { type: "user", session_id: sessao, parent_tool_use_id: null, message: { role: "user", content: pedido.prompt } };
    }
    process.exit(0); // a bandeja fechou
  }

  for await (const message of query({ prompt: pedidos(), options })) {
    acompanhar(atual, message);
    if (message.type === "result") console.log(JSON.stringify(concluir(atual, message)));
  }
}

try {
  await (process.argv.includes("--uso") ? soUso() : process.argv.includes("--unico") ? unico() : continuo());
} catch (erro) {
  console.error(erro);
  process.exit(1);
}
