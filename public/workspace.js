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
  const toggle = make('button','rail-toggle','目錄');
  toggle.setAttribute('aria-controls',rail.id);
  const compact=window.matchMedia('(max-width: 1120px)');
  let mobileOpen=false, openGroup=null;
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
  function placeNavigation() {
    if(compact.matches) bar.after(rail);
    else bar.querySelector('.brand').after(rail);
  }
  placeNavigation();

  function updateRail() {
    toggle.hidden=profile.hidden || !compact.matches;
    rail.hidden=profile.hidden || (compact.matches && !mobileOpen);
    toggle.setAttribute('aria-label',mobileOpen?'收合目錄':'展開目錄');
    toggle.setAttribute('aria-expanded',String(mobileOpen));
  }
  function closeGroup() {
    if(openGroup) openGroup.setAttribute('aria-expanded','false');
    openGroup=null;
  }
  function closePopups() {
    closeGroup();
    menu.hidden=true;
    avatar.setAttribute('aria-expanded','false');
    mobileOpen=false;
    updateRail();
  }
  compact.addEventListener('change',()=>{
    const focus=document.activeElement;
    placeNavigation();
    closePopups();
    if(rail.contains(focus) || focus===toggle) {
      if(compact.matches) toggle.focus();
      else if(focus.offsetWidth) focus.focus();
      else (focus.closest('.nav-section')?.querySelector('.nav-disclosure') || rail.querySelector('a'))?.focus();
    }
  });
  avatar.onclick=()=>{
    const open=menu.hidden;
    closePopups(); menu.hidden=!open; avatar.setAttribute('aria-expanded',String(open));
  };
  toggle.onclick=()=>{
    menu.hidden=true;
    avatar.setAttribute('aria-expanded','false');
    mobileOpen=!mobileOpen; updateRail();
  };
  document.addEventListener('pointerdown',event=>{
    if(event.target.closest('dialog[open]')) return;
    if(openGroup && !openGroup.parentElement.contains(event.target)) closeGroup();
    if ((!menu.hidden || mobileOpen) && !profile.contains(event.target) && !rail.contains(event.target) && event.target!==toggle) closePopups();
  });
  document.addEventListener('focusin',event=>{
    if(openGroup && !openGroup.parentElement.contains(event.target)) closeGroup();
    if(!menu.hidden && !profile.contains(event.target)) {menu.hidden=true; avatar.setAttribute('aria-expanded','false');}
  });
  document.addEventListener('keydown',event=>{
    if(event.key!=='Escape' || event.target.closest('dialog[open]')) return;
    if(!menu.hidden) {
      closePopups(); avatar.focus();
    } else if(openGroup) {
      const trigger=openGroup; closeGroup(); trigger.focus();
    } else if(mobileOpen) {
      closePopups(); toggle.focus();
    }
  });
  function render(person,permissions={},onNavigate) {
    document.body.classList.toggle('has-workspace',!!person);
    profile.hidden=!person;
    closePopups();
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
    const primary=make('div','nav-primary');
    rail.replaceChildren(make('h2','rail-heading','工作區目錄'),primary);
    function group(id,title) {
      const section=make('section','nav-section');
      const trigger=make('button','nav-disclosure');
      trigger.append(make('span','',title));
      const items=make('div','nav-items');
      items.id=id;
      trigger.type='button';
      trigger.setAttribute('aria-expanded','false');
      trigger.setAttribute('aria-controls',id);
      trigger.onclick=()=>{
        const expand=openGroup!==trigger;
        closePopups();
        if(expand) {openGroup=trigger; trigger.setAttribute('aria-expanded','true');}
      };
      section.append(make('h2','rail-heading',title),trigger,items);
      rail.append(section);
      return items;
    }
    function link(parent,view,label) {
      const a=make('a','work-link');
      a.href='/#'+view;
      a.dataset.view=view;
      a.append(document.createTextNode(label));
      a.onclick=event=>{
        if(event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        closePopups();
        if(onNavigate) {event.preventDefault(); onNavigate(view);}
      };
      parent.append(a);
    }
    link(primary,'home',staff?'我的課程':'我的小組');
    if(staff===false) {
      link(primary,'join','加入小組');
      link(primary,'create-team','建立小組');
    }
    if(teacher) link(primary,'create-course','新增課程');
    const records=staff?'學生作答與批改':'作答紀錄';
    link(primary,'history',records);
    if(staff===false || teacher || owner) {
      const current=courseId && (!staff || owner);
      link(primary,current?'leaderboard/'+courseId:'leaderboard','課程排行榜');
    }
    if(courseId) {
      const path='course/'+courseId;
      const courseLinks=group('work-course-links',courseTitle || '目前課程');
      link(courseLinks,path,'課程活動');
      if(owner) {
        link(courseLinks,path+'/new-activity','建立課堂活動');
        link(courseLinks,path+'/assistant','加入助教');
        link(courseLinks,path+'/password','重設小組密碼');
      }
    }
    if(admin) {
      const adminLinks=group('work-admin-links','管理工具');
      link(adminLinks,'admin','授予教師資格');
      link(adminLinks,'legacy','將未歸屬活動加入課程');
    }
    link(menu,'history',records);
    link(menu,'account','我的帳號資料');
    const logout=make('button','work-link','登出 Google 帳號');
    logout.id='signout';
    logout.onclick=()=>{
      closePopups();
      if(onNavigate) onNavigate('signout');
      else {sessionStorage.setItem('course.signout','1'); location.assign('/');}
    };
    menu.append(logout);
  }
  function revealActivity() {
    if(!mobileOpen) return;
    closePopups();
    document.getElementById('content-title').focus();
  }
  window.courseNav={render, revealActivity, select(view,current='page') {
    for(const a of [...rail.querySelectorAll('a'),...menu.querySelectorAll('a')]) {
      if(a.dataset.view===view) a.setAttribute('aria-current',current); else a.removeAttribute('aria-current');
    }
  }};
  let room;
  if(location.pathname==='/classroom') {
    try {room=JSON.parse(sessionStorage.getItem('classroom.auth'));} catch {}
  }
  const staff=room?.role==='teacher', owner=staff && !room.assistant;
  render(room?.course ? room.profile || {name:'帳號'} : null,
         {teacher:owner,...room?.navigation,staff,owner,courseId:room?.course});
  if(room?.course) window.courseNav.select('course/'+room.course,'location');
  if(room?.course && staff) {
    const tabs=document.getElementById('teacher-tabs');
    const tools=make('section','rail-activity');
    tools.id='work-activity';
    tools.hidden=!sessionStorage.getItem('classroom.activity');
    tools.append(make('h2','rail-heading','本場搶答'));
    rail.append(tools);
    tabs.addEventListener('click',revealActivity);
    const controls=owner?[tabs,document.getElementById('teacher-controls')]:[tabs];
    const locations=controls.map(control=>{
      const marker=document.createComment(control.id);
      control.before(marker);
      return marker;
    });
    function placeActivityControls() {
      const focus=document.activeElement;
      const movingFocus=controls.some(control=>control.contains(focus));
      controls.forEach((control,i)=>{
        if(compact.matches) tools.append(control);
        else locations[i].after(control);
      });
      if(movingFocus) (compact.matches?toggle:focus).focus();
    }
    placeActivityControls();
    compact.addEventListener('change',placeActivityControls);
  }
})();
