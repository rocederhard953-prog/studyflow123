const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/whiteboard.js'),'utf8');
function setup(){
 const handlers={},logs=[],timers=new Map(),windowHandlers={};let timerId=0;
 function canvas(){const ctx=new Proxy({},{get(o,k){if(k in o)return o[k];return (...args)=>logs.push([k,ctx.globalCompositeOperation,...args]);}});return {width:1600,height:1000,getContext:()=>ctx,getBoundingClientRect:()=>({left:0,top:0,width:1600,height:1000}),setPointerCapture(){},style:{}};}
 const surface=canvas(),nodes={wbCanvas:surface,wbWidth:{},wbWidthValue:{},wbStatus:{},wbPhotoFile:{},wbDropZone:{style:{},clientWidth:1600,clientHeight:1000,getBoundingClientRect:()=>({left:0,top:0,width:1600,height:1000}),setPointerCapture(){},addEventListener(name,fn){this[name]=fn;},classList:{add(){},remove(){}}}};
 const context=vm.createContext({page:'whiteboard',document:{addEventListener:(name,f)=>handlers[name]=f,querySelectorAll:()=>[],querySelector:()=>null,getElementById:id=>nodes[id]||null,createElement:name=>name==='canvas'?canvas():{}},window:{addEventListener:(n,f)=>windowHandlers[n]=f},confirm:()=>true,toast(){},setTimeout:f=>{timers.set(++timerId,f);return timerId;},clearTimeout:id=>timers.delete(id),requestAnimationFrame:f=>{f();return 0;},api:async()=>({revision:1})});
 vm.runInContext(source,context);vm.runInContext('wb.view={zoom:1,x:0,y:0,w:1600,h:1000}',context);
 const run=code=>vm.runInContext(code,context);
 const key=(code,extra={})=>handlers.keydown({code,key:'',target:{tagName:'BODY'},preventDefault(){},...extra});
 const runTimer=()=>{const next=timers.entries().next().value;if(next){timers.delete(next[0]);next[1]();}};
 return {context,handlers,run,key,surface,logs,timers,runTimer,windowHandlers,zone:nodes.wbDropZone};
}
test('left-hand shortcuts use physical positions and ignore text input',()=>{
 const s=setup();for(const [code,tool] of [['KeyQ','pen'],['KeyW','marker'],['KeyE','eraser'],['KeyR','line'],['KeyA','select']]){s.key(code,{key:'й'});assert.equal(s.run('wb.tool'),tool);}
 s.key('KeyZ');assert.equal(s.run('wb.width'),2);s.key('KeyX');assert.equal(s.run('wb.width'),4);s.key('KeyC');assert.equal(s.run('wb.width'),6);s.key('Digit3');assert.equal(s.run('wb.color'),'#16803d');s.key('KeyD');assert.equal(s.run('wb.color'),'#111111');
 s.key('KeyQ',{target:{tagName:'TEXTAREA'}});assert.equal(s.run('wb.tool'),'select');
});
test('photo moves and proportional resizing can be undone and redone',()=>{
 const s=setup();s.run("wb.images=[{stored_name:'photo',x:100,y:100,w:200,h:100}];wb.bitmaps.set('photo',{});wb.tool='select';bindWhiteboard()");
 const event=(x,y)=>({button:0,pointerId:1,clientX:x,clientY:y});
 s.surface.onpointerdown(event(150,150));s.surface.onpointermove(event(300,200));s.surface.onpointerup(event(300,200));
 assert.equal(s.run('wb.images[0].x'),250);assert.equal(s.run('wb.images[0].y'),150);
 s.surface.onpointerdown(event(450,250));s.surface.onpointermove(event(650,350));s.surface.onpointerup(event(650,350));
 assert.equal(s.run('wb.images[0].w'),400);assert.equal(s.run('wb.images[0].h'),200);
 s.key('KeyZ',{ctrlKey:true});assert.equal(s.run('wb.images[0].w'),200);s.key('KeyZ',{ctrlKey:true,shiftKey:true});assert.equal(s.run('wb.images[0].w'),400);
});
test('resize stays on the board and preserves aspect ratio',()=>{
 const s=setup();const p=s.run('wbResizePhoto({x:1000,y:800,w:200,h:100},[4000,4000])');assert.ok(p.x+p.w<=12000.01);assert.ok(p.y+p.h<=8000.01);assert.equal(p.w/p.h,2);
});
test('eraser affects a separate ink layer, not the grid or photo',()=>{
 const s=setup();s.run("wb.images=[{stored_name:'photo',x:0,y:0,w:200,h:100}];wb.bitmaps.set('photo',{});wb.strokes=[{tool:'eraser',width:4,color:'#182033',points:[[10,10],[20,20]]}];wbDraw(true)");
 assert.ok(s.logs.some(x=>x[0]==='stroke'&&x[1]==='destination-out'));
 assert.equal(s.logs.filter(x=>x[0]==='drawImage').length,2);
 assert.ok(s.logs.some(x=>x[0]==='lineTo'&&x[2]===1600));
});
test('paste accepts image files only outside text fields',()=>{
 const s=setup();s.run('wbInsertPhotos=files=>{globalThis.received=files.length}');let prevented=false;const data={items:[{kind:'file',type:'image/png',getAsFile:()=>({type:'image/png'})}]};
 s.handlers.paste({target:{tagName:'BODY'},clipboardData:data,preventDefault(){prevented=true;}});assert.equal(s.run('received'),1);assert.ok(prevented);
 s.run('received=0');s.handlers.paste({target:{tagName:'TEXTAREA'},clipboardData:data,preventDefault(){throw Error('intercepted typing');}});assert.equal(s.run('received'),0);
});
test('saving includes images, strokes and the grid preference',async()=>{
 const s=setup();let payload;s.context.api=async(url,options)=>{payload=JSON.parse(options.body);return {revision:2};};s.run("wb.images=[{stored_name:'photo',x:0,y:0,w:200,h:100}];wb.grid=false;wb.dirty=true");await s.run("wbAction('save')");assert.equal(payload.images.length,1);assert.equal(payload.grid,false);assert.equal(s.run('wb.revision'),2);assert.equal(s.run('wb.dirty'),false);
});
test('legacy homework sheets merge into one large world without losing drawings or photos',async()=>{const s=setup();s.run("Object.assign(wb,wbImportDocument({pages:[{strokes:[{tool:'pen',width:4,color:'#111111',points:[[10,10]]}],images:[],grid:true},{strokes:[],images:[{stored_name:'photo',x:100,y:200,w:200,h:100}]}]}));wb.dirty=true");assert.equal(s.run('wb.strokes[0].points[0][0]'),10);assert.equal(s.run('wb.images[0].x'),2100);let payload;s.context.api=async(u,o)=>{payload=JSON.parse(o.body);return {revision:1};};await s.run("wbAction('save')");assert.equal(payload.layout,'large-v1');assert.equal(payload.pages,undefined);assert.equal(payload.images.length,1);});
test('single world has no sheet creation and drawing canvas stays viewport sized',()=>{const s=setup();assert.equal(s.run('typeof wbChangePage'),'undefined');s.run('wbFitView();wbDraw()');assert.equal(s.surface.width,1600);assert.equal(s.surface.height,1000);assert.ok(s.run('wb.view.zoom')<1);s.key('Home');assert.equal(s.run('wb.view.zoom'),1);});

