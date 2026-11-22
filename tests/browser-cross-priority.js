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
    await post(teacher.token, path+'/end', {});
    return {prior:prior.id, next:next.id, teacher, low:students[0].current, high:students[1].current};
  });

  async function openRoom(tab, room) {
    await tab.goto(fixturePage);
    await tab.evaluate(({room, aid}) => {
      sessionStorage.setItem('classroom.auth', JSON.stringify(room));
      sessionStorage.setItem('classroom.activity', aid);
    }, {room, aid:fixture.next});
    await tab.goto(classroom);
    await tab.waitForFunction(() => current?.phase === 'preparing');
  }
  await openRoom(page, fixture.teacher);
  const source = page.getByLabel('跨場保底的成績來源');
  if (await source.inputValue() !== '') throw Error('新活動應預設全班同時開始');
  await source.selectOption(fixture.prior);
  await page.locator('#save-settings').click();
  await page.waitForFunction(id => current.settings.priority_source === id, fixture.prior);
  await page.reload();
  await page.waitForFunction(id => document.querySelector('#priority-source').value === id, fixture.prior);
  await page.locator('#quiz-mode').selectOption('sequential');
  if (await source.isVisible()) throw Error('逐題模式應使用本場成績');
  await page.locator('#quiz-mode').selectOption('all');

  const low = await page.context().newPage();
  const high = await page.context().newPage();
  try {
    await Promise.all([openRoom(low, fixture.low), openRoom(high, fixture.high)]);
    await page.locator('#start').click();
    await Promise.all([
      low.waitForFunction(() => document.querySelector('#round-status').textContent.includes('本組可先答') && !document.querySelector('.question-card button').disabled),
      high.waitForFunction(() => document.querySelector('#round-status').textContent.includes('請等倒數結束後作答') && document.querySelector('.question-card button').disabled)
    ]);
    await high.waitForFunction(() => !document.querySelector('.question-card button').disabled && document.querySelector('#round-status').hidden);
    await high.locator('#answer-0').fill('一般作答');
    await high.locator('.question-card button').click();
    await high.waitForFunction(() => current.answers[0]?.text === '一般作答');
    return {passed:true, sourceSaved:true, bothStudentStates:true, submittedAfterWindow:true};
  } finally {
    await Promise.all([low.close(), high.close()]);
  }
}
