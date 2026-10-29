const $ = (id) => document.getElementById(id);
const reactor = $("reactor");
const log = $("log");
let ws;
let userName = "sir";

/* ---------- clock ---------- */
function tick() {
  const now = new Date();
  $("time").textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  $("date").textContent = now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}
setInterval(tick, 1000);
tick();

/* ---------- reactor state ---------- */
const STATE_LABELS = { idle: "Standing by", thinking: "Processing", speaking: "Speaking", listening: "Listening", offline: "Offline" };
function setState(state) {
  reactor.className = `reactor ${state}`;
  $("state").textContent = STATE_LABELS[state];
}

/* ---------- system stats ---------- */
const CIRC = 213.6;
function setGauge(id, percent, label, invert = false) {
  const g = $(id);
  const value = percent ?? 0;
  g.querySelector(".value").style.strokeDashoffset = CIRC * (1 - value / 100);
  g.querySelector("b").textContent = percent == null ? "N/A" : label ?? `${Math.round(value)}%`;
  const level = invert ? 100 - value : value;
  g.classList.toggle("warn", percent != null && level >= 75 && level < 90);
  g.classList.toggle("crit", percent != null && level >= 90);
}
const fmtRate = (kbps) => (kbps >= 1024 ? `${(kbps / 1024).toFixed(1)} MB/s` : `${kbps.toFixed(0)} KB/s`);

async function refreshStats() {
  try {
    const s = await (await fetch("/api/stats")).json();
    if (s.cloud) {  // cloud mode: no laptop to report on
      document.body.classList.add("cloud");
      return clearInterval(statsTimer);
    }
    setGauge("g-cpu", s.cpu);
    setGauge("g-memory", s.memory);
    setGauge("g-disk", s.disk);
    setGauge("g-battery", s.battery, s.battery == null ? null : `${s.battery}%${s.charging ? "⚡" : ""}`, true);
    $("r-ram").textContent = `${s.memory_used_gb} / ${s.memory_total_gb} GB`;
    $("r-disk").textContent = `${s.disk_free_gb} GB`;
    $("r-down").textContent = fmtRate(s.net_down_kbps);
    $("r-up").textContent = fmtRate(s.net_up_kbps);
    $("r-uptime").textContent = `${s.uptime_hours} h`;
    $("procs").replaceChildren(...s.processes.map((p) => {
      const li = document.createElement("li");
      li.innerHTML = `<span></span><span>${p.mb} MB</span>`;
      li.firstChild.textContent = p.name;
      return li;
    }));
  } catch { /* server restarting; next tick retries */ }
}
const statsTimer = setInterval(refreshStats, 2000);
refreshStats();

/* ---------- memory ---------- */
async function refreshMemory() {
  try {
    const m = await (await fetch("/api/memory")).json();
    userName = m.user;
    const facts = m.facts.length ? m.facts : ["Nothing remembered yet."];
    $("facts").replaceChildren(...facts.map((f) => Object.assign(document.createElement("li"), { textContent: f })));
    const sums = m.summaries.slice().reverse();
    $("summaries").replaceChildren(...(sums.length ? sums.map((s) => {
      const li = document.createElement("li");
      const time = Object.assign(document.createElement("time"), { textContent: s.when });
      li.append(time, s.text);
      return li;
    }) : [Object.assign(document.createElement("li"), { textContent: "No past sessions yet.", className: "muted" })]));
  } catch { /* ignore */ }
}
setInterval(refreshMemory, 30000);
refreshMemory();

