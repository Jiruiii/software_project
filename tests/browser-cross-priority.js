async page => {
  const classroom = new URL('/classroom', page.url()).href;
  const fixturePage = new URL('/api/health', classroom).href;
  await page.goto(fixturePage);
  const fixture = await page.evaluate(async () => {
    async function post(token, path, data) {
      const response = await fetch(path, {method:'POST', headers:{Authorization:'Bearer '+token, 'Content-Type':'application/json'}, body:JSON.stringify(data)});
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      return result;
    }
    const course = (await post('teacher', '/api/account/create-course', {title:'跨場測試'})).course;
    const teacher = await post('teacher', '/api/account/staff-room', {course});
    const prior = await post(teacher.token, '/api/activities', {title:'第一堂', questions:['1']});
    const next = await post(teacher.token, '/api/activities', {title:'第二堂', questions:['1']});
    const students = [];
    for (const [user, name] of [['student','甲組'], ['assistant','乙組']]) {
      await post(user, '/api/account/create-team', {course, name, password:'class123'});
      const previous = await post(user, '/api/account/student-room', {course, aid:prior.id});
      const current = await post(user, '/api/account/student-room', {course, aid:next.id});
      students.push({previous, current});
    }
    const path = '/api/activities/' + prior.id;
    await post(teacher.token, path+'/question-settings', {unit:'1', betting_enabled:true,
      questions:[{question:'1', type:'choice', options:['是','否'], correct_index:0}]});
    await post(teacher.token, path+'/start', {});
    await post(students[1].previous.token, path+'/answers', {question:'1', answer:'是'});
    return {prior:prior.id, next:next.id, teacher, low:students[0].current, high:students[1].current};
  });

  async function openRoom(tab, room, aid=fixture.next) {
    await tab.goto(fixturePage);
    await tab.evaluate(({room, aid}) => {
      sessionStorage.setItem('classroom.auth', JSON.stringify(room));
      sessionStorage.setItem('classroom.activity', aid);
    }, {room, aid});
    await tab.goto(classroom);
    await tab.waitForFunction(() => current?.phase === 'preparing');
  }
  await openRoom(page, fixture.teacher);
  const enable = page.getByRole('checkbox',{name:'讓低分組先答 3 秒'});
  const source = page.getByLabel('參考哪一場活動的成績？');
  await page.getByText('這門課還沒有已結束的活動可供參考，各組會同時開始。').waitFor();
  if (!await enable.isDisabled() || await source.isVisible()) throw Error('沒有活動時不應能開啟保底');
  const ended=await page.request.post(new URL('/api/activities/'+fixture.prior+'/end',classroom).href,{
    headers:{Authorization:'Bearer '+fixture.teacher.token},data:{}});
  if (!ended.ok()) throw Error('參考活動未結束');
  await page.getByText('各組同時開始作答。',{exact:true}).waitFor();
  if (await enable.isChecked() || await source.isVisible()) throw Error('預設應關閉低分組先答');
  await enable.check();
  for (const action of ['save-settings','start']) {
    await page.locator('#'+action).click();
    await page.getByText('請選擇要參考的活動，或取消「讓低分組先答 3 秒」。').waitFor();
    if (!await source.evaluate(el=>document.activeElement===el) || await page.evaluate(()=>current.phase)!=='preparing') throw Error('缺少來源時應保留在設定頁');
  }
  await source.selectOption(fixture.prior);
  await page.evaluate(()=>refresh());
  if (!await enable.isChecked() || await source.inputValue()!==fixture.prior) throw Error('輪詢蓋掉未儲存的選擇');
  await page.locator('#priority-rule-help').filter({hasText:'已進入「第二堂」且參加過「第一堂」'}).waitFor();
  const desktop=page.viewportSize();
  await page.setViewportSize({width:390,height:844});
  await page.locator('#priority-rule-field').screenshot({path:'output/playwright/priority-rule-mobile.png'});
  if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw Error('手機版參考活動設定超出畫面');
  await page.setViewportSize(desktop);
  await page.locator('#save-settings').click();
  await page.waitForFunction(id => current.settings.priority_source === id, fixture.prior);
  await page.reload();
  await page.waitForFunction(id => document.querySelector('#priority-source').value === id, fixture.prior);
  if (!await enable.isChecked() || !await source.isVisible()) throw Error('重新載入沒有還原已啟用的規則');
  await enable.uncheck();
  await page.locator('#save-settings').click();
  await page.waitForFunction(()=>current.settings.priority_source===null);
  await page.reload();
  await enable.waitFor();
  if (await enable.isChecked() || await source.isVisible()) throw Error('停用後重開應為全班同時開始');
  await enable.check();
  await source.selectOption(fixture.prior);
  await page.locator('#quiz-mode').selectOption('sequential');
  if (await source.isVisible() || await enable.isVisible()) throw Error('逐題模式應使用本場成績');
  await page.locator('#quiz-mode').selectOption('all');
  if (!await source.isVisible() || await source.inputValue()!==fixture.prior) throw Error('切回全題模式未保留草稿');

  const low = await page.context().newPage();
  const high = await page.context().newPage();
  const sound = tab=>tab.getByRole('checkbox',{name:'作答倒數最後 3 秒播放心跳聲'});
  function observeAudio() {
    const prototype=AudioBufferSourceNode.prototype;
    const start=prototype.start, stop=prototype.stop;
    window.heartbeats={starts:[],stops:0,decoded:0};
    const decode=AudioContext.prototype.decodeAudioData;
    AudioContext.prototype.decodeAudioData=async function(...args) {
      const buffer=await decode.apply(this,args);
      heartbeats.decoded++;
      return buffer;
    };
    prototype.start=function(when,offset=0,...rest) {
      const result=start.call(this,when,offset,...rest);
      heartbeats.starts.push({offset,duration:this.buffer.duration,countdown:document.getElementById('countdown').textContent});
      return result;
    };
    prototype.stop=function(...args) {heartbeats.stops++;return stop.apply(this,args);};
  }
  try {
    await Promise.all([low.addInitScript(observeAudio),high.addInitScript(observeAudio)]);
    await Promise.all([openRoom(low, fixture.low), openRoom(high, fixture.high)]);
    if(await sound(low).isVisible()) throw Error('不限時不應顯示倒數音效');
    await page.locator('#quiz-duration').fill('11');
    await page.locator('#save-settings').click();
    await Promise.all([sound(low).waitFor(),sound(high).waitFor()]);
    if(await sound(page).count() || await sound(low).isChecked() || await sound(high).isChecked()) throw Error('心跳聲應只在學生端選用，預設關閉');
    await sound(low).check();
    await page.locator('#start').click();
    await Promise.all([
      low.waitForFunction(() => document.querySelector('#round-status').textContent.includes('本組可先答') && !document.querySelector('.question-card button').disabled),
      high.waitForFunction(() => document.querySelector('#round-status').textContent.includes('請等倒數結束後作答') && document.querySelector('.question-card button').disabled)
    ]);
    await low.locator('#priority-track').waitFor({state:'visible'});
    await high.locator('#priority-track').waitFor({state:'visible'});
    await low.evaluate(()=>refresh());
    await high.waitForFunction(() => !document.querySelector('.question-card button').disabled && document.querySelector('#round-status').hidden);
    if(await high.locator('#priority-track').isVisible()) throw Error('保底結束後仍顯示倒數線');
    if(await low.evaluate(()=>heartbeats.starts.length) || await high.evaluate(()=>heartbeats.starts.length)) throw Error('開場保底三秒不應播放心跳');
    await high.locator('#answer-0').fill('一般作答');
    await high.locator('.question-card button').click();
    await high.waitForFunction(() => current.answers[0]?.text === '一般作答');
    await low.waitForFunction(()=>heartbeats.starts.length===1);
    const first=await low.evaluate(()=>heartbeats.starts[0]);
    if(first.duration!==3 || !first.countdown.startsWith('剩餘 3 秒')) throw Error('開啟音效後應在作答剩三秒時開始播放');
    if(await high.evaluate(()=>heartbeats.starts.length)) throw Error('靜音的學生播放了心跳');
    await sound(high).check();
    await high.waitForFunction(()=>heartbeats.starts.length===1);
    const late=await high.evaluate(()=>heartbeats.starts[0]);
    if(late.offset<=0 || late.offset>=3 || !/剩餘 [1-3] 秒/.test(late.countdown)) throw Error('中途開啟應只播放剩餘部分');
    for(const tab of [low,high]) {
      await tab.waitForFunction(()=>heartbeats.stops===1);
      if(await tab.evaluate(()=>heartbeats.starts.length!==1)) throw Error('更新狀態時重播了倒數');
    }
    await low.waitForFunction(()=>current.phase==='results');
    await verifyAudioLifecycle(low);
    await verifySequentialCountdown(low);
    return {passed:true, sourceSaved:true, bothStudentStates:true, submittedAfterWindow:true,
      answerDeadline:true,sequentialCountdown:true,lateEnable:true,mute:true,background:true,loadFailure:true};
  } finally {
    await Promise.all([low.close(), high.close()]);
  }

  async function verifySequentialCountdown(tab) {
    async function post(token,path,data={}) {
      const response=await page.request.post(new URL(path,classroom).href,{headers:{Authorization:'Bearer '+token},data});
      if(!response.ok()) throw Error('逐題倒數驗收請求失敗 '+path);
      return response.json();
    }
    const teacher=fixture.teacher.token;
    const activity=await post(teacher,'/api/activities',{title:'逐題限時驗收',questions:['1','2']});
    const path='/api/activities/'+activity.id;
    await post(teacher,path+'/settings',{mode:'sequential',duration_seconds:6,fairness:false});
    const student=await post('student','/api/account/student-room',{course:fixture.low.course,aid:activity.id});
    await openRoom(tab,student,activity.id);
    await sound(tab).check();
    await post(teacher,path+'/start');
    await tab.waitForFunction(()=>heartbeats.starts.length===1);
    await post(teacher,path+'/round',{action:'close'});
    await tab.waitForFunction(()=>!current.round.round_open && heartbeats.stops===1);
    await post(teacher,path+'/round',{action:'next'});
    await tab.waitForFunction(()=>current.round.unit_id==='2' && current.round.round_open);
    if(await tab.evaluate(()=>heartbeats.starts.length!==1)) throw Error('第二題開放時太早播放心跳');
    await tab.waitForFunction(()=>heartbeats.starts.length===2);
    await tab.waitForFunction(()=>current.phase==='results' && heartbeats.stops===2);
    if(await tab.evaluate(()=>heartbeats.starts.some(play=>!play.countdown.startsWith('剩餘 3 秒')))) throw Error('逐題心跳沒有對準最後三秒');
  }

  async function verifyAudioLifecycle(tab) {
    // Drive repeatable deadline and visibility transitions through the normal student renderer.
    await tab.evaluate(()=>{
      const countdown=classroomMotion.countdown;
      classroomMotion.countdown=()=>{}; // Keep fixture transitions independent of polling.
      let deadline=0;
      window.showCountdown=(seconds,newWindow=false,limit=10)=>{
        if(newWindow) deadline++;
        countdown({...current,phase:'active',settings:{mode:'sequential',fairness:false,duration_seconds:limit},
          round:{deadline:limit?deadline:null,round_index:deadline,round_open:seconds>0},server_time:deadline-seconds});
      };
      window.simulateHidden=hidden=>{
        Object.defineProperty(document,'hidden',{configurable:true,value:hidden});
        document.dispatchEvent(new Event('visibilitychange'));
      };
      showCountdown(2.8,true,0);
      if(heartbeats.starts.length!==1) throw Error('無期限不應播放心跳');
      showCountdown(2.8,true);
    });
    await tab.waitForFunction(()=>heartbeats.starts.length===2);
    await tab.evaluate(()=>simulateHidden(true));
    await tab.waitForFunction(()=>heartbeats.stops===2);
    await tab.evaluate(()=>simulateHidden(false));
    await tab.waitForFunction(()=>heartbeats.starts.length===3);
    const offsets=await tab.evaluate(()=>heartbeats.starts.slice(-2).map(s=>s.offset));
    if(offsets[1]<=offsets[0]) throw Error('切回分頁後從頭重播');
    await sound(tab).uncheck();
    await tab.waitForFunction(()=>heartbeats.stops===3);
    await tab.route('**/priority-heartbeat.wav',route=>route.fulfill({status:503,body:''}));
    await sound(tab).check();
    await tab.locator('#heartbeat-error').waitFor();
    if(await sound(tab).isChecked()) throw Error('載入失敗時開關沒有回復');
    await tab.unroute('**/priority-heartbeat.wav');
    await tab.evaluate(()=>showCountdown(0));
    let deliver;
    const hold=new Promise(resolve=>{deliver=resolve;});
    await tab.route('**/priority-heartbeat.wav',async route=>{await hold;await route.fallback();});
    const decoded=await tab.evaluate(()=>heartbeats.decoded);
    const request=tab.waitForRequest('**/priority-heartbeat.wav');
    await sound(tab).check();
    await request;
    await tab.evaluate(()=>{showCountdown(1.8,true);showCountdown(0);});
    deliver();
    await tab.waitForFunction(before=>heartbeats.decoded>before,decoded);
    if(await tab.evaluate(()=>heartbeats.starts.length!==3)) throw Error('關題後才載入的音軌不應播放');
    await tab.evaluate(()=>showCountdown(2.5,true));
    await tab.waitForFunction(()=>heartbeats.starts.length===4);
    await tab.evaluate(()=>classroomMotion.reset());
    if(await tab.evaluate(()=>heartbeats.stops!==4 || document.getElementById('heartbeat-enabled').checked)) throw Error('離開活動後未重設心跳');
  }
}
