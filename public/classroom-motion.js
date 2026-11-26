/* Feedback for confirmed classroom actions. The polling renderer owns the data. */
const classroomMotion = (() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let receipt = null, sequence = 0, lastConfirmed = 0;
  let priorityKey = '', priorityTimer = 0;
  let countdownKey = '', countdownTimer = 0, answerEndsAt = 0, expiryAction = '';
  let podiumObserver = null, podiumPlayed = false;
  const soundToggle = document.getElementById('countdown-sound-enabled');
  const soundSetting = document.getElementById('countdown-sound-setting');
  const previewButton = document.getElementById('countdown-sound-preview');
  const soundNote = document.getElementById('countdown-sound-error');
  const Audio = window.AudioContext || window.webkitAudioContext;
  const soundPreference = 'classroom.countdownSound';
  try { soundToggle.checked = localStorage.getItem(soundPreference)!=='muted'; } catch { /* Use the page default. */ }
  let soundContext = null, bufferLoad = null, countdownBuffer = null, playing = null;
  let preview = null, previewRequest = 0, soundFailed = false;

  function updateSoundControls() {
    previewButton.disabled = !soundToggle.checked;
    let hint = '';
    if (soundToggle.checked && soundFailed) hint = '音效載入失敗，請按「試聽倒數音效」重試。';
    else if (soundToggle.checked && soundContext?.state!=='running') hint = '點一下畫面即可啟用聲音，也可以先試聽。';
    if (soundNote.textContent!==hint) soundNote.textContent = hint;
    soundNote.hidden = !hint;
  }
  function stopPreview() {
    previewRequest++;
    if (!preview) return;
    preview.stop();
    preview.disconnect();
    preview = null;
  }

  function stopCountdownSound() {
    if (!playing) return;
    playing.stop();
    playing.disconnect();
    playing = null;
  }
  function syncCountdownSound(remaining = (answerEndsAt-performance.now())/1000) {
    if (document.hidden || !soundToggle.checked || soundContext?.state!=='running') {
      stopCountdownSound();
      return;
    }
    if (playing || !countdownKey || remaining<=0 || remaining>3 || !countdownBuffer) return;
    stopPreview();
    // The first three seconds count down; the final chime rings beyond the deadline.
    const source = soundContext.createBufferSource();
    playing = source;
    source.buffer = countdownBuffer;
    source.connect(soundContext.destination);
    source.onended = () => {
      if (playing===source) { source.disconnect(); playing = null; }
    };
    source.start(0,3-remaining);
  }
  function closeAudio() {
    stopPreview();
    stopCountdownSound();
    const context = soundContext;
    soundContext = null;
    countdownBuffer = null;
    bufferLoad = null;
    if (context) {
      context.onstatechange = null;
      context.close().catch(()=>{});
    }
  }
  async function loadCountdownSound(context) {
    const response = await fetch('/electronic-countdown.wav');
    if (!response.ok) throw Error('Countdown audio unavailable');
    return context.decodeAudioData(await response.arrayBuffer());
  }
  async function prepareAudio() {
    let context;
    try {
      context = soundContext || (soundContext = new Audio());
      context.onstatechange = () => { updateSoundControls(); syncCountdownSound(); };
      const resumed = context.state==='running' ? undefined : context.resume();
      // Unlock on the join/start gesture, even if the timed activity state is still arriving.
      if (!soundSetting.hidden) bufferLoad ??= loadCountdownSound(context);
      updateSoundControls();
      const [,buffer] = await Promise.all([resumed,bufferLoad]);
      if (context!==soundContext) return false;
      if (buffer) countdownBuffer = buffer;
      updateSoundControls();
      syncCountdownSound();
      return !!countdownBuffer && context.state==='running';
    } catch {
      if (context && context!==soundContext) return false;
      closeAudio();
      soundFailed = true;
      updateSoundControls();
      return false;
    }
  }
  function unlockOnInteraction(event) {
    if (!Audio || !event.isTrusted || event.target.closest?.('#countdown-sound-setting label, #countdown-sound-preview') || !soundToggle.checked || soundFailed) return;
    if (soundContext?.state!=='running') prepareAudio();
  }
  document.addEventListener('click',unlockOnInteraction,true);
  document.addEventListener('keydown',unlockOnInteraction,true);
  soundToggle.onchange = () => {
    try { localStorage.setItem(soundPreference,soundToggle.checked?'on':'muted'); } catch { /* Applies in this tab. */ }
    soundFailed = false;
    if (soundToggle.checked) prepareAudio();
    else closeAudio();
    updateSoundControls();
  };
  previewButton.onclick = async () => {
    stopPreview();
    const request = previewRequest;
    const atDeadline = countdownKey && answerEndsAt-performance.now()<=3000;
    soundFailed = false;
    if (!await prepareAudio() || atDeadline || request!==previewRequest || document.hidden || soundSetting.hidden || playing) return;
    const source = soundContext.createBufferSource();
    preview = source;
    source.buffer = countdownBuffer;
    source.connect(soundContext.destination);
    source.onended = () => {
      if (preview===source) { source.disconnect(); preview = null; }
    };
    source.start(0,0,countdownBuffer.duration);
  };
  function pauseCountdown() {
    clearTimeout(countdownTimer);
    stopPreview();
    stopCountdownSound();
  }
  function tickCountdown() {
    clearTimeout(countdownTimer);
    if (document.hidden) {pauseCountdown(); return;}
    if (!countdownKey) return;
    const ms = Math.max(0,answerEndsAt-performance.now());
    const seconds = Math.ceil(ms/1000);
    $('countdown').textContent = `剩餘 ${seconds} 秒 · 到期自動${expiryAction}`;
    syncCountdownSound(ms/1000);
    if (seconds>0) countdownTimer = setTimeout(tickCountdown,Math.ceil(ms-(seconds-1)*1000));
  }
  function countdown(state,previous) {
    const timed = state.settings.duration_seconds>0;
    const sequential = state.settings.mode==='sequential';
    const {deadline,round_index,round_open} = state.round;
    const hideSound = !Audio || !timed || state.phase==='results';
    if (hideSound!==soundSetting.hidden) {
      soundSetting.hidden = hideSound;
      if (hideSound) stopPreview();
      else if (soundToggle.checked && !soundFailed) prepareAudio();
      updateSoundControls();
    }
    const active = timed && state.phase==='active' && Number.isFinite(deadline) && (!sequential || round_open);
    $('countdown').hidden = !active;
    const key = active ? `${state.id}/${round_index}/${deadline}` : '';
    if (key===countdownKey) return;
    clearTimeout(countdownTimer);
    stopPreview();
    const priorDeadline = previous?.round.deadline;
    const expired = !active && timed && previous?.id===state.id && previous.round.round_index===round_index &&
      Number.isFinite(priorDeadline) && (state.ended_at ?? state.server_time)>=priorDeadline;
    if (!expired) stopCountdownSound();
    countdownKey = key;
    if (!active) return;
    answerEndsAt = performance.now()+(deadline-state.server_time)*1000;
    expiryAction = sequential?'關閉本題':'公布結果';
    tickCountdown();
  }
  document.addEventListener('visibilitychange',tickCountdown);
  window.addEventListener('pagehide',pauseCountdown);
  window.addEventListener('pageshow',tickCountdown);

  function animate(node, frames, duration, delay=0, easing='cubic-bezier(.2,.75,.25,1)') {
    if (reduced.matches || !node.animate) return null;
    return node.animate(frames, {duration, delay, easing, fill:'backwards'});
  }
  function reset() {
    receipt?.node.remove();
    receipt = null;
    stopPriority();
    countdownKey = '';
    pauseCountdown();
    $('countdown').hidden = true;
    soundSetting.hidden = true;
    soundFailed = false;
    podiumObserver?.disconnect();
    podiumObserver = null;
    podiumPlayed = false;
  }
  function mountReview(cell, answer) {
    if (receipt?.answer.id !== answer.id || receipt.activity !== activityId) return;
    if (answer.review_revision > receipt.revision) { receipt = null; return; }
    cell.append(receipt.node);
  }
  function playReview(ticket) {
    const stage = ticket.node.querySelector('.review-stage');
    if (reduced.matches || !stage.animate || !stage.getClientRects().length) return;
    if (ticket.effect === 'stamp') {
      stampAnimation(stage.querySelector('.verdict-stamp'));
      return;
    }
    if (!['erase','restore'].includes(ticket.effect)) return;
    const scene = el('div',undefined,'erase-scene');
    scene.setAttribute('aria-hidden','true');
    const writing = el('span',undefined,'chalk-answer');
    writing.append(el('b',ticket.answer.group_name), el('span',ticket.answer.text));
    scene.append(writing);
    stage.append(scene);
    const erasing = ticket.effect==='erase';
    const duration = erasing ? 1650 : 850;
    if (erasing) {
      const sweep = el('span',undefined,'eraser-sweep');
      sweep.append(el('span',undefined,'board-eraser'));
      scene.append(sweep);
      // The eraser's centre and the edge of the remaining writing share the same coordinate.
      animate(sweep,[
        {transform:'translate(145%, -19%)'}, {transform:'translate(145%, -19%)',offset:.28},
        {transform:'translate(100%, 0)',offset:.47}, {transform:'translate(0, 0)',offset:.85},
        {transform:'translate(-45%, 12%)'}
      ],duration,0,'linear');
      animate(writing,[
        {clipPath:'inset(0)'}, {clipPath:'inset(0)',offset:.47},
        {clipPath:'inset(0 100% 0 0)',offset:.85}, {clipPath:'inset(0 100% 0 0)'}
      ],duration,0,'linear');
    } else {
      animate(writing,[{clipPath:'inset(0 100% 0 0)'},{clipPath:'inset(0)',offset:.50},{clipPath:'inset(0)'}],duration,0,'ease-out');
    }
    animate(scene,[{opacity:1},{opacity:1,offset:.86},{opacity:0}],duration,0,'linear')
      .finished.catch(()=>{}).finally(()=>scene.remove());
  }

  async function present(ticket, order, session, keyboard) {
    if (session !== generation || order < lastConfirmed) return;
    lastConfirmed = order;
    receipt?.node.remove();
    receipt = ticket;
    const node = ticket.node = el('div',undefined,'review-receipt');
    const stage = el('div',undefined,'review-stage');
    stage.dataset.effect = ticket.effect;
    stage.setAttribute('role','status');
    stage.append(el('span',ticket.caption,'review-caption'));
    if (ticket.message) stage.append(el('strong',ticket.message,ticket.effect==='stamp'?'verdict-stamp':'review-outcome'));
    node.append(stage);
    if (ticket.batch) {
      const undo = el('button','復原這筆判定','text-button review-revert');
      undo.onclick = event => action(undo,async()=>{
        const undoOrder = ++sequence;
        await api(`/api/activities/${ticket.activity}/review-undo`,{batch_id:ticket.batch});
        await present({...ticket, batch:null, revision:ticket.revision+1, caption:'已復原',
          message:verdictNames[ticket.answer.verdict], effect:ticket.effect==='erase'?'restore':''},undoOrder,session,event.detail===0);
      });
      node.append(undo);
    }
    await refresh();
    if (generation !== session || receipt !== ticket) return;
    const cell = $('monitor-table').querySelector(`[data-answer-id="${ticket.answer.id}"]`);
    if (cell && current?.role==='teacher') {
      cell.append(node);
      if (ticket.effect==='erase' && node.getClientRects().length) {
        node.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
      }
      playReview(ticket);
      if (keyboard && document.activeElement===document.body && cell.getClientRects().length) {
        const next = node.querySelector('.review-revert') || cell.querySelector('.review-controls button:enabled');
        next?.focus({preventScroll:true});
      }
    }
  }
  async function review(activity, answer, verdict, keyboard) {
    const session = generation, order = ++sequence;
    const result = await api(`/api/activities/${activity}/review`,{answer_id:answer.id,verdict,revision:answer.review_revision});
    const next = result.candidate;
    const incorrect = verdict==='incorrect';
    const caption = incorrect ? `${answer.group_name} 判錯` : '單筆批改';
    let message = verdict==='pending'?'已改回待判定':incorrect?'':'正解';
    if (result.displaced) message = next ? `遞補：${next.group_name} · ${verdictNames[next.verdict]}` : '沒有其他候選答案';
    await present({activity,answer,batch:result.batch_id,revision:answer.review_revision+1,caption,message,
      effect:verdict==='pending'?'':incorrect?'erase':'stamp'},order,session,keyboard);
  }
  function stopPriority() {
    clearTimeout(priorityTimer);
    priorityKey = '';
    const track = $('priority-track');
    track.hidden = true;
    track.firstElementChild.getAnimations().forEach(a=>a.cancel());
  }
  function priority(state, active) {
    if (!active || state.role!=='student') {
      if (priorityKey) stopPriority();
      return;
    }
    const key = state.id+'/'+state.round.priority_until;
    if (key===priorityKey) return;
    stopPriority();
    priorityKey = key;
    const track = $('priority-track'), line = track.firstElementChild;
    track.hidden = false;
    const remaining = Math.max(0,Math.min(3000,(state.round.priority_until-state.server_time)*1000));
    if (!reduced.matches) line.animate([{transform:`scaleX(${remaining/3000})`},{transform:'scaleX(0)'}],
                                      {duration:remaining, easing:'linear', fill:'forwards'});
    priorityTimer = setTimeout(()=>{if(priorityKey===key) refresh();},Math.ceil(remaining)+10);
  }
  function submitted(previous,state) {
    if (state.role!=='student' || previous?.id!==state.id || state.phase!=='active' ||
        previous.answers.length===state.answers.length) return;
    const before = new Set(previous.answers.map(a=>a.question_id));
    for (const card of $('student-questions').children) {
      if (before.has(card.dataset.question) || !card.classList.contains('sent')) continue;
      animate(card.querySelector('.question-status'), [
        {transform:'scale(1.25) rotate(-7deg)',opacity:.35},{transform:'scale(.95)',offset:.7},{transform:'none'}
      ],300);
    }
  }
  function stampAnimation(stamp) {
    animate(stamp, [
      {transform:'scale(1.14) rotate(-9deg)', opacity:0},
      {transform:'scale(.94) rotate(-5deg)', opacity:1, offset:.55},
      {transform:'scale(1) rotate(-5deg)'}
    ], 490);
  }
  function studentVerdicts(previous,state) {
    if(state.role!=='student' || previous?.id!==state.id || reduced.matches) return;
    const before=new Map(previous.answers.map(a=>[a.question_id,a.verdict]));
    const changed=state.answers.filter(a=>before.get(a.question_id)!==a.verdict);
    if(!changed.length) return;
    const questions=new Set(changed.map(a=>a.question_id));
    const entries=state.phase==='results'?$('report-table'):$('student-questions');
    for(const stamp of entries.querySelectorAll('.student-stamp:not([hidden])')) {
      if(questions.has(stamp.closest('[data-question]').dataset.question)) stampAnimation(stamp);
    }
  }
  function standings(previous,state) {
    const final = state.phase==='results' && state.grading.complete;
    if (!final) {podiumObserver?.disconnect(); podiumObserver=null; return;}
    if (!previous || previous.id!==state.id) podiumPlayed=true;
    if (podiumPlayed || podiumObserver) return;
    podiumObserver = new IntersectionObserver((entries,observer)=>{
      if (podiumObserver!==observer || !entries.some(entry=>entry.isIntersecting)) return;
      observer.disconnect(); podiumObserver=null; podiumPlayed=true;
      for (const row of $('scoreboard-table').querySelectorAll('[data-podium]')) {
        const delay = (3-Number(row.dataset.podium))*90;
        animate(row.querySelector('.podium-slip'),[{transform:'translate(-12px,3px) rotate(-3deg)',opacity:.2},{transform:'none',opacity:1}],320,delay);
        const star = row.querySelector('.rank-star');
        if (star) animate(star,[{clipPath:'inset(0 100% 0 0)'},{clipPath:'inset(0)'}],260,delay+180);
      }
    });
    podiumObserver.observe($('scoreboard-table'));
  }
  return {reset, review, mountReview, countdown, priority, submitted, studentVerdicts, standings};
})();