/* ---------- chat ---------- */
function addMessage(kind, text) {
  const div = document.createElement("div");
  div.className = `msg ${kind}`;
  div.textContent = text;
  log.append(div);
  log.scrollTop = log.scrollHeight;
}
function addActivity(name, args) {
  const list = $("activity");
  list.querySelector(".muted")?.remove();
  const li = document.createElement("li");
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  li.innerHTML = `${time} <b></b>`;
  li.querySelector("b").textContent = `${name}(${Object.values(args).map((v) => JSON.stringify(v)).join(", ")})`;
  list.prepend(li);
  while (list.children.length > 12) list.lastChild.remove();
}

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    $("link-dot").className = "dot on";
    $("link-text").textContent = "ONLINE";
    setState("idle");
    if (!log.children.length) {
      const hour = new Date().getHours();
      const part = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";
      addMessage("jarvis", `Good ${part}, ${userName}. All systems are online. How may I help?`);
    }
  };
  ws.onclose = () => {
    fetch("/api/stats").then((r) => r.status === 401 && location.assign("/login")).catch(() => {});
    $("link-dot").className = "dot off";
    $("link-text").textContent = "OFFLINE";
    setState("offline");
    setTimeout(connect, 2000);
  };
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "thinking") setState("thinking");
    else if (msg.type === "tool") {
      addMessage("tool", `⚙ ${msg.name}`);
      addActivity(msg.name, msg.args);
    } else if (msg.type === "reply") {
      $("model").textContent = msg.model;
      addMessage("jarvis", msg.text);
      (msg.images || []).forEach((id) => {
        const img = Object.assign(document.createElement("img"), { src: `/api/image/${id}`, alt: "Image made by JARVIS" });
        img.className = "msg-image";
        log.append(img);
        img.onload = () => { log.scrollTop = log.scrollHeight; };
      });
      speak(msg.text);
      refreshMemory();
    } else if (msg.type === "confirm") {
      askPermission(msg.text);
    } else if (msg.type === "error") {
      addMessage("error", msg.text);
      setState("idle");
    }
  };
}
connect();

/* ---------- permission prompts (risky actions need the user's own click) ---------- */
const dialog = $("confirm");
function answerPermission(approved) {
  if (!dialog.open) return;
  ws.send(JSON.stringify({ type: "confirm_reply", approved }));
  addMessage("tool", `${approved ? "✔ Allowed" : "✖ Denied"}: ${$("confirm-text").textContent}`);
  dialog.close();
}
function askPermission(text) {
  $("confirm-text").textContent = text;
  dialog.showModal();
  $("deny").focus();
  if (navigator.vibrate) navigator.vibrate(200);
}
$("allow").addEventListener("click", () => answerPermission(true));
$("deny").addEventListener("click", () => answerPermission(false));
dialog.addEventListener("cancel", (event) => { event.preventDefault(); answerPermission(false); });

$("form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("input").value.trim();
  if (!text || ws.readyState !== WebSocket.OPEN) return;
  addMessage("user", text);
  ws.send(JSON.stringify({ text }));
  $("input").value = "";
});

/* ---------- browser voice (optional) ---------- */
const speakToggle = $("speak");
try { speakToggle.checked = localStorage.getItem("jarvis-speak") === "1"; } catch {}
speakToggle.addEventListener("change", () => {
  try { localStorage.setItem("jarvis-speak", speakToggle.checked ? "1" : "0"); } catch {}
  if (!speakToggle.checked) speechSynthesis.cancel();
});

function speak(text) {
  if (!speakToggle.checked || !("speechSynthesis" in window)) return setState("idle");
  const utter = new SpeechSynthesisUtterance(text);
  const voices = speechSynthesis.getVoices();
  utter.voice = voices.find((v) => v.lang === "en-GB" && /male|ryan|george/i.test(v.name))
    || voices.find((v) => v.lang === "en-GB") || null;
  utter.rate = 1.02;
  utter.onstart = () => setState("speaking");
  utter.onend = () => setState("idle");
  speechSynthesis.speak(utter);
}

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!Recognition) {
  $("mic").hidden = true;
} else {
  const rec = new Recognition();
  rec.lang = "en-GB";
  rec.interimResults = true;
  let listening = false;
  rec.onresult = (event) => {
    const result = event.results[event.results.length - 1];
    $("input").value = result[0].transcript;
    if (result.isFinal) $("form").requestSubmit();
  };
  rec.onstart = () => { listening = true; $("mic").classList.add("active"); setState("listening"); };
  rec.onend = () => {
    listening = false;
    $("mic").classList.remove("active");
    if (reactor.classList.contains("listening")) setState("idle");
  };
  $("mic").addEventListener("click", () => (listening ? rec.stop() : rec.start()));
}
