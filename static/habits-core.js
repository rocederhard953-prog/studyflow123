/* Date-only habit math, shared by the browser and Node regression checks. */
(function(root){
  'use strict';
  const key=d=>d.toISOString().slice(0,10);
  function parse(s){if(typeof s!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(s))return null;const d=new Date(s+'T12:00:00Z');return Number.isFinite(+d)&&key(d)===s?d:null;}
  function add(s,n){const d=parse(s);if(!d)throw Error('Invalid day');d.setUTCDate(d.getUTCDate()+n);return key(d);}
  function weekday(s){const d=parse(s);return d?(d.getUTCDay()+6)%7:-1;}
  function scheduled(h,day){return !!parse(day)&&day>=String(h.created_at||'0000-01-01').slice(0,10)&&(h.config?.mode==='weekly'||Array.isArray(h.days)&&h.days.includes(weekday(day)));}
  function days(start,end){const out=[];if(!parse(start)||!parse(end)||start>end)return out;for(let d=start;d<=end&&out.length<3660;d=add(d,1))out.push(d);return out;}
  function summary(habits,start,end,today){let done=0,total=0;for(const h of habits){const checks=new Set(h.checks||[]),weeks=new Map();for(const day of days(start,end)){if(day>today||!scheduled(h,day))continue;const week=add(day,-weekday(day)),value=weeks.get(week)||{done:0,total:0};value.total++;if(checks.has(day))value.done++;weeks.set(week,value);}for(const [week,value] of weeks){const created=String(h.created_at||week).slice(0,10),available=7-Math.max(0,Math.min(6,Math.round((parse(created)-parse(week))/86400000))),goal=h.config?.mode==='weekly'?(start===end?1:Math.min(h.config.weekly_target,available)):value.total;total+=goal;done+=Math.min(goal,value.done);}}return {done,total,percent:total?Math.round(done/total*100):0};}
  function series(h,today){if(h.config?.mode==='weekly'){const goal=h.config.weekly_target,checks=new Set(h.checks||[]),created=String(h.created_at||add(today,-365)).slice(0,10);let run=0,best=0;for(let week=add(created,-weekday(created));week<=today;week=add(week,7)){const end=add(week,6),eligible=days(week,end).filter(d=>d>=created),hits=eligible.filter(d=>d<=today&&checks.has(d)).length;if(hits>=Math.min(goal,eligible.length)){run++;best=Math.max(best,run);}else if(end<today)run=0;}return {current:run,best};}const checks=new Set(h.checks||[]);const created=String(h.created_at||add(today,-365)).slice(0,10);const start=created>add(today,-3659)?created:add(today,-3659);let run=0,best=0;for(const day of days(start,today)){if(!scheduled(h,day))continue;if(checks.has(day)){run++;best=Math.max(best,run);}else if(day!==today)run=0;}return {current:run,best};}
  function monthCells(month){if(!/^\d{4}-\d{2}$/.test(month)||!parse(month+'-01'))throw Error('Invalid month');const first=month+'-01';const d=parse(first);d.setUTCMonth(d.getUTCMonth()+1,0);return [...Array(weekday(first)).fill(null),...days(first,key(d))];}
  const api={parse,add,weekday,scheduled,days,summary,series,monthCells};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.HabitStats=api;
})(globalThis);
