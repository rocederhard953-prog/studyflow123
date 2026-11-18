const HABIT_TEMPLATES=[
  {name:'Читать 20 минут',icon:'📖',group:'study',description:'Несколько страниц каждый день — книга за книгой.'},
  {name:'Повторять английский',icon:'🌍',group:'study',description:'Десять минут на слова, аудирование или карточки.'},
  {name:'Повторить материал урока',icon:'✏️',group:'study',description:'Закрепить то, что узнал сегодня.'},
  {name:'Одна фокус-сессия',icon:'◷',group:'study',description:'Одна задача без телефона и отвлечений.'},
  {name:'Утренняя зарядка',icon:'☀️',group:'health',description:'Несколько минут движения для начала дня.'},
  {name:'Прогулка на свежем воздухе',icon:'🌿',group:'health',description:'Небольшая прогулка в удобном тебе темпе.'},
  {name:'Перерыв для глаз',icon:'👁',group:'health',description:'Отдохнуть от экрана между занятиями.'},
  {name:'Ложиться вовремя',icon:'🌙',group:'health',description:'Выделить время для полноценного отдыха.'},
  {name:'Планировать завтрашний день',icon:'🗓',group:'balance',description:'Выбрать несколько понятных дел на завтра.'},
  {name:'Вечер без телефона',icon:'✨',group:'balance',description:'Оставить немного времени для себя.'},
  {name:'Записать хорошее за день',icon:'☘',group:'balance',description:'Замечать небольшие радостные моменты.'},
  {name:'Навести порядок на столе',icon:'✦',group:'balance',description:'Подготовить удобное место для следующего занятия.'},
];
let habitView={tab:'mine',category:'all',selected:null,month:null,busy:false,range:7,day:null,notes:{}};

function habitIcon(h){return HABIT_TEMPLATES.find(t=>t.name===h.name)?.icon||'✦';}
function habitDayLabel(day){return new Date(day+'T12:00:00Z').toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});}
function habitMonthLabel(month){return new Date(month+'-01T12:00:00Z').toLocaleDateString('ru-RU',{month:'long',year:'numeric',timeZone:'UTC'});}
function shiftHabitMonth(offset){const d=HabitStats.parse(habitView.month+'-01');d.setUTCMonth(d.getUTCMonth()+offset);habitView.month=d.toISOString().slice(0,7);renderHabitsLocal();}

