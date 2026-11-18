/* A per-account, memory-only conversation. No API key or persisted transcript in the browser. */
const AI_PAGES=new Set(['home','tasks','schedule','habits','pomodoro','calendar','grades','cards','cheats','goals','analytics','subjects','telegram','reminders','appearance','settings','search']);
let ai={messages:[],mode:'study',taskId:null,photos:false,status:null,tasks:[],busy:false,controller:null,origin:'home',generation:0};

function resetAssistantAccount(){
  ai.controller?.abort();
  ai={messages:[],mode:'study',taskId:null,photos:false,status:null,tasks:[],busy:false,controller:null,origin:'home',generation:ai.generation+1};
}

function openAssistant(taskId=null){
  if(page!=='assistant')ai.origin=AI_PAGES.has(page)?page:'home';
  if(taskId!==null){ai.taskId=Number(taskId);ai.mode='study';ai.photos=false;}
  navigate('assistant');
}

async function assistantPage(){
  const [status,tasks]=await Promise.all([api('/assistant/status'),api('/tasks')]);
  ai.status=status;ai.tasks=tasks;
  if(!status.ai_ready&&ai.messages.length===0&&ai.taskId===null)ai.mode='navigation';
  if(ai.taskId!==null&&!tasks.some(t=>t.id===ai.taskId)){ai.taskId=null;ai.photos=false;}
  return `<div class="ai-heading"><div><span class="eyebrow">MY-STUDY · РЯДОМ, КОГДА НУЖНО</span><h2>Разберёмся вместе <span>✦</span></h2><p>Объяснить задание или найти нужный раздел — начни с вопроса.</p></div><button class="secondary" id="aiNewChat">＋ Новый диалог</button></div>
  <div class="ai-layout"><section class="ai-conversation card" aria-label="Диалог с помощником">
    <div class="ai-chat-top"><div class="ai-avatar" aria-hidden="true">✦</div><div><b>Помощник My-Study</b><small id="aiStatus">${status.ai_ready?'Готов помочь с учёбой и сайтом':'Навигация работает · учебный ИИ ещё не подключён'}</small></div></div>
    <div id="aiMessages" class="ai-messages" role="log" aria-label="Сообщения помощника" aria-live="polite" aria-relevant="additions"></div>
    <div id="aiError" class="ai-error hidden" role="alert"></div>
    <form id="aiForm" class="ai-composer"><label class="sr-only" for="aiInput">Вопрос помощнику</label><textarea id="aiInput" maxlength="3000" rows="2" placeholder="Напиши вопрос…" required></textarea><div class="ai-composer-bottom"><small>Enter — отправить · Shift + Enter — новая строка</small><button class="primary" type="submit" id="aiSend">Отправить ↑</button></div></form>
    <p class="ai-disclaimer">ИИ может ошибаться. Проверяй ответы. Переписка хранится только до выхода или перезагрузки страницы.</p>
  </section>
  <aside class="ai-context"><div class="card"><h3>С чем помочь?</h3><div class="ai-mode-switch" role="group" aria-label="Режим помощника"><button data-ai-mode="study">📚 С учёбой</button><button data-ai-mode="navigation">◈ По сайту</button></div><p class="ai-mode-description" id="aiModeDescription"></p><div id="aiSetupNotice" class="ai-setup ${status.ai_ready?'hidden':''}">Объяснение ДЗ появится после подключения ИИ владельцем сайта. Пока можешь спрашивать, где находятся нужные функции.</div></div>
  <div class="card" id="aiTaskContext"><h3>Задание для разбора</h3><label for="aiTaskSelect">Выбери своё ДЗ</label><select id="aiTaskSelect"><option value="">Без выбранного задания</option>${tasks.filter(t=>!t.done||t.id===ai.taskId).map(t=>`<option value="${t.id}" ${t.id===ai.taskId?'selected':''}>${esc(t.subject||'Без предмета')} · ${esc(t.title)}</option>`).join('')}</select><div id="aiTaskPreview" class="ai-task-preview"></div><label class="ai-photo-option"><input id="aiPhotos" type="checkbox" ${ai.photos?'checked':''}>Передать фото выбранного задания</label><p class="ai-context-note">В ИИ отправится вопрос, история этого диалога и только выбранное задание. Фото — по твоему выбору, до двух, JPG/PNG/WEBP, до 4 МБ каждое.</p></div>
  <div class="card"><h3>Попробуй спросить</h3><div id="aiSuggestions" class="ai-suggestions"></div></div>
  ${status.privacy_notice?`<div class="ai-setup">${esc(status.privacy_notice)}</div>`:''}<div class="ai-limit" id="aiLimit"></div></aside></div>`;
}

