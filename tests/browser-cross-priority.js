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
  await page.addInitScript(observeAudio);
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
  const sound = tab=>tab.getByRole('checkbox',{name:'作答倒數最後 3 秒播放提示音'});
  function observeAudio() {
    const prototype=AudioBufferSourceNode.prototype;
    const start=prototype.start, stop=prototype.stop;
    const outputs=new WeakMap(), countdownSources=new WeakSet(), connect=AudioNode.prototype.connect;
    AudioNode.prototype.connect=function(destination,...args) {
      if (!(this instanceof AudioBufferSourceNode) || destination!==this.context.destination) {
        return connect.call(this,destination,...args);
      }
      const meter=this.context.createAnalyser();
      meter.fftSize=1024;
      meter.smoothingTimeConstant=0;
      connect.call(this,meter,...args);
      connect.call(meter,destination);
      outputs.set(this,meter);
      return destination;
    };
    window.countdownAudio={starts:[],previews:[],stops:0,decoded:0};
    const decode=AudioContext.prototype.decodeAudioData;
    AudioContext.prototype.decodeAudioData=async function(...args) {
      const buffer=await decode.apply(this,args);
      countdownAudio.decoded++;
      return buffer;
    };
    prototype.start=function(when,offset=0,...rest) {
      const result=start.call(this,when,offset,...rest);
      const record={offset,duration:this.buffer.duration,countdown:document.getElementById('countdown').textContent,
        peak:[0,0,0,0],toneDb:[-100,-100,-100,-100],ended:false};
      (rest.length ? countdownAudio.previews : countdownAudio.starts).push(record);
      if (!rest.length) countdownSources.add(this);
      const context=this.context, playedAt=context.currentTime;
      const meter=outputs.get(this);
      if (!meter) throw Error('倒數音效音源未接上分頁輸出');
      const samples=new Float32Array(meter.fftSize), bins=new Float32Array(meter.frequencyBinCount);
      const timer=setInterval(()=>{
        const second=Math.floor(context.currentTime-playedAt+offset);
        if (second<0 || second>=4) return;
        meter.getFloatTimeDomainData(samples);
        meter.getFloatFrequencyData(bins);
        for(const s of samples) record.peak[second]=Math.max(record.peak[second],Math.abs(s));
        const hz=context.sampleRate/meter.fftSize;
        const frequency=second===3 ? 1046 : 523;
        const bin=Math.round(frequency/hz);
        record.toneDb[second]=Math.max(record.toneDb[second],bins[bin]);
      },15);
      this.addEventListener('ended',()=>{record.ended=true;clearInterval(timer);meter.disconnect();},{once:true});
      return result;
    };
    prototype.stop=function(...args) {
      if (countdownSources.has(this)) countdownAudio.stops++;
      return stop.apply(this,args);
    };
  }
  try {
    await Promise.all([low.addInitScript(observeAudio),high.addInitScript(observeAudio)]);
    await Promise.all([openRoom(low, fixture.low), openRoom(high, fixture.high)]);
    if(await sound(low).isVisible()) throw Error('不限時不應顯示倒數音效');
    await page.locator('#quiz-duration').fill('11');
    await page.locator('#save-settings').click();
    await Promise.all([sound(low).waitFor(),sound(high).waitFor()]);
    for(const tab of [page,low,high]) {
      if(!await sound(tab).isVisible() || !await sound(tab).isChecked()) throw Error('限時活動應向師生預設開啟倒數聲');
    }
    await low.getByRole('button',{name:'試聽倒數音效'}).click();
    await low.waitForFunction(()=>countdownAudio.previews[0]?.ended);
    if(!await low.evaluate(()=>countdownAudio.previews[0].toneDb.every(v=>v>-43))) throw Error('試聽缺少倒數或收尾音');
    await sound(high).uncheck();
    await high.reload();
    await sound(high).waitFor();
    if(await sound(high).isChecked()) throw Error('重新載入後沒有保留靜音');
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
    if(await low.evaluate(()=>countdownAudio.starts.length) || await high.evaluate(()=>countdownAudio.starts.length)) throw Error('開場保底三秒不應播放倒數音效');
    await high.locator('#answer-0').fill('一般作答');
    await high.locator('.question-card button').click();
    await high.waitForFunction(() => current.answers[0]?.text === '一般作答');
    await low.waitForFunction(()=>countdownAudio.starts.length===1);
    const first=await low.evaluate(()=>countdownAudio.starts[0]);
    if(Math.abs(first.duration-4.66)>.001 || first.offset>.2 || !first.countdown.startsWith('剩餘 3 秒')) throw Error('完整音檔應在作答剩三秒時從開頭播放');
    if(await high.evaluate(()=>countdownAudio.starts.length)) throw Error('靜音的學生播放了倒數音效');
    await sound(high).check();
    await high.waitForFunction(()=>countdownAudio.starts.length===1);
    const late=await high.evaluate(()=>countdownAudio.starts[0]);
    if(late.offset<=0 || late.offset>=3 || !/剩餘 [1-3] 秒/.test(late.countdown)) throw Error('中途開啟應只播放剩餘部分');
    await high.getByRole('button',{name:'試聽倒數音效'}).click();
    if(await high.evaluate(()=>countdownAudio.previews.length)) throw Error('試聽與真正倒數重疊');
    for(const tab of [page,low,high]) {
      await tab.waitForFunction(()=>countdownAudio.starts[0].ended);
      if(await tab.evaluate(()=>countdownAudio.starts.length!==1 || countdownAudio.stops!==0)) throw Error('自然到期應播放一次且保留收尾');
    }
    for(const tab of [page,low]) {
      if(!await tab.evaluate(()=>countdownAudio.starts[0].peak.every(v=>v>.18) && countdownAudio.starts[0].toneDb.every(v=>v>-43)))
        throw Error('師生的實際輸出應有三聲倒數和到期的高音');
    }
    await low.waitForFunction(()=>current.phase==='results');
    await verifyAudioLifecycle(low);
    await verifySequentialCountdown(low);
    const output=await page.evaluate(()=>countdownAudio.starts[0]);
    return {passed:true, sourceSaved:true, bothStudentStates:true, submittedAfterWindow:true,
      answerDeadline:true,sequentialCountdown:true,teacherAndStudentSignal:true,previewSignal:true,
      teacherPeakBySecond:output.peak.map(v=>Number(v.toFixed(2))),
      savedMute:true,lateEnable:true,mute:true,background:true,loadFailure:true};
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
    await tab.locator('#content-title').click();
    await post(teacher,path+'/start');
    await tab.waitForFunction(()=>countdownAudio.starts.length===1);
    await post(teacher,path+'/round',{action:'close'});
    await tab.waitForFunction(()=>!current.round.round_open && countdownAudio.stops===1);
    if(await tab.evaluate(()=>countdownAudio.starts[0].peak[3]>0)) throw Error('提早關題仍播放截止音');
    await post(teacher,path+'/round',{action:'next'});
    await tab.waitForFunction(()=>current.round.unit_id==='2' && current.round.round_open);
    if(await tab.evaluate(()=>countdownAudio.starts.length!==1)) throw Error('第二題開放時太早播放倒數音效');
    await tab.waitForFunction(()=>countdownAudio.starts.length===2);
    await tab.waitForFunction(()=>current.phase==='results' && countdownAudio.starts[1].ended);
    if(await tab.evaluate(()=>countdownAudio.stops!==1 || countdownAudio.starts[1].toneDb[3]<=-43)) throw Error('逐題自然截止時高音遭切斷');
    if(await tab.evaluate(()=>countdownAudio.starts.some(play=>!play.countdown.startsWith('剩餘 3 秒')))) throw Error('逐題倒數音效沒有對準最後三秒');
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
      if(countdownAudio.starts.length!==1) throw Error('無期限不應播放倒數音效');
      showCountdown(2.8,true);
    });
    await tab.waitForFunction(()=>countdownAudio.starts.length===2);
    await tab.evaluate(()=>simulateHidden(true));
    await tab.waitForFunction(()=>countdownAudio.stops===1);
    await tab.evaluate(()=>simulateHidden(false));
    await tab.waitForFunction(()=>countdownAudio.starts.length===3);
    const offsets=await tab.evaluate(()=>countdownAudio.starts.slice(-2).map(s=>s.offset));
    if(offsets[1]<=offsets[0]) throw Error('切回分頁後從頭重播');
    await sound(tab).uncheck();
    await tab.waitForFunction(()=>countdownAudio.stops===2);
    await tab.route('**/electronic-countdown.wav',route=>route.fulfill({status:503,body:''}));
    await sound(tab).check();
    await tab.getByText('音效載入失敗，請按「試聽倒數音效」重試。').waitFor();
    if(!await sound(tab).isChecked()) throw Error('載入失敗不應覆寫音效偏好');
    await tab.unroute('**/electronic-countdown.wav');
    await tab.evaluate(()=>showCountdown(0));
    let deliver;
    const hold=new Promise(resolve=>{deliver=resolve;});
    await tab.route('**/electronic-countdown.wav',async route=>{await hold;await route.fallback();});
    const decoded=await tab.evaluate(()=>countdownAudio.decoded);
    const request=tab.waitForRequest('**/electronic-countdown.wav');
    await tab.getByRole('button',{name:'試聽倒數音效'}).click();
    await request;
    await tab.evaluate(()=>{showCountdown(1.8,true);showCountdown(0);});
    deliver();
    await tab.waitForFunction(before=>countdownAudio.decoded>before,decoded);
    if(await tab.evaluate(()=>countdownAudio.starts.length!==3)) throw Error('關題後才載入的音軌不應播放');
    await tab.evaluate(()=>showCountdown(2.5,true));
    await tab.waitForFunction(()=>countdownAudio.starts.length===4);
    await tab.evaluate(()=>classroomMotion.reset());
    if(await tab.evaluate(()=>countdownAudio.stops!==3 || !document.getElementById('countdown-sound-setting').hidden ||
        !document.getElementById('countdown-sound-enabled').checked)) throw Error('離開活動後應停止倒數音效並保留偏好');
  }
}