async function habitsPage(){
  const [hs,notes]=await Promise.all([api('/habits'),api('/habit-notes')]);cache.habits=hs;habitView.notes=notes;
  return renderHabitContent(hs);
}
function renderHabitContent(hs){
  const day=today();if(!habitView.month)habitView.month=day.slice(0,7);
  if(!habitView.day)habitView.day=day;
  if(!hs.some(h=>h.id===habitView.selected))habitView.selected=hs[0]?.id??null;
  const selected=hs.find(h=>h.id===habitView.selected),week=HabitStats.summary(hs,HabitStats.add(day,-6),day,day);
  const due=hs.filter(h=>HabitStats.scheduled(h,day)),done=due.filter(h=>h.checks.includes(day)).length;
  return `<div class="habit-hero"><div><div class="eyebrow">МАЛЕНЬКИЕ ШАГИ КАЖДЫЙ ДЕНЬ</div><h2>Привычки, которые остаются <span>✦</span></h2><p>Выбери свой ритм. Отмечай действия. Замечай прогресс.</p></div>${btn('＋ Своя привычка','newHabit')}</div>
  <div class="habit-summary-grid"><div class="habit-stat"><span>СЕГОДНЯ</span><b>${done}<small> / ${due.length}</small></b><p>${due.length?'Выполнено сегодня':'На сегодня привычек нет'}</p><div class="progress"><span style="width:${due.length?Math.round(done/due.length*100):0}%"></span></div></div><div class="habit-stat"><span>ЗА ПОСЛЕДНИЕ 7 ДНЕЙ</span><b>${week.percent}<small>%</small></b><p>${week.done} из ${week.total} ${ruPlural(week.total,'запланированной отметки','запланированных отметок','запланированных отметок')}</p></div><div class="habit-stat"><span>МОЯ КОЛЛЕКЦИЯ</span><b>${hs.length}</b><p>${ruPlural(hs.length,'привычка','привычки','привычек')} в твоём ритме</p></div></div>
  <div class="habit-tabs" role="group" aria-label="Раздел привычек"><button data-habit-tab="mine" aria-pressed="${habitView.tab==='mine'}" class="${habitView.tab==='mine'?'active':''}">Мои привычки <span>${hs.length}</span></button><button data-habit-tab="catalog" aria-pressed="${habitView.tab==='catalog'}" class="${habitView.tab==='catalog'?'active':''}">✦ Каталог привычек</button></div>
  ${habitView.tab==='catalog'?habitCatalog(hs):`<div class="habit-dashboard"><div class="habit-main"><div class="habit-cards">${hs.map(h=>habitCard(h,day)).join('')||`<div class="card habit-empty"><div>🌱</div><h3>Начни с одной привычки</h3><p>Выбери идею из каталога или добавь свою.</p><button class="primary" data-habit-tab="catalog">Открыть каталог →</button></div>`}</div>${habitChart(hs,day)}</div><aside class="habit-aside">${selected?habitCalendar(selected,day)+habitDayPanel(cache.habits,habitView.day,day):`<div class="card habit-calendar-empty">После добавления привычки здесь появится календарь отметок.</div>`}<div class="habit-tip"><span>✦</span><p>Пропуск — часть пути.<br>Продолжи в следующий запланированный день.</p></div></aside></div>`}`;
}

function habitDayPanel(hs,day,todayDate){
 const due=hs.filter(h=>HabitStats.scheduled(h,day)),done=due.filter(h=>h.checks.includes(day)).length,pct=due.length?Math.round(done/due.length*100):0;
 return `<section class="card habit-day-panel"><div class="section-head"><div><div class="eyebrow">ВЫБРАННЫЙ ДЕНЬ</div><h2>${habitDayLabel(day)}</h2><p>${done} из ${due.length} ${ruPlural(due.length,'привычки','привычек','привычек')} выполнено</p></div><div class="habit-ring" style="--value:${pct}%"><b>${pct}%</b></div></div><div class="habit-day-list">${hs.map(h=>{const scheduled=HabitStats.scheduled(h,day),checked=h.checks.includes(day);return `<label class="habit-day-row"><input class="check" type="checkbox" data-day-habit="${h.id}" ${checked?'checked':''} ${!scheduled||day>todayDate?'disabled':''}><span>${esc(h.name)}</span><small>${!scheduled?'Не запланировано':checked?'Готово':'Отметить'}</small></label>`}).join('')||'<p class="muted">Добавь привычку, чтобы отмечать дни</p>'}</div>${day<=todayDate?due.map(h=>habitProgressHTML(h,day)).join(''):''}<label class="habit-note-label">Заметка дня<textarea data-day-note maxlength="1000" placeholder="Что помогло или помешало сегодня?">${esc(habitView.notes[day]||'')}</textarea></label><button class="secondary" data-save-day-note="${day}">Сохранить заметку</button></section>`;
}

