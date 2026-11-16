"use strict";
const $ = (id) => document.getElementById(id);
const phaseNames = {preparing: "準備中", active: "作答中", results: "結果"};
let auth = null, activityId = null, current = null, generation = 0;
let refreshPromise = null, connected = true, cardsKey = "", lastMonitor = "", lastResults = "", lastList = "";
const pendingAnswers = new Set();
let sheetPreview = null, lastGoogleCheck = 0;
try { auth = JSON.parse(sessionStorage.getItem("classroom.auth")); activityId = sessionStorage.getItem("classroom.activity"); } catch { sessionStorage.clear(); }

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function notice(message, success = false) {
  $("notice").textContent = message;
  $("notice").className = success ? "success" : "";
  $("notice").hidden = !message;
}
function connection(ok) {
  connected = ok;
  $("connection").textContent = !auth ? "本機課堂" : ok ? "已連線 · 自動同步" : "連線中斷 · 正在重試";
  $("connection").classList.toggle("offline", !ok);
}
async function api(path, data, token = auth?.token) {
  const headers = {"Content-Type": "application/json"};
  if (token) headers.Authorization = "Bearer " + token;
  let response;
  try {
    response = await fetch(path, {method: data === undefined ? "GET" : "POST", headers,
      body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(path.startsWith("/api/sheets/") || path.endsWith("/export") ? 45000 : 5000)});
  } catch { throw Object.assign(new Error("暫時無法連線，請確認服務仍在執行。"), {network: true}); }
  const payload = await response.json();
  if (!response.ok) throw Object.assign(new Error(payload.error || "操作失敗。"), {status: response.status});
  return payload;
}
function showView() {
  $("entry").hidden = !!auth;
  $("dashboard").hidden = !auth || auth.role !== "teacher" || !!activityId;
  $("activity").hidden = !auth || !activityId || !current;
  $("logout").hidden = !auth;
  $("back").hidden = auth?.role !== "teacher";
}
function saveAuth(value) {
  generation++;
  auth = value; activityId = value?.activity_id || null; current = null;
  cardsKey = lastMonitor = lastResults = lastList = "";
  sheetPreview = null; lastGoogleCheck = 0;
  $("sheet-preview").hidden = $("google-auth-link").hidden = true;
  sessionStorage.removeItem("classroom.activity");
  if (value) sessionStorage.setItem("classroom.auth", JSON.stringify(value));
  else sessionStorage.removeItem("classroom.auth");
  if (activityId) sessionStorage.setItem("classroom.activity", activityId);
  showView(); connection(true);
}
function selectActivity(id) {
  generation++; activityId = id; current = null; cardsKey = lastMonitor = lastResults = "";
  if (id) sessionStorage.setItem("classroom.activity", id); else sessionStorage.removeItem("classroom.activity");
  showView(); notice(""); refresh();
}
async function action(button, fn) {
  if (button.classList.contains("busy")) return;
  button.classList.add("busy"); button.disabled = true; notice("");
  try { await fn(); }
  catch (error) { notice(error.message); if (error.network) connection(false); }
  finally { button.classList.remove("busy"); button.disabled = false; if (current) updateInputs(); }
}
function role(isTeacher) {
  $("login-form").hidden = !isTeacher; $("join-form").hidden = isTeacher;
  $("choose-teacher").setAttribute("aria-pressed", String(isTeacher));
  $("choose-student").setAttribute("aria-pressed", String(!isTeacher)); notice("");
}
$("choose-teacher").onclick = () => role(true);
$("choose-student").onclick = () => role(false);
$("login-form").onsubmit = (event) => {
  event.preventDefault(); action(event.submitter, async () => {
    const result = await api("/api/teacher/login", {password: $("teacher-password").value});
    $("teacher-password").value = ""; saveAuth(result); await refresh();
  });
};
$("join-form").onsubmit = (event) => {
  event.preventDefault(); action(event.submitter, async () => {
    saveAuth(await api("/api/join", {code: $("join-code").value, group: $("join-group").value})); await refresh();
  });
};
$("create-form").onsubmit = (event) => {
  event.preventDefault(); action(event.submitter, async () => {
    const data = await api("/api/activities", {title: $("activity-title").value,
      questions: $("question-numbers").value.trim().split(/\r?\n/)});
    $("create-form").reset(); selectActivity(data.id); await refresh();
  });
};
$("logout").onclick = () => action($("logout"), async () => {await api("/api/logout", {}); saveAuth(null);});
$("back").onclick = () => selectActivity(null);
async function googleStatus() {
  const ownGeneration = generation;
  const status = await api("/api/google/status");
  if (ownGeneration !== generation) return;
  $("google-status").textContent = status.connected ? "Google 已連線" : status.configured ? "設定已就緒，請連線 Google" : "尚未設定 Google，公開學習單仍可預覽與匯入";
  $("google-connect").hidden = status.connected;
  $("google-disconnect").hidden = !status.connected;
  if (status.connected) $("google-auth-link").hidden = true;
}
$("google-connect").onclick = () => action($("google-connect"), async () => {
  const result = await api("/api/google/connect", {});
  $("google-auth-link").href = result.url; $("google-auth-link").hidden = false;
  notice("請點選「開啟 Google 授權頁」，使用 Chrome 或 Edge 完成授權，再回到此分頁。", true);
});
$("google-disconnect").onclick = () => action($("google-disconnect"), async () => {
  await api("/api/google/disconnect", {}); $("google-auth-link").hidden = true; await googleStatus();
});
$("sheet-url").oninput = () => {
  sheetPreview = null; $("sheet-preview").hidden = $("worksheet-field").hidden = true;
};
$("sheet-worksheet").onchange = () => {sheetPreview = null; $("sheet-preview").hidden = true;};
$("sheet-preview-form").onsubmit = (event) => {
  event.preventDefault(); action(event.submitter, async () => {
    sheetPreview = null; $("sheet-preview").hidden = true;
    const ownGeneration = generation, url = $("sheet-url").value;
    const worksheet = $("worksheet-field").hidden ? undefined : $("sheet-worksheet").value;
    const result = await api("/api/sheets/preview", {url, worksheet});
    if (ownGeneration !== generation || url !== $("sheet-url").value) return;
    if (result.needs_selection) {
      $("sheet-worksheet").replaceChildren(...result.worksheets.map(title => {const option = el("option", title); option.value = title; return option;}));
      $("worksheet-field").hidden = false; notice("請選擇工作表，再按一次讀取預覽。", true); return;
    }
    sheetPreview = result;
    $("sheet-preview-title").textContent = `${result.sheet_title} · 共 ${result.count} 題`;
    $("sheet-preview-warning").textContent = result.official_template ? "這是官方原始範本，可用於試讀。若要寫回答案，請先建立自己的副本並重新匯入。" : "請核對題號及答案格。確認後會重新檢查來源，再建立活動。";
    const table = el("table"), head = el("tr"), body = el("tbody"), thead = el("thead");
    head.append(el("th", "題號"), el("th", "答案儲存格")); thead.append(head);
    for (const target of result.targets) {const row = el("tr"); row.append(el("td", target.question), el("td", target.cell)); body.append(row);}
    table.append(thead, body); $("sheet-preview-table").replaceChildren(table);
    $("sheet-activity-title").value = result.sheet_title + "・課堂搶答";
    $("sheet-preview").hidden = false;
  });
};
$("sheet-import").onclick = () => action($("sheet-import"), async () => {
  if (!sheetPreview) throw new Error("請先讀取預覽。");
  const ownGeneration = generation;
  const result = await api("/api/sheets/import", {preview_id: sheetPreview.preview_id, title: $("sheet-activity-title").value});
  if (ownGeneration !== generation) return;
  sheetPreview = null; $("sheet-preview").hidden = true; selectActivity(result.id); await refresh();
});
$("sheet-export").onclick = () => action($("sheet-export"), async () => {
  const result = await api(`/api/activities/${activityId}/export`, {}); notice(result.message, true); await refresh();
});
for (const kind of ["start", "end"]) $(kind).onclick = () => action($(kind), async () => {
  await api(`/api/activities/${activityId}/${kind}`, {}); await refresh();
});

