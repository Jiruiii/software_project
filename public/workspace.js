/* Shared navigation for signed-in course and classroom pages. */
(() => {
  const make = (tag, cls, text) => {
    const element = document.createElement(tag);
    element.className = cls;
    if (text) element.textContent = text;
    return element;
  };
  const rail = make('nav','work-rail');
  rail.setAttribute('aria-label','工作區導覽');
  rail.id='work-rail';
  const toggle = make('button','rail-toggle','☰');
  toggle.setAttribute('aria-label','工作區導覽');
  toggle.setAttribute('aria-controls',rail.id);
  const profile = make('div','work-profile');
  const avatar = make('button','work-avatar');
  avatar.setAttribute('aria-label','帳號選單');
  avatar.setAttribute('aria-controls','work-menu');
  const menu = make('nav','work-menu');
  menu.id='work-menu';
  menu.setAttribute('aria-label','帳號選項');
  profile.append(avatar,menu);
  const bar=document.querySelector('.topbar');
  (bar.querySelector('.top-actions') || bar).append(toggle,profile);
  bar.after(rail);

  function close() {
    menu.hidden=true;
    avatar.setAttribute('aria-expanded','false');
    rail.classList.remove('unfold');
    toggle.setAttribute('aria-expanded','false');
  }
  close();
  avatar.onclick=()=>{
    const open=menu.hidden;
    close(); menu.hidden=!open; avatar.setAttribute('aria-expanded',String(open));
  };
  toggle.onclick=()=>{
    const open=!rail.classList.contains('unfold');
    close(); rail.classList.toggle('unfold',open); toggle.setAttribute('aria-expanded',String(open));
  };
  document.addEventListener('pointerdown',event=>{
    if (!profile.contains(event.target) && !rail.contains(event.target) && event.target!==toggle) close();
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape' && (!menu.hidden || rail.classList.contains('unfold'))) {
      const trigger=menu.hidden?toggle:avatar; close(); trigger.focus();
    }
  });
  function render(person,permissions={},onNavigate) {
    close();
    document.body.classList.toggle('has-workspace',!!person);
    profile.hidden=rail.hidden=toggle.hidden=!person;
    if (!person) return;
    const name=person.name || person.email || '帳號';
    avatar.textContent=Array.from(name)[0].toUpperCase();
    if (person.photo) {
      const image=make('img','');
      image.alt=''; image.referrerPolicy='no-referrer';
      image.onerror=()=>image.remove();
      image.src=person.photo; avatar.append(image);
    }
    menu.replaceChildren(make('span','profile-name',name));
    const {staff,teacher,admin,courseId,courseTitle,owner}=permissions;
    rail.replaceChildren(make('span','rail-heading','工作區目錄'));
    function link(parent,view,label,mark) {
      const a=make('a','work-link');
      a.href='/#'+view;
      a.dataset.view=view;
      if(mark) { const icon=make('span','rail-icon',mark); icon.setAttribute('aria-hidden','true'); a.append(icon); }
      a.append(document.createTextNode(label));
      a.onclick=event=>{
        if(event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        close();
        if(onNavigate) {event.preventDefault(); onNavigate(view);}
      };
      parent.append(a);
    }
    link(rail,'home',staff?'我的課程':'我的小組','⌂');
    if(staff===false) {
      link(rail,'join','加入小組','＋');
      link(rail,'create-team','建立小組','＋');
    }
    if(teacher) link(rail,'create-course','新增課程','＋');
    const records=staff?'學生作答與批改':'作答紀錄';
    link(rail,'history',records,'◷');
    if(staff===false || teacher || owner) {
      const current=courseId && (!staff || owner);
      link(rail,current?'leaderboard/'+courseId:'leaderboard','課程排行榜','≡');
    }
    if(admin) {
      link(rail,'admin','授予教師資格','⚙');
      link(rail,'legacy','分配舊活動','▤');
    }
    if(courseId) {
      const path='course/'+courseId;
      rail.append(make('span','rail-heading',courseTitle || '目前課程'));
      link(rail,path,'課程活動','▤');
      if(owner) {
        link(rail,path+'/new-activity','建立課堂活動','＋');
        link(rail,path+'/assistant','加入助教','＋');
        link(rail,path+'/password','重設小組密碼','⚙');
      }
    }
    const accountHeading=make('span','rail-heading','帳號');
    accountHeading.id='work-account-heading';
    rail.append(accountHeading);
    link(rail,'account','我的帳號資料','○');
    link(menu,'history',records);
    link(menu,'account','我的帳號資料');
    const logout=make('button','work-link','登出 Google 帳號');
    logout.id='signout';
    logout.onclick=()=>{
      close();
      if(onNavigate) onNavigate('signout');
      else {sessionStorage.setItem('course.signout','1'); location.assign('/');}
    };
    const railLogout=make('button','work-link','登出 Google 帳號');
    railLogout.onclick=logout.onclick;
    rail.append(railLogout); menu.append(logout);
  }
  window.courseNav={render, select(view) {
    for(const a of rail.querySelectorAll('a')) {
      if(a.dataset.view===view) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current');
    }
  }};
  let room;
  if(location.pathname==='/classroom') {
    try {room=JSON.parse(sessionStorage.getItem('classroom.auth'));} catch {}
  }
  const staff=room?.role==='teacher', owner=staff && !room.assistant;
  render(room?.course ? room.profile || {name:'帳號'} : null,
         {teacher:owner,...room?.navigation,staff,owner,courseId:room?.course});
  if(room?.course && staff) {
    const tabs=document.getElementById('teacher-tabs');
    const tools=make('section','rail-activity');
    tools.id='work-activity';
    tools.hidden=!sessionStorage.getItem('classroom.activity');
    tools.append(make('span','rail-heading','本場搶答'),tabs);
    document.getElementById('work-account-heading').before(tools);
    tabs.addEventListener('click',close);
    if(owner) {
      tools.append(document.getElementById('teacher-controls'),document.getElementById('round-controls'));
    }
  }
})();