function habitCard(h,day){
  const due=HabitStats.scheduled(h,day),done=h.checks.includes(day),stats=HabitStats.summary([h],HabitStats.add(day,-6),day,day),streak=HabitStats.series(h,day);
  return `<article class="habit-item card ${habitView.selected===h.id?'selected':''}"><div class="habit-card-top"><span class="habit-symbol">${habitIcon(h)}</span><div class="grow"><h3>${esc(h.name)}</h3><small>${h.config?.mode==='weekly'?ruCount(h.config.weekly_target,'раз','раза','раз')+' в неделю':h.days.map(d=>['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][d]).join(' · ')||'Нет запланированных дней'}</small></div><label class="habit-today-check"><input type="checkbox" class="check" data-habit-today="${h.id}" aria-label="${esc(h.name)} — сегодня" ${done?'checked':''} ${!due||habitView.busy?'disabled':''}><span>${!due?'Выходной':done?'Готово':'Сегодня'}</span></label></div><div class="habit-mini-week">${HabitStats.days(HabitStats.add(day,-6),day).map(d=>`<div title="${habitDayLabel(d)}"><span>${['П','В','С','Ч','П','С','В'][HabitStats.weekday(d)]}</span><i class="${HabitStats.scheduled(h,d)?h.checks.includes(d)?'done':'pending':'off'}">${HabitStats.scheduled(h,d)&&h.checks.includes(d)?'✓':'·'}</i></div>`).join('')}</div><div class="habit-card-bottom"><span>🔥 ${streak.current} ${h.config?.mode==='weekly'?ruPlural(streak.current,'неделя','недели','недель'):ruPlural(streak.current,'день','дня','дней')} подряд <small>· ${stats.percent}% за неделю</small></span><button class="ghost" data-habit-select="${h.id}" aria-pressed="${habitView.selected===h.id}">Календарь →</button><button class="ghost" data-edit-habit="${h.id}">Настроить</button><button class="icon-btn habit-delete" data-deletehabit="${h.id}" title="Удалить привычку ${esc(h.name)}" aria-label="Удалить привычку ${esc(h.name)}">×</button></div></article>`;
}

function habitCatalog(hs){
  const categories=[['all','Все идеи'],['study','Учёба'],['health','Здоровье'],['balance','Баланс']];
  return `<div class="habit-catalog-heading"><div><h3>Найди то, что подходит тебе</h3><p>Идеи для старта. Название и дни можно изменить перед добавлением.</p></div><div class="habit-categories">${categories.map(([key,label])=>`<button data-habit-category="${key}" aria-pressed="${habitView.category===key}" class="${habitView.category===key?'active':''}">${label}</button>`).join('')}</div></div><div class="habit-template-grid">${HABIT_TEMPLATES.map((t,i)=>({...t,index:i})).filter(t=>habitView.category==='all'||habitView.category===t.group).map(t=>{const exists=hs.some(h=>h.name.trim().toLocaleLowerCase('ru')===t.name.toLocaleLowerCase('ru'));return `<article class="card habit-template"><span class="template-symbol">${t.icon}</span><small>${categories.find(c=>c[0]===t.group)[1]}</small><h3>${esc(t.name)}</h3><p>${esc(t.description)}</p><button class="${exists?'secondary':'primary'}" data-habit-template="${t.index}" ${exists?'disabled':''}>${exists?'✓ Уже добавлено':'＋ Добавить привычку'}</button></article>`;}).join('')}</div>`;
}

function habitCalendar(h,day){
  const cells=HabitStats.monthCells(habitView.month),streak=HabitStats.series(h,day),monthStats=HabitStats.summary([h],habitView.month+'-01',cells.filter(Boolean).at(-1),day);
  return `<section class="card habit-calendar"><div class="habit-calendar-title"><span class="habit-symbol">${habitIcon(h)}</span><div><small>КАЛЕНДАРЬ ПРИВЫЧКИ</small><h3>${esc(h.name)}</h3></div></div><div class="habit-month-navigation"><button class="icon-btn" data-habit-month="-1" aria-label="Предыдущий месяц">‹</button><b>${habitMonthLabel(habitView.month)}</b><button class="icon-btn" data-habit-month="1" aria-label="Следующий месяц">›</button></div><div class="habit-month-grid">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(d=>`<span class="habit-weekday">${d}</span>`).join('')}${cells.map(d=>d?`<button class="habit-date ${d===day?'today':''} ${d===habitView.day?'selected':''} ${h.checks.includes(d)&&HabitStats.scheduled(h,d)?'done':''}" data-habit-calendar="${d}" aria-label="Открыть ${habitDayLabel(d)}${h.checks.includes(d)?', есть отметка':''}" aria-pressed="${d===habitView.day}" ${d>day?'disabled':''}><span>${Number(d.slice(-2))}</span>${h.checks.includes(d)&&HabitStats.scheduled(h,d)?'<i>✓</i>':''}</button>`:'<span class="habit-date-blank"></span>').join('')}</div><div class="habit-calendar-legend"><span><i></i> Выполнено</span><span>Выбери день, чтобы открыть список</span></div><div class="habit-calendar-stats"><div><b>${monthStats.done}<small> / ${monthStats.total}</small></b><span>в выбранном месяце</span></div><div><b>${streak.best}</b><span>лучшая серия</span></div></div>${typeof habitHeatmapHTML==='function'?habitHeatmapHTML(h):''}<p class="habit-footnote">${h.config?.mode==='weekly'?'Серия растёт за каждую неделю, в которой выполнена недельная цель.':'Серия учитывает запланированные дни; выходные не прерывают её.'}</p></section>`;
}

