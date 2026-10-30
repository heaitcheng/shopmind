#!/usr/bin/env node
// Context7 MCP 直连小工具
// 用途：本会话里 Context7 MCP 未注册为工具，直接走它的 HTTP(streamable) 端点调用
// 用法：
//   node tools/ctx7.mjs list
//   node tools/ctx7.mjs resolve "langchain" ["<想查什么>"]
//   node tools/ctx7.mjs docs <libraryId> "<查询问题>" [语言]

const ENDPOINT = "https://mcp.context7.com/mcp";
const API_KEY = process.env.CONTEXT7_API_KEY ||
  "ctx7sk-37986855-df3d-4e5a-83e6-edba97c6d7cc";

let sessionId = null;
let rpcId = 0;

async function rpc(method, params) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
    Authorization: `Bearer ${API_KEY}`,
  };
  if (sessionId) headers["MCP-Session-Id"] = sessionId;

  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers,
    body: JSON.stringify({ jsonrpc: "2.0", id: ++rpcId, method, params }),
  });

  const sid = res.headers.get("mcp-session-id");
  if (sid) sessionId = sid;

  const text = await res.text();
  // SSE: 取最后一条 data: 行
  const lines = text.split(/\r?\n/).filter((l) => l.startsWith("data:"));
  const payload = lines.length ? lines[lines.length - 1].slice(5).trim() : text.trim();
  const parsed = JSON.parse(payload);
  if (parsed.error) throw new Error(JSON.stringify(parsed.error));
  return parsed.result;
}

async function init() {
  await rpc("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "shopmind-dev", version: "1.0" },
  });
  // 某些实现要求 initialize 后发 notifications/initialized（无 id，无需等响应）
  await fetch(ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
      Authorization: `Bearer ${API_KEY}`,
      "MCP-Session-Id": sessionId,
    },
    body: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
  }).catch(() => {});
}

async function callTool(name, args) {
  const r = await rpc("tools/call", { name, arguments: args });
  return r.content.map((c) => c.text ?? "").join("\n");
}

const [cmd, ...rest] = process.argv.slice(2);

await init();

if (cmd === "list") {
  const r = await rpc("tools/list", {});
  for (const t of r.tools) console.log(`${t.name}\n  ${(t.description || "").slice(0, 120)}`);
} else if (cmd === "resolve") {
  const [libraryName, query = libraryName] = rest;
  console.log(await callTool("resolve-library-id", { libraryName, query }));
} else if (cmd === "docs") {
  const [libraryId, query, language] = rest;
  console.log(
    await callTool("query-docs", {
      libraryId,
      query,
      ...(language ? { language } : {}),
    })
  );
} else {
  console.error("用法: node tools/ctx7.mjs list | resolve <name> [query] | docs <libId> <query> [language]");
  process.exit(1);
}
