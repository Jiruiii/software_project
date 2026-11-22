const $ = id => document.getElementById(id);
let loginAsStaff = sessionStorage.getItem('course.role') === 'staff';
let staff = false;
let auth, sdk, home;
let authReady=false;
let pageVersion=0;
let leaderboardTimer;
const phase = {preparing:'準備中', active:'作答中', results:'已結束'};
function status(message = '') {
  $('notice').textContent = message;
  $('notice').hidden = !message;
}
function node(tag, text, cls) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (cls) element.className = cls;
  return element;
}
async function run(button, fn) {
  button.disabled = true;
  status();
  try { await fn(); } catch (error) { status(error.message); }
  finally { button.disabled = false; }
}
function button(parent, title, fn, cls='secondary') {
  const b = node('button',title,cls);
  b.type = 'button';
  b.onclick = () => run(b,fn);
  parent.append(b);
  return b;
}
function listEntry(parent, title, detail, open, phaseName) {
  const row = button(parent,'',open,'activity-card course-row');
  row.setAttribute('aria-label',title+' · '+detail);
  row.append(node('strong',title),node('span',detail,phaseName ? 'phase-pill '+phaseName : 'row-detail'));
}
function panel(title) {
  const section = node('section',undefined,'panel');
  if(title) section.append(node('h2',title));
  $('workspace').append(section);
  return section;
}
function form(section, fields, submit, fn) {
  const f = node('form');
  for (const [key,caption,type='text'] of fields) {
    const label = node('label',caption);
    const input = node('input');
    input.name = key; input.type = type; input.required = true;
    if (type === 'password') { input.minLength=8; input.maxLength=128; }
    label.append(input); f.append(label);
  }
  const b = node('button',submit,'primary');
  f.append(b); section.append(f);
  f.onsubmit = e => {e.preventDefault(); run(b,()=>fn(Object.fromEntries(new FormData(f))));};
}
async function api(action,data={}) {
  const token = await auth.currentUser.getIdToken();
  const response = await fetch('/api/account/'+action,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || '操作失敗，請重試。');
  return result;
}
async function reload(message) {
  const user=auth.currentUser;
  const result=await api('home');
  if(auth.currentUser!==user) return;
  home=result;
  draw();
  status(message);
}
function draw() {
  ++pageVersion;
  clearTimeout(leaderboardTimer);
  $('workspace').replaceChildren();
  staff = home ? (home.teacher || home.admin || home.teaching.length > 0) : loginAsStaff;
  $('login-roles').hidden = !authReady || !!auth?.currentUser;
  $('student').setAttribute('aria-pressed',String(!staff));
  $('staff').setAttribute('aria-pressed',String(staff));
  $('title').textContent = home ? (staff ? '我的課程' : '我的小組') : '進入課堂';
  $('login').hidden = $('login-roles').hidden;
  const view=location.hash.slice(1) || 'home';
  const [page,id,task]=view.split('/');
  const courses=home ? (staff ? home.teaching : home.studying) : [];
  const match=page==='course' && courses.find(c=>c.id===id);
  const owner=!!match && home.uid===match.owner;
  const selected=match && (view==='course/'+id || (owner && ['assistant','password','new-activity'].some(action=>view==='course/'+id+'/'+action))) ? match : null;
  window.courseNav.render(home ? profile() : null,{
    staff,teacher:home?.teacher,admin:home?.admin,courseId:selected?.id,courseTitle:selected?.title,owner:!!selected && owner
  },navigate);
  $('intro').textContent = staff ? '登入教學工作區' : '登入你的小組';
  $('hint').textContent = staff ? '建立自己的課程，或進入受邀協助批改的課程。' : '用自己的 Google 帳號加入或建立課程小組。';
  if (!home) return;
  window.courseNav.select(view);
  if(selected) {
    $('title').textContent=selected.title;
    if(task==='new-activity') {
      enter(selected.id,undefined,false,true).catch(error=>status(error.message));
    } else course(selected,task).catch(error=>status(error.message));
    return;
  }
  if(view==='account') {
    $('title').textContent='我的帳號資料';
    const section=panel(profile().name || home.email);
    section.append(node('p',home.email),createShareCode('帳號 UID',home.uid));
    return;
  }
  if(view==='history') {historyView(); return;}
  if(page==='leaderboard' && (!staff || home.teacher)) {
    window.courseNav.select('leaderboard');
    leaderboardView(staff ? courses.filter(c=>c.owner===home.uid) : courses,id);
    return;
  }
  if((view==='admin' || view==='legacy') && home.admin) {
    $('title').textContent=view==='admin'?'授予教師資格':'分配舊活動';
    adminPanel(view);
    return;
  }
  if(view==='create-course' && home.teacher) {
    $('title').textContent='新增課程';
    form(panel(),[['title','課程名稱']],'建立課程',async data=>{
      const result=await api('create-course',data);
      home=await api('home');
      navigate('course/'+result.course);
    });
    return;
  }
  if(!staff && (view==='join' || view==='create-team')) {
    const create=view==='create-team', section=panel();
    $('title').textContent=create?'建立小組':'加入小組';
    if(!create) section.append(node('p','已加入的小組可在「我的小組」找到。忘記密碼可請授課老師重設。','muted'));
    form(section,[['course','老師提供的課程代碼'],['name','小組名稱'],['password',create?'設定小組密碼（至少 8 字元）':'小組密碼','password']],
      create?'建立小組':'加入小組',async data=>{
        await api(create?'create-team':'join-team',data);
        home=await api('home');
        navigate('home');
      });
    return;
  }
  if(view!=='home') history.replaceState(null,'','#home');
  window.courseNav.select('home');
  const list=panel();
  list.classList.add('course-index');
  const head=node('div',undefined,'index-heading');
  head.append(node('h2',staff?'課程清單':'已加入的課程'),node('span',courses.length+' 門','count'));
  list.append(head);
  if(!courses.length) list.append(node('p',staff?'目前沒有授課或受邀的課程。':'目前尚未加入課程小組。','muted'));
  for(const c of courses) listEntry(list,c.title,staff?(c.owner===home.uid?'授課教師':'助教'):c.name,()=>navigate('course/'+c.id));
  if(!courses.length && (home.teacher || !staff)) {
    const actions=node('div',undefined,'form-actions');
    if(home.teacher) button(actions,'新增課程',()=>navigate('create-course'),'primary');
    if(!staff) {
      button(actions,'加入小組',()=>navigate('join'),'primary');
      button(actions,'建立小組',()=>navigate('create-team'));
    }
    list.append(actions);
  }
}
function profile() {
  const user=auth.currentUser;
  return {email:home?.email || user?.email, name:user?.displayName, photo:user?.photoURL};
}
function navigate(view) {
  if(view==='signout') {
    sdk.signOut(auth).catch(error=>status(error.message));
    return;
  }
  status();
  if(location.hash==='#'+view) draw(); else location.hash=view;
}
window.addEventListener('hashchange',()=>{status(); draw();});
const verdicts={correct:'正確',incorrect:'錯誤',pending:'待批改',withheld:'等待公布'};
function leaderboardView(courses,preferred) {
  $('title').textContent='課程排行榜';
  const section=panel();
  if(!courses.length) {
    section.append(node('p',staff?'建立課程後即可查看排行榜。':'加入課程小組後即可查看排行榜。','muted'));
    return;
  }
  const label=node('label','選擇課程'), select=node('select');
  for(const course of courses) {
    const option=node('option',course.title);
    option.value=course.id;
    select.append(option);
  }
  if(courses.some(c=>c.id===preferred)) select.value=preferred;
  const course=select.value, version=pageVersion;
  select.onchange=()=>navigate('leaderboard/'+select.value);
  label.append(select);
  const message=node('p','讀取中…','muted'), table=node('table',undefined,'course-ranking');
  message.setAttribute('role','status');
  table.setAttribute('aria-label','小組累積排名');
  const header=table.createTHead().insertRow(), body=table.createTBody();
  for(const title of ['名次','小組','累積分數']) {
    const th=node('th',title);
    th.scope='col';
    header.append(th);
  }
  table.hidden=true;
  section.append(label,node('p','累計各場已公布的押注分與搶答分。批改後，分數與名次會自動更新。','muted'),message,table);
  const ownName=courses.find(c=>c.id===course).name;
  let previous;
  async function refresh() {
    try {
      const {rows}=await api('leaderboard',{course});
      if(version!==pageVersion) return;
      const current=JSON.stringify(rows);
      if(current!==previous) {
        body.replaceChildren();
        for(const row of rows) {
          const tr=body.insertRow();
          tr.insertCell().textContent=row.rank;
          const group=tr.insertCell();
          group.textContent=row.group_name;
          if(row.group_name===ownName) group.append(node('small','本組','ranking-own'));
          tr.insertCell().textContent=row.score;
        }
        previous=current;
      }
      table.hidden=!rows.length;
      message.hidden=!!rows.length;
      if(!rows.length) message.textContent='這門課還沒有小組。';
    } catch(error) {
      if(version!==pageVersion) return;
      table.hidden=true;
      message.hidden=false;
      message.textContent=error.message+' 稍後會自動重試。';
    } finally {
      if(version===pageVersion) leaderboardTimer=setTimeout(refresh,5000);
    }
  }
  refresh();
}

