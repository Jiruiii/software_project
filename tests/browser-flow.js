// Run with playwright-cli run-code --filename tests/browser-flow.js against QA server.
async (page) => {
  const base = new URL(page.url()).origin;
  const check = (value, message) => {if (!value) throw new Error(message);};
  const errors = [];
  for (const existing of page.context().pages()) if (existing !== page) await existing.close();
  page.on('pageerror', error => errors.push(String(error)));
  await page.goto(base);
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.setViewportSize({width:1360, height:1000});
  await page.screenshot({path:'output/playwright/entry.png', fullPage:true});
  await page.getByRole('button', {name:'我是老師', exact:true}).click();
  await page.getByLabel('教師密碼', {exact:true}).fill('classroom-qa-only');
  await page.getByRole('button', {name:'進入教師空間'}).click();
  await page.getByLabel('活動名稱', {exact:true}).fill('課堂驗收・概念複習');
  await page.getByLabel('幾題？').fill('3');
  await page.getByRole('button', {name:'下一步：設定活動'}).click();
  await page.locator('#session-code').filter({hasText:/^[A-Z2-9]{6}$/}).waitFor();
  const code = await page.locator('#session-code').innerText();
  const studentA = await page.context().newPage();
  const studentB = await page.context().newPage();
  const groupmate = await page.context().newPage();
  for (const [student, name] of [[studentA,'第 1 組'],[studentB,'第 2 組'],[groupmate,'第 1 組']]) {
    student.on('pageerror', error => errors.push(String(error)));
    await student.goto(base);
    await student.getByLabel('活動代碼', {exact:true}).fill(code);
    await student.getByLabel('小組名稱', {exact:true}).fill(name);
    await student.getByRole('button', {name:'加入活動', exact:true}).click();
    await student.locator('#activity').waitFor({state:'visible'});
    await student.locator('#answer-0').waitFor({state:'attached'});
    check(await student.locator('#answer-0').isDisabled(), 'F-10: answers enabled before start');
  }
  // Timestamp actual DOM changes, excluding automation polling/round-trip delay.
  for (const student of [studentA,studentB,groupmate]) await student.evaluate(() => {
    window.qaPhaseTimes = {};
    new MutationObserver(() => {
      if (!document.querySelector('#answer-0').disabled && !window.qaPhaseTimes.start) window.qaPhaseTimes.start = Date.now();
      if (!document.querySelector('#results').hidden && !window.qaPhaseTimes.end) window.qaPhaseTimes.end = Date.now();
    }).observe(document.querySelector('#activity'), {attributes:true,subtree:true});
  });
  await page.evaluate(() => document.querySelector('#start').addEventListener('click', () => window.qaStartClick = Date.now(), {once:true}));
  await page.getByRole('button', {name:'開始搶答'}).click();
  await Promise.all([studentA,studentB,groupmate].map(p => p.waitForFunction(() => !document.querySelector('#answer-0').disabled, undefined, {timeout:2000})));
  const started = await page.evaluate(() => window.qaStartClick);
  const startSyncMs = Math.max(...await Promise.all([studentA,studentB,groupmate].map(p => p.evaluate(() => window.qaPhaseTimes.start)))) - started;
  check(startSyncMs <= 2000, `F-15: start sync ${startSyncMs}ms exceeded 2 seconds`);
  await studentA.locator('#answer-0').fill('規格先行，讓需求與驗收一致。');
  await studentA.locator('.question-card').nth(0).getByRole('button').click();
  await studentA.locator('.question-card').nth(0).locator('.saved-answer').waitFor({state:'visible'});
  await groupmate.locator('.question-card').nth(0).locator('.saved-answer').waitFor({state:'visible'});
  check(await groupmate.locator('.question-card').nth(0).locator('button').isHidden(), 'F-11: groupmate can resubmit');
  check(!(await studentB.locator('#activity').innerText()).includes('規格先行'), 'F-13: another group answer leaked');
  await studentB.locator('#answer-0').fill('先建立規格，再開始實作。');
  await studentB.locator('.question-card').nth(0).getByRole('button').click();
  await studentB.locator('.question-card').nth(0).locator('.saved-answer').waitFor({state:'visible'});
  await studentB.locator('#answer-1').fill('<script>unsafe()</script> 測試純文字');
  await studentB.locator('.question-card').nth(1).getByRole('button').click();
  await page.getByText('規格先行，讓需求與驗收一致。', {exact:true}).waitFor();
  await page.getByText('<script>unsafe()</script> 測試純文字', {exact:true}).waitFor();
  await page.screenshot({path:'output/playwright/teacher-active.png', fullPage:true});
  await studentA.locator('#answer-1').fill('未送出草稿');
  await studentA.reload();
  await studentA.locator('.question-card').nth(0).locator('.saved-answer').waitFor({state:'visible'});
  check((await studentA.locator('.saved-answer').first().innerText()).includes('規格先行'), 'saved answer lost after refresh');
  await studentA.locator('#answer-1').fill('保留正在輸入的草稿');
  await studentA.waitForTimeout(900);
  check(await studentA.locator('#answer-1').inputValue() === '保留正在輸入的草稿', 'polling erased draft');
  await studentA.setViewportSize({width:390,height:844});
  await studentA.screenshot({path:'output/playwright/student-mobile.png', fullPage:true});
  check(await studentA.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile horizontal overflow');
  for (const student of [studentA,studentB,groupmate]) await student.evaluate(() => {
    window.qaPhaseTimes = {};
    new MutationObserver(() => {
      if (!document.querySelector('#results').hidden && !window.qaPhaseTimes.end) window.qaPhaseTimes.end = Date.now();
    }).observe(document.querySelector('#results'), {attributes:true});
  });
  await page.evaluate(() => document.querySelector('#confirm-end').addEventListener('click', () => window.qaEndClick = Date.now(), {once:true}));
  await page.getByRole('button', {name:'結束搶答並公布結果'}).click();
  await page.locator('#confirm-end').click();
  await Promise.all([studentA,studentB,groupmate].map(p => p.locator('#results').waitFor({state:'visible',timeout:2000})));
  const ended = await page.evaluate(() => window.qaEndClick);
  const endSyncMs = Math.max(...await Promise.all([studentA,studentB,groupmate].map(p => p.evaluate(() => window.qaPhaseTimes.end)))) - ended;
  check(endSyncMs <= 2000, `F-15: end sync ${endSyncMs}ms exceeded 2 seconds`);
  await page.locator('#teacher-tabs [data-view="monitor"]').click();
  await page.locator('#monitor-question').selectOption('1');
  await page.getByRole('button',{name:'第 1 組 第 1 題判為正確',exact:true}).click();
  for (const student of [studentA,studentB]) {
    const results = student.locator('#results');
    await results.locator('.winner').first().filter({hasText:/^第 1 組$/}).waitFor();
    check(await results.locator('.result-answer').count()===0, '學生結算顯示答案內容');
    check((await results.innerText()).includes('無人作答'), 'unanswered question not marked');
    check(await student.locator('#student-questions').isHidden(), 'F-06: answer area not closed');
  }
  await page.locator('#teacher-tabs [data-view="results"]').click();
  await page.screenshot({path:'output/playwright/teacher-results.png', fullPage:true});
  await page.context().setOffline(true);
  await studentB.getByText('連線中斷 · 正在重試', {exact:true}).waitFor({timeout:7000});
  await page.context().setOffline(false);
  await studentB.getByText('已連線 · 自動同步', {exact:true}).waitFor({timeout:7000});
  check(errors.length === 0, errors.join('\n'));
  return {passed:true,startSyncMs,endSyncMs,groups:2,tabs:4,checks:['phase-gates','group-shared-answer','privacy','teacher-monitor','results','literal-html','refresh','draft-preserved','mobile','reconnect'],pageErrors:errors};
}
