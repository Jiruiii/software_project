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
      const animation=native.apply(this,args);
      if (window.holdErase && this.closest('.erase-scene')) animation.pause();
      return animation;
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
    await page.evaluate(()=>{window.holdErase=true;});
    await page.getByRole('button',{name:'海獺組 第 1 題判為錯誤',exact:true}).press('Enter');
    await receipt.getByText('遞補：山雀組 · 待批改').waitFor();
    check(await page.evaluate(()=>motionCounts['eraser-sweep'])===1,'判錯未擦除領先答案');
    const stage=receipt.locator('.review-stage'), scene=stage.locator('.erase-scene');
    const desktop=page.viewportSize();
    for (const width of [desktop.width,390]) {
      await page.setViewportSize({width,height:desktop.height});
      const readable=await scene.evaluate(node=>{
        const animations=node.getAnimations({subtree:true});
        animations.forEach(a=>{a.currentTime=400;});
        const writing=node.querySelector('.chalk-answer'), eraser=node.querySelector('.board-eraser');
        const board=node.getBoundingClientRect(), group=writing.querySelector('b');
        const atRest=animations.every(a=>a.effect.getTiming().duration>=1200) &&
          eraser.getBoundingClientRect().left>=board.right && parseFloat(getComputedStyle(group).fontSize)>=18 &&
          node.clientHeight>=96 && eraser.offsetWidth>=72 && node.clientWidth<=node.closest('td').clientWidth &&
          document.documentElement.scrollWidth<=innerWidth;
        // At two different points on the board, the exposed text ends beneath the eraser.
        const synchronized=[950,1250].every(time=>{
          animations.forEach(a=>{a.currentTime=time;});
          const block=eraser.getBoundingClientRect();
          const match=getComputedStyle(writing).clipPath.match(/ ([\d.]+)%/);
          if (!match) return false;
          const edge=board.right-board.width*Number(match[1])/100;
          return edge>board.left && edge<board.right && block.left<edge && block.right>edge;
        });
        return atRest && synchronized;
      });
      check(readable,'判錯回饋尺寸或認讀停留不足：'+width);
    }
    await page.setViewportSize(desktop);
    await page.evaluate(async()=>{await refresh();await refresh();});
    check(await page.evaluate(()=>motionCounts['eraser-sweep'])===1,'輪詢重播擦除');
    const stageHeight=await stage.evaluate(node=>node.offsetHeight);
    await scene.evaluate(node=>{
      window.holdErase=false;
      node.getAnimations({subtree:true}).forEach(a=>a.play());
    });
    await scene.waitFor({state:'detached'});
    await receipt.getByText('海獺組 判錯',{exact:true}).waitFor();
    await receipt.getByText('遞補：山雀組 · 待批改').waitFor();
    check(await stage.evaluate(node=>node.offsetHeight)===stageHeight,'擦除結束造成批改列跳動');
    check(await undo.evaluate(button=>document.activeElement===button),'鍵盤批改後焦點未到復原按鈕');
    await undo.press('Enter');
    await receipt.getByText('已復原').waitFor();
    check(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')==='海獺組 第 1 題判為正確'),'復原後焦點未回原題');
    check(await page.evaluate(()=>motionCounts['chalk-answer'])===2,'復原未重現字跡');
    await page.setViewportSize({width:390,height:520});
    const peerWrong=page.getByRole('button',{name:'山雀組 第 1 題判為錯誤',exact:true});
    await peerWrong.evaluate(button=>button.scrollIntoView({block:'end'}));
    await peerWrong.click();
    await receipt.getByText('山雀組 判錯',{exact:true}).waitFor();
    check(await page.evaluate(()=>motionCounts['eraser-sweep'])===2,'非領先組判錯未播放板擦');
    check(!await receipt.locator('.review-outcome').count(),'非領先組顯示了遞補結果');
    check(await stage.evaluate(el=>{
      const rect=el.getBoundingClientRect(), table=el.closest('.table-scroll').getBoundingClientRect();
      return rect.bottom<=Math.min(table.bottom,innerHeight)+1 && rect.top>=Math.max(table.top,0)-1;
    }),'窄螢幕上看不到本次判錯回饋');
    await page.evaluate(()=>refresh());
    check(await page.evaluate(()=>motionCounts['eraser-sweep'])===2,'輪詢重播非領先組判錯');
    await undo.click();
    await receipt.getByText('已復原').waitFor();
    check(await page.evaluate(()=>motionCounts['chalk-answer'])===4,'非領先組復原未重現字跡');
    await peerWrong.click();
    await receipt.getByText('山雀組 判錯',{exact:true}).waitFor();
    await page.setViewportSize(desktop);
    await judge('海獺組','錯誤');
    await receipt.getByText('沒有其他候選答案').waitFor();
    await undo.click();
    await receipt.getByText('已復原').waitFor();
    check(!await page.locator('.eraser-sweep').count(),'復原後仍顯示前一次判錯板擦');
    await judge('海獺組','正確');
    await receipt.getByText('正解',{exact:true}).waitFor();
    check(await page.evaluate(()=>motionCounts['verdict-stamp'])===1,'判對未蓋章');
    for (const width of [desktop.width,390]) {
      await page.setViewportSize({width,height:desktop.height});
      check(await receipt.locator('.verdict-stamp').evaluate(stamp=>{
        const box=stamp.getBoundingClientRect(), stage=stamp.parentElement.getBoundingClientRect();
        return parseFloat(getComputedStyle(stamp).fontSize)>=32 && box.left>=stage.left && box.right<=stage.right;
      }),'正解章尺寸不足或被截斷');
    }
    await page.setViewportSize(desktop);
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
    check(!await page.evaluate(()=>motionCounts['eraser-sweep']),'減少動態時仍播放');
    await receipt.getByText('海獺組 判錯',{exact:true}).waitFor();
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
    check(!await receipt.count() && !await page.evaluate(()=>motionCounts['eraser-sweep']),'上一場回應影響新活動');
    check(!errors.length,errors.join('\n'));
    return {passed:true,erase:true,nonLeaderErase:true,visibleFeedback:true,stamp:true,undo:true,peerCandidate:true,noCandidate:true,
      noReplay:true,sessionIsolation:true,receipt:true,podium:true,tiedFirst:true,keyboard:true,reducedMotion:true,mobile:true};
  } finally {await student.close();}
}
