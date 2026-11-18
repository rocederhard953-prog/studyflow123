const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..'),planet=fs.readFileSync(path.join(root,'static/planet-menu.js'),'utf8'),app=fs.readFileSync(path.join(root,'static/app.js'),'utf8');
function context(){const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const ctx=vm.createContext({esc});vm.runInContext(planet,ctx);return ctx;}
test('planet menu contains every existing section and escapes the display name',()=>{
 const ctx=context(),html=ctx.planetMenuHTML({name:'<script>bad</script>',openTasks:3,habitsDone:1,habitsTotal:4});assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));
 const expected=[...new Set([...fs.readFileSync(path.join(root,'static/index.html'),'utf8').matchAll(/data-page="([^"]+)"/g)].map(m=>m[1]))].filter(k=>k!=='home').sort();const actual=[...html.matchAll(/data-planet-page="([^"]+)"/g)].map(m=>m[1]).sort();assert.deepEqual(actual,expected);assert.equal((html.match(/data-planet-ray=/g)||[]).length,actual.length);
});
test('home renders the planet and keeps todays tasks and habits available',async()=>{
 const ctx=context();ctx.me={display_name:'Иван',username:'ivan',timezone:'UTC'};ctx.cache={};ctx.timer={running:false};ctx.today=()=> '2026-11-18';ctx.fmt=d=>d;ctx.api=async url=>({'/habits':[{id:4,name:'Чтение',days:[0,1,2,3,4,5,6],checks:[]}],'/tasks':[{id:7,title:'Решить пример',subject:'Математика',due:'2026-11-20',done:false}],'/lessons':[],'/goals':[],'/settings':{widgets:'tasks,habits,schedule,pomodoro,goals'},'/subject-colors':{},'/lesson-notes':{}}[url]);
 for(const name of ['renderSectionHeading','btn','empty']){const line=app.split('\n').find(l=>l.startsWith('function '+name+'('));vm.runInContext(line,ctx);}
 const start=app.indexOf('function subjectColor'),end=app.indexOf('function showHomePhotos',start);vm.runInContext(app.slice(start,end),ctx);const html=await ctx.homePage();assert.ok(html.includes('planet-menu'));assert.ok(html.includes('id="planetToday"'));assert.ok(html.includes('Решить пример'));assert.ok(html.includes('Чтение'));assert.ok(html.includes('data-taskdone="7"'));assert.ok(!html.includes('undefined'));
});
