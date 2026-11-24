"use strict";
const $ = (id) => document.getElementById(id);
const phaseNames = {preparing: "準備中", active: "作答中", results: "結果"};
const verdictNames = {pending:"待批改", withheld:"等待本題結束", correct:"正確", incorrect:"錯誤", unanswered:"未作答"};
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
function checkedOptions(group) {
  return [...group.querySelectorAll('input:checked')].map(box=>box.value);
}
function fillChecks(group, options, selected, legend) {
  group.replaceChildren(el('legend',legend));
  for (const value of options) {
    const label=el('label'), box=el('input'); box.type='checkbox'; box.value=value;
    box.checked=selected.includes(value); label.append(box,document.createTextNode(value)); group.append(label);
  }
}
function answerValue(input) {
  return input.tagName==='FIELDSET'?checkedOptions(input):input.value;
}
function scoreParts(parts) {
  const signed=value=>value>0?`+${value}`:String(value);
  return `押注分 ${signed(parts.wager)}｜搶答分 ${signed(parts.speed)}｜合計 ${signed(parts.total)}`;
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
  if(!current) activityChat.sync(null);
  if (location.pathname==='/classroom' && !auth?.course) {
    location.replace('/');
    return;
  }
  $("entry").hidden = !!auth;
  $("dashboard").hidden = !auth || auth.role !== "teacher" || !!activityId;
  $('activity-list').closest('.panel').hidden=!!auth?.course;
  $("activity").hidden = !auth || !activityId || !current;
  const activityMenu=$('work-activity');
  if(activityMenu) activityMenu.hidden=$('activity').hidden;
  $("logout").hidden = !auth || !!auth.course;
  $("back").hidden = auth?.role !== "teacher" || auth?.assistant || !!auth?.course;
  if(auth?.course && !current) {
    for(const id of ['teacher-tabs','teacher-controls','round-controls']) $(id).hidden=true;
  }
}
function saveAuth(value) {
  classroomMotion.reset();
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
  classroomMotion.reset();
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
  if (status.server_managed) {
    $("google-status").textContent = "在試算表的「共用」中，將「一般存取權」設為「知道連結的任何人」及「編輯者」，再貼上副本網址。匯入後會連結到目前課程。";
    $("google-connect").hidden = $("google-disconnect").hidden = $("google-auth-link").hidden = true;
    document.querySelector('a[href="/google-setup.html"]').hidden = true;
    return;
  }
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
  const result = await api(`/api/activities/${activityId}/sheet-sync`, {}); notice(result.message, true); await refresh();
});
$('start').onclick = () => action($('start'), async () => {
  if (savingSettings) return;
  const id = activityId;
  window.courseNav.revealActivity();
  await saveAllSettings();
  await api(`/api/activities/${id}/start`, {}); await refresh();
});
$('end').onclick = async () => {
  const id = activityId, dialog = $('end-dialog');
  if (!current || dialog.open) return;
  $('end-title').textContent = '要結束「'+current.title+'」嗎？';
  dialog.returnValue = '';
  const choice = new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue), {once:true}));
  dialog.showModal();
  dialog.querySelector('[value="cancel"]').focus();
  if (await choice !== 'end' || activityId !== id || current?.phase !== 'active') return;
  window.courseNav.revealActivity();
  await action($('end'),async () => {await api(`/api/activities/${id}/end`, {}); await refresh();});
};

