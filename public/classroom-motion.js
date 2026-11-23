/* Feedback for confirmed classroom actions. The polling renderer owns the data. */
const classroomMotion = (() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let receipt = null, sequence = 0, lastConfirmed = 0;
  let priorityKey = '', priorityTimer = 0, priorityEndsAt = 0;
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
  function syncHeartbeat() {
    if (document.hidden || !soundToggle.checked || soundContext?.state!=='running') {
      stopHeartbeat();
      return;
    }
    const remaining = (priorityEndsAt-performance.now())/1000;
    if (playing || !heartbeat || remaining<=0) return;
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
      context.onstatechange = syncHeartbeat;
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
  document.addEventListener('visibilitychange',syncHeartbeat);
  window.addEventListener('pagehide',stopHeartbeat);
  window.addEventListener('pageshow',syncHeartbeat);

  function animate(node, frames, duration, delay=0, easing='cubic-bezier(.2,.75,.25,1)') {
    if (reduced.matches || !node.animate) return null;
    return node.animate(frames, {duration, delay, easing, fill:'backwards'});
  }
  function reset() {
    receipt?.node.remove();
    receipt = null;
    stopPriority();
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
        {transform:'scale(1.75) rotate(-15deg)', opacity:0},
        {transform:'scale(.9) rotate(-5deg)', opacity:1, offset:.6},
        {transform:'scale(1) rotate(-5deg)'}
      ], 330);
      return;
    }
    if (!['kick','return'].includes(ticket.effect)) return;
    const paper = el('span',undefined,'flying-answer');
    paper.setAttribute('aria-hidden','true');
    paper.append(el('b',ticket.answer.group_name), el('span',ticket.answer.text));
    stage.append(paper);
    if (ticket.effect === 'kick') {
      const shoe = el('span',undefined,'kicking-shoe');
      shoe.setAttribute('aria-hidden','true');
      shoe.append(el('i',undefined,'shoe-upper'),el('i',undefined,'shoe-sole'),el('i',undefined,'shoe-laces'));
      stage.append(shoe);
      animate(shoe, [
        {transform:'translate(112%, -50%) rotate(20deg)',opacity:0},
        {transform:'translate(40%, -8%) rotate(8deg)',opacity:1,offset:.22},
        {transform:'translate(-15%, 0) rotate(-12deg)',opacity:1,offset:.43},
        {transform:'translate(125%, -55%) rotate(12deg)',opacity:0}
      ], 455,0,'linear').finished.catch(()=>{}).finally(()=>shoe.remove());
    }
    const frames = ticket.effect === 'kick' ? [
      {transform:'none',opacity:1}, {transform:'translateX(2%) rotate(2deg)',opacity:1,offset:.36,easing:'ease-in'},
      {transform:'translate(-116%,-26%) rotate(-16deg)',opacity:0}
    ] : [
      {transform:'translate(-112%,-18%) rotate(-13deg)'}, {transform:'translateX(4%) rotate(2deg)',offset:.65},
      {transform:'none',opacity:1,offset:.82}, {transform:'none',opacity:0}
    ];
    animate(paper,frames,470,0,ticket.effect==='kick'?'linear':'ease-out').finished.catch(()=>{}).finally(()=>paper.remove());
  }

  async function present(ticket, order, session, keyboard) {
    if (session !== generation || order < lastConfirmed) return;
    lastConfirmed = order;
    receipt?.node.remove();
    receipt = ticket;
    const node = ticket.node = el('div',undefined,'review-receipt');
    const stage = el('div',undefined,'review-stage');
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
          message:verdictNames[ticket.answer.verdict], effect:ticket.effect==='kick'?'return':''},undoOrder,session,event.detail===0);
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
    const caption = result.displaced ? '領先答案判錯' : '單筆批改';
    const message = result.displaced ? (next ? `遞補：${next.group_name} · ${verdictNames[next.verdict]}` : '沒有其他候選答案')
                                    : verdict==='correct'?'正解':'已判錯';
    await present({activity,answer,batch:result.batch_id,revision:answer.review_revision+1,caption,message,
      effect:result.displaced?'kick':verdict==='correct'?'stamp':''},order,session,keyboard);
  }
  function stopPriority() {
    clearTimeout(priorityTimer);
    priorityKey = '';
    priorityEndsAt = 0;
    stopHeartbeat();
    const track = $('priority-track');
    track.hidden = true;
    track.firstElementChild.getAnimations().forEach(a=>a.cancel());
  }
  function priority(state, active) {
    const canUseSound = state.phase==='preparing' || active ||
      (state.phase==='active' && state.settings.mode==='sequential' && state.settings.fairness);
    $('heartbeat-setting').hidden = !Audio || state.role!=='student' || !canUseSound;
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
    priorityEndsAt = performance.now()+remaining;
    syncHeartbeat();
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
  return {reset, review, mountReview, priority, submitted, standings};
})();