function timeText(seconds) { return new Date(seconds * 1000).toLocaleTimeString("zh-TW", {hour12:false}); }
async function downloadFile(path, filename) {
  const response = await fetch(path, {headers:{Authorization:`Bearer ${auth.token}`}});
  if (!response.ok) throw new Error((await response.json()).error || "下載失敗。");
  const url = URL.createObjectURL(await response.blob()), link = el("a");
  link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("download-csv").onclick = () => action($("download-csv"), () => downloadFile(`/api/activities/${activityId}/csv`, "課堂搶答結果.csv"));
$("settings-form").onsubmit = event => {
  event.preventDefault(); action(event.submitter, async () => {
    await api(`/api/activities/${activityId}/settings`, {mode:$("quiz-mode").value, fairness:$("quiz-fairness").checked});
    notice("活動規則已儲存。", true); await refresh();
  });
};
$("quiz-mode").onchange = () => {if ($("quiz-mode").value === "all") $("quiz-fairness").checked = false;};
for (const [id, kind] of [["close-round","close"],["next-round","next"]]) $(id).onclick = () => action($(id), async () => {
  await api(`/api/activities/${activityId}/round`, {action:kind}); await refresh();
});
function renderList(items) {
  const key = JSON.stringify(items); if (lastList === key) return; lastList = key;
  $("activity-count").textContent = items.length;
  $("activity-list").replaceChildren();
  if (!items.length) $("activity-list").append(el("p", "還沒有活動。\n從左側建立你的第一場課堂搶答。", "empty"));
  for (const item of items) {
    const button = el("button", undefined, "activity-card");
    const info = el("div"); info.append(el("strong", item.title), el("small", `代碼 ${item.code} · ${new Date(item.created_at * 1000).toLocaleDateString("zh-TW")}`));
    button.append(info, el("span", phaseNames[item.phase], "phase-pill " + item.phase));
    button.onclick = () => selectActivity(item.id); $("activity-list").append(button);
  }
}
function renderCards(state) {
  const key = JSON.stringify([state.id, state.questions]);
  if (cardsKey === key) return;
  cardsKey = key; $("student-questions").replaceChildren();
  state.questions.forEach((q, i) => {
    const card = el("form", undefined, "question-card"); card.dataset.question = q;
    const top = el("div", undefined, "question-top"); top.append(el("h3", `第 ${q} 題`), el("span", "尚未送出", "question-status"));
    const label = el("label", "本組答案"); label.htmlFor = "answer-" + i;
    const input = el("textarea"); input.id = label.htmlFor; input.maxLength = 2000; input.required = true; input.placeholder = "和組員討論後，在這裡寫下答案…";
    const saved = el("p", undefined, "saved-answer"); saved.hidden = true;
    const time = el("p", undefined, "answer-time"); time.hidden = true;
    const button = el("button", "送出本組答案 →", "primary wide"); button.type = "submit";
    card.append(top, label, input, saved, time, button);
    card.onsubmit = (event) => {
      event.preventDefault(); const requestActivity = activityId;
      action(button, async () => {
        pendingAnswers.add(q); updateInputs();
        try { await api(`/api/activities/${requestActivity}/answers`, {question:q, answer:input.value}); notice(`第 ${q} 題已送出。`, true); }
        finally { pendingAnswers.delete(q); await refresh(); }
      });
    };
    $("student-questions").append(card);
  });
}
function updateInputs() {
  if (!current) return;
  $("start").disabled = !connected || $("start").classList.contains("busy");
  $("end").disabled = !connected || $("end").classList.contains("busy");
  if (current.role !== "student") return;
  const answers = new Map(current.answers.map(a => [a.question_id, a]));
  for (const card of $("student-questions").children) {
    const answer = answers.get(card.dataset.question), input = card.querySelector("textarea"), button = card.querySelector("button");
    const disabled = !!answer || !connected || current.phase !== "active" || !current.available_questions.includes(card.dataset.question) || pendingAnswers.has(card.dataset.question);
    input.disabled = disabled; button.disabled = disabled;
    card.classList.toggle("sent", !!answer);
    card.querySelector(".question-status").textContent = answer ? "✓ 已送出" : "尚未送出";
    input.hidden = !!answer; button.hidden = !!answer;
    card.querySelector("label").hidden = !!answer;
    const saved = card.querySelector(".saved-answer"), time = card.querySelector(".answer-time");
    saved.hidden = time.hidden = !answer;
    if (answer) { saved.textContent = answer.text; time.textContent = `已於 ${timeText(answer.received_at)} 送出 · 開始後 ${(answer.elapsed_ms / 1000).toFixed(3)} 秒`; }
  }
}
function renderMonitor(state) {
  const key = JSON.stringify([state.groups, state.answers, state.questions]);
  if (lastMonitor === key) return; lastMonitor = key;
  $("monitor-summary").textContent = `${state.groups.length} 個小組已加入 · ${state.questions.length} 題 · 已收到 ${state.answers.length} 份答案`;
  const wrap = $("monitor-table"); wrap.replaceChildren();
  if (!state.groups.length) {wrap.append(el("p", "等待同學加入。分享左側活動代碼，開始今天的討論。", "empty")); return;}
  const table = el("table"), thead = el("thead"), head = el("tr");
  head.append(el("th", "小組")); for (const q of state.questions) head.append(el("th", `第 ${q} 題`)); thead.append(head);
  const body = el("tbody");
  const lookup = new Map(state.answers.map(a => [JSON.stringify([a.group_id,a.question_id]), a]));
  for (const group of state.groups) {
    const row = el("tr"); row.append(el("th", group.name));
    for (const q of state.questions) {
      const cell = el("td"), answer = lookup.get(JSON.stringify([group.id,q]));
      if (answer) cell.append(el("span", answer.text, "cell-answer"), el("small", `${timeText(answer.received_at)} · ${(answer.elapsed_ms / 1000).toFixed(3)} 秒`));
      else cell.append(el("span", "尚未送出", "unsent"));
      row.append(cell);
    }
    body.append(row);
  }
  table.append(thead, body); wrap.append(table);
}
function renderResults(state) {
  const key = JSON.stringify(state.results); if (lastResults === key) return; lastResults = key;
  const list = el("div", undefined, "results-list");
  for (const result of state.results) {
    const row = el("div", undefined, "result-row"), detail = el("div");
    row.append(el("span", `第 ${result.question_id} 題`, "result-number"));
    detail.append(el("div", result.winner ? `${result.winner.group_name} · 搶答成功` : "無人作答", "winner"));
    if (result.winner) detail.append(el("p", result.winner.text, "result-answer"));
    row.append(detail); list.append(row);
  }
  $("results").replaceChildren(list);
}
let replayKey = "", replayFrame = 0, replayElapsed = 0, replayLast = 0, replayRunning = false;
function resetReplay() {
  cancelAnimationFrame(replayFrame); replayRunning = false; replayElapsed = 0;
  $("replay-play").textContent = "播放"; $("replay-answers").replaceChildren();
  $("replay-status").textContent = "準備播放";
}
function replayTick(now) {
  if (!replayRunning) return;
  replayElapsed += now - replayLast; replayLast = now;
  const answers = current.answers.filter(a => a.question_id === $("replay-question").value);
  // Keep the immutable receipt ordering; cap long gaps for classroom playback.
  let due = 0, previous = 0, shown = 0;
  for (const answer of answers) {
    due += Math.max(400, Math.min(1500, answer.elapsed_ms - previous)); previous = answer.elapsed_ms;
    if (replayElapsed < due) break;
    shown++;
    if ($("replay-answers").children.length < shown)
      $("replay-answers").append(el("li", `${answer.group_name}：${answer.text} · ${(answer.elapsed_ms/1000).toFixed(3)} 秒`));
  }
  if (shown === answers.length) {
    replayRunning = false; $("replay-play").textContent = "播放";
    const winner = current.results.find(r => r.question_id === $("replay-question").value)?.winner;
    $("replay-status").textContent = winner ? `播放完成 · 目前成功組別：${winner.group_name}` : "播放完成 · 無成功組別";
  } else { $("replay-status").textContent = `已播放 ${shown} / ${answers.length} 筆`; replayFrame = requestAnimationFrame(replayTick); }
}
function playReplay() {
  if (replayRunning) {replayRunning = false; cancelAnimationFrame(replayFrame); $("replay-play").textContent = "繼續播放"; return;}
  replayRunning = true; replayLast = performance.now(); $("replay-play").textContent = "暫停";
  replayFrame = requestAnimationFrame(replayTick);
}
$("replay-play").onclick = playReplay;
$("replay-reset").onclick = () => {resetReplay(); playReplay();};
$("replay-question").onchange = resetReplay;
function renderReplay(state) {
  const enabled = state.role === "teacher" && state.phase === "results";
  $("replay").hidden = !enabled;
  const key = enabled ? JSON.stringify([state.id, state.answers, state.results]) : "";
  if (key === replayKey) return;
  replayKey = key; resetReplay();
  if (enabled) $("replay-question").replaceChildren(...state.questions.map(q => {const option = el("option", `第 ${q} 題`); option.value = q; return option;}));
}
function renderState(state) {
  current = state;
  renderReplay(state);
  showView();
  const teacher = state.role === "teacher", ended = state.phase === "results";
  $("session-title").textContent = state.title;
  $("session-code").textContent = state.code;
  $("session-subtitle").textContent = teacher ? `${state.questions.length} 道題目 · 掌握每一組的思考` : `${state.group_name} · ${state.questions.length} 道題目，一起完成`;
  $("role-badge").textContent = teacher ? "教師" : state.group_name;
  $("teacher-controls").hidden = !teacher || ended;
  $("start").hidden = state.phase !== "preparing";
  $("end").hidden = state.phase !== "active";
  $("phase-label").textContent = phaseNames[state.phase]; $("phase-label").className = "phase-pill " + state.phase;
  for (const step of document.querySelectorAll(".phase-steps li")) {
    step.classList.toggle("current", step.dataset.phase === state.phase);
    if (step.dataset.phase === state.phase) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current");
  }
  $("session-rule").textContent = teacher ? "每組每題以第一筆有效答案為準。作答中請勿向學生投影此頁，以免公開他組答案。" : "每題由小組共同送出一份答案。送出後不能修改；結果公布前看不到其他組別的作答。";
  $("content-title").textContent = ended ? "本次搶答成果" : teacher ? "小組作答狀況" : "本組作答區";
  $("phase-help").textContent = ended ? "依伺服器收到答案的先後順序公布。搶答成功不代表答案已判定正確。" : state.phase === "preparing" ? "同學可以先加入。老師開始搶答後，作答區會自動開放。" : teacher ? "答案會自動更新。結束搶答後，所有同學才能看到成功組別。" : "搶答進行中。確認本組答案後送出，無需重新整理頁面。";
  $("student-questions").hidden = teacher || ended;
  $("teacher-monitor").hidden = !teacher;
  $("results").hidden = !ended;
  $("download-csv").hidden = !teacher || !ended;
  $("settings-form").hidden = !teacher || state.phase !== "preparing";
  if ($("settings-form").dataset.activity !== state.id) {
    $("settings-form").dataset.activity = state.id;
    $("quiz-mode").value = state.settings.mode; $("quiz-fairness").checked = !!state.settings.fairness;
  }
  const sequential = state.settings.mode === "sequential";
  $("round-controls").hidden = !teacher || !sequential || state.phase !== "active";
  $("close-round").hidden = !state.round.round_open;
  $("next-round").hidden = !!state.round.round_open;
  $("round-status").hidden = !sequential;
  const priorityLeft = Math.max(0, Math.ceil(state.round.priority_until - state.server_time));
  $("round-status").textContent = state.round.unit_id === null ? "逐題模式：老師開始後開放第一題。" :
    `目前第 ${state.round.unit_id} 題 · ${state.round.round_open && !ended ? "作答中" : "已關閉"}` +
    (priorityLeft && !ended ? ` · 保底先答剩 ${priorityLeft} 秒${state.round.own_priority ? "（本組可先答）" : ""}` : "");
  $("sheet-export-controls").hidden = !teacher || !state.source;
  if (teacher && state.source) {
    $("source-name").textContent = `來源：${state.source.sheet_title}` + (state.source.exported_at ? " · 已核對寫回" : "");
    $("source-link").href = state.source.url;
    $("sheet-export").hidden = !ended;
  }
  if (teacher) renderMonitor(state); else renderCards(state);
  if (ended) renderResults(state);
  updateInputs();
}
async function refresh() {
  if (!auth) return;
  if (refreshPromise) {await refreshPromise; if (!auth) return;}
  // Recheck after waiting, so timer and manual refresh cannot overlap.
  if (refreshPromise) return refreshPromise;
  const ownGeneration = generation, id = activityId, token = auth.token;
  refreshPromise = (async () => {
    try {
      const data = await api(id ? `/api/activities/${id}` : "/api/activities", undefined, token);
      if (ownGeneration !== generation) return;
      connection(true);
      if (id) renderState(data); else renderList(data.activities);
      if (auth?.role === "teacher" && !id && Date.now() - lastGoogleCheck > 5000) {
        lastGoogleCheck = Date.now(); googleStatus().catch(error => {if (ownGeneration === generation) $("google-status").textContent = error.message;});
      }
    } catch (error) {
      if (ownGeneration !== generation) return;
      if (error.status === 401) {saveAuth(null); notice(error.message);}
      else {connection(false); updateInputs(); if (!error.network) notice(error.message);}
    }
  })();
  try {await refreshPromise;} finally {refreshPromise = null;}
}
async function poll() {await refresh(); setTimeout(poll, 700);}
showView(); connection(true); poll();
