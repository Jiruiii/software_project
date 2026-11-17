// Isolated QA browser: 30 HTTP participants, teacher + 3 representative student tabs.
async (page) => {
  const base = new URL(page.url()).origin;
  const check = (value,message) => {if(!value) throw new Error(message);};
  const errors = [], students = [];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.evaluate(()=>sessionStorage.clear()); await page.reload();
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#choose-teacher').click();
  await page.locator('#teacher-password').fill('many-groups-test-only');
  await page.locator('#login-form button').click();
  await page.locator('#activity-title').fill('30 組同時搶答・自動驗收');
  await page.locator('#question-count').fill('6');
  await page.locator('#create-form button').click();
  await page.locator('#activity').waitFor({state:'visible'});
  const code = await page.locator('#session-code').innerText();
  const teacher = await page.evaluate(()=>JSON.parse(sessionStorage.getItem('classroom.auth')));
  const activityId = await page.evaluate(()=>sessionStorage.getItem('classroom.activity'));
  const path = '/api/activities/'+activityId;
  const api = async (url,body,token) => {
    const response=await page.request.fetch(base+url,{method:body===undefined?'GET':'POST',
      headers:token?{Authorization:'Bearer '+token}:{},data:body,timeout:5000});
    const result=await response.json();
    check(response.ok(),`${url}: ${response.status()} ${result.error||''}`); return result;
  };
  const people=[];
  for(let i=1;i<=30;i++) {
    const name=`測試組${String(i).padStart(2,'0')}`;
    people.push({name,...await api('/api/join',{code,group:name})});
  }
  for(const index of [0,14,29]) {
    const student=await page.context().newPage(); students.push({page:student,index});
    student.on('pageerror',error=>errors.push(String(error)));
    await student.goto(base);
    await student.locator('#join-code').fill(code);
    await student.locator('#join-group').fill(people[index].name);
    await student.locator('#join-form button').click();
    await student.locator('#activity').waitFor({state:'visible'});
    check(await student.locator('#answer-0').isDisabled(),'before-start gate');
    await student.evaluate(()=>{
      window.qaTimes={};
      new MutationObserver(()=>{
        if(!document.querySelector('#answer-0').disabled&&!window.qaTimes.start)window.qaTimes.start=Date.now();
        if(!document.querySelector('#results').hidden&&!window.qaTimes.end)window.qaTimes.end=Date.now();
      }).observe(document.querySelector('#activity'),{attributes:true,subtree:true});
    });
  }
  await page.waitForFunction(()=>document.querySelectorAll('#monitor-table tbody tr').length===30);
  await page.evaluate(()=>{
    document.querySelector('#start').addEventListener('click',()=>window.qaStartClick=Date.now(),{once:true});
    document.querySelector('#end').addEventListener('click',()=>window.qaEndClick=Date.now(),{once:true});
    new MutationObserver(()=>{
      if(document.querySelectorAll('#monitor-table .cell-answer').length===180&&!window.qaAllAnswersAt)window.qaAllAnswersAt=Date.now();
    }).observe(document.querySelector('#monitor-table'),{childList:true,subtree:true});
  });
  await page.locator('#start').click();
  await Promise.all(students.map(s=>s.page.waitForFunction(()=>!!window.qaTimes.start,undefined,{timeout:3000})));
  const started=await page.evaluate(()=>window.qaStartClick);
  const startSyncMs=Math.max(...await Promise.all(students.map(s=>s.page.evaluate(()=>window.qaTimes.start))))-started;
  check(startSyncMs<=2000,`start sync ${startSyncMs}ms`);
  let lastReceived=0;
  for(let q=1;q<=6;q++) {
    // Give each question a different known first sender to catch UI rows that
    // accidentally reuse another question's winner; the remaining 29 race.
    const leader=people[(q-1)*5];
    const first=await api(path+'/answers',{question:String(q),answer:`${leader.name} / 第 ${q} 題`},leader.token);
    const replies=[first,...await Promise.all(people.filter(p=>p!==leader).map(p=>api(path+'/answers',{question:String(q),answer:`${p.name} / 第 ${q} 題`},p.token)))];
    lastReceived=Math.max(lastReceived,...replies.map(r=>r.received_at*1000));
  }
  await page.waitForFunction(()=>document.querySelectorAll('#monitor-table .cell-answer').length===180,undefined,{timeout:3000});
  const teacherDisplayLagMs=Math.max(0,Math.round(await page.evaluate(()=>window.qaAllAnswersAt)-lastReceived));
  check(teacherDisplayLagMs<=2000,`teacher display lag ${teacherDisplayLagMs}ms`);
  const table=await page.locator('#monitor-table tbody tr').evaluateAll(rows=>rows.map(row=>({
    name:row.querySelector('th').textContent,
    answers:[...row.querySelectorAll('td')].map(td=>({text:td.querySelector('.cell-answer')?.textContent,time:td.querySelector('small')?.textContent}))
  })));
  check(table.length===30,'teacher missing groups');
  for(const row of table) {
    check(row.answers.length===6,'teacher missing question');
    row.answers.forEach((answer,i)=>{
      check(answer.text===`${row.name} / 第 ${i+1} 題`,'teacher mixed group/question');
      check(/\d+:\d+:\d+.*秒/.test(answer.time),'teacher missing receipt time');
    });
  }
  const active=await api(path,undefined,teacher.token);
  check(active.answers.length===180,'server missing answers');
  const expected=[];
  for(let q=1;q<=6;q++) {
    const ordered=active.answers.filter(a=>a.question_id===String(q)).sort((a,b)=>a.id-b.id);
    check(ordered.length===30,'server missing per-question answer');
    check(ordered[0].group_name===people[(q-1)*5].name,'known first sender lost');
    expected.push({question:String(q),group:ordered[0].group_name,text:ordered[0].text});
  }
  for(const s of students) {
    await s.page.waitForFunction(()=>document.querySelectorAll('.saved-answer:not([hidden])').length===6,undefined,{timeout:3000});
    const own=await s.page.locator('.saved-answer').allTextContents();
    check(own.every((answer,i)=>answer===`${people[s.index].name} / 第 ${i+1} 題`),'student mixed answers');
    const state=await api(path,undefined,people[s.index].token);
    check(!('results' in state)&&!('groups' in state),'pre-end privacy');
    check(state.answers.length===6,'student received other group answers');
  }
  await page.screenshot({path:'output/playwright/many-groups-teacher-active.png',fullPage:true});
  await page.locator('#end').click();
  await Promise.all(students.map(s=>s.page.waitForFunction(()=>!!window.qaTimes.end,undefined,{timeout:3000})));
  const ended=await page.evaluate(()=>window.qaEndClick);
  const endSyncMs=Math.max(...await Promise.all(students.map(s=>s.page.evaluate(()=>window.qaTimes.end))))-ended;
  check(endSyncMs<=2000,`end sync ${endSyncMs}ms`);
  for(const view of [page,...students.map(s=>s.page)]) {
    const rows=await view.locator('#results .result-row').evaluateAll(nodes=>nodes.map(row=>({
      number:row.querySelector('.result-number').textContent,group:row.querySelector('.winner').textContent,
      answer:row.querySelector('.result-answer')?.textContent
    })));
    check(rows.length===6,'result missing question');
    rows.forEach((row,i)=>{
      check(row.number===`第 ${expected[i].question} 題`,'result question mismatch');
      check(row.group===`${expected[i].group} · 搶答成功（未判定）`,'result winner mismatch');
      check(row.answer===expected[i].text,'result answer mismatch');
    });
  }
  await page.screenshot({path:'output/playwright/many-groups-teacher-results.png',fullPage:true});
  await students[0].page.setViewportSize({width:390,height:844});
  check(await students[0].page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile overflow');
  await students[0].page.screenshot({path:'output/playwright/many-groups-student-results.png',fullPage:true});
  check(errors.length===0,errors.join('\n'));
  return {passed:true,simulatedGroups:30,questions:6,savedAnswers:180,
    actualBrowserTabs:4,studentTabsChecked:3,teacherCellsChecked:180,
    startSyncMs,endSyncMs,teacherDisplayLagMs,winners:expected,pageErrors:errors};
}
