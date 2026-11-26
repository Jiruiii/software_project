"use strict";

function confirmDeletion(title, message, confirmText="確認刪除") {
  const dialog = document.createElement('dialog');
  dialog.className = 'delete-dialog';
  dialog.setAttribute('aria-labelledby', 'delete-title');
  dialog.setAttribute('aria-describedby', 'delete-message');
  dialog.innerHTML = `<h2 id="delete-title"></h2><p id="delete-message"></p>
    <form method="dialog" class="form-actions">
      <button class="secondary" value="cancel" autofocus>取消</button>
      <button class="danger" value="delete">確認刪除</button>
    </form>`;
  dialog.querySelector('[value=delete]').textContent = confirmText;
  dialog.querySelector('h2').textContent = title;
  dialog.querySelector('p').textContent = message;
  document.body.append(dialog);
  return new Promise(resolve => {
    dialog.addEventListener('close', () => {
      const confirmed = dialog.returnValue === 'delete';
      dialog.remove();
      resolve(confirmed);
    }, {once:true});
    dialog.showModal();
  });
}
