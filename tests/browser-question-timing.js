async (page) => {
  const check=(value,message)=>{if(!value) throw new Error(message);};
  const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
  await page.setViewportSize({width:1280,height:900});
  await page.locator('#choose-teacher').click();
  await page.locator('#teacher-password').fill('extras-test-only');
  await page.locator('#login-form button').click();
  await page.locator('.activity-card').filter({hasText:'逐題計時驗收'}).click();
  await page.locator('#teacher-monitor').waitFor({state:'visible'});
  await page.locator('#monitor-question').selectOption('2');
  await page.locator('#monitor-table').filter({hasText:'該題開放後 2.350 秒'}).waitFor();
  const checkOrder=async expected=>{
    const rows=await page.locator('#monitor-table tbody th').allTextContents();
    check(rows.join(',')===expected.map(letter=>'計時'+letter+'組').join(','),'批改表列序錯誤：'+rows.join('、'));
  };
  await checkOrder(['D','C','A','B']);
  await page.locator('#monitor-question').selectOption('1');
  await checkOrder(['A','B','C','D']);
  await page.locator('#monitor-question').selectOption('');
  await checkOrder(['A','B','C','D']);
  await page.locator('#monitor-question').selectOption('2');
  const student=await page.context().newPage();
  try {
    await student.goto(new URL(page.url()).origin);
    await student.locator('#join-code').fill(await page.locator('#session-code').innerText());
    await student.locator('#join-group').fill('計時A組');
    await student.locator('#join-form button').click();
    await student.locator('.answer-time').filter({hasText:'該題開放後 2.350 秒'}).waitFor();
    await student.locator('.answer-time').filter({hasText:'活動開始後（舊紀錄） 3.000 秒'}).waitFor();
    await page.locator('#end').click(); await page.locator('#confirm-end').click();
    await page.locator('#teacher-tabs [data-view="monitor"]').click();
    await page.locator('#monitor-question').selectOption('2');
    await page.getByRole('button',{name:'計時D組 第 2 題判為錯誤',exact:true}).click();
    await page.waitForFunction(()=>current.answers.some(a=>a.group_name==='計時D組' && a.verdict==='incorrect'));
    await checkOrder(['D','C','A','B']);
    await page.getByRole('button',{name:'計時D組 第 2 題判為正確',exact:true}).click();
    await page.waitForFunction(()=>current.answers.some(a=>a.group_name==='計時D組' && a.verdict==='correct'));
    await checkOrder(['D','C','A','B']);
    await page.reload();
    await page.locator('#teacher-tabs [data-view="monitor"]').click();
    await page.locator('#monitor-question').selectOption('2');
    await checkOrder(['D','C','A','B']);
    await page.locator('#teacher-tabs [data-view="tools"]').click();
    await page.locator('#tool-replay > summary').click();
    await page.locator('#replay-question').selectOption('2');
    await page.locator('#replay-play').click();
    await page.locator('#replay-status').filter({hasText:'播放完成'}).waitFor();
    check((await page.locator('#replay-answers').innerText()).includes('該題開放後 2.350 秒'),'Replay timing incorrect');
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:'output/playwright/question-timing-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'output/playwright/question-timing-mobile.png',fullPage:true});
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile overflow');
    await page.locator('#replay-question').selectOption('1');
    await page.locator('#replay-play').click();
    await page.locator('#replay-status').filter({hasText:'播放完成'}).waitFor();
    check((await page.locator('#replay-answers').innerText()).includes('活動開始後（舊紀錄） 3.000 秒'),'Legacy timing mislabeled');
    const csv=await page.evaluate(async()=>{
      const auth=JSON.parse(sessionStorage.getItem('classroom.auth'));
      const id=sessionStorage.getItem('classroom.activity');
      return (await fetch(`/api/activities/${id}/csv`,{headers:{Authorization:'Bearer '+auth.token}})).text();
    });
    check(csv.includes('計時基準') && csv.includes('該題開放,2.350') && csv.includes('活動開始（舊紀錄）,3.000'),'CSV timing differs');
    check(!errors.length,errors.join('\n'));
    return {passed:true,checks:['teacher-2.350','student-2.350','replay-2.350','csv-2.350','legacy-labels','mobile-no-overflow','single-question-receipt-order','all-questions-group-order','stable-after-grading'],pageErrors:errors};
  } finally {await student.close();}
}
