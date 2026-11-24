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
  await page.evaluate(()=>{sessionStorage.fixture='teacher';});
  const button=name=>page.getByRole('button',{name,exact:true});
  let releaseConfig;
  const configFailure=new Promise(resolve=>{releaseConfig=resolve;});
  await page.route('**/api/firebase-config',async route=>{
    await configFailure;
    await route.fulfill({status:503,json:{error:'temporarily unavailable'}});
  },{times:1});
  await page.reload({waitUntil:'domcontentloaded'});
  try {
    await page.getByRole('status').filter({hasText:'正在準備登入'}).waitFor();
  } finally { releaseConfig(); }
  await button('重新載入').click();
  await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:new URL(page.url()).origin});
  async function checkCopy(label, expected) {
    await page.bringToFront();
    await page.evaluate(()=>navigator.clipboard.writeText('尚未複製代碼'));
    const copy=button('複製'+label);
    await copy.focus();
    await copy.press('Enter');
    await copy.getByText('已複製',{exact:true}).waitFor();
    if(await page.evaluate(()=>navigator.clipboard.readText())!==expected) throw Error(label+' 的剪貼簿內容不正確');
  }
  const rail=page.locator('#work-rail');
  const directory=page.getByRole('button',{name:/^(展開|收合)目錄$/});
  async function expectDirectory(open) {
    await button(open?'收合目錄':'展開目錄').waitFor();
    if(await directory.getAttribute('aria-expanded')!==String(open) || await rail.isVisible()!==open)
      throw Error('目錄按鈕宣告的狀態與畫面不一致');
  }
  async function checkDirectoryHierarchy() {
    for(const name of ['工作區目錄','生物','本場搶答']) {
      await rail.getByRole('heading',{name,exact:true,level:2}).waitFor();
    }
    const heading=rail.getByRole('heading',{name:'工作區目錄'});
    const home=rail.getByRole('link',{name:'我的課程',exact:true});
    function metrics(el) {
      const style=getComputedStyle(el), box=el.getBoundingClientRect();
      return {size:parseFloat(style.fontSize),weight:Number(style.fontWeight),
        textLeft:box.left+parseFloat(style.paddingLeft),height:box.height};
    }
    const title=await heading.evaluate(metrics), item=await home.evaluate(metrics);
    if(title.size<=item.size || title.weight<=item.weight || title.textLeft>=item.textLeft || item.height<44)
      throw Error('分區標題與連結的字級、字重、縮排或點擊區不符');
    await home.focus();
    await page.keyboard.press('Tab');
    if(!await rail.getByRole('link',{name:'新增課程',exact:true}).evaluate(el=>el.matches(':focus-visible') && getComputedStyle(el).outlineStyle!=='none'))
      throw Error('鍵盤未移至下一個側欄連結並顯示焦點');
  }
  async function nav(name) {
    if(!await rail.isVisible()) await button('展開目錄').click();
    const target=rail.getByRole('link',{name,exact:true});
    if(!await target.isVisible()) await rail.locator('.nav-section').filter({has:page.getByText(name,{exact:true})}).getByRole('button').click();
    await target.click();
  }
  await button('學生').click();
  await page.route('**/api/account/home',route=>route.fulfill({status:503,json:{error:'請稍後再試'}}),{times:1});
  await button('使用 Google 帳號登入').click();
  await page.getByRole('status').filter({hasText:'課程資料載入失敗'}).waitFor();
  await page.screenshot({path:'output/playwright/course-login-retry.png'});
  await button('重新載入').click();
  await page.getByRole('heading',{name:'我的課程'}).waitFor();
  if(await button('重新載入').isVisible()) throw Error('恢復課程後仍顯示重試');
  await page.reload();
  await page.getByRole('heading',{name:'我的課程'}).waitFor();
  if(await page.locator('#login-roles').isVisible() || await rail.getByText('加入小組').count() || await page.locator('#workspace form').count()) throw Error('教師首頁角色或內容錯誤');
  if(!await rail.evaluate(e=>e.closest('.topbar')?.contains(e)) || await directory.isVisible()) throw Error('桌面功能應直接列在頂列');
  if(await rail.getByText('我的帳號資料',{exact:true}).count() || await rail.getByText('登出 Google 帳號').count()) throw Error('工作區導覽重複列出帳號操作');
  await button('帳號選單').click();
  const accountMenu=page.locator('#work-menu');
  await accountMenu.getByRole('link',{name:'我的帳號資料'}).waitFor();
  if(await accountMenu.getByRole('link',{name:'學生作答與批改'}).count()) throw Error('教師頭像選單重複列出批改入口');
  await page.keyboard.press('Escape');
  await nav('學生作答與批改');
  await page.getByRole('heading',{name:'學生作答與批改',level:1}).waitFor();
  const adminPreview=await page.context().newPage();
  await adminPreview.addInitScript(()=>{sessionStorage.fixture='admin';sessionStorage.signed='1';});
  await adminPreview.goto(new URL('/#legacy',page.url()).href);
  await adminPreview.waitForURL('**/#home');
  if(await adminPreview.getByText('將未歸屬活動加入課程').count()) throw Error('舊活動入口仍存在');
  await adminPreview.close();
  await nav('新增課程');
  await page.getByLabel('課程名稱').fill('數學');
  await button('建立課程').click();
  await page.getByRole('heading',{name:'數學',level:1}).waitFor();
  const mathCode=await page.locator('#workspace .share-code code').innerText();
  await nav('新增課程');
  await page.getByLabel('課程名稱').fill('生物');
  await button('建立課程').click();
  const code=await page.locator('#workspace .share-code code').innerText();
  await checkCopy('課程代碼',code);
  await nav('我的課程');
  await page.setViewportSize({width:390,height:800});
  await page.locator('.gallery-arrow').last().click();
  await page.waitForFunction(()=>document.querySelector('.card-track').scrollLeft>0 && document.querySelector('.gallery-arrow:last-child').disabled && document.documentElement.scrollWidth<=innerWidth);
  await page.locator('.gallery-arrow').first().press('Enter');
  await page.waitForFunction(()=>document.querySelector('.card-track').scrollLeft<2);
  await page.setViewportSize({width:1360,height:950});
  await page.screenshot({path:'output/playwright/course-cards-desktop.png'});
  await button('生物 · 授課教師').click();
  const historyTab=await page.context().newPage();
  await historyTab.addInitScript(()=>{sessionStorage.fixture='teacher';sessionStorage.signed='1';});
  await historyTab.goto(new URL('/#course/'+mathCode,page.url()).href);
  await historyTab.getByRole('link',{name:'學生作答與批改'}).click();
  if(await historyTab.getByLabel('選擇課程').inputValue()!==mathCode) throw Error('批改頁跳到其他課程');
  await historyTab.close();
  await page.screenshot({path:'output/playwright/course-workspace-desktop.png'});
  const courseMenu=rail.getByRole('button',{name:'生物',exact:true});
  await courseMenu.press('Enter');
  await rail.getByRole('link',{name:'課程活動'}).focus();
  await page.keyboard.press('Escape');
  if(await rail.getByRole('link',{name:'課程活動'}).isVisible() || !await courseMenu.evaluate(el=>el===document.activeElement)) throw Error('桌面課程選單未正確收合或返回焦點');
  await page.locator('#workspace').getByRole('button',{name:'建立搶答活動',exact:true}).click();
  await page.locator('#activity-title').fill('第一堂');
  await rail.getByRole('link',{name:'我的課程',exact:true}).waitFor();
  await page.locator('#create-form button').click();
  await page.locator('#session-code').waitFor();
  if(await page.locator('#session-code').innerText()!==code) throw Error('活動內課程代碼不一致');
  await checkCopy('課程代碼',code);
  await page.setViewportSize({width:390,height:800});
  await expectDirectory(false);
  await directory.click();
  await expectDirectory(true);
  await page.setViewportSize({width:1360,height:950});
  await rail.getByRole('button',{name:'生物',exact:true}).waitFor();
  if(await rail.locator('a[aria-current=location]').innerText()!=='課程活動') throw Error('課堂頂列未標明目前課程');
  if(await rail.locator('#teacher-tabs').count() || !await page.locator('.session-main #teacher-tabs').isVisible()) throw Error('桌面活動分頁未返回主內容');
  await page.screenshot({path:'output/playwright/navigation-desktop.png'});
  await page.setViewportSize({width:390,height:800});
  await expectDirectory(false);
  await directory.click();
  await page.screenshot({path:'output/playwright/navigation-mobile.png'});
  await checkDirectoryHierarchy();
  await directory.click();
  async function fromDirectory(control) {
    await directory.click();
    await rail.locator(control).click();
  }
  async function expectContentFocus(id) {
    await page.waitForFunction(expected=>document.activeElement.id===expected,id);
    if(await directory.getAttribute('aria-expanded')!=='false') throw Error('活動目錄仍蓋住內容');
  }
  await fromDirectory('[data-view="questions"]');
  await expectContentFocus('content-title');
  if(await rail.locator('#teacher-tabs [aria-current="page"]').getAttribute('data-view')!=='questions')
    throw Error('目錄未標示目前的搶答頁籤');
  await fromDirectory('[data-view="settings"]');
  await page.locator('#quiz-duration').fill('3601');
  await fromDirectory('#start');
  await expectContentFocus('quiz-duration');
  if(await page.locator('#start').getAttribute('hidden')!==null) throw Error('設定無效仍開始活動');
  await page.locator('#quiz-duration').fill('0');
  await fromDirectory('#save-settings');
  await expectContentFocus('content-title');
  await page.getByText('所有設定已儲存。').waitFor();
  await fromDirectory('#start');
  await expectContentFocus('content-title');
  await page.locator('#live-ranking').waitFor();
  await page.screenshot({path:'output/playwright/course-mobile-started.png'});
  await page.setViewportSize({width:1360,height:950});
  if(await page.locator('#activity-chat').isVisible()) throw Error('教師看到學生公用頻道');
  await page.locator('#end').click();
  if(await page.locator(':focus').getAttribute('value')!=='cancel') throw Error('預設焦點應在取消');
  await page.keyboard.press('Enter');
  await page.waitForFunction(()=>!document.querySelector('#end-dialog').open && current.phase==='active');
  await page.locator('#end').click();
  await page.keyboard.press('Escape');
  await nav('我的課程');
  await button('帳號選單').click();
  await page.locator('#work-menu').getByRole('button',{name:'登出 Google 帳號'}).click();
  await page.evaluate(()=>{sessionStorage.fixture='student';});
  await button('老師與助教').click();
  await button('使用 Google 帳號登入').click();
  await page.getByRole('heading',{name:'我的課程'}).waitFor();
  if(await page.locator('#login-roles').isVisible() || await rail.getByText('學生作答與批改').count() || await page.locator('#workspace form').count()) throw Error('學生首頁角色或內容錯誤');
  await nav('加入小組');
  await page.getByLabel('小組密碼',{exact:true}).waitFor();
  await nav('建立小組');
  await page.getByLabel('老師提供的課程代碼').fill(code);
  await page.getByLabel('小組名稱').fill('甲組');
  await page.getByLabel(/設定小組密碼/).fill('class123');
  await button('建立小組').click();
  await button('生物 · 甲組').click();
  await page.reload();
  await page.getByText(/本課程累計.*0 分/).waitFor();
  await checkCopy('課程代碼',code);
  await nav('課程排行榜');
  await page.getByRole('row',{name:/1.*甲組.*本組.*0/}).waitFor();
  if(await page.getByRole('option').count()!==1) throw Error('學生排行榜洩漏其他課程');
  await nav('我的課程');
  await button('生物 · 甲組').click();
  await page.getByRole('button',{name:/第一堂/}).click();
  await page.waitForFunction(()=>document.getElementById('role-badge')?.textContent==='甲組');
  for(const width of [320,601,768,1024,1280]) {
    await page.setViewportSize({width,height:800});
    const fits=await page.locator('#session-code-block').evaluate(block=>{
      const card=block.getBoundingClientRect();
      const value=block.querySelector('code');
      const text=document.createRange();
      text.selectNodeContents(value);
      return [text.getBoundingClientRect(),block.querySelector('button').getBoundingClientRect()]
        .every(r=>r.left>=card.left && r.right<=Math.min(card.right,innerWidth) && r.top>=card.top && r.bottom<=card.bottom);
    });
    if(!fits) throw Error('學生課程代碼或按鈕超出 '+width+'px 卡片');
  }
  await checkCopy('課程代碼',code);
  await page.evaluate(()=>{
    Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined});
    Object.defineProperty(document,'execCommand',{configurable:true,value:()=>false});
  });
  await button('複製課程代碼').click();
  await page.getByText('請用系統的複製指令複製已選取的文字。').waitFor();
  if(await page.evaluate(()=>getSelection().toString())!==code) throw Error('未選取完整代碼');
  await page.evaluate(()=>{delete navigator.clipboard; delete document.execCommand;});
  const peer=await page.context().newPage();
  await peer.addInitScript(()=>{sessionStorage.fixture='teammate';sessionStorage.signed='1';});
  await peer.goto(new URL('/#join',page.url()).href);
  await peer.getByLabel('老師提供的課程代碼').fill(code);
  await peer.getByLabel('小組名稱').fill('甲組');
  await peer.getByLabel('小組密碼',{exact:true}).fill('wrong-pass');
  await peer.getByRole('button',{name:'加入小組',exact:true}).click();
  await peer.getByRole('status').filter({hasText:'小組名稱或密碼錯誤'}).waitFor();
  await peer.getByLabel('小組密碼',{exact:true}).fill('class123');
  await peer.getByRole('button',{name:'加入小組',exact:true}).click();
  await peer.getByRole('button',{name:'生物 · 甲組'}).click();
  await peer.getByRole('button',{name:/第一堂/}).click();
  await peer.locator('#activity-chat summary').click();
  await page.locator('#activity-chat summary').click();
  await page.getByLabel('以「甲組」發言').fill('課堂討論');
  await page.locator('#chat-form button').click();
  await page.locator('#chat-log p').filter({hasText:'課堂討論'}).getByText('甲組',{exact:true}).waitFor();
  await peer.locator('#chat-log p').filter({hasText:'課堂討論'}).getByText('甲組',{exact:true}).waitFor();
  await page.locator('#activity-chat summary').click();
  await page.locator('#answer-0').fill('測試答案');
  await page.locator('#stake-0').selectOption('2');
  await nav('作答紀錄');
  await page.getByRole('heading',{name:'作答紀錄',level:1}).waitFor();
  await nav('我的課程');
  await button('生物 · 甲組').click();
  await page.getByRole('button',{name:/第一堂/}).click();
  await page.locator('#answer-0').waitFor();
  if(await page.locator('#answer-0').inputValue()!=='測試答案' || await page.locator('#stake-0').inputValue()!=='2') throw Error('返回活動後未還原答案與押注');
  await page.locator('#stake-0').selectOption('0');
  await page.locator('.question-card button').first().click();
  await page.waitForFunction(()=>current.answers.length===1);
  await peer.locator('.saved-answer').first().filter({hasText:'測試答案'}).waitFor();
  await peer.getByText('✓ 隊友已送出',{exact:true}).waitFor();
  await page.getByText('✓ 已交卷',{exact:true}).waitFor();
  const destination=await page.request.post(new URL('/api/account/create-team',page.url()).href,{
    headers:{Authorization:'Bearer assistant'},data:{course:code,name:'紅組',password:'right-team'}
  });
  if(!destination.ok()) throw Error('未建立換組目的地');
  const membership=await page.context().newPage();
  await membership.addInitScript(()=>{sessionStorage.fixture='teammate';sessionStorage.signed='1';});
  await membership.setViewportSize({width:390,height:800});
  await membership.goto(new URL('/#course/'+code,page.url()).href);
  const leave=membership.getByRole('button',{name:'退出小組',exact:true});
  const [confirmation]=await Promise.all([
    membership.waitForEvent('dialog').then(async dialog=>{const text=dialog.message();await dialog.dismiss();return text;}),
    leave.click()
  ]);
  if(!['生物','甲組','分數'].every(text=>confirmation.includes(text))) throw Error('退組確認缺少組別或成績說明');
  await leave.waitFor();
  await peer.getByText('✓ 隊友已送出',{exact:true}).waitFor();
  await Promise.all([membership.waitForEvent('dialog').then(dialog=>dialog.accept()),leave.click()]);
  await membership.getByText(/已退出「甲組」/).waitFor();
  if(await membership.getByLabel('老師提供的課程代碼').inputValue()!==code) throw Error('退出後未帶入原課程代碼');
  await peer.getByRole('heading',{name:'我的課程',exact:true}).waitFor();
  await membership.getByLabel('小組名稱').fill('紅組');
  await membership.getByLabel('小組密碼',{exact:true}).fill('right-team');
  await membership.getByRole('button',{name:'加入小組',exact:true}).click();
  await membership.getByRole('button',{name:'生物 · 紅組'}).click();
  await membership.getByRole('button',{name:/第一堂/}).click();
  await membership.waitForFunction(()=>document.getElementById('role-badge')?.textContent==='紅組');
  await membership.locator('#answer-0').waitFor();
  if(await membership.locator('.saved-answer:visible').count()) throw Error('舊組答案被帶進新組');
  await membership.locator('#answer-0').fill('紅組的答案');
  await membership.locator('.question-card button').first().click();
  await membership.getByText('✓ 已交卷',{exact:true}).waitFor();
  await page.getByText('✓ 已交卷',{exact:true}).waitFor();
  await membership.close();
  await peer.close();
  await button('帳號選單').click();
  await page.locator('#work-menu').getByRole('link',{name:'作答紀錄'}).click();
  await page.locator('.record summary').click();
  await page.locator('.answer-record').getByText('測試答案').waitFor();
  await page.locator('.answer-record').getByText('等待公布').waitFor();
  await page.setViewportSize({width:390,height:800});
  if(await page.locator('#work-rail').isVisible()) throw Error('手機導覽應收合');
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw Error('手機紀錄頁橫向溢出');
  await page.screenshot({path:'output/playwright/course-history-mobile.png'});
  await button('展開目錄').click();
  if(!await rail.evaluate(e=>e.getBoundingClientRect().right===innerWidth && e.getBoundingClientRect().left>0)) throw Error('手機目錄應從右側展開');
  await page.screenshot({path:'output/playwright/course-menu-mobile.png'});
  await page.locator('#work-rail').getByRole('link',{name:'我的課程'}).click();
  await button('生物 · 甲組').waitFor();
  await button('帳號選單').click();
  await page.locator('#work-menu').getByRole('button',{name:'登出 Google 帳號'}).click();
  await page.evaluate(()=>{sessionStorage.fixture='teacher';});
  await button('老師與助教').click();
  await button('使用 Google 帳號登入').click();
  await button('生物 · 授課教師').click();
  await nav('加入助教');
  await page.getByLabel('助教的帳號 UID').fill('assistant');
  await button('加入助教').click();
  await page.getByText('已加入本課程的助教。').waitFor();
  await nav('重設小組密碼');
  await page.getByLabel(/新小組密碼/).fill('changed-pass');
  await button('儲存新密碼').click();
  await page.getByText('已重設「甲組」的小組密碼。').waitFor();
  await nav('課程活動');
  await page.getByRole('button',{name:/第一堂/}).click();
  await page.locator('#end').click();
  await button('確認結束').click();
  await page.waitForFunction(()=>current.phase==='results');
  await expectContentFocus('content-title');
  await nav('學生作答與批改');
  await page.locator('.record summary').click();
  await page.locator('.answer-record').getByText('測試答案').waitFor();
  await button('前往批改').click();
  const board=await page.context().newPage();
  await board.addInitScript(()=>{sessionStorage.fixture='teacher';sessionStorage.signed='1';});
  await board.goto(new URL('/#leaderboard/'+code,page.url()).href);
  await board.getByRole('row',{name:/1.*甲組.*0/}).waitFor();
  await board.getByLabel('選擇課程').selectOption({label:'數學'});
  await board.getByText('這門課還沒有小組。').waitFor();
  const joined=await board.request.post(new URL('/api/account/create-team',board.url()).href,{
    headers:{Authorization:'Bearer student'},
    data:{course:await board.getByLabel('選擇課程').inputValue(),name:'數學小組',password:'class123'}
  });
  if(!joined.ok()) throw Error('測試小組建立失敗');
  await board.getByRole('row',{name:/1.*數學小組.*0/}).waitFor({timeout:15000});
  await board.getByLabel('選擇課程').selectOption({label:'生物'});
  await board.getByRole('row',{name:/1.*甲組.*0/}).waitFor();
  const studentReport=await page.context().newPage();
  await studentReport.addInitScript(()=>{sessionStorage.fixture='student';sessionStorage.signed='1';});
  await studentReport.goto(new URL('/#course/'+code,page.url()).href);
  await studentReport.getByRole('button',{name:/第一堂/}).click();
  const verdictCell=studentReport.locator('#report-table tr[data-question="1"] td').nth(1);
  const studentStamp=verdictCell.locator('.student-stamp');
  await button('甲組 第 1 題判為正確').click();
  await studentStamp.waitFor();
  await button('甲組 第 1 題判為錯誤').click();
  await verdictCell.getByText('錯誤',{exact:true}).waitFor();
  await studentStamp.waitFor({state:'detached'});
  await button('甲組 第 1 題判為正確').click();
  await studentStamp.waitFor();
  const history=page.locator('#monitor-table tr').filter({has:page.getByRole('rowheader',{name:'甲組',exact:true})}).locator('details');
  await history.locator('summary').click();
  await history.locator('summary').focus();
  const other=await page.evaluate(()=>{
    const answer=current.answers.find(a=>a.text==='紅組的答案');
    return {aid:current.id,id:answer.id,revision:answer.review_revision};
  });
  const staffRoom=await page.request.post(new URL('/api/account/staff-room',page.url()).href,{
    headers:{Authorization:'Bearer assistant'},data:{course:code,aid:other.aid}
  });
  if(!staffRoom.ok()) throw Error('助教無法進入批改');
  const reviewed=await page.request.post(new URL('/api/activities/'+other.aid+'/review',page.url()).href,{
    headers:{Authorization:'Bearer '+(await staffRoom.json()).token},data:{answer_id:other.id,revision:other.revision,verdict:'incorrect'}
  });
  if(!reviewed.ok()) throw Error('助教無法批改紅組：'+await reviewed.text());
  await page.waitForFunction(id=>current.answers.some(a=>a.id===id && a.verdict==='incorrect'),other.id);
  if(!await history.evaluate(el=>el.open && document.activeElement===el.querySelector('summary'))) throw Error('助教批改其他組後，老師正在閱讀的紀錄或鍵盤焦點被重設');
  await board.getByRole('row',{name:/1.*甲組.*[4-7]/}).waitFor({timeout:15000});
  await board.close();
  await nav('課程排行榜');
  await page.getByRole('table',{name:'小組累積排名'}).waitFor();
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw Error('手機排行榜橫向溢出');
  await button('帳號選單').click();
  await page.locator('#work-menu').getByRole('link',{name:'我的帳號資料'}).click();
  await checkCopy('帳號 UID','teacher');
  await nav('我的課程');
  await button('生物 · 授課教師').click();
  await nav('建立搶答活動');
  await page.locator('#activity-title').fill('逐題手機課堂');
  await page.locator('#question-count').fill('2');
  await page.locator('#create-form button').click();
  await page.locator('#quiz-mode').selectOption('sequential');
  await fromDirectory('#start');
  await page.waitForFunction(()=>current.phase==='active' && current.round.round_open);
  const roundLine=page.locator('.round-line');
  await roundLine.getByText(/目前第 1 題/).waitFor();
  if(await rail.locator('#round-controls').count() || await rail.isVisible()) throw Error('關題不應依賴功能目錄');
  await roundLine.getByRole('button',{name:'關閉本題'}).scrollIntoViewIfNeeded();
  await page.screenshot({path:'output/playwright/round-controls-mobile.png'});
  await roundLine.getByRole('button',{name:'關閉本題'}).click();
  await page.waitForFunction(()=>!current.round.round_open);
  await page.setViewportSize({width:1360,height:950});
  await roundLine.getByText(/第 1 題.*已關閉/).waitFor();
  await roundLine.getByRole('button',{name:'開啟下一題'}).click();
  await page.waitForFunction(()=>current.round.unit_id==='2' && current.round.round_open);
  await page.setViewportSize({width:390,height:800});
  if(await rail.isVisible() || await rail.locator('#end').count()) throw Error('結束整場應在主畫面');
  await page.locator('#end').click();
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>!document.querySelector('#end-dialog').open);
  if(await rail.isVisible() || await page.locator(':focus').getAttribute('id')!=='end') throw Error('取消結束後應回到原控制');
  await page.locator('#end').click();
  await button('確認結束').click();
  await expectContentFocus('content-title');
  await page.waitForFunction(()=>current.phase==='results');
  await button('帳號選單').click();
  await page.locator('#work-menu').getByRole('button',{name:'登出 Google 帳號'}).click();
  await page.evaluate(()=>{sessionStorage.fixture='assistant';});
  await button('學生').click();
  await button('使用 Google 帳號登入').click();
  await page.getByRole('heading',{name:'我的課程'}).waitFor();
  if(await rail.getByText('加入小組').count() || await rail.getByText('新增課程').count() || await rail.getByText('課程排行榜').count()) throw Error('助教首頁顯示錯誤角色');
  await button('生物 · 助教').click();
  await page.evaluate(()=>{location.hash='course/'+location.hash.split('/')[1]+'/assistant';});
  await page.getByRole('heading',{name:'我的課程'}).waitFor();
  if(await page.getByLabel('助教的帳號 UID').count() || await rail.getByText('加入助教').count()) throw Error('出現未授權的課程工具');
  await nav('學生作答與批改');
  const firstLesson=page.locator('.record').filter({has:page.locator('summary').filter({hasText:'第一堂'})});
  await firstLesson.locator('summary').click();
  await firstLesson.locator('.answer-record').getByText('正確',{exact:true}).waitFor();
  await firstLesson.getByRole('button',{name:'前往批改'}).click();
  if(await page.locator('#end').isVisible()) throw Error('助教可以結束整場');
  await button('甲組 第 1 題判為錯誤').click();
  await verdictCell.getByText('錯誤',{exact:true}).waitFor();
  await studentStamp.waitFor({state:'detached'});
  await button('甲組 第 1 題判為正確').click();
  await studentStamp.waitFor();
  await studentReport.close();
  await button('帳號選單').click();
  await page.locator('#work-menu').getByRole('button',{name:'登出 Google 帳號'}).click();
  await page.evaluate(()=>{sessionStorage.fixture='admin';});
  await button('使用 Google 帳號登入').click();
  await nav('授予教師資格');
  await page.getByLabel('教師的帳號 UID').waitFor();
  if(await rail.getByText('將未歸屬活動加入課程').count()) throw Error('管理員仍有舊活動歸屬操作');
  return {passed:true, provider:'offline test fixture', loginRecovery:true, mobileTeacherActions:true, studentLeaveAndRejoin:true, roles:['student','teacher','assistant','admin']};
}
