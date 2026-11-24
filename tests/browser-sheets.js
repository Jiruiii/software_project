// Uses the configured QA server's public template reader; never writes to Google.
async (page) => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const errors=[]; page.on('pageerror',error=>errors.push(String(error)));
  const base=new URL(page.url()).origin;
  await page.goto(base);
  await page.evaluate(()=>sessionStorage.clear()); await page.reload();
  await page.setViewportSize({width:1360,height:1000});
  await page.locator('#choose-teacher').click();
  await page.locator('#teacher-password').fill('classroom-qa-only');
  await page.locator('#login-form button').click();
  await page.locator('#dashboard').waitFor({state:'visible'});
  await page.locator('#source-sheets').click();
  const [guide]=await Promise.all([
    page.waitForEvent('popup'), page.getByRole('link',{name:'學習單匯入說明'}).click()
  ]);
  await guide.getByRole('heading',{name:'核對工作表與題號'}).waitFor();
  check(await guide.getByRole('heading',{name:'建立 Google Cloud 專案'}).isHidden(),'本機管理員設定應預設收合');
  await guide.close();
  await page.locator('#google-connect').click();
  await page.locator('#notice').filter({hasText:'尚未設定 Google OAuth'}).waitFor();
  await page.locator('#sheet-url').fill('https://docs.google.com/spreadsheets/d/12uh5xhIx2wXFMy42KU8lN7rLFQ8GDugt9zfAFEvu-1E/edit');
  await page.locator('#sheet-preview-form button').click();
  await page.locator('#sheet-preview').waitFor({state:'visible',timeout:45000});
  check(await page.locator('#sheet-preview-table tbody tr').count()===6,'not six questions');
  check((await page.locator('#sheet-preview-table').innerText()).includes('G15'),'missing dynamic target');
  await page.locator('#sheet-preview').scrollIntoViewIfNeeded();
  await page.screenshot({path:'output/playwright/sheets-preview.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'sheets mobile overflow');
  await page.screenshot({path:'output/playwright/sheets-mobile.png',fullPage:true});
  await page.setViewportSize({width:1360,height:1000});
  await page.locator('#sheet-import').click();
  await page.locator('#activity').waitFor({state:'visible',timeout:45000});
  check((await page.locator('#session-subtitle').innerText()).includes('6 道題目'),'import count mismatch');
  const checkTemplatePanel=async()=>{
    await page.getByRole('link',{name:'開啟學習單'}).waitFor();
    check(await page.locator('#sheet-sync-status').isHidden(),'read-only notice visible in teacher workspace');
    check(await page.locator('#sheet-sync-help').isHidden(),'read-only template offered sync setup');
  };
  check(await page.locator('#sheet-export').isHidden(),'export visible before end');
  await checkTemplatePanel();
  const code=await page.locator('#session-code').innerText();
  const student=await page.context().newPage(); await student.goto(base);
  await student.locator('#join-code').fill(code); await student.locator('#join-group').fill('範本測試組');
  await student.locator('#join-form button').click();
  await student.locator('#activity').waitFor({state:'visible'});
  check(await student.locator('.question-card').count()===6,'student count mismatch');
  check(await student.locator('#sheet-export-controls').isHidden(),'student can see source');
  await page.locator('#start').click();
  await student.locator('#answer-0').fill('範本測試答案');
  await checkTemplatePanel();
  await student.locator('.question-card').first().getByRole('button').click();
  await student.locator('.saved-answer').first().filter({hasText:'範本測試答案'}).waitFor();
  await page.locator('#end').click(); await page.locator('#confirm-end').click();
  await page.locator('#results').waitFor();
  await checkTemplatePanel();
  check(await page.locator('#sheet-export').isHidden(),'offered retry for a read-only template');
  const denied=await page.evaluate(async()=>{
    const aid=sessionStorage.getItem('classroom.activity');
    const {token}=JSON.parse(sessionStorage.getItem('classroom.auth'));
    const result=await fetch('/api/activities/'+aid+'/export',{method:'POST',
      headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:'{}'});
    return {status:result.status,error:(await result.json()).error};
  });
  check(denied.status===403 && denied.error.includes('官方範本'),'official template export was not blocked');
  await page.screenshot({path:'output/playwright/sheets-results.png',fullPage:true});
  check(!errors.length,errors.join('\n'));
  await student.close();
  return {passed:true,templateQuestions:6,studentQuestions:6,studentSubmitted:true,officialWriteBlocked:true,realGoogleWriteTested:false,pageErrors:errors};
}
