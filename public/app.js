"use strict";
const $ = (id) => document.getElementById(id);
const phaseNames = {preparing: "準備中", active: "作答中", results: "結果"};
const verdictNames = {pending:"未判定", correct:"正確", incorrect:"錯誤", unanswered:"未作答"};
let auth = null, activityId = null, current = null, generation = 0;
let refreshPromise = null, connected = true, cardsKey = "", lastMonitor = "", lastResults = "", lastList = "";
const pendingAnswers = new Set();
let sheetPreview = null, lastGoogleCheck = 0;
let teacherView = 'settings', teacherViewKey = '', savingSettings = false, monitorKey = '', monitorFollow = true;
let clusterBusy = false, clusterUndo = null, clusterRequest = 0;
try { auth = JSON.parse(sessionStorage.getItem("classroom.auth")); activityId = sessionStorage.getItem("classroom.activity"); } catch { sessionStorage.clear(); }

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function answerElapsedText(answer) {
  const origin=answer.elapsed_basis==='question'?'該題開放後':'活動開始後（舊紀錄）';
  return `${origin} ${(answer.elapsed_ms/1000).toFixed(3)} 秒`;
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
  resetClusterReview();
  resetReplay();
  for (const key of Object.keys(sessionStorage)) if (key.startsWith('classroom.draft.')) sessionStorage.removeItem(key);
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
  resetClusterReview();
  resetReplay();
  generation++; activityId = id; current = null; cardsKey = lastMonitor = lastResults = "";
  teacherViewKey = ''; monitorKey = '';
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
      questions: $('custom-questions').open ? $("question-numbers").value.trim().split(/\r?\n/) : Array.from({length:Number($('question-count').value)},(_,i)=>String(i+1))});
    $("create-form").reset(); $('custom-questions').open=false; syncQuestionInput(); selectActivity(data.id); await refresh();
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
    head.append(el("th", "題號"), el("th", "題組"), el("th", "答案儲存格")); thead.append(head);
    for (const target of result.targets) {const row = el("tr"); row.append(el("td", target.question), el("td", target.unit), el("td", target.cell)); body.append(row);}
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
  if (savingSettings) return;
  if (kind==='start') await saveAllSettings();
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
$("settings-form").onsubmit = event => event.preventDefault();
$("quiz-mode").onchange = syncModeHelp;
for (const [id, kind] of [["close-round","close"],["next-round","next"]]) $(id).onclick = () => action($(id), async () => {
  await api(`/api/activities/${activityId}/round`, {action:kind}); await refresh();
});
function renderList(items) {
  const key = JSON.stringify(items); if (lastList === key) return; lastList = key;
  $("activity-count").textContent = items.length;
  $("activity-list").replaceChildren();
  if (!items.length) $("activity-list").append(el("p", "還沒有活動。建立第一場搶答後，紀錄會保存在這裡。", "empty"));
  for (const item of items) {
    const button = el("button", undefined, "activity-card");
    const info = el("div"); info.append(el("strong", item.title), el("small", `代碼 ${item.code} · ${new Date(item.created_at * 1000).toLocaleDateString("zh-TW")}`));
    button.append(info, el("span", phaseNames[item.phase], "phase-pill " + item.phase));
    button.onclick = () => selectActivity(item.id); $("activity-list").append(button);
  }
}
function renderCards(state) {
  const key=JSON.stringify([state.id,state.units,state.question_settings]); if (cardsKey===key) return;
  cardsKey=key; $('student-questions').replaceChildren();
  state.units.forEach((unit,i)=>{
    const card=el('form',undefined,'question-card'); card.dataset.question=unit.questions[0]; card.dataset.unit=unit.id;
    const top=el('div',undefined,'question-top'); top.append(el('h3',`第 ${unit.id} ${unit.questions.length>1?'題組':'題'}`),el('span','尚未送出','question-status')); card.append(top);
    const inputs={};
    for (const q of unit.questions) {
      const field=el('div',undefined,'answer-field'); field.dataset.question=q;
      const config=state.question_settings[q], choice=config.type==='choice';
      const label=el('label',`${unit.questions.length>1?`子題 ${q}`:'本組'}答案（${choice?'單選・自動判分':'簡答・人工批改'}）`), input=el(choice?'select':'textarea');
      input.className='answer-input';
      if (choice) {
        const empty=el('option','請選擇一個答案'); empty.value=''; input.append(empty);
        config.options.forEach((value,index)=>{const option=el('option',`${String.fromCharCode(65+index)}. ${value}`); option.value=value; input.append(option);});
      }
      input.id=`answer-${state.questions.indexOf(q)}`; label.htmlFor=input.id; input.maxLength=2000; input.required=true;
      input.placeholder='和組員討論後，在這裡寫下答案…'; inputs[q]=input;
      const saved=el('p',undefined,'saved-answer'), time=el('p',undefined,'answer-time'); saved.hidden=time.hidden=true;
      field.append(label,input,saved,time); card.append(field);
    }
    const betting=state.question_settings[unit.questions[0]].betting_enabled;
    const label=el('label',betting?'信心下注（可不押，題組只計一次分）':'本題未開放下注'), stake=el('select'); stake.id=`stake-${i}`; label.htmlFor=stake.id; stake.className='stake';
    for (const v of betting?[0,1,2,3]:[0]) {const option=el('option',v===0?'不押（0 分）':`${v} 分`); option.value=v; stake.append(option);}
    card.dataset.betting=String(betting);
    const button=el('button',unit.questions.length>1?'一次送出整個題組 →':'送出本組答案 →','primary wide'); button.type='submit';
    card.append(label,stake,button);
    const draftKey=`classroom.draft.${auth.token}.${state.id}.${unit.id}`; card.dataset.draftKey=draftKey;
    try {const draft=JSON.parse(sessionStorage.getItem(draftKey)); if (draft) {for (const q of unit.questions) inputs[q].value=draft.answers?.[q] || draft.answer || ''; stake.value=String(betting?(draft.stake ?? 0):0);}} catch {sessionStorage.removeItem(draftKey);}
    const saveDraft=()=>{try {sessionStorage.setItem(draftKey,JSON.stringify({answers:Object.fromEntries(unit.questions.map(q=>[q,inputs[q].value])),stake:Number(stake.value)}));} catch {notice('瀏覽器無法保存草稿，重新整理前請先複製答案。');}};
    for (const input of Object.values(inputs)) {input.oninput=saveDraft; input.onchange=saveDraft;} stake.onchange=saveDraft;
    card.onsubmit=event=>{
      event.preventDefault(); const requestActivity=activityId;
      action(button,async()=>{
        pendingAnswers.add(unit.id); updateInputs();
        try {
          const grouped=unit.questions.length>1;
          const data=grouped?{unit:unit.id,answers:Object.fromEntries(unit.questions.map(q=>[q,inputs[q].value])),stake:Number(stake.value)}:
            {question:unit.questions[0],answer:inputs[unit.questions[0]].value,stake:Number(stake.value)};
          await api(`/api/activities/${requestActivity}/${grouped?'bundle':'answers'}`,data); notice(`第 ${unit.id} 題已送出。`,true);
        } finally {pendingAnswers.delete(unit.id); await refresh();}
      });
    };
    $('student-questions').append(card);
  });
}
function updateInputs() {
  if (!current) return;
  $('start').disabled=!connected || savingSettings || $('start').classList.contains('busy');
  $('save-settings').disabled=!connected || savingSettings || $('save-settings').classList.contains('busy');
  $('end').disabled=!connected || $('end').classList.contains('busy');
  if (current.role!=='student') return;
  const answers=new Map(current.answers.map(a=>[a.question_id,a]));
  for (const card of $('student-questions').children) {
    const fields=[...card.querySelectorAll('.answer-field')], sent=fields.every(f=>answers.has(f.dataset.question));
    const disabled=sent || !connected || current.phase!=='active' || !current.available_questions.includes(card.dataset.question) || pendingAnswers.has(card.dataset.unit);
    const button=card.querySelector('button'), stake=card.querySelector('.stake'); button.disabled=stake.disabled=disabled; button.hidden=sent;
    if (card.dataset.betting==='false') stake.disabled=true;
    card.classList.toggle('sent',sent); card.querySelector('.question-status').textContent=sent?'✓ 已送出':'尚未送出';
    if (sent) {stake.value=answers.get(card.dataset.question).stake; sessionStorage.removeItem(card.dataset.draftKey);}
    for (const field of fields) {
      const answer=answers.get(field.dataset.question), input=field.querySelector('.answer-input'); input.disabled=disabled; input.hidden=!!answer;
      const saved=field.querySelector('.saved-answer'), time=field.querySelector('.answer-time'); saved.hidden=time.hidden=!answer;
      if (answer) {input.value=answer.text; saved.textContent=answer.text; time.textContent=`已於 ${timeText(answer.received_at)} 送出 · ${answerElapsedText(answer)} · ${verdictNames[answer.verdict]} · ${answer.stake===0?'不押':`下注 ${answer.stake} 分`}`;}
    }
  }
}
function renderMonitor(state) {
  const selected=$('monitor-question').value, questions=selected?[selected]:state.questions;
  const key = JSON.stringify([state.groups, state.answers, questions, state.reviewable_questions]);
  if (lastMonitor === key) return; lastMonitor = key;
  $("monitor-summary").textContent = `${state.groups.length} 個小組已加入 · ${state.questions.length} 題 · 已收到 ${state.answers.length} 份答案`;
  const wrap = $("monitor-table"); wrap.replaceChildren();
  if (!state.groups.length) {wrap.append(el("p", "還沒有小組加入。將上方活動代碼提供給同學即可加入。", "empty")); return;}
  const table = el("table"), thead = el("thead"), head = el("tr");
  head.append(el("th", "小組")); for (const q of questions) head.append(el("th", `第 ${q} 題`)); thead.append(head);
  const body = el("tbody");
  const lookup = new Map(state.answers.map(a => [JSON.stringify([a.group_id,a.question_id]), a]));
  for (const group of state.groups) {
    const row = el("tr"); row.append(el("th", group.name));
    for (const q of questions) {
      const cell = el("td"), answer = lookup.get(JSON.stringify([group.id,q]));
      if (answer) {
        const content=el('span',answer.text,'cell-answer');
        if(answer.text.length>300) {content.tabIndex=0; content.setAttribute('role','region'); content.setAttribute('aria-label',`${group.name} 第 ${q} 題完整答案，可捲動閱讀`);}
        cell.append(content, el("small", `${timeText(answer.received_at)} · ${answerElapsedText(answer)} · ${answer.stake===0?'不押':`下注 ${answer.stake}`} · ${verdictNames[answer.verdict]}`));
        if (state.reviewable_questions.includes(q)) {
          const controls = el("div", undefined, "review-controls");
          for (const verdict of ['correct','incorrect','pending']) {
            const button = el('button', verdictNames[verdict], 'text-button'); button.dataset.verdict = verdict;
            button.setAttribute('aria-label', `${group.name} 第 ${q} 題判為${verdictNames[verdict]}`);
            button.disabled = answer.verdict === verdict;
            button.onclick = () => action(button, async () => {await api(`/api/activities/${state.id}/review`, {answer_id:answer.id, verdict}); await refresh();});
            controls.append(button);
          }
          cell.append(controls);
        }
      }
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
    detail.append(el("div", result.winner ? `${result.winner.group_name} · 搶答成功（${verdictNames[result.winner.verdict]}）` : result.has_answers ? "無成功組別（候選已判錯）" : "無人作答", "winner"));
    if (result.winner) {
      const text=result.winner.text;
      if(text.length>300) {
        detail.append(el('p',text.slice(0,140)+'…','result-answer'));
        const full=el('details',undefined,'full-answer'); full.append(el('summary','查看完整答案'),el('p',text,'result-answer')); detail.append(full);
      } else detail.append(el('p',text,'result-answer'));
    }
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
  let due = 0, previous = null, shown = 0;
  for (const answer of answers) {
    const gap=previous===null?answer.elapsed_ms:(answer.received_at-previous)*1000;
    due += Math.max(400, Math.min(1500, gap)); previous = answer.received_at;
    if (replayElapsed < due) break;
    shown++;
    if ($("replay-answers").children.length < shown)
      $("replay-answers").append(el("li", `${answer.group_name}：${answer.text} · ${answerElapsedText(answer)}`));
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
  $('activity').classList.toggle('teacher-view',teacher);
  renderQuestionSettings(state);
  $('own-score').hidden=teacher;
  if (!teacher) {
    $('own-score-total').textContent=`${state.own_score.total} 分`;
    $('own-score-pending').textContent=state.own_score.pending_units?`還有 ${state.own_score.pending_units} 個作答單位等待判定`:'目前已送出答案沒有待判定項目';
  }
  $('scoreboard').hidden=!ended;
  if (ended && $('scoreboard').dataset.values!==JSON.stringify(state.scoreboard)) {
    $('scoreboard').dataset.values=JSON.stringify(state.scoreboard);
    const table=el('table'), head=el('tr'); head.append(el('th','名次'),el('th','組別'),el('th','總分')); table.append(head);
    for (const score of state.scoreboard) {const row=el('tr'); row.append(el('td',score.rank),el('th',score.group_name),el('td',score.score)); table.append(row);}
    $('scoreboard-table').replaceChildren(table);
  }
  renderReport(state);
  $("classification").hidden = !teacher;
  if ($("classification").dataset.activity !== state.id) {
    $("classification").dataset.activity = state.id; $("cluster-list").replaceChildren(); $("cluster-limit").textContent = '';
    $("cluster-question").replaceChildren(...state.questions.map(q=>{const option=el('option',`第 ${q} 題`); option.value=q; return option;}));
  }
  updateClusterControls();
  $("session-title").textContent = state.title;
  $("session-code").textContent = state.code;
  $("session-subtitle").textContent = teacher ? `${state.questions.length} 道題目 · ${state.groups.length} 個小組已加入` : `${state.group_name} · ${state.questions.length} 道題目，一起完成`;
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
    $('settings-form').dataset.dirty='false';
    $("quiz-mode").value = state.settings.mode; $("quiz-fairness").checked = !!state.settings.fairness;
    $('quiz-duration').value=state.settings.duration_seconds;
    syncModeHelp();
  }
  const sequential = state.settings.mode === "sequential";
  $('countdown').hidden=state.round.deadline===null || state.phase!=='active';
  $('countdown').textContent=`剩餘 ${Math.max(0,Math.ceil(state.round.deadline-state.server_time))} 秒 · 到期自動${sequential?'關閉本題':'公布結果'}`;
  $("round-controls").hidden = !teacher || !sequential || state.phase !== "active";
  $("close-round").hidden = !state.round.round_open;
  $("next-round").hidden = !!state.round.round_open;
  $("round-status").hidden = !sequential || (teacher && state.phase==='preparing');
  const priorityLeft = Math.max(0, Math.ceil(state.round.priority_until - state.server_time));
  $("round-status").textContent = state.round.unit_id === null ? "逐題模式：老師開始後開放第一題。" :
    `目前第 ${state.round.unit_id} 題 · ${state.round.round_open && !ended ? "作答中" : "已關閉"}` +
    (priorityLeft && !ended ? ` · 保底先答剩 ${priorityLeft} 秒${state.round.own_priority ? "（本組可先答）" : ""}` : "");
  $("sheet-export-controls").hidden = !teacher || !state.source;
  if (teacher && state.source) {
    $("source-name").textContent = `來源：${state.source.sheet_title}` + (state.source.export_stale ? " · 判定已變更，請重新寫回" : state.source.exported_at ? " · 已核對寫回" : "");
    $("source-link").href = state.source.url;
    $("sheet-export").hidden = !ended;
  }
  if (teacher) {syncMonitorFilter(state); renderMonitor(state);} else renderCards(state);
  if (ended) renderResults(state);
  renderTeacherWorkspace(state);
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
let reportKey = '';
$("download-report").onclick = () => action($("download-report"),()=>downloadFile(`/api/activities/${activityId}/report`, '本組學習報告.csv'));
function renderReport(state) {
  const ended=state.phase==='results', teacher=state.role==='teacher';
  $('references').hidden=!ended || !teacher; $('group-report').hidden=!ended || teacher;
  if (!ended) return;
  if (teacher) {
    if ($('references').dataset.activity !== state.id) {
      $('references').dataset.activity=state.id;
      $('reference-forms').replaceChildren(...state.questions.map((q,i)=>{
        const form=el('form'), label=el('label',`第 ${q} 題參考答案`), input=el('textarea'), button=el('button','儲存參考答案','primary');
        input.id=`reference-${i}`; label.htmlFor=input.id; input.maxLength=2000; input.value=state.references[q];
        form.append(label,input,button);
        form.onsubmit=event=>{event.preventDefault(); action(button,async()=>{await api(`/api/activities/${state.id}/reference`,{question:q,answer:input.value}); notice('參考答案已儲存。',true); await refresh();});};
        return form;
      }));
    }
  } else {
    const key=JSON.stringify([state.id,state.report]); if (key===reportKey) return; reportKey=key;
    const table=el('table'), head=el('tr');
    for (const title of ['題號','本組答案','判定','下注','單位得分','搶答成功','參考答案']) head.append(el('th',title));
    table.append(head);
    for (const r of state.report) {const row=el('tr'); for (const value of [r.question,r.answer,verdictNames[r.verdict],r.stake??'—',r.points??'同題組',r.successful?'是':'否',r.reference||'老師尚未填寫']) row.append(el('td',value)); table.append(row);}
    $('report-table').replaceChildren(table);
  }
}
function resetClusterReview() {
  clusterRequest++; clusterUndo = null;
  $('cluster-undo-area').hidden = true;
  $('cluster-feedback').hidden = true;
  $('cluster-list').replaceChildren();
}
function updateClusterControls() {
  const reviewable = current?.reviewable_questions?.includes($('cluster-question').value);
  $('cluster-refresh').disabled = clusterBusy;
  $('cluster-question').disabled = clusterBusy;
  $('cluster-undo').disabled = clusterBusy;
  for (const section of $('cluster-list').children) {
    section.querySelector('fieldset').disabled = clusterBusy;
    const boxes = [...section.querySelectorAll('.cluster-choice')];
    const count = boxes.filter(b=>b.checked).length;
    const all = section.querySelector('.cluster-all');
    all.checked = count === boxes.length && count > 0;
    all.indeterminate = count > 0 && count < boxes.length;
    for (const button of section.querySelectorAll('[data-verdict]')) {
      button.textContent = `將勾選答案判為${button.dataset.verdict === 'correct' ? '答對' : '答錯'}（${count} 組）`;
      button.disabled = clusterBusy || !count || !reviewable;
    }
    section.querySelector('.cluster-review-hint').hidden = !!reviewable;
  }
}
async function clusterOperation(fn) {
  if (clusterBusy) return;
  clusterBusy = true; updateClusterControls(); notice('');
  $('cluster-feedback').hidden = true;
  try { await fn(); }
  catch (error) {
    $('cluster-feedback').textContent=error.message; $('cluster-feedback').hidden=false;
    notice(error.message); if (error.network) connection(false);
  }
  finally { clusterBusy = false; updateClusterControls(); }
}
async function loadClusters() {
  const id = activityId, question = $("cluster-question").value;
  const request = ++clusterRequest, session = generation;
  const result = await api(`/api/activities/${id}/clusters`, {question});
  if (generation !== session || request !== clusterRequest || activityId !== id || $("cluster-question").value !== question) return;
  $("cluster-limit").textContent = !result.clusters.length ? '這題目前還沒有答案。' : result.limited ? '已超過 200 類，後續答案僅比較相同文字。' : '已更新目前答案分類。';
  $("cluster-list").replaceChildren(...result.clusters.map((cluster,i) => {
    const section = el('section',undefined,'cluster-card'), fields=el('fieldset');
    fields.append(el('legend',`分類 ${i+1} · ${cluster.answers.length} 組`));
    fields.append(el('p',cluster.exact ? '原文相同 · 已預先勾選' : '文字相似 · 請逐筆確認後勾選','field-hint'));
    const allLabel=el('label',undefined,'check-label'), all=el('input',undefined,'cluster-all'); all.type='checkbox';
    allLabel.append(all,document.createTextNode('勾選此分類全部答案')); fields.append(allLabel);
    const choices=[];
    for (const answer of cluster.answers) {
      const label=el('label',undefined,'cluster-answer'), box=el('input',undefined,'cluster-choice'), content=el('span',undefined,'cluster-answer-content');
      box.type='checkbox'; box.checked=cluster.exact; box.setAttribute('aria-label',`選取 ${answer.group_name} 的答案`);
      content.append(el('strong',answer.group_name),el('span',`目前：${verdictNames[answer.verdict]}`,'cluster-verdict'),el('span',answer.text,'cluster-answer-text'));
      label.append(box,content); fields.append(label); choices.push({box,answer});
      box.onchange=updateClusterControls;
    }
    all.onchange=()=>{for(const c of choices) c.box.checked=all.checked; updateClusterControls();};
    const actions=el('div',undefined,'cluster-actions');
    for(const verdict of ['correct','incorrect']) {
      const button=el('button',undefined,verdict==='correct'?'primary':'secondary'); button.type='button'; button.dataset.verdict=verdict;
      button.onclick=()=>clusterOperation(async()=>{
        const selections=choices.filter(c=>c.box.checked).map(c=>({id:c.answer.id,revision:c.answer.review_revision}));
        if(!selections.length) return;
        const saved=await api(`/api/activities/${id}/review-batch`,{question,selections,verdict});
        if(generation!==session || activityId!==id) return;
        clusterUndo={id,batch_id:saved.batch_id};
        $('cluster-undo-status').textContent=`第 ${question} 題：已將 ${saved.count} 組判為${verdict==='correct'?'答對':'答錯'}。`;
        $('cluster-undo-area').hidden=false;
        await refresh(); await loadClusters();
      });
      actions.append(button);
    }
    fields.append(actions,el('p','請先關閉此題或結束活動，再批改答案。','cluster-review-hint field-hint'));
    section.append(fields); return section;
  }));
  updateClusterControls();
}
$("cluster-refresh").onclick = () => clusterOperation(loadClusters);
$('cluster-undo').onclick = () => clusterOperation(async()=>{
  const undo=clusterUndo, session=generation;
  if(!undo || undo.id!==activityId) return;
  const result=await api(`/api/activities/${undo.id}/review-undo`,{batch_id:undo.batch_id});
  if(generation!==session || activityId!==undo.id) return;
  clusterUndo=null; $('cluster-undo-area').hidden=true;
  notice(`已撤銷 ${result.count} 組的批改，還原原本判定與分數。`,true);
  await refresh(); await loadClusters();
});
$("cluster-question").onchange = () => {clusterRequest++; $("cluster-list").replaceChildren(); $("cluster-limit").textContent='請按比較目前答案。';};
function renderQuestionSettings(state) {
  const panel=$('question-settings'); panel.hidden=state.role!=='teacher' || state.phase!=='preparing';
  if (panel.hidden || panel.dataset.activity===state.id) return;
  panel.dataset.activity=state.id;
  $('question-settings-forms').replaceChildren(...state.units.map((unit,index)=>{
    const details=el('details',undefined,'question-config-unit'); details.open=index===0; details.dataset.unit=unit.id;
    const summary=el('summary'), name=el('span',`第 ${unit.id} ${unit.questions.length>1?'題組':'題'}`), description=el('span',undefined,'question-config-summary'); summary.append(name,description);
    details.ontoggle=()=>{if(details.open) for(const other of $('question-settings-forms').children) if(other!==details) other.open=false;};
    const form=el('form',undefined,'question-config-form'), fields=el('fieldset'); form.dataset.dirty='false';
    const betLabel=el('label',undefined,'check-label'), betting=el('input'); betting.type='checkbox'; betting.className='betting-enabled';
    betting.checked=state.question_settings[unit.questions[0]].betting_enabled;
    betLabel.append(betting,document.createTextNode('開放信心下注（學生仍可選擇不押）')); fields.append(betLabel);
    const configs=[];
    for (const [childIndex,q] of unit.questions.entries()) {
      const config=state.question_settings[q], box=el('section',undefined,'question-config-child'); box.dataset.question=q;
      const kind=el('select'), label=el('label',`第 ${q} 題的題型`); kind.id=`question-type-${index}-${childIndex}`; kind.className='question-type'; label.htmlFor=kind.id;
      for (const [value,title] of [['short','簡答（人工批改）'],['choice','單選（自動判分）']]) {const option=el('option',title); option.value=value; kind.append(option);}
      kind.value=config.type; box.append(label,kind);
      const choiceBox=el('div',undefined,'choice-settings'), options=el('textarea'), optionLabel=el('label','選項（每行一個，2～8 個，每個最多 200 字）');
      options.id=`choice-options-${index}-${childIndex}`; options.className='choice-options'; options.rows=4; options.maxLength=2000; options.value=config.options.join('\n'); optionLabel.htmlFor=options.id;
      const correct=el('select'), correctLabel=el('label','正確選項（僅老師可見）'); correct.id=`choice-correct-${index}-${childIndex}`; correct.className='choice-correct'; correctLabel.htmlFor=correct.id;
      const lines=()=>options.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
      const rebuild=(preferred)=>{
        const old=preferred ?? correct.selectedOptions[0]?.dataset.answer;
        const empty=el('option','請指定正確選項'); empty.value=''; correct.replaceChildren(empty);
        lines().forEach((answer,i)=>{const option=el('option',`${String.fromCharCode(65+i)}. ${answer}`); option.value=String(i); option.dataset.answer=answer; correct.append(option);});
        const found=lines().indexOf(old); correct.value=found<0?'':String(found);
      };
      rebuild(config.correct_index===null?undefined:config.options[config.correct_index]);
      const toggle=()=>{choiceBox.hidden=kind.value!=='choice'; options.required=correct.required=kind.value==='choice'; options.disabled=correct.disabled=kind.value!=='choice';};
      kind.onchange=toggle; options.oninput=()=>rebuild(); toggle();
      choiceBox.append(optionLabel,options,correctLabel,correct); box.append(choiceBox); fields.append(box);
      configs.push({q,kind,lines,correct});
    }
    const status=el('p','設定已儲存','field-hint');
    const summarize=()=>{description.textContent=`${configs.map(c=>c.kind.value==='choice'?'單選':'簡答').filter((v,i,a)=>a.indexOf(v)===i).join('＋')} · ${betting.checked?'可下注':'不押分'}`;};
    const dirty=()=>{form.dataset.dirty='true'; status.textContent='尚未儲存，開始前會一起儲存'; summarize(); updateSetupStatus();}; form.oninput=dirty; form.onchange=dirty; summarize();
    fields.append(status); form.append(fields);
    form.prepareSettings=()=>{
      const questions=configs.map(c=>({question:c.q,type:c.kind.value,options:c.kind.value==='choice'?c.lines():[],correct_index:c.correct.value===''?null:Number(c.correct.value)}));
      for (const q of questions) if(q.type==='choice' && (q.options.length<2 || q.options.length>8 || q.options.some(x=>x.length>200) || new Set(q.options).size!==q.options.length || q.correct_index===null || q.correct_index>=q.options.length)) {
        showTeacherView('questions'); details.open=true; const box=form.querySelector(`[data-question="${CSS.escape(q.question)}"]`); box.scrollIntoView({block:'center'}); box.querySelector(q.correct_index===null?'.choice-correct':'.choice-options').focus();
        throw new Error(`第 ${q.question} 題：請填寫 2～8 個不重複選項（每項最多 200 字），並指定正確選項。`);
      }
      return {unit:unit.id,betting_enabled:betting.checked,questions};
    };
    form.persistSettings=async payload=>{
      try {await api(`/api/activities/${state.id}/question-settings`,payload); form.dataset.dirty='false'; status.textContent='設定已儲存'; updateSetupStatus();}
      catch(error) {showTeacherView('questions'); details.open=true; summary.scrollIntoView({block:'center'}); throw new Error(`第 ${unit.id} 題儲存失敗：${error.message}`);}
    };
    form.onsubmit=event=>event.preventDefault();
    details.append(summary,form); return details;
  }));
}

function setCreateSource(source) {
  const manual=source==='manual'; $('create-form').hidden=!manual; $('sheets-create').hidden=manual;
  $('source-manual').setAttribute('aria-pressed',String(manual)); $('source-sheets').setAttribute('aria-pressed',String(!manual));
}
function syncQuestionInput() {
  const custom=$('custom-questions').open;
  $('question-count').disabled=custom; $('question-numbers').disabled=!custom; $('question-numbers').required=custom;
}
function syncModeHelp() {
  const sequential=$('quiz-mode').value==='sequential';
  $('fairness-field').hidden=!sequential;
  if(!sequential) $('quiz-fairness').checked=false;
  $('mode-help').textContent=sequential?'一次開放一題，由你控制關題與下一題。':'開始後所有題目一起開放，學生自行選題作答。';
}
function updateSetupStatus() {
  const count=document.querySelectorAll('.question-config-form[data-dirty="true"]').length;
  const dirty=$('settings-form').dataset.dirty==='true' || count>0;
  $('setup-status').textContent=dirty?'有尚未儲存的變更。開始搶答時會先儲存並檢查所有設定。':'所有設定已儲存。準備好後按「開始搶答」。';
  $('setup-status').classList.toggle('unsaved',dirty);
}
function showTeacherView(view) {
  teacherView=view;
  if(current) renderTeacherWorkspace(current);
}
function renderTeacherWorkspace(state) {
  const teacher=state.role==='teacher', preparing=state.phase==='preparing', ended=state.phase==='results';
  $('teacher-tabs').hidden=!teacher; $('setup-status').hidden=!teacher || !preparing;
  $('save-settings').hidden=!preparing;
  for(const id of ['references','replay','classification']) $(`tool-${id}`).hidden=true;
  $('result-actions').hidden=true;
  if(!teacher) return;
  const key=state.id+state.phase;
  if(teacherViewKey!==key) {teacherViewKey=key; teacherView=preparing?'settings':ended?'results':'monitor';}
  const allowed=preparing?['settings','questions','monitor']:ended?['results','monitor','tools']:['monitor','tools'];
  for(const button of $('teacher-tabs').children) {
    button.hidden=!allowed.includes(button.dataset.view);
    button.setAttribute('aria-current',button.dataset.view===teacherView?'page':'false');
    if(button.dataset.view==='monitor') button.textContent=preparing?`已加入小組（${state.groups.length}）`:`作答與批改（${state.answers.filter(a=>a.verdict==='pending').length} 待判定）`;
  }
  const sections={settings:['settings-form'],questions:['question-settings'],monitor:['teacher-monitor'],results:['results','scoreboard','result-actions'],tools:[]};
  for(const id of ['settings-form','question-settings','teacher-monitor','results','scoreboard','result-actions']) $(id).hidden=!sections[teacherView]?.includes(id);
  $('content-title').textContent={settings:'1. 設定活動方式',questions:'2. 設定題目與計分',monitor:preparing?'等待小組加入':'查看作答與批改',results:'本次搶答成果',tools:'更多教學工具'}[teacherView];
  $('phase-help').textContent={settings:'保留預設也能直接開始。需要逐題控制時，切換開放方式。',questions:'單選自動批改；簡答由老師批改。每題可獨立開關下注。',monitor:preparing?'分享上方代碼；同組同學使用相同組名加入。':'答案自動更新。選擇題目可集中查看與批改。',results:'這裡顯示搶答成果與總分。需要改判時，切換到「作答與批改」。',tools:'需要時再展開。這些工具不影響原本的搶答流程。'}[teacherView];
  for(const id of ['references','replay','classification']) $(`tool-${id}`).hidden=teacherView!=='tools' || (id!=='classification' && !ended);
  $('download-csv').hidden=!ended; $('sheet-export-controls').hidden=!state.source;
  $('start').textContent='開始搶答 →';
  $('end').textContent=state.settings.mode==='sequential'?'提早結束整場':'結束搶答並公布結果';
  updateSetupStatus();
}
function activitySettingsPayload() {
  if(!$('quiz-duration').checkValidity()) {showTeacherView('settings'); $('quiz-duration').focus(); $('quiz-duration').reportValidity(); throw new Error('作答時間請填 0～3600 的整數秒。');}
  return {mode:$('quiz-mode').value,fairness:$('quiz-fairness').checked,duration_seconds:Number($('quiz-duration').value)};
}
async function saveActivitySettings(payload=activitySettingsPayload()) {
  try {await api(`/api/activities/${activityId}/settings`,payload); $('settings-form').dataset.dirty='false'; updateSetupStatus();}
  catch(error) {showTeacherView('settings'); throw new Error(`活動規則儲存失敗：${error.message}`);}
}
async function saveAllSettings() {
  // Validate all drafts before issuing any writes. A failed write never starts the activity.
  const rules=activitySettingsPayload();
  const drafts=[...document.querySelectorAll('.question-config-form[data-dirty="true"]')].map(form=>({form,payload:form.prepareSettings()}));
  await withSettingsLock(async()=>{
    if($('settings-form').dataset.dirty==='true') await saveActivitySettings(rules);
    for(const draft of drafts) await draft.form.persistSettings(draft.payload);
  });
}
async function withSettingsLock(save) {
  savingSettings=true; updateInputs();
  const controls=[...document.querySelectorAll('#settings-form input,#settings-form select,#settings-form button,#question-settings fieldset,#back,#logout')];
  const previous=controls.map(control=>control.disabled); controls.forEach(control=>control.disabled=true);
  try {await save();}
  finally {controls.forEach((control,i)=>control.disabled=previous[i]); savingSettings=false; updateInputs();}
}
function syncMonitorFilter(state) {
  const key=state.id+JSON.stringify(state.questions);
  if(monitorKey!==key) {
    monitorKey=key; monitorFollow=true;
    $('monitor-question').replaceChildren(...['',...state.questions].map(q=>{const o=el('option',q?`第 ${q} 題`:'全部題目'); o.value=q; return o;}));
  }
  if(monitorFollow) $('monitor-question').value=state.settings.mode==='sequential' && state.phase==='active' ? state.units.find(u=>u.id===state.round.unit_id)?.questions[0] || '' : '';
}
$('create-panel').append($('sheets-create'));
$('source-manual').onclick=()=>setCreateSource('manual'); $('source-sheets').onclick=()=>setCreateSource('sheets');
$('custom-questions').ontoggle=syncQuestionInput;
$('go-questions').onclick=()=>showTeacherView('questions');
for(const button of $('teacher-tabs').children) button.onclick=()=>showTeacherView(button.dataset.view);
$('monitor-question').onchange=()=>{monitorFollow=false; renderMonitor(current);};
$('settings-form').oninput=$('settings-form').onchange=()=>{$('settings-form').dataset.dirty='true'; updateSetupStatus();};
$('save-settings').onclick=()=>action($('save-settings'),async()=>{if(savingSettings) return; await saveAllSettings(); notice('所有設定已儲存。',true); await refresh();});
$('result-actions').append($('download-csv'),$('sheet-export-controls'));
for(const [id,title] of [['references','提供參考答案'],['replay','重播搶答過程'],['classification','比較相似答案']]) {
  const section=$(id), wrapper=el('details',undefined,'tool-disclosure panel'); wrapper.id=`tool-${id}`; wrapper.hidden=true;
  const summary=el('summary',title); section.before(wrapper); wrapper.append(summary,section);
}
