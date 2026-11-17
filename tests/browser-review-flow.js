async page => {
  const check=(v,m)=>{if(!v)throw new Error(m);},errors=[];let student;
  page.on('pageerror',e=>errors.push(String(e)));
  try {
    await page.setViewportSize({width:1280,height:900});
    await page.locator('#choose-teacher').click();await page.locator('#teacher-password').fill('extras-test-only');await page.locator('#login-form button').click();
    await page.locator('#create-form').waitFor({state:'visible'});
    const token=await page.evaluate(()=>auth.token),base=new URL(page.url()).origin;
    const post=async(route,data)=>{const r=await page.request.post(base+route,{data,headers:{Authorization:'Bearer '+token}});check(r.ok(),await r.text());return r.json();};
    const a=await post('/api/activities',{title:'批改流程驗收',questions:['1','2','3']}),path=`/api/activities/${a.id}`;
    await post(path+'/settings',{mode:'sequential'});
    await page.evaluate(async aid=>{selectActivity(aid);await refresh();},a.id);
    student=await page.context().newPage();student.on('pageerror',e=>errors.push(String(e)));await student.goto(base);
    await student.locator('#join-code').fill(a.code);await student.locator('#join-group').fill('第一組');await student.locator('#join-form button').click();
    await page.locator('#start').click();await student.waitForFunction(()=>!document.querySelector('#answer-0').disabled);
    await student.locator('#answer-0').fill('第一題回答');await student.locator('.question-card').nth(0).locator('button').click();
    await page.waitForFunction(()=>current.answers.length===1);
    check(await page.locator('#teacher-tabs [data-view="monitor"]').innerText()==='作答與批改','Unclosed answers counted as reviewable');
    await student.setViewportSize({width:390,height:844});
    check(await student.locator('#answer-1').isHidden(),'Upcoming question shows disabled form');
    await student.screenshot({path:'output/playwright/ui-student-active-mobile.png',fullPage:true});
    await page.locator('#close-round').click();
    await page.waitForFunction(()=>current.round.round_open===0);
    check(await page.locator('#phase-label').innerText()==='本題已關閉','Closed round says active');
    check((await page.locator('#teacher-tabs [data-view="monitor"]').innerText()).includes('1 待批改'),'Closed pending count missing');
    await page.locator('#references > summary').click();await page.locator('#reference-answer').fill('第一題草稿');
    check(await page.locator('#reference-question').count()===0,'Independent selector remains');
    await page.locator('#next-round').click();await page.waitForFunction(()=>current.round.unit_id==='2');
    await student.locator('#answer-1').waitFor({state:'visible'});
    check(await page.locator('#monitor-question').inputValue()==='2','Shared selector did not follow');
    check(await page.locator('#reference-form').isHidden(),'Open question reference form editable');
    await page.locator('#monitor-question').selectOption('1');check(await page.locator('#reference-answer').inputValue()==='第一題草稿','Draft lost');
    check((await page.locator('#monitor-table').innerText()).includes('第一題回答'),'Monitor disagrees');
    await page.locator('#reference-save').click();await page.waitForFunction(()=>current.references['1']==='第一題草稿');
    await page.locator('#monitor-question').selectOption('2');
    await student.locator('#answer-1').fill('第二題回答');await student.locator('.question-card').nth(1).locator('button').click();
    await page.waitForFunction(()=>current.answers.length===2);await page.locator('#close-round').click();
    await page.locator('#reference-answer').fill('第二題草稿');await page.locator('#monitor-question').selectOption('');
    check(await page.locator('#reference-form').isHidden(),'All questions silently edits a question');
    await page.locator('#monitor-question').selectOption('2');check(await page.locator('#reference-answer').inputValue()==='第二題草稿','Second draft lost');
    await page.locator('#next-round').click();await page.waitForFunction(()=>current.round.unit_id==='3');
    await page.locator('#close-round').click();await page.waitForFunction(()=>current.phase==='results' && !current.grading.complete);
    await student.waitForFunction(()=>current.phase==='results' && !current.grading.complete);
    check((await page.locator('#grading-message').innerText()).includes('2 筆'),'Missing pending count');
    check((await student.locator('#scoreboard h3').innerText()).includes('暫時成績'),'Student sees final scoreboard');
    await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'output/playwright/review-flow-desktop.png',fullPage:true});
    await page.locator('#grading-review').click();check(await page.locator('#monitor-question').inputValue()==='1','Review link wrong question');
    check(await page.locator('#reference-answer').inputValue()==='第一題草稿','Reference disagrees with review');
    await page.getByRole('button',{name:'第一組 第 1 題判為正確',exact:true}).click();await page.waitForFunction(()=>current.grading.pending_answers===1);
    await page.locator('#monitor-question').selectOption('2');
    const answer=await page.evaluate(()=>current.answers.find(a=>a.question_id==='2'));
    const batch=await post(path+'/review-batch',{question:'2',selections:[{id:answer.id,revision:answer.review_revision}],verdict:'correct'});
    await student.waitForFunction(()=>current.grading.complete);await page.waitForFunction(()=>current.grading.complete);
    check((await student.locator('#group-report h3').innerText()).includes('批改完成'),'Report not finalized');
    await post(path+'/review-undo',{batch_id:batch.batch_id});await student.waitForFunction(()=>!current.grading.complete);await page.waitForFunction(()=>!current.grading.complete);
    await page.setViewportSize({width:390,height:844});await page.evaluate(()=>window.scrollTo(0,0));
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Teacher mobile overflow');
    await page.screenshot({path:'output/playwright/review-flow-mobile.png',fullPage:true});
    check(await page.locator('#grading-review').isHidden(),'Review workspace has redundant review button');
    await student.setViewportSize({width:390,height:844});check(await student.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Student mobile overflow');
    await student.screenshot({path:'output/playwright/review-flow-student.png',fullPage:true});
    for(const [target,name] of [[page,'teacher'],[student,'student']]) {
      await target.setViewportSize({width:320,height:720});
      check(await target.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name} narrow overflow`);
      await target.screenshot({path:`output/playwright/ui-${name}-320.png`,fullPage:true});
    }
    await student.locator('#scoreboard .scoring-help > summary').focus();await student.keyboard.press('Enter');
    check(await student.locator('#scoreboard .scoring-help').evaluate(e=>e.open),'Scoring help not keyboard accessible');
    await student.evaluate(async()=>{await refresh();});
    check(await student.locator('#scoreboard .scoring-help').evaluate(e=>e.open),'Polling reset scoring help');
    await page.getByRole('button',{name:'第一組 第 2 題判為正確',exact:true}).click();await student.waitForFunction(()=>current.grading.complete);
    check(!errors.length,errors.join('\n'));
    return {passed:true,checks:['single-question-selector','round-follow','closed-only-editing','per-question-drafts','all-selection-safe','provisional-results','student-provisional','review-shortcut','automatic-completion','undo-provisional','mobile-layout','closed-round-label','reviewable-pending-count','no-redundant-review-button','320px-layout','keyboard-help-retained'],pageErrors:errors};
  } catch(error) {
    await page.screenshot({path:'output/playwright/ui-review-failure.png',fullPage:true});
    const state=await page.evaluate(()=>({phase:current?.phase,round:current?.round,answers:current?.answers?.length}));
    throw new Error(error.message+' '+JSON.stringify(state));
  } finally {if(student)await student.close();}
}