function bindAssistant(){
  document.querySelectorAll('[data-ai-task]').forEach(b=>b.onclick=()=>openAssistant(b.dataset.aiTask));
  if(!document.getElementById('aiForm'))return;
  document.getElementById('aiForm').onsubmit=sendAssistantMessage;
  document.getElementById('aiInput').onkeydown=e=>{
    if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!ai.busy)document.getElementById('aiForm').requestSubmit();}
  };
  document.getElementById('aiNewChat').onclick=()=>{
    ai.controller?.abort();ai.generation++;ai.messages=[];ai.busy=false;ai.photos=false;
    document.getElementById('aiPhotos').checked=false;document.getElementById('aiError').classList.add('hidden');
    document.getElementById('aiInput').value='';renderAssistantMessages();updateAssistantContext();
  };
  document.querySelectorAll('[data-ai-mode]').forEach(b=>b.onclick=()=>{ai.mode=b.dataset.aiMode;updateAssistantContext();});
  document.getElementById('aiTaskSelect').onchange=e=>{ai.taskId=e.target.value?Number(e.target.value):null;ai.photos=false;document.getElementById('aiPhotos').checked=false;updateAssistantContext();};
  document.getElementById('aiPhotos').onchange=e=>ai.photos=e.target.checked;
  renderAssistantMessages();updateAssistantContext();
}

