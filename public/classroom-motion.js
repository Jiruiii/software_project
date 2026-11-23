/* Feedback for confirmed classroom actions. The polling renderer owns the data. */
const classroomMotion = (() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let receipt = null, sequence = 0, lastConfirmed = 0;
  let priorityKey = '', priorityTimer = 0;
  let countdownKey = '', countdownTimer = 0, answerEndsAt = 0, expiryAction = '';
  let podiumObserver = null, podiumPlayed = false;
  const soundToggle = document.getElementById('heartbeat-enabled');
  const Audio = window.AudioContext || window.webkitAudioContext;
  let soundContext = null, heartbeat = null, playing = null;

  function stopHeartbeat() {
    if (!playing) return;
    playing.stop();
    playing.disconnect();
    playing = null;
  }
  function syncHeartbeat(remaining = (answerEndsAt-performance.now())/1000) {
    if (!countdownKey || remaining<=0 || remaining>3 || document.hidden || !soundToggle.checked ||
        $('heartbeat-setting').hidden || soundContext?.state!=='running') {
      stopHeartbeat();
      return;
    }
    if (playing || !heartbeat) return;
    const offset = Math.max(0, heartbeat.duration-remaining);
    playing = soundContext.createBufferSource();
    playing.buffer = heartbeat;
    playing.connect(soundContext.destination);
    playing.start(0,offset);
  }
  function disableHeartbeat() {
    stopHeartbeat();
    const context = soundContext;
    soundContext = null;
    heartbeat = null;
    soundToggle.checked = false;
    if (context) {
      context.onstatechange = null;
      context.close().catch(()=>{});
    }
  }
  async function loadHeartbeat(context) {
    const response = await fetch('/priority-heartbeat.wav');
    if (!response.ok) throw Error('heartbeat');
    return context.decodeAudioData(await response.arrayBuffer());
  }
  soundToggle.onchange = async () => {
    const message = document.getElementById('heartbeat-error');
    message.hidden = true;
    if (!soundToggle.checked) {disableHeartbeat(); return;}
    let context;
    try {
      context = soundContext = new Audio();
      context.onstatechange = () => syncHeartbeat();
      const [,buffer] = await Promise.all([context.resume(),loadHeartbeat(context)]);
      if (context!==soundContext) return;
      heartbeat = buffer;
      syncHeartbeat();
    } catch {
      if (context && context!==soundContext) return;
      disableHeartbeat();
      message.textContent = '無法播放心跳聲，可重新勾選再試。';
      message.hidden = false;
    }
  };
  function pauseCountdown() {
    clearTimeout(countdownTimer);
    stopHeartbeat();
  }
  function tickCountdown() {
    clearTimeout(countdownTimer);
    if (!countdownKey || document.hidden) {stopHeartbeat(); return;}
    const ms = Math.max(0,answerEndsAt-performance.now());
    const seconds = Math.ceil(ms/1000);
    $('countdown').textContent = `剩餘 ${seconds} 秒 · 到期自動${expiryAction}`;
    syncHeartbeat(ms/1000);
    if (seconds>0) countdownTimer = setTimeout(tickCountdown,Math.ceil(ms-(seconds-1)*1000));
  }
  function countdown(state) {
    const timed = state.settings.duration_seconds>0;
    const sequential = state.settings.mode==='sequential';
    const {deadline,round_index,round_open} = state.round;
    $('heartbeat-setting').hidden = !Audio || state.role!=='student' || !timed || state.phase==='results';
    const active = timed && state.phase==='active' && Number.isFinite(deadline) && (!sequential || round_open);
    $('countdown').hidden = !active;
    const key = active ? `${state.id}/${round_index}/${deadline}` : '';
    if (key===countdownKey) return;
    pauseCountdown();
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
    disableHeartbeat();
    $('heartbeat-error').hidden = true;
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
      animate(stage.querySelector('.verdict-stamp'), [
        {transform:'scale(1.14) rotate(-9deg)', opacity:0},
        {transform:'scale(.94) rotate(-5deg)', opacity:1, offset:.55},
        {transform:'scale(1) rotate(-5deg)'}
      ], 490);
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
    stage.append(el('span',ticket.caption,'review-caption'),
                 el('strong',ticket.message,ticket.effect==='stamp'?'verdict-stamp':'review-outcome'));
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
    const caption = result.displaced ? `${answer.group_name} 判錯` : '單筆批改';
    const message = result.displaced ? (next ? `遞補：${next.group_name} · ${verdictNames[next.verdict]}` : '沒有其他候選答案')
                                    : verdict==='correct'?'正解':'已判錯';
    await present({activity,answer,batch:result.batch_id,revision:answer.review_revision+1,caption,message,
      effect:result.displaced?'erase':verdict==='correct'?'stamp':''},order,session,keyboard);
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
  return {reset, review, mountReview, countdown, priority, submitted, standings};
})();
