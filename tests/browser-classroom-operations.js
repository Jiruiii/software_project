async page => {
  await page.context().route('https://www.gstatic.com/firebasejs/**',route=>{
    const body=route.request().url().endsWith('firebase-app.js') ?
      'export const initializeApp = config => config;' :
      `let notify;
      const identity = () => ({getIdToken:async()=>sessionStorage.fixture});
      const state = {currentUser:sessionStorage.signed ? identity() : null};
      export const getAuth = ()=>state, browserSessionPersistence = {}, setPersistence=async()=>{};
      export const onAuthStateChanged=(a,cb)=>{notify=cb;cb(a.currentUser);};
      export class GoogleAuthProvider {setCustomParameters(){}}
      export async function signInWithPopup(a){sessionStorage.signed='1';a.currentUser=identity();await notify(a.currentUser);}
      export async function signOut(a){delete sessionStorage.signed;a.currentUser=null;await notify(null);}`;
    return route.fulfill({contentType:'text/javascript',headers:{'Access-Control-Allow-Origin':'*'},body});
  });
  const base=new URL(page.url()).origin;
  const check=(ok,message)=>{if(!ok) throw new Error(message);};
  const errors=[];
  function watch(tab) {tab.on('pageerror',err=>errors.push(err.message));}
  watch(page);
  const request=(tab,token,path,data)=>tab.evaluate(async({token,path,data})=>{
    const res=await fetch(path,{method:data===undefined?'GET':'POST',
      headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data)});
    return {status:res.status,value:await res.json()};
  },{token,path,data});
  async function api(tab,token,path,data) {
    const r=await request(tab,token,path,data);
    check(r.status<300,path+' '+JSON.stringify(r.value)); return r.value;
  }
  const account=(actor,action,data={})=>api(page,actor,'/api/account/'+action,data);
  const course=(await account('teacher','create-course',{title:'課堂操作 A'})).course;
  const other=(await account('teacher','create-course',{title:'課堂操作 B'})).course;
  for(const id of [course,other]) await account('teacher','assistant',{course:id,uid:'assistant'});
  const teacher=await account('teacher','staff-room',{course});
  async function openRoom(tab,room,id) {
    await tab.goto(base);
    await tab.evaluate(({room,id})=>{
      sessionStorage.setItem('classroom.auth',JSON.stringify(room));
      if(id) sessionStorage.setItem('classroom.activity',id); else sessionStorage.removeItem('classroom.activity');
    },{room,id});
    await tab.goto(base+'/classroom');
  }
  const view=(tab,id)=>tab.locator('#teacher-tabs [data-view='+id+']').click();
  await openRoom(page,teacher);
  await page.locator('#activity-title').fill('手動題組與批改');
  await page.locator('#question-count').fill('2');
  await page.locator('#add-group').click();
  await page.locator('#create-form button[type=submit]').click();
  await view(page,'questions');
  const id=await page.evaluate(()=>sessionStorage.getItem('classroom.activity'));
  const path='/api/activities/'+id;
  const data=()=>api(page,teacher.token,path);
  const config=page.locator('#question-settings-forms details');
  if(!await config.nth(0).evaluate(e=>e.open)) await config.nth(0).locator('summary').click();
  await page.locator('.setup-reference').nth(0).fill('水的參考答案');
  await page.locator('.setup-reference').nth(1).fill('冰的參考答案');
  await config.nth(1).locator('summary').click();
  await page.locator('.setup-reference').nth(2).fill('仍在作答的參考答案');
  await page.locator('#save-settings').click();
  await page.waitForFunction(()=>!document.querySelector('#save-settings').disabled);
  await page.reload();
  await view(page,'questions');
  check(await page.locator('.setup-reference').nth(0).inputValue()==='水的參考答案','預填答案未保存');
  await page.locator('#start').click();
  const rooms=[];
  for(const [index,actor] of ['student','teammate','third'].entries()) {
    await account(actor,'create-team',{course,name:'測試組'+index,password:'class123'});
    rooms.push(await account(actor,'student-room',{course,aid:id}));
  }
  const student=await page.context().newPage(); watch(student);
  await openRoom(student,rooms[0],id);
  const group=student.locator('#student-questions form').first();
  await group.locator('.answer-input').nth(0).fill('相同');
  await group.locator('button[type=submit]').click();
  check((await data()).answers.length===0,'不完整的題組已收件');
  await group.locator('.answer-input').nth(1).fill('子題答案');
  await group.locator('.stake').selectOption('2');
  await group.locator('button[type=submit]').click();
  await group.locator('.saved-answer').first().waitFor();
  for(const room of rooms.slice(1))
    await api(page,room.token,path+'/bundle',{unit:'1',answers:{'1.1':'相同','1.2':'子題答案'},stake:2});
  await page.locator('#monitor-question').selectOption('1.2');
  check((await page.locator('#close-selected-scope').innerText()).includes('1.1、1.2'),'關閉範圍錯誤');
  await page.getByRole('button',{name:'關閉整個題組',exact:true}).click();
  await student.getByText('水的參考答案',{exact:true}).waitFor();
  const partial=await api(student,rooms[0].token,path);
  check(partial.available_questions.join()==='2' && !('2' in partial.references),'未關閉的答案提前公布');
  const single=student.locator('#student-questions form').nth(1);
  await single.locator('.answer-input').fill('另一題'); await single.locator('button[type=submit]').click();
  await single.locator('.saved-answer').waitFor();
  const assistant=await account('assistant','staff-room',{course,aid:id});
  const ta=await page.context().newPage();watch(ta); await openRoom(ta,assistant,id);
  await ta.locator('#monitor-question').selectOption('1.1');
  await ta.locator('#monitor-table button[data-verdict=incorrect]').first().click();
  await ta.locator('#monitor-table button[data-verdict=pending]').first().click();
  await ta.waitForFunction(()=>!document.querySelector('#monitor-table button[data-verdict=pending]'));
  const answer=(await data()).answers[0];
  check(answer.verdict==='pending' && answer.reviews.length===2,'待判或歷程錯誤');
  async function tools(tab) {
    await view(tab,'tools');
    if(!await tab.locator('#tool-classification').evaluate(e=>e.open)) await tab.locator('#tool-classification > summary').click();
  }
  await tools(ta);
  await ta.locator('#cluster-question').selectOption('1.1');
  await ta.locator('#cluster-refresh').click();
  await ta.locator('.cluster-card button[data-verdict=correct]').first().click();
  await ta.locator('#cluster-undo-area').waitFor();
  const renewed=await account('assistant','staff-room',{course,aid:id});
  await openRoom(ta,renewed,id);
  await tools(ta);
  await ta.locator('#batch-history > summary').click();
  await ta.getByRole('button',{name:'復原這個批次'}).click();
  await ta.locator('#batch-history-list').getByText('已復原',{exact:true}).waitFor();
  check((await data()).answers.filter(a=>a.question_id==='1.1').every(a=>a.verdict==='pending'),'批次復原不完整');
  await page.locator('#end').click(); await page.locator('#confirm-end').click();
  await view(page,'tools'); await page.locator('#tool-replay > summary').click();
  await page.locator('#replay-question').selectOption('1.1');
  const events=(await data()).answers.filter(a=>a.question_id==='1.1');
  const gap=(ms)=>Math.max(400,Math.min(1500,ms));
  const gaps=events.map((a,i)=>gap(i?(a.received_at-events[i-1].received_at)*1000:a.elapsed_ms));
  // Advance a controlled animation clock and compare displayed immutable receipt times.
  await page.clock.install();
  await page.clock.pauseAt(new Date(Date.now()+2000));
  const play=page.locator('#replay-play'), speed=page.locator('#replay-speed');
  const shown=page.locator('#replay-answers li');
  check(await speed.inputValue()==='1','預設速度錯誤');
  await play.click(); await page.clock.runFor(Math.ceil(gaps[0])+20);
  check(await shown.count()===1,'1× 首筆錯誤');
  await speed.selectOption('2'); await page.clock.runFor(Math.ceil(gaps[1]/2)+10);
  check(await shown.count()===2,'2× 進度錯誤');
  await play.click(); await speed.selectOption('0.5'); await page.clock.runFor(2000);
  check(await shown.count()===2,'暫停時進度改變');
  await play.click(); await page.clock.runFor(Math.ceil(gaps[2]*2)+32);
  const displayed=await shown.allTextContents();
  check(displayed.length===3 && events.every((a,i)=>displayed[i].includes(a.group_name) && displayed[i].includes((a.elapsed_ms/1000).toFixed(3))),'回放順序或秒數錯誤');
  await page.locator('#replay-reset').click();check(await shown.count()===0,'從頭重播未重置');
  await page.clock.resume();
  const board=await page.context().newPage();watch(board);
  await board.addInitScript(()=>{sessionStorage.signed='1';sessionStorage.fixture='assistant';});
  await board.goto(base+'/#course/'+course);
  await board.locator('#workspace').getByRole('button',{name:'課程排行榜',exact:true}).click();
  await board.locator('.course-ranking tbody tr').first().waitFor();
  check((await account('assistant','leaderboard',{course:other})).rows.length===0,'助教無法讀取 B 課');
  await page.evaluate(()=>{sessionStorage.signed='1';sessionStorage.fixture='teacher';});
  await page.goto(base+'/#course/'+course+'/assistant');
  await page.getByRole('button',{name:'移除助教',exact:true}).click();
  check((await page.locator('dialog').innerText()).includes('assistant@example.org'),'移除確認缺少身分');
  await page.getByRole('button',{name:'確認移除'}).click();
  await page.getByText('本課程尚未加入助教。',{exact:true}).waitFor();
  await board.getByText(/無此課程排行榜權限/).waitFor({timeout:12000});
  const denied=await request(ta,renewed.token,path+'/review',{answer_id:answer.id,revision:answer.review_revision,verdict:'correct'});
  check([401,403].includes(denied.status),'撤權後舊分頁尚可批改');
  check((await account('assistant','leaderboard',{course:other})).rows.length===0,'其他課程權限受影響');
  const history=await account('teacher','history-detail',{course,aid:id,staff:true});
  check(history.answers[0].reviews[0].email==='assistant@example.org','歷史署名消失');
  check(!errors.length,errors.join('; '));
  await student.close(); await ta.close(); await board.close();
  return {passed:true,groups:3,manualQuestions:3,batchUndoCount:3,replaySpeeds:[1,2,0.5],removedFromOneOfTwoCourses:true};
}
