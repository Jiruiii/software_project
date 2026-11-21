async (page) => {
  const base=page.url(), student=await page.context().newPage();
  try {
    await page.locator('#choose-teacher').click(); await page.locator('#teacher-password').fill('extras-test-only');
    await page.locator('#login-form button').click(); await page.locator('#activity-title').fill('多選測試');
    await page.locator('#question-count').fill('1'); await page.locator('#create-form button').click();
    await page.locator('#teacher-tabs [data-view="questions"]').click();
    await page.locator('.question-type').selectOption('multiple');
    await page.locator('.choice-options').fill('甲\n乙\n丙');
    await page.getByRole('checkbox',{name:'甲',exact:true}).check();
    await page.getByRole('checkbox',{name:'丙',exact:true}).check();
    const code=await page.locator('#session-code').innerText(); await page.locator('#start').click();
    await student.goto(base); await student.locator('#join-code').fill(code); await student.locator('#join-group').fill('多選組');
    await student.locator('#join-form button').click();
    const card=student.locator('.question-card');
    await card.getByLabel('丙',{exact:true}).check(); await card.getByLabel('甲',{exact:true}).check();
    await student.reload(); await card.getByLabel('甲',{exact:true}).waitFor();
    if(await card.locator('input:checked').count()!==2) throw new Error('未恢復多選草稿');
    await card.locator('button').click();
    await student.waitForFunction(()=>current.answers[0]?.text==='甲\n丙' && current.answers[0].verdict==='withheld');
    await page.locator('#end').click(); await page.locator('#confirm-end').click(); await student.waitForFunction(()=>current.answers[0]?.verdict==='correct');
    return {passed:true};
  } finally {await student.close();}
}