function habitChart(hs,day){
  const days=HabitStats.days(HabitStats.add(day,1-habitView.range),day),values=days.map(d=>({...HabitStats.summary(hs,d,d,day),day:d}));
  const total=HabitStats.summary(hs,days[0],day,day),width=600,height=150,step=width/values.length;
  return `<section class="card habit-chart"><div class="section-head"><div><h2>Твой прогресс</h2><p>Выполнение запланированных привычек по дням</p></div><div class="habit-range">${[7,30].map(n=>`<button data-habit-range="${n}" class="${habitView.range===n?'active':''}" aria-pressed="${habitView.range===n}">${n} дней</button>`).join('')}</div></div><div class="habit-chart-summary"><b>${total.percent}%</b><span>${total.done} выполнено из ${total.total} ${ruPlural(total.total,'запланированной отметки','запланированных отметок','запланированных отметок')}</span></div><svg class="habit-bar-chart" viewBox="0 0 660 210" role="img" aria-label="Процент выполнения за ${habitView.range} дней: ${total.percent} процентов"><g transform="translate(35,12)">${[0,50,100].map(n=>`<line x1="0" y1="${height-n/100*height}" x2="${width}" y2="${height-n/100*height}" class="habit-chart-line"/><text x="-9" y="${height-n/100*height+4}" text-anchor="end" class="habit-chart-axis">${n}%</text>`).join('')}${values.map((v,i)=>`<g><title>${habitDayLabel(v.day)}: ${v.done} из ${v.total}${v.total?', '+v.percent+'%':', нет запланированных привычек'}</title><rect x="${i*step+step*.2}" y="${height-(v.total?v.percent/100*height:2)}" width="${step*.6}" height="${v.total?Math.max(2,v.percent/100*height):2}" rx="${Math.min(5,step*.2)}" class="${v.total?'habit-chart-bar':'habit-chart-empty'}"/>${(habitView.range===7||i%5===0||i===values.length-1)?`<text x="${i*step+step*.5}" y="${height+23}" text-anchor="middle" class="habit-chart-axis">${Number(v.day.slice(-2))}.${v.day.slice(5,7)}</text>`:''}</g>`).join('')}</g></svg><p class="habit-footnote">${hs.length?'Дни без запланированных привычек не снижают результат.':'Добавь привычку, и здесь появится твой график.'}</p></section>`;
}