function timeText(seconds) { return new Date(seconds * 1000).toLocaleTimeString("zh-TW", {hour12:false}); }
async function downloadFile(path, filename) {
  const response = await fetch(path, {headers:{Authorization:`Bearer ${auth.token}`}});
  if (!response.ok) throw new Error((await response.json()).error || "下載失敗。");
  const url = URL.createObjectURL(await response.blob()), link = el("a");
  link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("download-csv").onclick = () => action($("download-csv"), () => downloadFile(`/api/activities/${activityId}/csv`, "課堂搶答結果.csv"));
$("settings-form").onsubmit = event => event.preventDefault();
$("quiz-mode").onchange = ()=>{$('quiz-fairness').checked=$('quiz-mode').value==='sequential'; syncModeHelp();};
$('use-priority-source').onchange = syncPrioritySetup;
$('priority-source').onchange = syncPrioritySetup;
for (const [id, kind] of [["close-round","close"],["next-round","next"]]) $(id).onclick = () => action($(id), async () => {
  const roundActivity=activityId;
  await api(`/api/activities/${roundActivity}/round`, {action:kind}); await refresh();
  if(activityId===roundActivity && document.activeElement===document.body) {
    ($('round-status').hidden ? $('content-title') : $('round-status')).focus();
  }
});
function renderList(items) {
  const key = JSON.stringify(items); if (lastList === key) return; lastList = key;
  $("activity-count").textContent = items.length;
  $("activity-list").replaceChildren();
  if (!items.length) $("activity-list").append(el("p", "還沒有活動。建立第一場搶答後，紀錄會保存在這裡。", "empty"));
  for (const item of items) {
    const button = el("button", undefined, "activity-card");
    const info = el("div");
    const created = new Date(item.created_at * 1000).toLocaleDateString("zh-TW");
    info.append(el("strong", item.title), el("small", created));
    button.append(info, el("span", phaseNames[item.phase], "phase-pill " + item.phase));
    button.onclick = () => selectActivity(item.id);
    if (auth?.course) {
      $("activity-list").append(button);
    } else {
      const entry = el("article", undefined, "activity-list-entry");
      entry.append(button, createShareCode('活動代碼',item.code));
      $("activity-list").append(entry);
    }
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
      const config=state.question_settings[q], choice=config.type==='choice', multiple=config.type==='multiple';
      const label=el('label',`${unit.questions.length>1?`子題 ${q}`:'本組'}答案（${multiple?'多選・全部選對才得分':choice?'單選・自動判分':'簡答・人工批改'}）`), input=el(multiple?'fieldset':choice?'select':'textarea');
      input.className='answer-input';
      if (multiple) {
        fillChecks(input,config.options,[],label.textContent); input.classList.add('multi-checks'); label.hidden=true;
      }
      if (choice) {
        const empty=el('option','請選擇一個答案'); empty.value=''; input.append(empty);
        config.options.forEach((value,index)=>{const option=el('option',`${String.fromCharCode(65+index)}. ${value}`); option.value=value; input.append(option);});
      }
      input.id=`answer-${state.questions.indexOf(q)}`; label.htmlFor=input.id; input.maxLength=2000; input.required=true;
      if (config.prompt) {
        const prompt=el('p',config.prompt,'question-prompt'); prompt.id=`${input.id}-prompt`;
        input.setAttribute('aria-describedby',prompt.id); field.append(prompt);
      }
      input.placeholder='和組員討論後，在這裡寫下答案…'; inputs[q]=input;
      const saved=el('p',undefined,'saved-answer'), time=el('p',undefined,'answer-time'); saved.hidden=time.hidden=true;
      const reference=el('aside',undefined,'published-reference'); reference.hidden=true;
      reference.append(el('strong','老師正確答案'),el('p',undefined,'reference-text'));
      field.append(label,input,saved,time,reference); card.append(field);
    }
    const betting=state.question_settings[unit.questions[0]].betting_enabled;
    const label=el('label',betting?`信心下注（可不押${unit.questions.length>1?'，整題組計一次分':''}）`:'本題未開放下注'), stake=el('select'); stake.id=`stake-${i}`; label.htmlFor=stake.id; stake.className='stake';
    for (const v of betting?[0,1,2,3]:[0]) {const option=el('option',v===0?'不押（0 分）':`${v} 分`); option.value=v; stake.append(option);}
    card.dataset.betting=String(betting);
    const button=el('button',unit.questions.length>1?'一次送出整個題組':'送出本組答案','primary wide'); button.type='submit';
    card.append(label,stake,button);
    const draftKey=`classroom.draft.${auth.token}.${state.id}.${unit.id}`; card.dataset.draftKey=draftKey;
    try {const draft=JSON.parse(sessionStorage.getItem(draftKey)); if (draft) {for (const q of unit.questions) {
      const value=draft.answers?.[q] ?? draft.answer ?? '';
      if(inputs[q].tagName==='FIELDSET') for(const box of inputs[q].querySelectorAll('input')) box.checked=Array.isArray(value)&&value.includes(box.value);
      else inputs[q].value=typeof value==='string'?value:'';
    } stake.value=String(betting?(draft.stake ?? 0):0);}} catch {sessionStorage.removeItem(draftKey);}
    const readAnswers=()=>Object.fromEntries(unit.questions.map(q=>[q,answerValue(inputs[q])]));
    const saveDraft=()=>{try {sessionStorage.setItem(draftKey,JSON.stringify({answers:readAnswers(),stake:Number(stake.value)}));} catch {notice('瀏覽器無法保存草稿，重新整理前請先複製答案。');}};
    for (const input of Object.values(inputs)) {input.oninput=saveDraft; input.onchange=saveDraft;} stake.onchange=saveDraft;
    card.onsubmit=event=>{
      event.preventDefault(); const requestActivity=activityId;
      const answers=readAnswers();
      for(const q of unit.questions) if(Array.isArray(answers[q]) && !answers[q].length) {notice(`第 ${q} 題請至少勾選一項。`); inputs[q].querySelector('input').focus(); return;}
      action(button,async()=>{
        pendingAnswers.add(unit.id); updateInputs();
        try {
          const grouped=unit.questions.length>1;
          const data=grouped?{unit:unit.id,answers,stake:Number(stake.value)}:
            {question:unit.questions[0],answer:answers[unit.questions[0]],stake:Number(stake.value)};
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
    const unitIndex=current.units.findIndex(u=>u.id===card.dataset.unit);
    const sequential=current.settings.mode==='sequential';
    const upcoming=current.phase==='preparing' || (sequential && unitIndex>current.round.round_index);
    const closed=current.phase==='results' || (sequential && (unitIndex<current.round.round_index || (unitIndex===current.round.round_index && !current.round.round_open)));
    card.classList.toggle('upcoming',upcoming);
    card.classList.toggle('sent',sent);
    const received=answers.get(card.dataset.question);
    card.querySelector('.question-status').textContent=sent?(received.submitted_by_me===false?'✓ 隊友已送出':'✓ 已交卷'):upcoming?'尚未開放':closed?'已關閉 · 未作答':'尚未送出';
    if (sent) {stake.value=answers.get(card.dataset.question).stake; sessionStorage.removeItem(card.dataset.draftKey);}
    for (const field of fields) {
      const answer=answers.get(field.dataset.question), input=field.querySelector('.answer-input'); input.disabled=disabled; input.hidden=!!answer;
      const saved=field.querySelector('.saved-answer'), time=field.querySelector('.answer-time'); saved.hidden=time.hidden=!answer;
      if (answer) {input.value=answer.text; saved.textContent=answer.text; time.textContent=`已於 ${timeText(answer.received_at)} 送出 · ${answerElapsedText(answer)} · ${verdictNames[answer.verdict]} · ${answer.stake===0?'不押':`下注 ${answer.stake} 分`}`;}
      if(answer?.points) time.textContent+=' · '+scoreParts(answer.points);
      const reference=field.querySelector('.published-reference'), text=current.references?.[field.dataset.question] || '';
      reference.hidden=!text; reference.querySelector('.reference-text').textContent=text;
    }
  }
}
function renderMonitor(state) {
  const selected=$('monitor-question').value, questions=selected?[selected]:state.questions;
  const key = JSON.stringify([state.groups, state.answers, questions, state.reviewable_questions]);
  if (lastMonitor === key) return; lastMonitor = key;
  $("monitor-summary").textContent = `${state.groups.length} 個小組已加入 · ${state.questions.length} 題 · 已收到 ${state.answers.length} 份答案`;
  const wrap = $("monitor-table"); wrap.replaceChildren();
  if (!state.groups.length) {wrap.append(el("p", auth?.course ? "還沒有小組進入活動。學生可從課程首頁進入。" : "還沒有小組加入。將上方活動代碼提供給同學即可加入。", "empty")); return;}
  const table = el("table"), thead = el("thead"), head = el("tr");
  const singleQuestion = questions.length === 1;
  head.append(el("th", singleQuestion ? "小組（先交卷在上）" : "小組")); for (const q of questions) head.append(el("th", `第 ${q} 題`)); thead.append(head);
  const body = el("tbody");
  const lookup = new Map(state.answers.map(a => [JSON.stringify([a.group_id,a.question_id]), a]));
  let groups = state.groups;
  if (singleQuestion) {
    const receipts = new Map(state.answers.filter(a => a.question_id === questions[0]).map(a => [a.group_id, a.id]));
    const receiptOrder = group => receipts.get(group.id) ?? Number.MAX_SAFE_INTEGER;
    groups = [...groups].sort((a, b) => receiptOrder(a) - receiptOrder(b));
  }
  for (const group of groups) {
    const row = el("tr"); row.append(el("th", group.name));
    for (const q of questions) {
      const cell = el("td"), answer = lookup.get(JSON.stringify([group.id,q]));
      if (answer) {
        cell.dataset.answerId=answer.id;
        const content=el('span',answer.text,'cell-answer');
        if(answer.text.length>300) {
          content.tabIndex=0;
          content.setAttribute('role','region');
          content.setAttribute('aria-label',`${group.name} 第 ${q} 題完整答案，可捲動閱讀`);
          cell.append(el('span','長答案，可上下捲動閱讀','answer-reading-hint'));
        }
        cell.append(content, el("small", `${timeText(answer.received_at)} · ${answerElapsedText(answer)} · ${answer.stake===0?'不押':`下注 ${answer.stake}`} · ${verdictNames[answer.verdict]}`));
        if(answer.points) cell.append(el('small',scoreParts(answer.points)));
        if(answer.author) cell.append(el('small','送出者　'+answer.author));
        if(answer.reviews?.length) {
          const history=el('details'); history.append(el('summary','批改紀錄（'+answer.reviews.length+'）'));
          for(const r of answer.reviews) history.append(el('small',new Date(r.stamp*1000).toLocaleString()+' · '+r.email+' · '+verdictNames[r.verdict]));
          cell.append(history);
        }
        if (state.reviewable_questions.includes(q)) {
          const controls = el("div", undefined, "review-controls");
          for (const verdict of ['correct','incorrect']) {
            const button = el('button', verdictNames[verdict], 'text-button'); button.dataset.verdict = verdict;
            button.setAttribute('aria-label', `${group.name} 第 ${q} 題判為${verdictNames[verdict]}`);
            button.disabled = answer.verdict === verdict;
            button.onclick = event => action(button,()=>classroomMotion.review(state.id,answer,verdict,event.detail===0));
            controls.append(button);
          }
          cell.append(controls);
          classroomMotion.mountReview(cell,answer);
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
  const selected=state.role==='teacher'?$('monitor-question').value:'';
  const key = JSON.stringify([state.results,selected]); if (lastResults === key) return; lastResults = key;
  const list = el("div", undefined, "results-list");
  for (const result of state.results) {
    if(selected && result.question_id!==selected) continue;
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
function renderLiveRanking(state) {
  const card=$('live-ranking'), rows=state.top_five;
  card.hidden=!rows;
  if(!rows) return;
  const list=$('live-ranking-rows');
  const key=JSON.stringify([state.id,rows,state.settings.mode,state.group_name]);
  if(list.dataset.values===key) return;
  list.dataset.values=key;
  const rule=state.settings.mode==='sequential' ? '累計本場已關題的得分' : '全題模式於本場結束時計分';
  $('live-ranking-hint').textContent=rows.length ? rule : '尚無小組加入本場。';
  list.replaceChildren(...rows.map(row=>{
    const item=el('li');
    const group=el('span',row.group_name);
    if(row.group_name===state.group_name) group.append(el('small','本組','ranking-own'));
    item.append(el('span',`第 ${row.rank} 名`),group,el('strong',`${row.score} 分`));
    return item;
  }));
}
function renderState(state) {
  const previous = current;
  current = state;
  activityChat.sync(state);
  renderLiveRanking(state);
  renderReplay(state);
  showView();
  const teacher = state.role === "teacher", ended = state.phase === "results";
  const provisional=ended && !state.grading.complete;
  $('grading-status').hidden=!ended;
  if(ended) {
    $('grading-message').textContent=provisional?`暫時成績 · ${state.grading.pending_answers} 筆待批改，分數與排名可能改變。`:'批改完成 · 所有答案皆已判定。';
    $('grading-status').classList.toggle('complete',!provisional);
    $('scoreboard').querySelector('h3').textContent=`小組得分排行（${provisional?'暫時成績':'批改完成'}）`;
    $('group-report').querySelector('h3').textContent=`本組學習報告（${provisional?'暫時成績':'批改完成'}）`;
  }
  $('grading-review').hidden=!teacher || !provisional;
  $('own-score').querySelector('span').textContent=provisional?'本組暫時成績':'本組目前總分';
  $('activity').classList.toggle('teacher-view',teacher);
  renderQuestionSettings(state);
  $('own-score').hidden=teacher;
  const rule=state.speed_scoring?'前三組答對依序加 4、2、1 搶答分，不押也能搶分。':'本場沿用舊制，不計搶答分。';
  $('speed-rule').textContent=rule;
  $('ranking-rule').textContent='答對加押注分，答錯扣押注分；題組只計一次，全對才算答對。'+rule+' 同總分同名次。';
  if (!teacher) {
    $('own-score-parts').textContent=scoreParts(state.own_points);
    $('own-score-total').textContent=`${state.own_score.total} 分`;
    const waiting=[];
    if(state.own_score.awaiting_close_units) waiting.push(`已送出 ${state.own_score.awaiting_close_units} 題，等待${state.settings.mode==='sequential'?'本題':'搶答'}結束`);
    if(state.own_score.pending_units) waiting.push(`${state.own_score.pending_units} 題待批改`);
    $('own-score-pending').textContent=waiting.join(' · ');
    $('own-score-pending').hidden=!waiting.length;
  }
  $('scoreboard').hidden=!ended;
  if (ended && $('scoreboard').dataset.values!==JSON.stringify([state.id,state.scoreboard,provisional])) {
    $('scoreboard').dataset.values=JSON.stringify([state.id,state.scoreboard,provisional]);
    const table=el('table'), head=el('tr'); head.append(el('th','名次'),el('th','組別'),el('th','押注分'),el('th','搶答分'),el('th',provisional?'暫時總分':'總分')); table.append(head);
    for (const score of state.scoreboard) {
      const row=el('tr'), group=el('th');
      if (!provisional && score.rank<=3) {
        row.dataset.podium=score.rank;
        const slip=el('span',score.group_name,'podium-slip');
        if (score.rank===1) {
          const star=el('span','☆','rank-star'); star.setAttribute('aria-hidden','true'); slip.append(star);
        }
        group.append(slip);
      } else group.textContent=score.group_name;
      row.append(el('td',score.rank),group,el('td',score.wager),el('td',score.speed),el('td',score.score));
      table.append(row);
    }
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
  const code = auth?.course || state.code;
  const block = $('session-code-block');
  if (block.dataset.value !== code) {
    block.dataset.value = code;
    block.replaceChildren(createShareCode(auth?.course?'課程代碼':'活動代碼',code,'session-code'),
      el('p',auth?.course?'從課程首頁加入小組，再選擇本場活動。':'讓同學在另一個分頁輸入此代碼。'));
  }
  $("session-subtitle").textContent = teacher ? `${state.questions.length} 道題目 · ${state.groups.length} 個小組已加入` : `${state.questions.length} 道題目`;
  $("role-badge").textContent = teacher ? (auth?.assistant?"助教":"教師") : state.group_name;
  $("teacher-controls").hidden = !teacher || ended || auth?.assistant;
  $("start").hidden = state.phase !== "preparing";
  $("end").hidden = state.phase !== "active";
  $("phase-label").textContent = phaseNames[state.phase]; $("phase-label").className = "phase-pill " + state.phase;
  if(ended) $('phase-label').textContent='作答結束';
  else if(state.phase==='active' && state.settings.mode==='sequential') {
    $('phase-label').textContent=state.round.round_open?'本題作答中':'本題已關閉';
    $('phase-label').classList.toggle('active',!!state.round.round_open);
  }
  for (const step of document.querySelectorAll(".phase-steps li")) {
    step.classList.toggle("current", step.dataset.phase === state.phase);
    if (step.dataset.phase === state.phase) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current");
  }
  $("session-rule").textContent = teacher ? "每組每題以第一筆有效答案為準。作答中請勿向學生投影此頁，以免公開他組答案。" : "每題由小組共同送出一份答案。送出後不能修改；結果公布前看不到其他組別的作答。";
  $("content-title").textContent = ended ? "本次搶答成果" : teacher ? "小組作答狀況" : "本組作答區";
  $("phase-help").textContent = ended ? "搶答成功代表最快且未判錯，請一併查看判定。" : state.phase === "preparing" ? "等待老師開始，作答區會自動開放。" : teacher ? "答案會自動更新。" : "每組送出一份答案，送出後不能修改。";
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
  if (state.priority_sources) {
    const select = $('priority-source');
    const choices = JSON.stringify(state.priority_sources);
    const editing = $('settings-form').dataset.dirty === 'true';
    const selected = editing ? select.value : state.settings.priority_source;
    if (select.dataset.choices !== choices) {
      const options = state.priority_sources.map(source => {
        const date = new Date(source.ended_at * 1000).toLocaleString('zh-TW');
        return new Option(`${source.title}（${date}）`, source.id);
      });
      select.replaceChildren(select.options[0], ...options);
      select.dataset.choices = choices;
    }
    select.value = selected || '';
    if (!editing) $('use-priority-source').checked = !!selected;
  }
  syncPrioritySetup();
  const sequential = state.settings.mode === "sequential";
  classroomMotion.countdown(state);
  $("round-controls").hidden = !teacher || auth?.assistant || !sequential || state.phase !== "active";
  $("close-round").hidden = !state.round.round_open;
  $("next-round").hidden = !!state.round.round_open;
  const priorityLeft = Math.max(0, Math.ceil(state.round.priority_until - state.server_time));
  const priorityActive = priorityLeft > 0 && state.phase === 'active' && (!sequential || state.round.round_open);
  const status = [];
  if (sequential) status.push(state.round.unit_id === null ? "逐題模式：老師開始後開放第一題。" :
    `目前第 ${state.round.unit_id} 題 · ${state.round.round_open && !ended ? "作答中" : "已關閉"}`);
  if (priorityActive) {
    status.push(`保底先答剩 ${priorityLeft} 秒`);
    if (!teacher) status.push(state.round.own_priority ? '本組可先答' : '請等倒數結束後作答');
  }
  $("round-status").hidden = !status.length || ended || (teacher && state.phase==='preparing');
  $("round-status").textContent = status.join(' · ');
  classroomMotion.priority(state,priorityActive);
  $("sheet-export-controls").hidden = !teacher || !state.source;
  if (teacher && state.source) {
    const sync=state.source.sync || {state:'idle',message:'關題後自動同步學習單。'};
    $("source-name").textContent = state.source.sheet_title;
    $('sheet-sync-status').textContent=sync.message;
    $('sheet-sync-status').dataset.state=sync.state;
    $('sheet-sync-help').hidden=sync.state==='readonly';
    $("source-link").href = state.source.url;
    $("sheet-export").hidden = !['error','needs_auth'].includes(sync.state);
    $("sheet-export").textContent = '重試同步';
  }
  if (teacher) {syncMonitorFilter(state); renderMonitor(state);} else renderCards(state);
  if (ended) renderResults(state);
  renderTeacherWorkspace(state);
  updateInputs();
  classroomMotion.submitted(previous,state);
  classroomMotion.standings(previous,state);
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
const referenceDrafts = new Map();
let referenceActivity = '';
function referenceDraft(state, q) {
  const key=`${state.id}:${q}`;
  if(!referenceDrafts.has(key)) referenceDrafts.set(key,{answer:'',override:false,dirty:false,saving:false});
  const draft=referenceDrafts.get(key);
  if(!draft.dirty && !draft.saving) {
    draft.answer=state.references[q] || '';
    draft.override=!!state.reference_overrides[q];
  }
  return draft;
}
function renderTeacherReference(state) {
  const questions=state.reviewable_questions;
  if(!questions.length) return;
  const q=$('monitor-question').value, activityChanged=referenceActivity!==state.id;
  if(activityChanged) $('references').open=false;
  referenceActivity=state.id;
  const available=questions.includes(q);
  $('reference-form').hidden=!available;
  $('reference-selection-help').hidden=available;
  if(!available) {
    $('reference-summary').textContent='老師正確答案（選填）';
    $('reference-selection-help').textContent=q?'此題尚未結束，關題後才能填寫老師答案。':'請在上方選擇一個已結束的題目，再填寫老師答案。';
    return;
  }
  const draft=referenceDraft(state,q);
  if($('reference-answer').value!==draft.answer) $('reference-answer').value=draft.answer;
  $('reference-override').checked=draft.override;
  $('reference-override-field').hidden=!state.source;
  $('reference-sheet-help').hidden=!state.source;
  $('reference-sheet-help').textContent=state.source?'取消勾選並儲存，恢復最快未判錯組的答案；無有效答案則還原原值。':'';
  $('reference-summary').textContent=`第 ${q} 題 · 老師正確答案（選填）`;
  $('reference-save').disabled=draft.saving;
  $('reference-status').textContent=draft.saving?'儲存中…':draft.dirty?'尚未儲存':draft.answer?(draft.override?'已儲存 · 已指定用於學習單':'已儲存 · 學生可見'):'';
}
function captureReferenceDraft() {
  if(current?.role!=='teacher') return;
  const draft=referenceDraft(current,$('monitor-question').value);
  draft.answer=$('reference-answer').value; draft.override=$('reference-override').checked; draft.dirty=true;
  renderTeacherReference(current);
}
$('reference-answer').oninput=captureReferenceDraft;
$('reference-override').onchange=captureReferenceDraft;
$('reference-form').onsubmit=event=>{
  event.preventDefault();
  const state=current, q=$('monitor-question').value, draft=referenceDraft(state,q);
  if(!state.reviewable_questions.includes(q)) {notice('請先選擇一個已結束的題目。');return;}
  const answer=draft.answer, override=draft.override;
  if(override && !answer.trim()) {notice('請先填寫老師答案，再勾選更新學習單。');$('reference-answer').focus();return;}
  action($('reference-save'),async()=>{
    draft.saving=true; renderTeacherReference(state);
    try {
      await api(`/api/activities/${state.id}/reference`,{question:q,answer,override});
      if(draft.answer===answer && draft.override===override) {draft.answer=answer.trim();draft.dirty=false;}
      notice(override?'老師答案已儲存，學習單將自動同步。':'老師答案已儲存。',true);
      await refresh();
    } finally {draft.saving=false;if(current?.id===state.id) renderTeacherReference(current);}
  });
};
$("download-report").onclick = () => action($("download-report"),()=>downloadFile(`/api/activities/${activityId}/report`, '本組學習報告.csv'));
function renderReport(state) {
  const ended=state.phase==='results', teacher=state.role==='teacher';
  $('group-report').hidden=!ended || teacher;
  if (!ended) return;
  if (!teacher) {
    const key=JSON.stringify([state.id,state.report]); if (key===reportKey) return; reportKey=key;
    const table=el('table'), head=el('tr');
    for (const title of ['題號','本組答案','判定','下注','押注分','搶答分','單位合計','搶答成功','參考答案']) head.append(el('th',title));
    table.append(head);
    for (const r of state.report) {const row=el('tr'); for (const value of [r.question,r.answer,verdictNames[r.verdict],r.stake??'—',r.wager??'—',r.speed??'—',r.points??'同題組',r.successful?'是':'否',r.reference||'老師尚未填寫']) row.append(el('td',value)); table.append(row);}
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
      const prompt=el('textarea'), promptLabel=el('label',`第 ${q} 題的題目內容（選填）`);
      prompt.id=`prompt-${index}-${childIndex}`; promptLabel.htmlFor=prompt.id; prompt.rows=3;
      prompt.defaultValue=config.prompt || ''; prompt.placeholder='輸入要讓學生閱讀的題目'; box.append(promptLabel,prompt);
      const kind=el('select'), label=el('label',`第 ${q} 題的題型`); kind.id=`question-type-${index}-${childIndex}`; kind.className='question-type'; label.htmlFor=kind.id;
      for (const [value,title] of [['short','簡答（人工批改）'],['choice','單選（自動判分）'],['multiple','多選（全部選對才得分）']]) {const option=el('option',title); option.value=value; kind.append(option);}
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
      const keys=el('fieldset',undefined,'multi-checks'), rebuildKeys=selected=>fillChecks(keys,lines(),selected,'勾選全部正確選項（僅老師可見）');
      rebuildKeys((config.correct_indices||[]).map(i=>config.options[i]));
      const toggle=()=>{choiceBox.hidden=options.disabled=kind.value==='short'; options.required=!options.disabled; correctLabel.hidden=correct.hidden=correct.disabled=kind.value!=='choice'; correct.required=!correct.disabled; keys.hidden=keys.disabled=kind.value!=='multiple';};
      kind.onchange=toggle; options.oninput=()=>{rebuild();rebuildKeys(checkedOptions(keys));}; toggle();
      choiceBox.append(optionLabel,options,correctLabel,correct,keys); box.append(choiceBox); fields.append(box);
      configs.push({q,kind,lines,correct,prompt,keys});
    }
    const status=el('p','設定已儲存','field-hint');
    const summarize=()=>{description.textContent=`${configs.map(c=>({choice:'單選',multiple:'多選',short:'簡答'})[c.kind.value]).filter((v,i,a)=>a.indexOf(v)===i).join('＋')} · ${betting.checked?'可下注':'不押分'}`;};
    const dirty=()=>{form.dataset.dirty='true'; status.textContent='尚未儲存，開始前會一起儲存'; summarize(); updateSetupStatus();}; form.oninput=dirty; form.onchange=dirty; summarize();
    fields.append(status); form.append(fields);
    form.prepareSettings=()=>{
      const questions=configs.map(c=>({question:c.q,type:c.kind.value,options:c.kind.value==='short'?[]:c.lines(),correct_index:c.correct.value===''?null:Number(c.correct.value),correct_indices:checkedOptions(c.keys).map(v=>c.lines().indexOf(v))}));
      configs.forEach((c,i)=>{if(c.prompt.value!==c.prompt.defaultValue) questions[i].prompt=c.prompt.value;});
      for (const q of questions) if(q.type!=='short' && (q.options.length<2 || q.options.length>8 || q.options.some(x=>x.length>200) || new Set(q.options).size!==q.options.length || (q.type==='multiple'?!q.correct_indices.length:q.correct_index===null || q.correct_index>=q.options.length))) {
        showTeacherView('questions'); details.open=true; const box=form.querySelector(`[data-question="${CSS.escape(q.question)}"]`); box.scrollIntoView({block:'center'}); box.querySelector(q.type==='choice' && q.correct_index===null?'.choice-correct':'.choice-options').focus();
        throw new Error(`第 ${q.question} 題：請填寫 2～8 個不重複選項（每項最多 200 字），並指定正確選項。`);
      }
      return {unit:unit.id,betting_enabled:betting.checked,questions};
    };
    form.persistSettings=async payload=>{
      try {await api(`/api/activities/${state.id}/question-settings`,payload); configs.forEach((c,i)=>{if ('prompt' in payload.questions[i]) c.prompt.defaultValue=payload.questions[i].prompt;}); form.dataset.dirty='false'; status.textContent='設定已儲存'; updateSetupStatus();}
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
  syncPrioritySetup();
  if(!sequential) $('quiz-fairness').checked=false;
  $('mode-help').textContent=sequential?'一次開放一題，由你控制關題與下一題。':'開始後所有題目一起開放，學生自行選題作答。';
}
function syncPrioritySetup() {
  const sources=current?.priority_sources;
  const rule=$('priority-rule-field'), toggle=$('use-priority-source'), select=$('priority-source');
  rule.hidden=$('quiz-mode').value!=='all' || !sources;
  if (!sources?.length) toggle.checked=false;
  toggle.disabled=savingSettings || !sources?.length;
  const enabled=!rule.hidden && toggle.checked;
  $('priority-source-field').hidden=!enabled;
  select.disabled=savingSettings || !enabled;
  select.required=enabled;
  if (rule.hidden) return;
  const source=sources.find(item=>item.id===select.value);
  let help='各組同時開始作答。';
  if (!sources.length) help='這門課還沒有已結束的活動可供參考，各組會同時開始。';
  else if (enabled && !source) help='可以選這門課中任何一場已結束的活動。';
  else if (enabled) help=`開場時，只比較已進入「${current.title}」且參加過「${source.title}」的小組。其中在「${source.title}」總分最低的小組先答 3 秒，並列最低的都可先答。`;
  const hint=$('priority-rule-help');
  if (hint.textContent!==help) hint.textContent=help;
}
function updateSetupStatus() {
  const count=document.querySelectorAll('.question-config-form[data-dirty="true"]').length;
  const dirty=$('settings-form').dataset.dirty==='true' || count>0;
  $('setup-status').textContent=dirty?'尚未儲存 · 按「開始搶答」也會一起儲存。':'設定已儲存，可以開始搶答。';
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
  for(const id of ['replay','classification']) $(`tool-${id}`).hidden=true;
  $('result-actions').hidden=true;
  $('references').hidden=true;
  $('teacher-question-filter').hidden=true;
  if(!teacher) return;
  const key=state.id+state.phase;
  if(teacherViewKey!==key) {
    teacherViewKey=key;
    const openReview=location.hash==='#review-'+state.id;
    teacherView=(auth?.assistant || openReview)?'monitor':preparing?'settings':ended?'results':'monitor';
  }
  const allowed=preparing?(auth?.assistant?['monitor']:['settings','questions','monitor']):ended?['results','monitor','tools']:['monitor','tools'];
  const pending=state.answers.filter(a=>a.verdict==='pending' && state.reviewable_questions.includes(a.question_id)).length;
  for(const button of $('teacher-tabs').children) {
    button.hidden=!allowed.includes(button.dataset.view);
    button.setAttribute('aria-current',button.dataset.view===teacherView?'page':'false');
    if(button.dataset.view==='monitor') button.textContent=preparing?`已加入小組（${state.groups.length}）`:`作答與批改${pending?`（${pending} 待批改）`:''}`;
  }
  const sections={settings:['settings-form'],questions:['question-settings'],monitor:['teacher-monitor'],results:['results','scoreboard','result-actions'],tools:[]};
  for(const id of ['settings-form','question-settings','teacher-monitor','results','scoreboard','result-actions']) $(id).hidden=!sections[teacherView]?.includes(id);
  $('content-title').textContent={settings:'1. 設定活動方式',questions:'2. 設定題目與計分',monitor:preparing?'等待小組加入':'查看作答與批改',results:'本次搶答成果',tools:'更多教學工具'}[teacherView];
  $('phase-help').textContent={settings:'選擇開放方式與時間，再設定題目。',questions:'單選與多選自動批改；簡答由老師批改。開始後不能修改設定。',monitor:preparing?'分享活動代碼；同組使用相同組名。':'答案自動更新，關題後可批改。',results:'選題查看成功答案，全部組別總分列於下方。',tools:'選擇需要的工具展開。'}[teacherView];
  $('grading-review').hidden=!ended || !pending || teacherView==='monitor';
  $('monitor-privacy').hidden=preparing;
  for(const id of ['replay','classification']) $(`tool-${id}`).hidden=teacherView!=='tools' || (id!=='classification' && !ended);
  renderTeacherReference(state);
  $('teacher-question-filter').hidden=preparing || !['monitor','results'].includes(teacherView);
  $('references').hidden=!state.reviewable_questions.length || !['monitor','results'].includes(teacherView);
  $('download-csv').hidden=!ended; $('sheet-export-controls').hidden=!state.source;
  $('end').textContent=state.settings.mode==='sequential'?'提早結束整場':'結束搶答並公布結果';
  updateSetupStatus();
  if (auth?.course && preparing && teacherView==='monitor') $('phase-help').textContent='學生加入課程小組後，可從活動清單進入。';
  if (auth?.assistant) {
    for(const id of ['setup-status','result-actions','references','sheet-export-controls','tool-replay']) $(id).hidden=true;
  }
}
function activitySettingsPayload() {
  if(!$('quiz-duration').checkValidity()) {showTeacherView('settings'); $('quiz-duration').focus(); $('quiz-duration').reportValidity(); throw new Error('作答時間請填 0～3600 的整數秒。');}
  const mode = $('quiz-mode').value;
  const select = $('priority-source');
  if (!select.checkValidity()) {
    showTeacherView('settings'); select.focus(); select.reportValidity();
    throw new Error('請選擇要參考的活動，或取消「讓低分組先答 3 秒」。');
  }
  const source = mode==='all' && $('use-priority-source').checked ? select.value : '';
  return {mode, fairness:$('quiz-fairness').checked, duration_seconds:Number($('quiz-duration').value), priority_source:source || null};
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
  if(monitorFollow) $('monitor-question').value=state.settings.mode==='sequential' && state.round.unit_id!==null ? state.units.find(u=>u.id===state.round.unit_id)?.questions[0] || '' : '';
}
$('create-panel').append($('sheets-create'));
$('source-manual').onclick=()=>setCreateSource('manual'); $('source-sheets').onclick=()=>setCreateSource('sheets');
$('custom-questions').ontoggle=syncQuestionInput;
$('go-questions').onclick=()=>showTeacherView('questions');
for(const button of $('teacher-tabs').children) button.onclick=()=>showTeacherView(button.dataset.view);
$('monitor-question').onchange=()=>{monitorFollow=false;renderMonitor(current);renderTeacherReference(current);if(current.phase==='results')renderResults(current);};
$('settings-form').oninput=$('settings-form').onchange=()=>{$('settings-form').dataset.dirty='true'; updateSetupStatus();};
$('save-settings').onclick=()=>action($('save-settings'),async()=>{
  if(savingSettings) return;
  window.courseNav.revealActivity();
  await saveAllSettings(); notice('所有設定已儲存。',true); await refresh();
});
$('result-actions').append($('download-csv'));
$('teacher-tabs').after($('sheet-export-controls'));
for(const [id,title] of [['replay','重播搶答過程'],['classification','比較相似答案']]) {
  const section=$(id), wrapper=el('details',undefined,'tool-disclosure panel'); wrapper.id=`tool-${id}`; wrapper.hidden=true;
  const summary=el('summary',title); section.before(wrapper); wrapper.append(summary,section);
}

$('own-score').before($('references'));

$('references').before($('teacher-question-filter'));
$('grading-review').onclick=()=>{const q=current.answers.find(a=>a.verdict==='pending')?.question_id;if(q){monitorFollow=false;$('monitor-question').value=q;showTeacherView('monitor');renderMonitor(current);}};
