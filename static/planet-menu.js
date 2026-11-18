const UI_ICON_PATHS={
 home:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M3 12h18M12 3c-4 4-4 14 0 18 4-4 4-14 0-18',
 tasks:'M7 3h10v4H7zM7 5H5v16h14V5h-2M8 11h8M8 15h5',
 habits:'m5 12 4 4L19 6M20 13a8 8 0 1 1-8-9',
 schedule:'M4 6h16v15H4zM7 3v6M17 3v6M4 11h16M8 15h2M14 15h2',
 calendar:'M4 6h16v15H4zM7 3v6M17 3v6M4 11h16M8 15h2M14 15h2M8 18h2',
 whiteboard:'M3 4h18v13H3zM8 21l4-4 4 4M7 12l4-5 4 5 3-3',
 assistant:'m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z',
 pomodoro:'M9 2h6M12 5v2m6-2 2 2M12 8a7 7 0 1 0 0 14 7 7 0 0 0 0-14M12 11v4l3 2',
 grades:'M4 21V10h4v11M10 21V4h4v17M16 21V7h4v14',
 cheats:'M5 3h11l4 4v14H5zM15 3v5h5M8 12h9M8 16h6',
 cards:'M4 6h12v15H4zM8 3h12v14M8 11h4M8 15h4',
 goals:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10M12 12l8-8M17 4h3v3',
 analytics:'M3 3v18h18M6 16l5-6 4 3 6-8',
 subjects:'M5 3h14v18H5zM8 7h8M8 11h8M8 15h5',
 search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14m5 12 6 6',
 telegram:'m3 10 18-7-4 18-5-6-4 3v-6zm5 2 9-6-5 9',
 reminders:'M5 17h14l-2-4V9a5 5 0 0 0-10 0v4zM10 21h4M12 2v2',
 appearance:'M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 0-4h-1a2 2 0 0 1 0-4h5a4 4 0 0 0 4-4c0-3-4-6-9-6M7 9h.01M10 6h.01M15 6h.01M18 9h.01',
 developer:'m8 6-6 6 6 6m8-12 6 6-6 6M14 3l-4 18',
 settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z',
 menu:'M4 6h16M4 12h16M4 18h16'
};
function uiSectionIcon(name){return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${UI_ICON_PATHS[name]||UI_ICON_PATHS.home}"/></svg>`;}
const HUB_GROUPS=[{id:'study',title:'Учёба',icon:'tasks',sections:[['schedule','Расписание'],['tasks','Домашка'],['whiteboard','Доска'],['cheats','Шпаргалки'],['subjects','Заметки']]},{id:'rhythm',title:'Привычки',icon:'habits',sections:[['day','Мой день'],['habits','Привычки'],['goals','Цели'],['calendar','Календарь'],['analytics','Аналитика']]},{id:'preferences',title:'Настройки',icon:'settings',sections:[['settings','Настройки'],['telegram','Telegram'],['appearance','Оформление'],['reminders','Напоминания']]}];
const PLANET_SECTIONS=HUB_GROUPS.map(g=>[g.id,g.title]);
Object.assign(UI_ICON_PATHS,{study:UI_ICON_PATHS.tasks,rhythm:UI_ICON_PATHS.habits,preferences:UI_ICON_PATHS.settings,day:UI_ICON_PATHS.home});
function uiFloatingIsland(key){
 const variants=["M12 32 47 12 112 8 183 28 164 45 94 53 32 45Z","M15 32 56 10 129 12 186 31 152 48 80 53 27 43Z","M12 31 59 13 110 6 184 29 170 44 105 51 40 46Z"];
 const index=Math.max(0,PLANET_SECTIONS.findIndex(row=>row[0]===key));
 return `<svg viewBox="0 0 200 90" fill="none" aria-hidden="true"><ellipse cx="100" cy="83" rx="52" ry="4" fill="var(--theme-back)" opacity=".6"/><path d="M14 33 48 63 68 67 89 81 116 70 142 64 181 30 145 45 93 52 38 45Z" fill="var(--surface-low)" stroke="var(--line)"/><path d="M48 43 68 67 89 81 93 52M116 70 119 48M142 64 146 43" stroke="var(--theme-accent)" opacity=".2"/><path d="${variants[index%3]}" fill="var(--surface-raised)" stroke="var(--theme-accent)" stroke-opacity=".6"/><path d="M34 32 64 21 105 19 160 30 137 39 81 42 46 37" stroke="var(--theme-accent)" opacity=".22"/><path d="m44 30 4-11 4 11-4 3Zm104 1 4-13 5 13-5 3Z" fill="var(--theme-accent)" opacity=".6"/><circle cx="59" cy="35" r="1.5" fill="var(--theme-accent)"/><circle cx="136" cy="35" r="1.5" fill="var(--theme-accent)"/>${key==='study'?'<path d="M75 24V4h20v20M100 24V0h24v24M78 9h13M104 7h16M104 13h16" stroke="currentColor" opacity=".7"/>':key==='rhythm'?'<path d="M85 24V7m0 8c-16 0-15-15-15-15 14 0 15 8 15 15Zm0-3c15 0 16-12 16-12-13 0-16 6-16 12Z" stroke="currentColor" opacity=".7"/>':'<path d="M78 23V5h12v18M96 23V0h12v23M114 23V8h12v15M76 12h16M94 6h16M112 15h16" stroke="currentColor" opacity=".7"/>'}</svg>`;
}
const PLANET_ISLAND_POSITIONS=[{x:190,y:130,tilt:-2},{x:810,y:170,tilt:2},{x:500,y:650,tilt:-1}];
function planetMenuHTML({name,openTasks,habitsDone,habitsTotal}){
 const count=Math.ceil(PLANET_SECTIONS.length/2),height=780;
 return `<section class="planet-menu" aria-label="Главное меню My-Study">${typeof motivationHTML==='function'?motivationHTML():''}<div class="planet-heading"><div><div class="eyebrow">MY-STUDY · ТВОЯ УЧЕБНАЯ ВСЕЛЕННАЯ</div><h2>Твой космос, ${esc(name)} <span>✦</span></h2><p>Выбери орбиту. Каждый небольшой шаг ведёт к цели.</p></div><button class="ghost" data-hub-day>Мой день →</button></div>${hubSearchHTML()}<div class="planet-stage" style="--planet-stage-height:${height}px">${Array.from({length:18},(_,i)=>`<span class="planet-star" aria-hidden="true" style="left:${(i*43+9)%100}%;top:${(i*29+7)%100}%;--star-delay:${-i*.41}s">${i%5===0?'✦':'·'}</span>`).join('')}<svg class="planet-rays" viewBox="0 0 1000 ${height}" preserveAspectRatio="none" aria-hidden="true">${PLANET_SECTIONS.map(([key],i)=>{const left=i<count,index=left?i:i-count;return `<line data-planet-ray="${key}" x1="500" y1="350" x2="${PLANET_ISLAND_POSITIONS[i].x}" y2="${PLANET_ISLAND_POSITIONS[i].y}" style="--ray-delay:${-i*.23}s"/>`;}).join('')}</svg><div class="planet-center" aria-hidden="true"><div class="planet-orbit orbit-a"></div><div class="planet-orbit orbit-b"></div><div class="planet-moon-track"><i></i></div><div class="planet-sphere"><div class="planet-texture"></div><div class="planet-world-grid"><svg viewBox="0 0 240 240" fill="none"><ellipse cx="120" cy="120" rx="46" ry="116"/><ellipse cx="120" cy="120" rx="90" ry="116"/><ellipse cx="120" cy="120" rx="116" ry="45"/><ellipse cx="120" cy="120" rx="116" ry="85"/><path d="M4 120h232M120 4v232"/></svg></div><div class="planet-sphere-shade"></div><span class="planet-brand">✦<b>My-Study</b><small>В твоём ритме</small></span></div><div class="planet-caption"><b class="planet-task-count">${openTasks}</b> <span class="planet-task-word">${ruPlural(openTasks,'задание','задания','заданий')}</span> в работе<br><span><b class="planet-habit-count">${habitsDone}</b> из ${habitsTotal} ${ruPlural(habitsTotal,'привычки','привычек','привычек')} сегодня</span></div></div>${PLANET_SECTIONS.map(([key,title],i)=>{const left=i<count,index=left?i:i-count;return `<button class="planet-node ${left?'planet-node-left':'planet-node-right'}" data-planet-page="${key}" style="--island-x:${PLANET_ISLAND_POSITIONS[i].x/10}%;--island-y:${PLANET_ISLAND_POSITIONS[i].y}px;--island-tilt:${PLANET_ISLAND_POSITIONS[i].tilt}deg;--node-delay:${Math.min(i*14,140)}ms"><span class="island-cluster"><span class="island-land" aria-hidden="true">${uiFloatingIsland(key)}</span><i>${uiSectionIcon(HUB_GROUPS[i].icon)}</i><span class="island-title">${title}</span><small class="hub-island-caption" data-hub-count="${key}">${key==='study'?ruCount(openTasks,'задание','задания','заданий')+' в работе':key==='rhythm'?habitsDone+' / '+ruCount(habitsTotal,'привычка','привычки','привычек')+' сегодня':'Твоё пространство'}</small></span></button>`;}).join('')}</div>${typeof continueWorkspaceHTML==='function'?continueWorkspaceHTML():''}</section>`;
}
function uiEmptyIllustration(){return `<svg viewBox="0 0 120 80" class="ui-empty-illustration" fill="none" aria-hidden="true"><ellipse cx="60" cy="72" rx="36" ry="4" fill="currentColor" opacity=".08"/><g class="ui-paper-back"><rect x="29" y="13" width="43" height="49" rx="6" fill="currentColor" opacity=".13"/></g><g class="ui-paper-front"><rect x="46" y="20" width="43" height="49" rx="6" fill="var(--surface)" stroke="currentColor" stroke-width="1.5"/><path d="M56 34h23M56 42h18M56 50h21M56 58h12" stroke="currentColor" opacity=".6" stroke-linecap="round"/></g><path class="ui-paper-spark" d="m27 36 2 6 6 2-6 2-2 6-2-6-6-2 6-2z" fill="currentColor"/></svg>`;}
function bindPlanetMenu(){
 document.querySelector('[data-hub-day]')?.addEventListener('click',()=>navigate('day'));
 if(typeof bindHubSearch==='function')bindHubSearch();
 const today=document.querySelector('.planet-today-link');if(today)today.onclick=e=>{e.preventDefault();const panel=document.getElementById('planetToday');if(panel){panel.open=true;panel.scrollIntoView({behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}};
 document.querySelectorAll('[data-planet-page]').forEach(button=>{const key=button.dataset.planetPage,ray=document.querySelector('[data-planet-ray="'+key+'"]');if(typeof bindIslandTilt==='function')bindIslandTilt(button);button.onmouseenter=button.onfocus=()=>ray?.classList.add('planet-ray-active');button.onmouseleave=button.onblur=()=>ray?.classList.remove('planet-ray-active');button.onclick=()=>{return openHubWithFlight(key,button);};});
}