function historyView() {
  const teaching=staff, courses=teaching?home.teaching:home.studying;
  $('title').textContent=teaching?'學生作答與批改':'作答紀錄';
  const section=panel('依課程查看');
  if(!courses.length) {section.append(node('p','目前沒有可查看的課程。','muted')); return;}
  const label=node('label','選擇課程'), select=node('select'), rows=node('div');
  label.append(select); section.append(label,rows);
  for(const c of courses) {const o=node('option',c.title+(teaching?'':' · '+c.name)); o.value=c.id; select.append(o);}
  async function load() {
    const version=++pageVersion, course=select.value;
    rows.replaceChildren(node('p','讀取中…','muted'));
    try {
      const data=await api('course',{course,staff:teaching});
      if(version!==pageVersion) return;
      rows.replaceChildren();
      const sessions=data.lessons.filter(l=>l.phase!=='preparing' && (teaching || l.attended));
      if(!sessions.length) rows.append(node('p','這門課目前沒有活動紀錄。','muted'));
      for(const l of sessions) {
        const item=node('details',undefined,'record'), heading=node('summary',l.title);
        const date=new Date(l.activity_date*1000).toLocaleDateString('zh-TW');
        heading.append(node('small',date+' · '+phase[l.phase]+(teaching?'':' · '+l.score+' 分')));
        const body=node('div'); item.append(heading);
        if(teaching) button(item,'前往批改',()=>enter(course,l.id,true));
        item.append(body); rows.append(item);
        item.ontoggle=async()=>{
          if(!item.open || item.dataset.loaded) return;
          item.dataset.loaded='1';
          body.textContent='讀取中…';
          try {
            const detail=await api('history-detail',{course,aid:l.id,staff:teaching});
            body.replaceChildren();
            if(!detail.answers.length) body.append(node('p','尚無作答紀錄。','muted'));
            for(const a of detail.answers) {
              const entry=node('article',undefined,'answer-record');
              entry.append(node('strong',(teaching?a.group_name+' · ':'')+'第 '+a.question_id+' 題'),
                           node('p',a.text),node('small',verdicts[a.verdict] || a.verdict));
              if(teaching && a.author) entry.append(node('small','送出者　'+a.author));
              for(const r of a.reviews || []) entry.append(node('small',new Date(r.stamp*1000).toLocaleString('zh-TW')+' · '+r.email+' · '+(verdicts[r.verdict] || r.verdict)));
              body.append(entry);
            }
          } catch(error) {delete item.dataset.loaded; body.textContent=error.message;}
        };
      }
    } catch(error) {if(version===pageVersion) rows.textContent=error.message;}
  }
  select.onchange=load; load();
}
function adminPanel(view) {
  const admin = panel();
  if(view==='admin') {
    form(admin,[['uid','教師的帳號 UID']],'授予教師資格',async data=>{await api('grant',data); await reload('已授予教師資格。');});
    return;
  }
  if (!home.legacy.length || !home.destinations.length) {
    admin.append(node('p',home.legacy.length?'請先建立可接收活動的課程。':'目前沒有待分配的舊活動。','muted'));
    return;
  }
  const select=node('select'); select.setAttribute('aria-label','歸屬課程');
  for (const c of home.destinations) {const o=node('option',c.title+' · '+c.email); o.value=c.id; select.append(o);}
  admin.append(select);
  for (const lesson of home.legacy) button(admin,'分配「'+lesson.title+'」',async()=>{
    if (!confirm('將「'+lesson.title+'」分配給 '+select.selectedOptions[0].textContent+'？')) return;
    await api('claim',{aid:lesson.id,course:select.value}); await reload('已分配活動。');
  });
}
async function enter(id,aid,review=false,replace=false) {
  const version=pageVersion;
  const room=await api(staff?'staff-room':'student-room',{course:id,aid});
  if(version!==pageVersion) return;
  room.profile=profile();
  room.navigation={teacher:home.teacher,admin:home.admin,courseTitle:(staff?home.teaching:home.studying).find(c=>c.id===id)?.title};
  sessionStorage.setItem('classroom.auth',JSON.stringify(room));
  if (aid) sessionStorage.setItem('classroom.activity',aid); else sessionStorage.removeItem('classroom.activity');
  const path=review ? '/classroom#review-'+aid : '/classroom';
  if(replace) location.replace(path); else location.assign(path);
}
async function course(c,task) {
  const version=++pageVersion;
  const data=await api('course',{course:c.id,staff});
  if(version!==pageVersion) return;
  $('workspace').replaceChildren();
  $('title').textContent=c.title;
  if(task==='assistant' && data.role==='owner') {
    form(panel('加入助教'),[['uid','助教的帳號 UID']],'加入助教',async d=>{await api('assistant',{...d,course:c.id});status('已加入本課程的助教。');});
    return;
  }
  if(task==='password' && data.role==='owner') {
      const reset=panel('重設小組密碼');
      if(!data.teams.length) {reset.append(node('p','這門課還沒有小組。','muted')); return;}
      const label=node('label','選擇小組'), select=node('select');
      for(const team of data.teams) {const o=node('option',team.name); o.value=team.id; select.append(o);}
      label.append(select); reset.append(label);
      form(reset,[['password','新小組密碼（8～128 字元）','password']],'儲存新密碼',async d=>{
        const group=select.selectedOptions[0];
        await api('reset-password',{course:c.id,team:group.value,password:d.password});
        reset.querySelector('form').reset();
        status('已重設「'+group.textContent+'」的小組密碼。');
      });
      return;
  }
  const details=panel(staff?null:c.name);
  details.append(createShareCode('課程代碼',c.id));
  if (!staff) details.append(node('p','本課程累計　'+data.total+' 分','score-card'));
  const list=panel(staff?'課堂活動與學生紀錄':'本組活動與答題紀錄');
  if (!data.lessons.length) {
    list.append(node('p','這門課還沒有活動。','muted'));
    if (data.role==='owner') button(list,'建立課堂活動',()=>navigate('course/'+c.id+'/new-activity'),'primary');
  }
  for (const l of data.lessons) {
    const caption=l.title+' · '+phase[l.phase]+(staff?'':' · '+l.score+' 分');
    if (!staff && l.phase==='results' && !l.attended) list.append(node('p',caption+' · 未參與'));
    else listEntry(list,l.title,staff ? phase[l.phase] : phase[l.phase]+'　'+l.score+' 分',()=>enter(c.id,l.id),l.phase);
  }
  button(list,'更新活動清單',()=>course(c),'text-button');
}
for (const id of ['staff','student']) $(id).onclick=()=>{
  if(auth?.currentUser) return;
  loginAsStaff=id==='staff';
  sessionStorage.setItem('course.role',id);
  navigate('home');
};
async function init() {
  draw();
  const config=await (await fetch('/api/firebase-config')).json();
  if (!config.apiKey) {status('尚未設定 Google 登入。請依專案內 docs/firebase.md 完成 Firebase 設定，再重新啟動。'); return;}
  const base='https://www.gstatic.com/firebasejs/10.14.1/';
  const [app,authentication]=await Promise.all([import(base+'firebase-app.js'),import(base+'firebase-auth.js')]);
  sdk=authentication; auth=sdk.getAuth(app.initializeApp(config));
  await sdk.setPersistence(auth,sdk.browserSessionPersistence);
  $('google').disabled=false;
  $('google').onclick=()=>run($('google'),async()=>{
    history.replaceState(null,'','#home');
    const provider=new sdk.GoogleAuthProvider(); provider.setCustomParameters({prompt:'select_account'});
    await sdk.signInWithPopup(auth,provider);
  });
  sdk.onAuthStateChanged(auth,async user=>{
    authReady=true;
    home=null; draw();
    const signout=sessionStorage.getItem('course.signout');
    sessionStorage.removeItem('course.signout');
    if(user && signout) {await sdk.signOut(auth); return;}
    if (user) {try {await reload();} catch(error) {status(error.message); window.courseNav.render(profile(),{},navigate);}}
  });
}
async function leaveRoom() {
  const prior=JSON.parse(sessionStorage.getItem('classroom.auth') || 'null');
  if (prior?.course) {
    await fetch('/api/logout',{method:'POST',headers:{Authorization:'Bearer '+prior.token,'Content-Type':'application/json'},body:'{}'});
    for (const key of Object.keys(sessionStorage)) if (key.startsWith('classroom.')) sessionStorage.removeItem(key);
  }
}
leaveRoom().then(init).catch(error=>status('登入服務無法載入。'+error.message));
