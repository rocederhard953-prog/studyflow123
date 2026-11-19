const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/quick-updates.js'),'utf8');
function setup(){const calls=[],context=vm.createContext({me:{id:1},page:'tasks',cache:{tasks:[{id:7,done:false,attachments:[]}],habits:[{id:4,checks:[],days:[0,1,2,3,4,5,6]}]},today:()=> '2026-11-18',HabitStats:{scheduled:()=>true},api:async(url,options)=>calls.push({url,options}),toast(){},document:{querySelector:()=>null,querySelectorAll:()=>[]},window:{},renderPage(){throw Error('Route reload is forbidden');}});vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/grammar.js'),'utf8'),context);vm.runInContext(source,context);return {context,calls};}
test('task checks save once and update cached status without reloading a route',async()=>{
 const s=setup(),input={dataset:{taskdone:'7'},checked:true,closest:()=>null};await s.context.updateTaskCheckbox(input);assert.equal(s.calls.length,1);assert.equal(s.context.cache.tasks[0].done,true);assert.equal(input.checked,true);assert.equal(input.disabled,false);
});
test('failed check reverts the input and leaves saved state unchanged',async()=>{
 const s=setup(),input={dataset:{taskdone:'7'},checked:true,closest:()=>null};s.context.api=async()=>{throw Error('offline');};await s.context.updateTaskCheckbox(input);assert.equal(input.checked,false);assert.equal(s.context.cache.tasks[0].done,false);assert.equal(input.disabled,false);
});
test('home habit check requires no follow-up GET or route refresh',async()=>{
 const s=setup(),input={dataset:{habit:'4'},checked:true,closest:()=>null};s.context.page='home';await s.context.updateHomeHabitCheckbox(input);assert.equal(s.calls.length,1);assert.equal(s.context.cache.habits[0].checks[0],'2026-11-18');assert.equal(input.disabled,false);
});
test('slow response from an old route cannot replace the newly opened route',async()=>{
 const app=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8'),start=app.indexOf('let pageRenderTicket='),end=app.indexOf('function renderSectionHeading',start),fragment=app.slice(start,end);
 const root={innerHTML:'existing content',setAttribute(){},removeAttribute(){}},context=vm.createContext({page:'home',document:{getElementById:()=>root},setTimeout(){return 1;},clearTimeout(){},bindCommon(){},animatePageEntrance(){},esc:s=>s});
 const names=['whiteboardPage','assistantPage','homePage','orbitLandingPage','dayPage','calendarPage','habitsPage','tasksPage','schedulePage','gradesPage','cheatsPage','cardsPage','goalsPage','pomodoroPage','analyticsPage','telegramPage','remindersPage','appearancePage','settingsPage','developerPage','subjectColorsPage','searchPage'];for(const name of names)context[name]=async()=>name;
 let resolveHome;context.homePage=()=>new Promise(r=>resolveHome=r);vm.runInContext(fragment,context);const slow=context.renderPage();assert.equal(root.innerHTML,'existing content');context.page='tasks';await context.renderPage();assert.equal(root.innerHTML,'tasksPage');resolveHome('stale home');await slow;assert.equal(root.innerHTML,'tasksPage');
});
test('habit check updates local data and panels without fetching the route',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../static/habits.js'),'utf8'),habit={id:4,created_at:'2026-11-01',days:[0,1,2,3,4,5,6],checks:[]},context=vm.createContext({me:{id:1},page:'habits',cache:{habits:[habit]},today:()=> '2026-11-18',HabitStats:{scheduled:()=>true},api:async()=>{},toast(){},document:{querySelectorAll:()=>[]},renderPage(){throw Error('Route reload forbidden');}});vm.runInContext(source,context);let panels=0;context.refreshHabitParts=()=>panels++;await context.toggleHabitMark(4,'2026-11-18',true);assert.equal(habit.checks[0],'2026-11-18');assert.equal(panels,1);
});

