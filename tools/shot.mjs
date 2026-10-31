// 用 CDP 驱动 headless Chrome：打开聊天页 → 发一条触发工具的问题 → 截图
// Chrome 必须在这个进程内启动，否则工具调用返回后会被回收
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PORT = 9400 + Math.floor(Math.random() * 400);
const WORK = path.join(os.tmpdir(), "wb-cdp-" + Date.now());
const OUT = process.argv[2] || "shot.png";
const QUESTION = process.argv[3] || "订单 1001 的物流到哪了";
const WAIT_MS = Number(process.argv[4] || 25000);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(url, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return await r.json();
    } catch (_) {}
    await sleep(250);
  }
  throw new Error("CDP 端点未就绪: " + url);
}

(async () => {
  fs.mkdirSync(WORK, { recursive: true });
  const chrome = spawn(
    CHROME,
    [
      "--headless=new",
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${WORK}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--no-proxy-server",
      "--disable-gpu",
      "--window-size=1000,900",
      "about:blank",
    ],
    { stdio: "ignore", detached: false }
  );

  try {
    const targets = await fetchJson(`http://127.0.0.1:${PORT}/json/list`);
    const page = targets.find((t) => t.type === "page");
    if (!page) throw new Error("没有找到 page target");

    const ws = new WebSocket(page.webSocketDebuggerUrl);
    let id = 0;
    const pending = new Map();

    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg);
        pending.delete(msg.id);
      }
    });

    const send = (method, params = {}) =>
      new Promise((resolve, reject) => {
        const mid = ++id;
        pending.set(mid, (m) => (m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result)));
        ws.send(JSON.stringify({ id: mid, method, params }));
      });

    await new Promise((r) => ws.addEventListener("open", r, { once: true }));

    await send("Page.enable");
    await send("Runtime.enable");
    await send("Page.navigate", { url: "http://127.0.0.1:8000/" });
    await sleep(2500);

    // 填入问题并点发送
    const fill = await send("Runtime.evaluate", {
      expression: `
        (() => {
          const i = document.getElementById('input');
          const b = document.getElementById('send');
          if (!i || !b) return 'no-controls';
          i.value = ${JSON.stringify(QUESTION)};
          i.dispatchEvent(new Event('input', { bubbles: true }));
          b.click();
          return 'sent';
        })()
      `,
      returnByValue: true,
    });
    if (fill.result.value !== "sent") throw new Error("发送失败: " + fill.result.value);

    // 等流式结束：轮询 busy 状态
    const deadline = Date.now() + WAIT_MS;
    let done = false;
    while (Date.now() < deadline) {
      await sleep(800);
      const st = await send("Runtime.evaluate", {
        expression: `({ busy: document.getElementById('send').disabled,
                       badges: document.querySelectorAll('.badge').length,
                       text: (document.querySelector('.row.bot .bubble')||{}).textContent || '' })`,
        returnByValue: true,
      });
      const v = st.result.value;
      if (!v.busy && v.text.length > 0) {
        done = true;
        console.log("徽章数:", v.badges);
        console.log("回答:", v.text.slice(0, 120));
        break;
      }
    }
    if (!done) console.log("⚠ 等待超时，仍截图");

    await sleep(600);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
    console.log("截图已保存:", OUT);
    ws.close();
  } finally {
    try { chrome.kill(); } catch (_) {}
  }
})().catch((e) => {
  console.error("失败:", e.message);
  process.exit(1);
});
