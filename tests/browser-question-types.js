async (page) => {
  const base=new URL(page.url()).origin, errors=[], students=[];
  const check=(value,message)=>{if(!value) throw new Error(message);};
  let stage='teacher setup';
  try {
    page.on('pageerror',e=>errors.push(String(e)));
    await page.locator('#choose-teacher').click(); await page.locator('#teacher-password').fill('extras-test-only');
    await page.locator('#login-form button').click(); await page.locator('#activity-title').fill('題型與不押驗收');
    await page.locator('#question-count').fill('4'); await page.locator('#create-form button').click();
    await page.locator('#settings-form').waitFor({state:'visible'});
    await page.locator('#quiz-mode').selectOption('sequential'); await page.locator('#save-settings').click();
    await page.locator('#notice').filter({hasText:'所有設定已儲存'}).waitFor();
    await page.locator('#teacher-tabs [data-view="questions"]').click();
    const configure=async(q,type,bet)=>{
      const box=page.locator(`.question-config-unit[data-unit="${q}"]`);
      if (!await box.getAttribute('open').then(x=>x!==null)) await box.locator('summary').click();
      await box.locator('.question-type').selectOption(type);
      if(type==='choice') {
        await box.locator('.choice-options').fill('甲\n乙\n丙'); await box.locator('.choice-correct').selectOption('1');
      }
      await box.locator('.betting-enabled').setChecked(bet); await page.locator('#save-settings').click();
      await box.locator('form[data-dirty="false"]').waitFor();
    };
    await page.locator('.question-type').first().selectOption('choice'); await page.locator('#start').click();
    check((await page.locator('#notice').innerText()).includes('第 1 題'),'invalid settings silently ignored');
    await configure('1','choice',true); await configure('2','choice',false); await configure('4','short',false);
    const code=await page.locator('#session-code').innerText();
    for (const name of ['測試A組','測試B組']) {
      const student=await page.context().newPage(); students.push(student); student.on('pageerror',e=>errors.push(String(e)));
      await student.goto(base); await student.locator('#join-code').fill(code); await student.locator('#join-group').fill(name);
      await student.locator('#join-form button').click(); await student.locator('#own-score').waitFor({state:'visible'});
      check(await student.locator('#question-settings').isHidden(),'student teacher settings exposed');
      check(await student.evaluate(()=>!JSON.stringify(current).includes('correct_index')),'answer key exposed');
    }
    const [a,b]=students;
    await page.screenshot({path:'output/playwright/question-types-teacher-settings.png',fullPage:true});
    stage='choice auto grading'; await page.locator('#start').click();
    await a.waitForFunction(()=>!document.querySelector('#answer-0').disabled);
    check(await a.locator('#stake-0').inputValue()==='0','default is not no-bet');
    await a.locator('#answer-0').selectOption('甲'); await a.reload();
    await a.waitForFunction(()=>!!document.querySelector('#answer-0')&&!document.querySelector('#answer-0').disabled);
    check(await a.locator('#answer-0').inputValue()==='甲','choice draft lost');
    check(await a.locator('#stake-0').inputValue()==='0','zero draft became a stake');
    await a.locator('#stake-0').selectOption('3'); await a.locator('.question-card').nth(0).locator('button').click();
    await b.locator('#answer-0').selectOption('乙'); await b.locator('#stake-0').selectOption('2'); await b.locator('.question-card').nth(0).locator('button').click();
    for(const student of [a,b]) {
      await student.waitForFunction(()=>current.answers.length===1);
      check(await student.evaluate(()=>current.own_score.total===0 && current.own_score.awaiting_close_units===1 && current.own_score.pending_units===0 && current.answers[0].verdict==='withheld'),'Open question leaked grading');
      check((await student.locator('#own-score-pending').innerText()).includes('已送出 1 題，等待本題結束'),'Missing withheld hint');
    }
    await a.setViewportSize({width:390,height:844});
    await a.screenshot({path:'output/playwright/score-publication-before-close.png',fullPage:true});
    check(await a.locator('#scoreboard').isHidden(),'active scoreboard exposed');
    check(await a.evaluate(()=>!current.answers.some(x=>x.text==='乙')&&!('groups' in current)),'other group answer exposed');
    stage='choice no betting'; await page.locator('#close-round').click();
    await a.waitForFunction(()=>current.own_score.total===-3 && current.answers[0].verdict==='incorrect');
    await b.waitForFunction(()=>current.own_score.total===2 && current.answers[0].verdict==='correct');
    await a.screenshot({path:'output/playwright/score-publication-after-close.png',fullPage:true});
    await page.locator('#next-round').click();
    await a.waitForFunction(()=>!document.querySelector('#answer-1').disabled);
    check(await a.locator('#stake-1').isDisabled(),'closed betting selectable');
    await a.locator('#answer-1').selectOption('乙'); await a.locator('.question-card').nth(1).locator('button').click();
    await a.waitForFunction(()=>current.answers.length===2); check(await a.evaluate(()=>current.own_score.total===-3),'no bet changed score');
    stage='short answer manual grading'; await page.locator('#close-round').click(); await page.locator('#next-round').click();
    await a.waitForFunction(()=>!document.querySelector('#answer-2').disabled);
    await a.locator('#answer-2').fill('人工批改答案'); await a.locator('#stake-2').selectOption('2'); await a.locator('.question-card').nth(2).locator('button').click();
    await a.waitForFunction(()=>current.own_score.awaiting_close_units===1 && current.answers.length===3);
    check(await a.evaluate(()=>current.own_score.total===-3),'pending added score');
    await page.locator('#close-round').click();
    await a.waitForFunction(()=>current.own_score.pending_units===1 && current.own_score.awaiting_close_units===0);
    check(await page.locator('#monitor-table [data-verdict="pending"]').count()===0,'Unexpected pending verdict control');
    for(const [name,total] of [['正確',-1],['錯誤',-5],['正確',-1]]) {
      await page.getByRole('button',{name:`測試A組 第 3 題判為${name}`,exact:true}).click();
      await a.waitForFunction(total=>current.own_score.total===total,total);
    }
    check(await a.evaluate(()=>current.phase==='active'),'manual grading ended activity');
    stage='short no bet'; await page.locator('#next-round').click(); await a.waitForFunction(()=>!document.querySelector('#answer-3').disabled);
    check(await a.locator('#stake-3').isDisabled(),'short no-bet switch ignored');
    await a.locator('#answer-3').fill('不押的簡答'); await a.locator('.question-card').nth(3).locator('button').click();
    await a.waitForFunction(()=>current.answers.length===4);
    await page.locator('#close-round').click(); await a.locator('#results').waitFor({state:'visible'});
    await page.locator('#teacher-tabs [data-view="monitor"]').click(); await page.locator('#monitor-question').selectOption('4');
    await page.getByRole('button',{name:'測試A組 第 4 題判為錯誤',exact:true}).click();
    await a.waitForFunction(()=>current.own_score.pending_units===0);
    check(await a.evaluate(()=>current.own_score.total===-1),'zero stake deducted');
    await a.setViewportSize({width:390,height:844});
    check(await a.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile overflow');
    await a.screenshot({path:'output/playwright/question-types-student.png',fullPage:true});
    check(!errors.length,errors.join('\n'));
    return {passed:true,combinations:['choice + stake','choice + no bet','short + stake','short + no bet'],
      ownScoreDuringActivity:true,scorePublishedOnlyAfterClose:true,manualRegrade:true,choiceAndZeroDraftRestored:true,answerKeyHidden:true,pageErrors:errors};
  } catch(error) {throw new Error(`${stage}: ${error.message}`);}
  finally {for(const student of students) await student.close();}
}