function updateAssistantContext(){
  if(page!=='assistant'||!document.getElementById('aiForm'))return;
  document.querySelectorAll('[data-ai-mode]').forEach(b=>{const active=b.dataset.aiMode===ai.mode;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
  const study=ai.mode==='study';
  document.getElementById('aiModeDescription').textContent=study?'Разберём условие, объясним тему и проверим решение по шагам.':'Подскажу, где что находится, и предложу кнопку перехода.';
  document.getElementById('aiTaskContext').classList.toggle('hidden',!study);
  const task=ai.tasks.find(t=>t.id===ai.taskId);
  document.getElementById('aiTaskPreview').textContent=task?`${task.subject||'Без предмета'}${task.due?' · к '+fmt(task.due):''}\n${task.title}${task.description?'\n'+task.description:''}`:'Можно задать вопрос без привязки к ДЗ.';
  const photos=document.getElementById('aiPhotos');photos.disabled=!task?.attachments?.length||ai.busy;
  if(photos.disabled){photos.checked=false;ai.photos=false;}
  document.getElementById('aiTaskSelect').disabled=ai.busy;
  const suggestions=study?['Помоги понять условие задания','Объясни решение по шагам','Проверь моё решение']:['Где добавить домашнее задание?','Как привязать Telegram?','Как изменить время вечерней сводки?'];
  const list=document.getElementById('aiSuggestions');list.replaceChildren();
  for(const text of suggestions){const b=document.createElement('button');b.textContent=text;b.type='button';b.onclick=()=>{document.getElementById('aiInput').value=text;document.getElementById('aiInput').focus();};list.append(b);}
  document.getElementById('aiSend').disabled=ai.busy||(study&&!ai.status?.ai_ready);
  document.getElementById('aiSend').textContent=ai.busy?'Думаю…':'Отправить ↑';
  document.getElementById('aiInput').placeholder=study?'Например: объясни, как решить это уравнение…':'Например: где настроить напоминания?';
  document.getElementById('aiInput').disabled=ai.busy;
  const remaining=ai.status?.remaining??0;
  document.getElementById('aiLimit').textContent=ai.status?.ai_ready?`Запросов ИИ осталось: ${remaining} из ${ai.status.daily_limit}. Обновление лимита — ${new Date(ai.status.reset_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}. Навигация без лимита.`:'Для навигации API-ключ не нужен.';
}

function renderAssistantMessages(){
  const log=document.getElementById('aiMessages');if(!log)return;log.replaceChildren();
  if(!ai.messages.length){
    const empty=document.createElement('div');empty.className='ai-welcome';
    const star=document.createElement('span');star.textContent='✦';
    const h=document.createElement('h3');h.textContent='С чего начнём?';
    const p=document.createElement('p');p.textContent=ai.status?.ai_ready?'Пришли вопрос или выбери задание справа. Разберём сложное небольшими шагами.':'Помогу найти нужный раздел сайта. Например, спроси: «Где добавить ДЗ?»';
    empty.append(star,h,p);log.append(empty);
  }
  for(const message of ai.messages){
    const row=document.createElement('div');row.className='ai-message '+message.role;
    const label=document.createElement('small');label.textContent=message.role==='user'?'Ты':message.source==='guide'?'Справочник сайта':'ИИ-помощник';
    const text=document.createElement('div');text.className='ai-message-text';text.textContent=message.content;
    row.append(label,text);
    if(message.actions?.length){
      const actions=document.createElement('div');actions.className='ai-message-actions';
      for(const a of message.actions){if(!AI_PAGES.has(a.page))continue;const b=document.createElement('button');b.className='secondary';b.textContent=a.label;b.onclick=()=>navigate(a.page);actions.append(b);}
      row.append(actions);
    }
    log.append(row);
  }
  if(ai.busy){const busy=document.createElement('div');busy.className='ai-thinking';busy.textContent='✦ Подготавливаю ответ…';log.append(busy);}
  log.scrollTop=log.scrollHeight;
}

async function sendAssistantMessage(event){
  event.preventDefault();if(ai.busy)return;
  const input=document.getElementById('aiInput'),message=input.value.trim();if(!message)return;
  const history=ai.messages.slice(-10).map(m=>({role:m.role,content:m.content.slice(0,8000)}));
  while(history.reduce((n,m)=>n+m.content.length,0)>15000)history.shift();
  const error=document.getElementById('aiError');error.classList.add('hidden');
  ai.messages.push({role:'user',content:message});
  if(ai.messages.length>30)ai.messages.splice(0,ai.messages.length-30);
  ai.busy=true;ai.controller=new AbortController();const generation=ai.generation;
  const payload={message,mode:ai.mode,page:ai.origin,task_id:ai.mode==='study'?ai.taskId:null,include_photos:ai.mode==='study'&&ai.photos,history};
  input.value='';renderAssistantMessages();updateAssistantContext();
  try{
    const response=await api('/assistant/chat',{method:'POST',body:JSON.stringify(payload),signal:ai.controller.signal});
    if(generation!==ai.generation)return;
    ai.messages.push({role:'assistant',content:response.reply,actions:response.actions,source:response.source});
    if(response.source==='ai'&&ai.status)ai.status.remaining=Math.max(0,ai.status.remaining-1);
  }catch(e){
    if(generation!==ai.generation||e.name==='AbortError')return;
    const failed=ai.messages[ai.messages.length-1];if(failed?.role==='user')ai.messages.pop();
    if(page==='assistant'&&document.getElementById('aiError')){document.getElementById('aiError').textContent=e.message;document.getElementById('aiError').classList.remove('hidden');document.getElementById('aiInput').value=message;}
    else toast(e.message);
  }finally{
    if(generation===ai.generation){
      try{const status=await api('/assistant/status');if(generation===ai.generation)ai.status=status;}catch{}
      if(generation===ai.generation){ai.busy=false;ai.controller=null;renderAssistantMessages();updateAssistantContext();}
    }
  }
}

document.getElementById('assistantLauncher').onclick=()=>openAssistant();
