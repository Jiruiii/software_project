const activityChat = (() => {
  const channel = document.getElementById('activity-chat');
  const log = document.getElementById('chat-log');
  const form = document.getElementById('chat-form');
  const sendButton = form.querySelector('button');
  const input = document.getElementById('chat-body');
  const readStatus = document.getElementById('chat-read-status');
  const sendStatus = document.getElementById('chat-send-status');
  let room = null;

  function clear() {
    room = null;
    channel.hidden = true;
    channel.open = false;
    log.replaceChildren();
    form.reset();
    sendButton.disabled = false;
    document.getElementById('chat-author').textContent = '訊息';
    readStatus.textContent = sendStatus.textContent = '';
  }

  async function read() {
    const active = room;
    if (!active || !channel.open || active.reading) return;
    active.reading = true;
    try {
      const {messages} = await api(active.path+'?after='+active.after);
      if (active !== room) return;
      const atEnd = log.scrollHeight - log.clientHeight - log.scrollTop < 24;
      for (const message of messages) {
        const row = el('p');
        row.append(el('strong', message.group_name), el('span', message.body));
        log.append(row);
        active.after = message.id;
      }
      if (atEnd && messages.length) log.scrollTop = log.scrollHeight;
      readStatus.textContent = active.after ? '' : '目前還沒有訊息。';
    } catch (error) {
      if (active !== room) return;
      if ([401,403,409].includes(error.status)) clear();
      else readStatus.textContent = '連線中斷，正在重新連線…';
    } finally {
      active.reading = false;
    }
  }

  channel.ontoggle = () => { if (channel.open) read(); };
  channel.addEventListener('keydown', event => {
    if (event.key === 'Escape' && channel.open) {
      channel.open = false;
      channel.querySelector('summary').focus();
    }
  });
  form.onsubmit = async event => {
    event.preventDefault();
    const active = room, body = input.value.trim();
    if (!active || active.sending || !body) return;
    if (active.pending?.body !== body) active.pending = {body, request_id:crypto.randomUUID()};
    active.sending = true;
    sendButton.disabled = true;
    sendStatus.textContent = '';
    try {
      await api(active.path, active.pending);
      if (active !== room) return;
      active.pending = null;
      if (input.value.trim() === body) input.value = '';
      read();
    } catch (error) {
      if (active !== room) return;
      if ([401,403,409].includes(error.status)) clear();
      else sendStatus.textContent = error.message+' 可重新送出。';
    } finally {
      if (active === room) {
        active.sending = false;
        sendButton.disabled = false;
      }
    }
  };

  window.addEventListener('pagehide', clear);
  return {sync(state) {
    if (!state?.chat_available) {
      if (room) clear();
      return;
    }
    if (room?.id !== state.id) {
      clear();
      room = {id:state.id, path:'/api/activities/'+state.id+'/chat', after:0};
      document.getElementById('chat-author').textContent = '以「'+state.group_name+'」發言';
      channel.hidden = false;
    }
    if (channel.open) read();
  }};
})();
