function createShareCode(label, value, valueId) {
  const row = document.createElement('div');
  row.className = 'share-code';
  const caption = document.createElement('span');
  caption.textContent = label;
  const code = document.createElement('code');
  if (valueId) code.id = valueId;
  code.textContent = value;
  const button = document.createElement('button');
  button.type = 'button';
  button.setAttribute('aria-label', '複製'+label);
  const feedback = document.createElement('span');
  feedback.setAttribute('role', 'status');
  feedback.textContent = '複製';
  button.append(feedback);
  const hint = document.createElement('small');
  hint.setAttribute('role', 'status');
  hint.hidden = true;
  row.append(caption, code, button, hint);

  let timer;
  button.onclick = async () => {
    clearTimeout(timer);
    hint.hidden = true;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      let copied = false;
      try { copied = document.execCommand('copy'); } catch {}
      if (!copied) {
        feedback.textContent = '複製';
        hint.textContent = '請用系統的複製指令複製已選取的文字。';
        hint.hidden = false;
        return;
      }
      selection.removeAllRanges();
    }
    feedback.textContent = '已複製';
    timer = setTimeout(() => { feedback.textContent = '複製'; }, 2000);
  };
  return row;
}
