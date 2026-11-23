// Run against the isolated course fixture with tests/run_extra_ui.py --suite motion.
async page => {
  const check=(value,message)=>{if(!value) throw Error(message);};
  const errors=[];
  function observeAnimations() {
    window.motionCounts={};
    const native=Element.prototype.animate;
    Element.prototype.animate=function(...args) {
      const name=this.className;
      window.motionCounts[name]=(window.motionCounts[name]||0)+1;
      return native.apply(this,args);
    };
  }
  await page.addInitScript(observeAnimations);
  page.on('pageerror',error=>errors.push(String(error)));
  await page.reload();
  const base=new URL(page.url()).origin;
  await page.locator('#choose-teacher').click();
  await page.locator('#teacher-password').fill('extras-test-only');
  await page.locator('#login-form button').click();
  await page.locator('#activity-title').fill('課堂動態驗收');
  await page.locator('#question-count').fill('1');
  await page.locator('#create-form button').click();
  const code=await page.locator('#session-code').innerText();
  const aid=await page.evaluate(()=>activityId);
  const student=await page.context().newPage();
  try {
    student.on('pageerror',error=>errors.push(String(error)));
    await student.addInitScript(observeAnimations);
    await student.goto(base);
    await student.locator('#join-code').fill(code);
    await student.locator('#join-group').fill('海獺組');
    await student.locator('#join-form button').click();
    const peer=await page.request.post(base+'/api/join',{data:{code,group:'山雀組'}});
    check(peer.ok(),'第二組無法加入');
    const {token}=await peer.json();
    await page.locator('#start').click();
    await student.locator('#answer-0').fill('葉綠體吸收光能');
    await student.locator('.question-card button').click();
    await student.getByText('✓ 已交卷',{exact:true}).waitFor();
    check(await student.evaluate(()=>motionCounts['question-status'])===1,'交卷未播一次');
    await student.evaluate(()=>refresh());
    check(await student.evaluate(()=>motionCounts['question-status'])===1,'輪詢重播交卷');
    await student.reload();
    await student.getByText('✓ 已交卷',{exact:true}).waitFor();
    check(!await student.evaluate(()=>motionCounts['question-status']),'重載重播交卷');
    const response=await page.request.post(base+'/api/activities/'+aid+'/answers',{
      headers:{Authorization:'Bearer '+token},data:{question:'1',answer:'葉綠素吸收光能',stake:0}});
    check(response.ok(),'第二組未成功作答');
    await page.locator('#end').click();
    await page.locator('#confirm-end').click();
    await page.locator('#results').waitFor();
    check(await page.locator('.rank-star').count()===0,'暫時排名出現冠軍星記');
    await page.locator('#teacher-tabs [data-view="monitor"]').click();
    const judge=(group,verdict)=>page.getByRole('button',{name:`${group} 第 1 題判為${verdict}`,exact:true}).click();
    const receipt=page.locator('.review-receipt'), undo=page.getByRole('button',{name:'復原這筆判定'});
    await page.getByRole('button',{name:'海獺組 第 1 題判為錯誤',exact:true}).press('Enter');
    await receipt.getByText('遞補：山雀組 · 待批改').waitFor();
    check(await page.evaluate(()=>motionCounts['kicking-shoe'])===1,'判錯未踹開領先答案');
    await page.evaluate(async()=>{await refresh();await refresh();});
    check(await page.evaluate(()=>motionCounts['kicking-shoe'])===1,'輪詢重播踹紙');
    check(await undo.evaluate(button=>document.activeElement===button),'鍵盤批改後焦點未到復原按鈕');
    await undo.press('Enter');
    await receipt.getByText('已復原').waitFor();
    check(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')==='海獺組 第 1 題判為正確'),'復原後焦點未回原題');
    check(await page.evaluate(()=>motionCounts['flying-answer'])===2,'復原未將紙張收回');
    await judge('山雀組','錯誤');
    await receipt.getByText('已判錯').waitFor();
    check(await page.evaluate(()=>motionCounts['kicking-shoe'])===1,'非領先組觸發踹紙');
    await judge('海獺組','錯誤');
    await receipt.getByText('沒有其他候選答案').waitFor();
    await undo.click();
    await receipt.getByText('已復原').waitFor();
    await judge('海獺組','正確');
    await receipt.getByText('正解',{exact:true}).waitFor();
    check(await page.evaluate(()=>motionCounts['verdict-stamp'])===1,'判對未蓋章');
    await page.locator('#teacher-tabs [data-view="results"]').click();
    await page.locator('#scoreboard-table').scrollIntoViewIfNeeded();
    await page.waitForFunction(()=>motionCounts['podium-slip']===2 && motionCounts['rank-star']===1);
    await page.evaluate(async()=>{await refresh();});
    check(await page.evaluate(()=>motionCounts['podium-slip'])===2,'輪詢重播排名');
    await page.reload();
    await page.locator('#scoreboard-table .rank-star').waitFor();
    await page.locator('#scoreboard-table').scrollIntoViewIfNeeded();
    check(!await page.evaluate(()=>motionCounts['rank-star']),'重載既有結果重播');
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.setViewportSize({width:390,height:844});
    await page.locator('#teacher-tabs [data-view="monitor"]').click();
    await judge('海獺組','錯誤');
    await receipt.getByText('沒有其他候選答案').waitFor();
    check(!await page.evaluate(()=>motionCounts['kicking-shoe']),'減少動態時仍播放');
    check(await page.locator('#scoreboard-table [data-podium="1"] .rank-star').count()===2,'並列第一未各獲星記');
    await undo.click();
    await receipt.getByText('已復原').waitFor();
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'手機版面溢出');
    // Hold only the response delivery. The production handler has already committed the grade.
    await page.evaluate(()=>{
      const original=api;
      api=async (...args)=>{
        const result=await original(...args);
        if (args[0].endsWith('/review')) await new Promise(resolve=>{window.releaseGrade=resolve;});
        return result;
      };
    });
    await page.emulateMedia({reducedMotion:'no-preference'});
    await judge('海獺組','錯誤');
    await page.waitForFunction(()=>!!window.releaseGrade);
    await page.locator('#back').click();
    await page.locator('#activity-title').fill('下一場活動');
    await page.locator('#create-form button').click();
    await page.getByRole('heading',{name:'下一場活動',exact:true}).waitFor();
    await page.evaluate(async()=>{window.releaseGrade();await refresh();});
    check(!await receipt.count() && !await page.evaluate(()=>motionCounts['kicking-shoe']),'上一場回應影響新活動');
    check(!errors.length,errors.join('\n'));
    return {passed:true,kick:true,stamp:true,undo:true,peerCandidate:true,noCandidate:true,
      noReplay:true,sessionIsolation:true,receipt:true,podium:true,tiedFirst:true,keyboard:true,reducedMotion:true,mobile:true};
  } finally {await student.close();}
}
