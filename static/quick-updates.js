/* Save a check without reloading the route or replacing its DOM. */
async function updateTaskCheckbox(input){
 const id=Number(input.dataset.taskdone),done=input.checked,user=me?.id;
 input.disabled=true;
 try{
    await api('/tasks/'+id,{method:'PUT',body:JSON.stringify({done})});
    if(me?.id!==user)return;
    const task=cache.tasks?.find(t=>t.id===id);if(task)task.done=done;
    const row=input.closest('.home-task,.card');row?.classList.toggle('task-is-done',done);
    if(page==='tasks'&&task){
      const status=row?.querySelector(':scope > .muted.small');if(status)status.textContent=done?'✓ Выполнено':!task.due?'Без срока':task.due<today()?'⚠ Просрочено':task.due===today()?'Сегодня':'В работе';
      const values=document.querySelectorAll('#content .stats-grid .stat-value');const tasks=cache.tasks||[];const counts=[tasks.length,tasks.filter(t=>!t.done).length,tasks.filter(t=>t.done).length,tasks.filter(t=>t.attachments?.length).length];values.forEach((el,i)=>{if(i<counts.length)el.textContent=counts[i];});
    }
    if(page==='home'){const count=document.querySelector('.day-metrics > div:first-child b');if(count)count.textContent=(cache.tasks||[]).filter(t=>!t.done).length;refreshHomeMenuCounts();}
    toast(done?'Задание выполнено':'Задание снова в работе');
 }catch(e){input.checked=!done;toast(e.message);}finally{input.disabled=false;}
}
async function updateHomeHabitCheckbox(input){
 const id=Number(input.dataset.habit),done=input.checked,day=today(),user=me?.id;input.disabled=true;
 try{
    await api('/habits/'+id+'/check',{method:'PUT',body:JSON.stringify({day,done})});
    if(me?.id!==user)return;
    const habit=cache.habits?.find(h=>h.id===id);if(habit)habit.checks=done?[...new Set([...habit.checks,day])]:habit.checks.filter(d=>d!==day);
    input.closest('.habit-row')?.classList.toggle('is-done',done);
    if(page==='home'){
      const habits=(cache.habits||[]).filter(h=>HabitStats.scheduled(h,day)),count=habits.filter(h=>h.checks.includes(day)).length,pct=habits.length?Math.round(count/habits.length*100):0;
      const metric=document.querySelector('.day-metrics > div:nth-child(2) b');if(metric)metric.innerHTML=`${count}<em> / ${habits.length}</em>`;
      const title=document.querySelector('.habit-progress b'),percent=document.querySelector('.habit-progress span'),progress=document.querySelector('.day-habits .progress span');if(title)title.textContent=count+' из '+habits.length;if(percent)percent.textContent=pct+'%';if(progress)progress.style.width=pct+'%';refreshHomeMenuCounts();
    }
 }catch(e){input.checked=!done;toast(e.message);}finally{input.disabled=false;}
}
function animatePageEntrance(root){
 if(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return;
 Array.from(root.children).slice(0,8).forEach((node,i)=>{if(typeof node.animate==='function')node.animate([{opacity:0,transform:'translateY(7px)'},{opacity:1,transform:'translateY(0)'}],{duration:190,delay:Math.min(i*15,60),easing:'cubic-bezier(.2,.65,.3,1)',fill:'backwards'});});
}

function refreshHomeMenuCounts(){const tasks=(cache.tasks||[]).filter(t=>!t.done).length,day=today(),habits=(cache.habits||[]).filter(h=>HabitStats.scheduled(h,day)),done=habits.filter(h=>h.checks.includes(day)).length;const taskCount=document.querySelector('.planet-task-count'),habitCount=document.querySelector('.planet-habit-count'),summary=document.querySelector('#planetToday>summary');if(taskCount)taskCount.textContent=tasks;if(habitCount)habitCount.textContent=done;if(summary)summary.textContent='Мой день · '+tasks+' заданий · '+done+'/'+habits.length+' привычек';}