test('autosave combines rapid actions and queues edits made during a save',async()=>{
 const s=setup(),payloads=[];let resolveFirst;
 s.context.api=async(url,options)=>{payloads.push(JSON.parse(options.body));if(payloads.length===1)return new Promise(r=>resolveFirst=r);return {revision:2};};
 s.run("wb.key='personal';wb.grid=false;wbChanged();wbChanged()");assert.equal(s.timers.size,1);s.runTimer();assert.equal(payloads.length,1);
 s.run('wb.grid=true;wbChanged()');s.runTimer();assert.equal(payloads.length,1);
 resolveFirst({revision:1});await new Promise(r=>setImmediate(r));assert.equal(s.timers.size,1);assert.equal(s.run('wb.dirty'),true);
 s.runTimer();await new Promise(r=>setImmediate(r));assert.equal(payloads.length,2);assert.equal(payloads[0].grid,false);assert.equal(payloads[1].grid,true);assert.equal(payloads[1].revision,1);assert.equal(s.run('wb.dirty'),false);
});
test('autosave preserves unsaved data on failure and retries when online',async()=>{
 const s=setup();let offline=true;s.context.api=async()=>{if(offline)throw Error('offline');return {revision:1};};
 s.run("wb.key='personal';wb.grid=false;wbChanged()");s.runTimer();await new Promise(r=>setImmediate(r));assert.equal(s.run('wb.dirty'),true);assert.equal(s.run('wb.error'),'offline');
 offline=false;s.windowHandlers.online();s.runTimer();await new Promise(r=>setImmediate(r));assert.equal(s.run('wb.dirty'),false);
});
test('autosave stops on revision conflict instead of overwriting another window',async()=>{
 const s=setup();s.context.api=async()=>{throw Error('Доска изменена в другом окне');};s.run("wb.key='personal';wbChanged()");s.runTimer();await new Promise(r=>setImmediate(r));assert.equal(s.run('wb.dirty'),true);assert.equal(s.run('wb.conflict'),true);assert.equal(s.timers.size,0);
});
test('object eraser removes one whole topmost stroke, supports undo and leaves photos intact',()=>{
 const s=setup();s.run("wb.images=[{stored_name:'photo',x:0,y:0,w:200,h:100}];wb.strokes=[{tool:'pen',width:2,color:'#111111',points:[[10,10],[90,10]]},{tool:'marker',width:6,color:'#dc2626',points:[[10,10],[90,10]]}];wb.tool='eraser';bindWhiteboard()");
 s.surface.onpointerdown({button:0,pointerId:1,clientX:50,clientY:10,pointerType:'mouse'});
 assert.equal(s.run('wb.strokes.length'),1);assert.equal(s.run('wb.strokes[0].tool'),'pen');assert.equal(s.run('wb.images.length'),1);
 s.surface.onpointermove({pointerId:1,clientX:60,clientY:10});assert.equal(s.run('wb.strokes.length'),1);
 s.key('KeyZ',{ctrlKey:true});assert.equal(s.run('wb.strokes.length'),2);s.key('KeyZ',{ctrlKey:true,shiftKey:true});assert.equal(s.run('wb.strokes.length'),1);
 assert.equal(s.run('wbEraseAt([800,800],2)'),false);assert.equal(s.run('wb.strokes.length'),1);
});
test('stroke hit testing uses actual straight lines and dots, not their bounding boxes',()=>{
 const s=setup();assert.equal(s.run("wbHitStroke({tool:'line',width:2,points:[[10,10],[80,90],[100,10]]},[50,10],2)"),true);
 assert.equal(s.run("wbHitStroke({tool:'line',width:2,points:[[10,10],[100,100]]},[20,90],2)"),false);
 assert.equal(s.run("wbHitStroke({tool:'pen',width:2,points:[[50,50]]},[51,50],1)"),true);
 assert.equal(s.run("wbHitStroke({tool:'eraser',width:20,points:[[50,50]]},[50,50],8)"),false);
});
test('hand panning, wheel scrolling and zoom do not draw or autosave',()=>{
 const s=setup();s.run("wb.tool='pan';bindWhiteboard()");
 const event=(x,y)=>({button:0,pointerId:1,clientX:x,clientY:y,preventDefault(){}});
 s.zone.onpointerdown(event(300,300));s.zone.onpointermove(event(340,320));s.zone.onpointerup(event(340,320));
 assert.equal(s.run('wb.view.x'),40);assert.equal(s.run('wb.view.y'),20);assert.equal(s.run('wb.strokes.length'),0);assert.equal(s.run('wb.dirty'),false);
 let prevented=false;s.zone.wheel({deltaX:5,deltaY:10,preventDefault(){prevented=true;}});assert.ok(prevented);assert.equal(s.run('wb.view.x'),35);assert.equal(s.run('wb.view.y'),10);
 s.key('Equal');assert.ok(s.run('wb.view.zoom')>1);s.key('Digit0');assert.ok(s.run('wb.view.zoom')<1);s.key('Home');assert.equal(s.run('wb.view.zoom'),1);
 s.key('KeyS');assert.equal(s.run('wb.tool'),'pan');s.key('KeyQ');s.key('Space');assert.equal(s.run('wb.spacePan'),true);s.handlers.keyup({code:'Space'});assert.equal(s.run('wb.spacePan'),false);
 assert.equal(s.run('wb.dirty'),false);assert.equal(s.timers.size,0);
});
