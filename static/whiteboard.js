const WB_COLORS=['#182033','#7060df','#2374da','#d34263','#22946d','#e2a327'];
function wbInitial(){return {task:null,key:null,revision:0,strokes:[],images:[],grid:true,pages:null,pageIndex:0,undo:[],redo:[],tool:'pen',color:WB_COLORS[0],width:4,dirty:false,saving:false,uploading:false,saveTimer:null,pending:null,error:null,attempts:0,conflict:false,active:null,selected:null,version:0,bitmaps:new Map()};}
let wb=wbInitial();
function resetWhiteboard(){clearTimeout(wb.saveTimer);wb=wbInitial();}
function whiteboardLeave(){if(wb.active||wb.gesture||wb.uploading){toast('Сначала заверши текущее действие');return false;}if(wb.dirty)wbScheduleSave(0);return true;}
async function openWhiteboard(task=null){if(wb.task===task&&wb.key){navigate('whiteboard');return;}if(!whiteboardLeave())return;if(!await wbFlush()){toast('Доска ещё не сохранена. Проверь подключение или экспортируй PNG.');return;}clearTimeout(wb.saveTimer);wb=Object.assign(wbInitial(),{task});navigate('whiteboard');}
function wbScheduleSave(delay=400){const target=wb;clearTimeout(target.saveTimer);if(!target.dirty||!target.key||target.conflict)return;target.saveTimer=setTimeout(()=>{target.saveTimer=null;if(wb===target&&target.dirty&&!target.saving)wbAction('save');},delay);}
async function wbFlush(){const target=wb;clearTimeout(target.saveTimer);if(target.active||target.gesture||target.uploading)return false;if(target.pending){try{await target.pending;}catch{}}if(wb!==target)return false;if(target.dirty&&!target.saving)await wbAction('save');return wb===target&&!target.dirty;}
function wbSnapshot(){return JSON.parse(JSON.stringify({strokes:wb.strokes,images:wb.images,grid:wb.grid}));}
function wbRemember(snapshot=wbSnapshot()){wb.undo.push(snapshot);if(wb.undo.length>30)wb.undo.shift();wb.redo=[];}
function wbChanged(){wbStorePage();wb.dirty=true;wb.version++;wbDraw();wbControls();wbScheduleSave();}
function wbLoadImage(stored,target=wb){
 if(target.bitmaps.has(stored))return Promise.resolve(target.bitmaps.get(stored));
 return new Promise((resolve,reject)=>{const image=new Image();const timer=setTimeout(()=>reject(Error('Фото не загрузилось. Попробуй обновить доску.')),15000);image.onload=()=>{clearTimeout(timer);target.bitmaps.set(stored,image);resolve(image);};image.onerror=()=>{clearTimeout(timer);reject(Error('Не удалось загрузить фото'));};image.src='/api/whiteboard/images/'+encodeURIComponent(stored);});
}
async function whiteboardPage(){
 const target=wb,key=String(wb.task||'personal');
 if(wb.key!==key){const data=await api('/whiteboard'+(wb.task?'?task_id='+wb.task:''));if(wb!==target)return '';const pages=wb.task?(data.pages||[{strokes:data.strokes,images:data.images||[],grid:data.grid!==false}]):null;const current=pages?pages[0]:data;Object.assign(wb,{strokes:current.strokes,images:current.images||[],grid:current.grid!==false,pages,pageIndex:0,revision:data.revision,undo:[],redo:[],dirty:false,key,active:null,selected:null});}
 await Promise.all(wb.images.map(i=>wbLoadImage(i.stored_name).catch(e=>toast(e.message))));
 const task=wb.task?cache.tasks?.find(t=>t.id===wb.task):null;
 return `${renderSectionHeading(task?'Доска · '+esc(task.subject||'Задание'):'Доска для решений','Фото условий, клетка и инструменты под левой рукой.')}${task?`<div class="card wb-task"><b>${esc(task.title)}</b><p>${esc(task.description||'')}</p></div>`:''}<section class="card wb-workspace">${wb.task?`<div class="wb-pages" aria-label="Листы домашнего задания"><span>Листы ДЗ</span>${wb.pages.map((p,i)=>`<button class="secondary" data-wb-page="${i}" aria-pressed="${wb.pageIndex===i}">Лист ${i+1}</button>`).join('')}<button class="primary" data-wb-action="newPage">＋ Следующий лист<kbd>Shift F</kbd></button><small>Лист ${wb.pageIndex+1} из ${wb.pages.length} · Сохраняются все листы</small></div>`:''}<div class="wb-toolbar"><div class="wb-tools">${[['pen','Перо','Q / Й'],['marker','Маркер','W / Ц'],['eraser','Ластик','E / У'],['line','Линия','R / К'],['select','Двигать фото','A / Ф']].map(([tool,label,key])=>`<button class="secondary" data-wb-tool="${tool}" aria-pressed="${wb.tool===tool}"><span>${label}</span><kbd>${key}</kbd></button>`).join('')}</div><div class="wb-colors">${WB_COLORS.map((c,i)=>`<button class="wb-color" data-wb-color="${c}" aria-label="Цвет ${i+1}" aria-pressed="${wb.color===c}"><i style="background:${c}"></i><kbd>${i+1}</kbd></button>`).join('')}<button class="ghost" data-wb-action="color">Следующий цвет<kbd>D / В</kbd></button></div><div class="wb-size"><label for="wbWidth">Толщина</label><input id="wbWidth" type="range" min="1" max="40" value="${wb.width}"><output id="wbWidthValue">${wb.width}</output><div class="wb-tools"><button class="ghost" data-wb-action="thinner">Тоньше<kbd>Z / Я</kbd></button><button class="ghost" data-wb-action="thicker">Толще<kbd>X / Ч</kbd></button></div></div><div class="wb-tools">${[['photo','Добавить фото','F / А · Ctrl/⌘ V'],['grid','Клетка','G / П'],['undo','Отменить','Ctrl/⌘ Z'],['redo','Вернуть','Ctrl/⌘ Shift Z'],['export','PNG','Ctrl/⌘ Shift S'],['clear','Очистить','Shift Delete']].map(([a,t,k])=>`<button class="${a==='save'?'primary':'ghost'}" data-wb-action="${a}" ${a==='grid'?`aria-pressed="${wb.grid}"`:''}>${t}<kbd>${k}</kbd></button>`).join('')}</div><input id="wbPhotoFile" type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif" multiple hidden></div><div class="wb-photo-actions"><span id="wbPhotoHint">Добавь до 8 фото. A — перемещение, нижний правый угол фото — размер.</span><button class="ghost" data-wb-action="deletePhoto">Удалить выбранное фото<kbd>Delete</kbd></button></div><div id="wbStatus" class="wb-status" role="status" aria-live="polite"></div><div class="wb-surface" id="wbDropZone"><canvas id="wbCanvas" width="1600" height="1000" aria-label="Доска в клетку для рисования и перемещения фотографий"></canvas></div><p class="muted small">Клавиши Q–R и A работают по положению на клавиатуре с любой раскладкой. Цвета — 1–6 или D, толщина — Z/X. Можно вставить фото через Ctrl/⌘ V или перетащить файл на доску. Доска сохраняется автоматически после каждого изменения.</p></section>`;
}
function wbDraw(exporting=false){
 const c=document.getElementById('wbCanvas');if(!c)return;const ctx=c.getContext('2d');ctx.clearRect(0,0,1600,1000);ctx.fillStyle='#fff';ctx.fillRect(0,0,1600,1000);
 if(wb.grid){ctx.strokeStyle='#dce5f0';ctx.lineWidth=1;ctx.beginPath();for(let x=0;x<=1600;x+=40){ctx.moveTo(x+.5,0);ctx.lineTo(x+.5,1000);}for(let y=0;y<=1000;y+=40){ctx.moveTo(0,y+.5);ctx.lineTo(1600,y+.5);}ctx.stroke();}
 for(const photo of wb.images){const image=wb.bitmaps.get(photo.stored_name);if(image)ctx.drawImage(image,photo.x,photo.y,photo.w,photo.h);else{ctx.fillStyle='#e7ebf2';ctx.fillRect(photo.x,photo.y,photo.w,photo.h);ctx.fillStyle='#445066';ctx.font='22px sans-serif';ctx.fillText('Фото не загрузилось',photo.x+10,photo.y+30);}}
 const ink=wb.ink||(wb.ink=document.createElement('canvas'));if(ink.width!==1600||ink.height!==1000){ink.width=1600;ink.height=1000;}const pen=ink.getContext('2d');pen.clearRect(0,0,1600,1000);
 for(const s of [...wb.strokes,...(wb.active?[wb.active]:[])]){pen.save();pen.globalCompositeOperation=s.tool==='eraser'?'destination-out':'source-over';pen.strokeStyle=pen.fillStyle=s.color;pen.lineWidth=s.width;pen.lineCap=pen.lineJoin='round';pen.globalAlpha=s.tool==='marker'?.3:1;pen.beginPath();const p=s.points;pen.moveTo(...p[0]);if(s.tool==='line')pen.lineTo(...p[p.length-1]);else for(const point of p.slice(1))pen.lineTo(...point);if(p.length===1){pen.arc(p[0][0],p[0][1],s.width/2,0,Math.PI*2);pen.fill();}else pen.stroke();pen.restore();}
 ctx.drawImage(ink,0,0);
 const photo=wb.images[wb.selected];if(!exporting&&wb.tool==='select'&&photo){const handle=wbHandleSize();ctx.strokeStyle='#7060df';ctx.lineWidth=3;ctx.strokeRect(photo.x,photo.y,photo.w,photo.h);ctx.fillStyle='#7060df';ctx.fillRect(photo.x+photo.w-handle/2,photo.y+photo.h-handle/2,handle,handle);}
}
let wbFrame=0;
function wbRequestDraw(){if(wbFrame)return;wbFrame=requestAnimationFrame(()=>{wbFrame=0;wbDraw();});}
function wbHandleSize(){const width=document.getElementById('wbCanvas')?.getBoundingClientRect().width||1600;return Math.min(80,Math.max(20,1600/width*18));}
function wbControls(){
 document.querySelectorAll('[data-wb-tool]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.wbTool===wb.tool)));document.querySelectorAll('[data-wb-color]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.wbColor===wb.color)));
 document.querySelector('[data-wb-action="grid"]')?.setAttribute('aria-pressed',String(wb.grid));const remove=document.querySelector('[data-wb-action="deletePhoto"]');if(remove)remove.disabled=wb.selected===null;
 const w=document.getElementById('wbWidth'),v=document.getElementById('wbWidthValue'),s=document.getElementById('wbStatus'),c=document.getElementById('wbCanvas');if(w)w.value=wb.width;if(v)v.textContent=wb.width;if(c)c.style.cursor=wb.tool==='select'?'move':'crosshair';if(s)s.textContent=wb.uploading?'Загружаем фото…':wb.saving?'Сохраняем…':wb.error?'Не удалось сохранить: '+wb.error:wb.dirty?'Ожидание автосохранения…':'Сохранено автоматически';
}
async function wbPreparePhoto(file){
 if(!['image/jpeg','image/png','image/webp','image/heic','image/heif'].includes(file.type))throw Error('Выбери JPG, PNG, WEBP или фото HEIC с телефона');if(file.size>20*1024*1024)throw Error('Фото должно быть не больше 20 МБ');
 const url=URL.createObjectURL(file);try{const image=await new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>reject(Error('Файл не удалось прочитать как изображение'));i.src=url;});if(image.naturalWidth*image.naturalHeight>40000000)throw Error('Слишком большое разрешение фото');const scale=Math.min(1,2000/image.naturalWidth,2000/image.naturalHeight),c=document.createElement('canvas');c.width=Math.max(1,Math.round(image.naturalWidth*scale));c.height=Math.max(1,Math.round(image.naturalHeight*scale));const ctx=c.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(image,0,0,c.width,c.height);const blob=await new Promise(resolve=>c.toBlob(resolve,'image/jpeg',.88));if(!blob)throw Error('Не удалось подготовить фото');return {blob,w:c.width,h:c.height};}finally{URL.revokeObjectURL(url);}
}
async function wbInsertPhotos(files){
 if(wb.uploading||wb.saving||wb.active||wb.gesture){toast('Сначала заверши текущее действие');return;}const target=wb;wb.uploading=true;wbControls();
 try{for(const file of files){if(wb!==target)return;if(wb.images.length>=8){toast('На одной доске можно разместить до 8 фото');break;}const prepared=await wbPreparePhoto(file);const form=new FormData();form.append('file',prepared.blob,'board-photo.jpg');const result=await api('/whiteboard/images',{method:'POST',body:form});if(wb!==target)return;await wbLoadImage(result.stored_name,target);const scale=Math.min(700/prepared.w,500/prepared.h);let w=Math.round(prepared.w*scale),h=Math.round(prepared.h*scale);if(w<40||h<40)throw Error('Фото слишком вытянутое. Выбери другой фрагмент.');wbRemember();wb.images.push({stored_name:result.stored_name,x:Math.round((1600-w)/2),y:Math.round((1000-h)/2),w,h});wb.selected=wb.images.length-1;wb.tool='select';wbChanged();}}
 catch(e){toast(e.message);}finally{target.uploading=false;wbControls();if(wb===target&&wb.dirty)wbScheduleSave();}
}
async function wbAction(action){
 if(wb.active||wb.gesture||wb.uploading)return;
 if(action==='newPage'){wbChangePage('new');return;}
 if(action==='undo'&&wb.undo.length){wb.redo.push(wbSnapshot());Object.assign(wb,wb.undo.pop());wb.selected=null;wbChanged();}
 if(action==='redo'&&wb.redo.length){wb.undo.push(wbSnapshot());Object.assign(wb,wb.redo.pop());wb.selected=null;wbChanged();}
 if(action==='clear'&&confirm('Очистить рисунок и фото? Можно отменить.')){wbRemember();wb.strokes=[];wb.images=[];wb.selected=null;wbChanged();}
 if(action==='deletePhoto'&&wb.selected!==null){wbRemember();wb.images.splice(wb.selected,1);wb.selected=null;wbChanged();}
 if(action==='grid'){wbRemember();wb.grid=!wb.grid;wbChanged();}
 if(action==='thinner'||action==='thicker'){wb.width=Math.max(1,Math.min(40,wb.width+(action==='thicker'?1:-1)));wbControls();}
 if(action==='color'){wb.color=WB_COLORS[(WB_COLORS.indexOf(wb.color)+1)%WB_COLORS.length];wbControls();}
 if(action==='photo')document.getElementById('wbPhotoFile')?.click();
 if(action==='export'){if(wb.images.some(p=>!wb.bitmaps.has(p.stored_name))){toast('Часть фото не загрузилась. Обнови страницу перед экспортом.');return;}wbDraw(true);const a=document.createElement('a');a.download=wb.task?'my-study-sheet-'+(wb.pageIndex+1)+'.png':'my-study-solution.png';a.href=document.getElementById('wbCanvas').toDataURL('image/png');a.click();wbDraw();}
 if(action==='save'&&!wb.saving&&wb.dirty){const target=wb,version=wb.version;target.saving=true;target.error=null;clearTimeout(target.saveTimer);wbControls();try{target.pending=api('/whiteboard'+(target.task?'?task_id='+target.task:''),{method:'PUT',body:JSON.stringify({revision:target.revision,...wbSaveDocument()})});const result=await target.pending;if(wb!==target)return;target.revision=result.revision;target.attempts=0;target.conflict=false;if(target.version===version)target.dirty=false;}catch(e){target.error=e.message;target.attempts++;target.conflict=/изменена в другом|Обнови страницу|перезагрузи/i.test(e.message);}finally{target.saving=false;target.pending=null;if(wb===target){wbControls();if(target.dirty&&!target.conflict&&target.attempts<=3)wbScheduleSave(target.error?Math.min(15000,1000*2**target.attempts):400);}}}

}
function wbResizePhoto(photo,point){const ratio=photo.w/photo.h;const minW=Math.max(40,40*ratio),maxW=Math.min(1600-photo.x,(1000-photo.y)*ratio);const w=Math.max(minW,Math.min(maxW,Math.max(point[0]-photo.x,(point[1]-photo.y)*ratio)));return {...photo,w:Math.round(w*100)/100,h:Math.round(w/ratio*100)/100};}
function bindWhiteboard(){
 document.querySelectorAll('[data-task-board]').forEach(x=>x.onclick=()=>openWhiteboard(Number(x.dataset.taskBoard)));if(page!=='whiteboard')return;const c=document.getElementById('wbCanvas');if(!c)return;wbDraw();wbControls();
 const point=e=>{const r=c.getBoundingClientRect();return [Math.round(Math.max(0,Math.min(1600,(e.clientX-r.left)/r.width*1600))),Math.round(Math.max(0,Math.min(1000,(e.clientY-r.top)/r.height*1000)))];};let pointer=null;
 c.onpointerdown=e=>{if(pointer!==null||e.button!==0||wb.uploading)return;const p=point(e);if(wb.tool==='select'){let found=-1,resize=false;for(let i=wb.images.length-1;i>=0;i--){const image=wb.images[i],handle=wbHandleSize();if(Math.abs(p[0]-image.x-image.w)<=handle&&Math.abs(p[1]-image.y-image.h)<=handle){found=i;resize=true;break;}if(p[0]>=image.x&&p[0]<=image.x+image.w&&p[1]>=image.y&&p[1]<=image.y+image.h){found=i;break;}}wb.selected=found<0?null:found;if(found<0){wbDraw();wbControls();return;}wb.gesture={photo:{...wb.images[found]},point:p,resize,snapshot:wbSnapshot()};}else{if(wb.strokes.length>=1500){toast('Экспортируй PNG и очисти доску');return;}wb.gesture={snapshot:wbSnapshot()};wb.active={tool:wb.tool,color:wb.color,width:wb.width,points:[p]};}pointer=e.pointerId;c.setPointerCapture(pointer);wbDraw();wbControls();};
 c.onpointermove=e=>{if(e.pointerId!==pointer||!wb.gesture)return;const p=point(e);if(wb.active){if(wb.active.points.length<4000)wb.active.points.push(p);}else{const g=wb.gesture,o=g.photo;wb.images[wb.selected]=g.resize?wbResizePhoto(o,p):{...o,x:Math.max(0,Math.min(1600-o.w,o.x+p[0]-g.point[0])),y:Math.max(0,Math.min(1000-o.h,o.y+p[1]-g.point[1]))};}wbRequestDraw();};
 const finish=e=>{if(e.pointerId!==pointer||!wb.gesture)return;const before=wb.gesture.snapshot;if(wb.active){wb.strokes.push(wb.active);wb.active=null;}wb.gesture=null;pointer=null;if(JSON.stringify(before)!==JSON.stringify(wbSnapshot())){wbRemember(before);wbChanged();}else{wbDraw();wbControls();}};c.onpointerup=finish;c.onpointercancel=finish;c.onlostpointercapture=finish;
 document.querySelectorAll('[data-wb-tool]').forEach(x=>x.onclick=()=>{if(wb.gesture)return;wb.tool=x.dataset.wbTool;wbControls();wbDraw();});document.querySelectorAll('[data-wb-color]').forEach(x=>x.onclick=()=>{wb.color=x.dataset.wbColor;wbControls();});document.getElementById('wbWidth').oninput=e=>{wb.width=Number(e.target.value);wbControls();};document.querySelectorAll('[data-wb-action]').forEach(x=>x.onclick=()=>wbAction(x.dataset.wbAction));document.querySelectorAll('[data-wb-page]').forEach(x=>x.onclick=()=>wbChangePage(Number(x.dataset.wbPage)));document.getElementById('wbPhotoFile').onchange=e=>{const files=Array.from(e.target.files);e.target.value='';wbInsertPhotos(files);};
 const zone=document.getElementById('wbDropZone');zone.ondragover=e=>{e.preventDefault();zone.classList.add('wb-drag-over');};zone.ondragleave=()=>zone.classList.remove('wb-drag-over');zone.ondrop=e=>{e.preventDefault();zone.classList.remove('wb-drag-over');wbInsertPhotos(Array.from(e.dataTransfer.files));};
}
function wbTyping(e){return /INPUT|TEXTAREA|SELECT/.test(e.target?.tagName)||e.target?.isContentEditable;}
document.addEventListener('keydown',e=>{
 if(page!=='whiteboard'||wbTyping(e)||e.altKey)return;const mod=e.ctrlKey||e.metaKey;
 if(mod){const action=e.code==='KeyZ'?(e.shiftKey?'redo':'undo'):e.code==='KeyY'?'redo':e.code==='KeyS'?(e.shiftKey?'export':'save'):null;if(action){e.preventDefault();wbAction(action);}return;}
 if(wb.gesture)return;
 const tool={KeyQ:'pen',KeyW:'marker',KeyE:'eraser',KeyR:'line',KeyA:'select'}[e.code];if(tool){e.preventDefault();wb.tool=tool;wbControls();wbDraw();return;}
 if(/^Digit[1-6]$/.test(e.code)){e.preventDefault();wb.color=WB_COLORS[Number(e.code.slice(-1))-1];wbControls();return;}
 if(e.shiftKey&&e.code==='KeyF'){if(wb.task){e.preventDefault();wbChangePage('new');}return;}
 const action={KeyZ:'thinner',KeyX:'thicker',KeyD:'color',KeyF:'photo',KeyG:'grid'}[e.code]||(e.key==='Delete'?(e.shiftKey?'clear':'deletePhoto'):null);if(action){e.preventDefault();wbAction(action);}
});
document.addEventListener('paste',e=>{if(page!=='whiteboard'||wbTyping(e))return;const files=Array.from(e.clipboardData?.items||[]).filter(i=>i.kind==='file'&&i.type.startsWith('image/')).map(i=>i.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();wbInsertPhotos(files);}});
window.addEventListener('beforeunload',e=>{if(wb.dirty||wb.uploading||wb.active){e.preventDefault();e.returnValue='';}});

function wbStorePage(){if(wb.task&&wb.pages)wb.pages[wb.pageIndex]=wbSnapshot();}
function wbSaveDocument(){wbStorePage();return wb.task?{...wb.pages[0],pages:wb.pages}:wbSnapshot();}
function wbChangePage(index){
 if(!wb.task||!wb.pages||wb.active||wb.gesture||wb.uploading)return;
 wbStorePage();const creating=index==='new';
 if(creating){if(wb.pages.length>=20){toast('Максимум 20 листов на одно ДЗ');return;}wb.pages.push({strokes:[],images:[],grid:wb.grid});index=wb.pages.length-1;}
 if(!Number.isInteger(index)||index<0||index>=wb.pages.length)return;
 wb.pageIndex=index;Object.assign(wb,JSON.parse(JSON.stringify(wb.pages[index])),{undo:[],redo:[],active:null,selected:null});if(creating)wbChanged();renderPage().catch(e=>toast(e.message));
}

window.addEventListener('online',()=>{wb.attempts=0;if(wb.dirty)wbScheduleSave(0);});
