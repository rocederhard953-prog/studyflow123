const MY_THEMES=[['cosmos','Космос','#7f84ff'],['sapphire','Сапфир','#5b9dff'],['amethyst','Аметист','#b07af5'],['violet','Фиолетовая','#9b6bff'],['emerald','Изумруд','#49c8a1'],['ruby','Рубин','#ed7e9c'],['onyx','Оникс','#a6b3c9']];
const THEME_DETAILS={
  cosmos:{description:'Индиго, мягкое свечение и спокойный ночной фон.',back:'#090d1c'},
  sapphire:{description:'Холодный синий, глубокие панели и ясные акценты.',back:'#080f1d'},
  amethyst:{description:'Фиолетовые кнопки и приглушённые сливовые оттенки.',back:'#100b19'},
  violet:{description:'Насыщенный фиолетовый акцент и тёмный графитовый фон.',back:'#0d0a16'},
  emerald:{description:'Изумрудные акценты и тёмный хвойный фон.',back:'#081410'},
  ruby:{description:'Тёплый розовый на глубоком винном фоне.',back:'#140c14'},
  onyx:{description:'Графит, серебристые кнопки и минимум свечения.',back:'#0b0e13'},
};
function applyTheme(name){
  if(!MY_THEMES.some(t=>t[0]===name))name='cosmos';
  document.documentElement.dataset.theme=name;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',THEME_DETAILS[name].back);
  try{localStorage.setItem('my-study-theme',name);}catch{}
}
try{applyTheme(localStorage.getItem('my-study-theme')||'cosmos');}catch{applyTheme('cosmos');}

async function appearancePage(){
  const [lessons,colors]=await Promise.all([api('/lessons'),api('/subject-colors')]);
  const subjects=[...new Set(lessons.map(x=>x.subject).filter(Boolean))].sort();window.subjectList=subjects;
  const active=document.documentElement.dataset.theme;
  return `<div class="appearance-hero"><div class="eyebrow">ТВОЁ ПРОСТРАНСТВО. ТВОЙ ЦВЕТ.</div><h2>Настрой своё настроение <span>✦</span></h2><p>Шесть тёмных оформлений. Кнопки, календарь, графики и помощник меняют цвет вместе с темой.</p></div><div class="theme-gallery">${MY_THEMES.map(([id,title,color])=>`<button class="theme-card ${active===id?'selected':''}" data-theme-choice="${id}" aria-pressed="${active===id}" style="--swatch:${color};--swatch-back:${THEME_DETAILS[id].back}"><div class="theme-window" aria-hidden="true"><div class="theme-window-top"><i></i><i></i><i></i></div><div class="theme-window-body"><div class="theme-window-sidebar"><span></span><span></span><span></span></div><div class="theme-window-content"><div class="theme-window-banner"><i>✦</i></div><div class="theme-window-tiles"><span></span><span></span></div><div class="theme-window-chart"><i></i><i></i><i></i><i></i><i></i></div><span class="theme-window-button">Кнопка темы</span></div></div></div><div class="theme-card-copy"><div><h3>${title}</h3><span class="theme-selected-label">${active===id?'✓ Выбрано':'Выбрать тему →'}</span></div><p>${THEME_DETAILS[id].description}</p></div></button>`).join('')}</div><p class="appearance-note">Оформление применяется сразу и сохраняется на этом устройстве. Твои записи не меняются.</p><div class="card subject-colors-panel"><div class="section-head"><div><h2>Цвета предметов</h2><p>Личные метки предметов можно настроить отдельно от темы.</p></div></div>${subjects.map((subject,i)=>`<div class="subject-config"><b>${esc(subject)}</b><input type="color" aria-label="Цвет предмета ${esc(subject)}" data-subjectcolor="${i}" value="${esc(colors[subject]||'#8b5cf6')}"></div>`).join('')||'<p class="muted small">Добавь уроки в расписание, чтобы выбрать цвета предметов.</p>'}</div>`;
}