async function toggleHabitMark(id,day,checked){
 if(habitView.busy)return;const h=cache.habits?.find(x=>x.id===Number(id));if(!h||day>today()||!HabitStats.scheduled(h,day))return;
 const user=me?.id;habitView.busy=true;document.querySelectorAll('[data-habit-calendar],[data-habit-today],[data-day-habit]').forEach(b=>b.disabled=true);
 try{await api('/habits/'+h.id+'/check',{method:'PUT',body:JSON.stringify({day,done:checked})});if(me?.id!==user)return;if(h.progress)h.progress[day]={...h.progress[day],amount:checked?(h.config?.target||1):0};h.checks=checked?[...new Set([...h.checks,day])]:h.checks.filter(d=>d!==day);if(typeof showUndo==='function')showUndo(checked?'Отметка сохранена':'Отметка снята',()=>toggleHabitMark(id,day,!checked));else toast(checked?'Отметка сохранена':'Отметка снята');}catch(e){toast(e.message);}finally{habitView.busy=false;if(page==='habits'&&me?.id===user)refreshHabitParts();}
}
function preserveHabitNote(){const note=document.querySelector('[data-day-note]');if(note&&habitView.day)habitView.notes[habitView.day]=note.value;}
function refreshHabitParts(){
 queueMicrotask(()=>{if(typeof bindHabitProgress==='function')bindHabitProgress();});
 preserveHabitNote();const focus=document.activeElement;let selector=null;
 for(const key of ['data-day-habit','data-habit-today','data-day-note'])if(focus?.hasAttribute?.(key)){selector=key==='data-day-note'?'[data-day-note]':'['+key+'="'+focus.getAttribute(key)+'"]';break;}
 const selection=typeof focus?.selectionStart==='number'?[focus.selectionStart,focus.selectionEnd]:null;
 const template=document.createElement('template');template.innerHTML=renderHabitContent(cache.habits||[]);
 for(const cls of ['.habit-summary-grid','.habit-cards','.habit-chart','.habit-calendar','.habit-day-panel']){const old=document.querySelector('#content '+cls),fresh=template.content.querySelector(cls);if(old&&fresh)old.replaceChildren(...fresh.childNodes);}
 bindCommon();if(selector){const next=document.querySelector(selector);next?.focus({preventScroll:true});if(selection&&next?.setSelectionRange)next.setSelectionRange(...selection);}
}
function renderHabitsLocal(preserve=true){if(preserve)preserveHabitNote();document.getElementById('content').innerHTML=renderHabitContent(cache.habits||[]);bindCommon();}

function bindHabits(){
  if(page!=='habits')return;
  document.querySelectorAll('[data-habit-tab]').forEach(b=>b.onclick=()=>{habitView.tab=b.dataset.habitTab;renderHabitsLocal();});
  document.querySelectorAll('[data-habit-category]').forEach(b=>b.onclick=()=>{habitView.category=b.dataset.habitCategory;renderHabitsLocal();});
  document.querySelectorAll('[data-habit-template]').forEach(b=>b.onclick=()=>{const t=HABIT_TEMPLATES[Number(b.dataset.habitTemplate)];if(t){newHabit();document.querySelector('#dynamicForm [name="name"]').value=t.name;}});
  document.querySelectorAll('[data-habit-select]').forEach(b=>b.onclick=()=>{habitView.selected=Number(b.dataset.habitSelect);renderHabitsLocal();});
  document.querySelectorAll('[data-habit-month]').forEach(b=>b.onclick=()=>shiftHabitMonth(Number(b.dataset.habitMonth)));
  document.querySelectorAll('[data-habit-today]').forEach(b=>b.onchange=()=>toggleHabitMark(b.dataset.habitToday,today(),b.checked));
  document.querySelectorAll('[data-habit-calendar]').forEach(b=>b.onclick=()=>{preserveHabitNote();habitView.day=b.dataset.habitCalendar;renderHabitsLocal(false);});
  document.querySelectorAll('[data-day-habit]').forEach(b=>b.onchange=()=>toggleHabitMark(b.dataset.dayHabit,habitView.day,b.checked));
  document.querySelectorAll('[data-save-day-note]').forEach(b=>b.onclick=async()=>{const note=document.querySelector('[data-day-note]').value;try{await api('/habit-notes',{method:'PUT',body:JSON.stringify({day:b.dataset.saveDayNote,note})});habitView.notes[b.dataset.saveDayNote]=note;toast('Заметка сохранена');}catch(e){toast(e.message);}});
  document.querySelectorAll('[data-habit-range]').forEach(b=>b.onclick=()=>{habitView.range=Number(b.dataset.habitRange);renderHabitsLocal();});
}

