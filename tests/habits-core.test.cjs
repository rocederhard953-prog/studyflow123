const test=require('node:test'),assert=require('node:assert/strict');
const H=require('../static/habits-core.js');
const weekdayHabit={id:1,name:'Study',created_at:'2026-11-02',days:[0,1,2,3,4],checks:['2026-11-12','2026-11-13','2026-11-16']};
test('date math is stable across DST and month/year boundaries',()=>{
  assert.equal(H.add('2026-03-29',1),'2026-03-30');assert.equal(H.add('2026-12-31',1),'2027-01-01');
  assert.equal(H.add('2024-02-28',1),'2024-02-29');assert.equal(H.parse('2026-02-30'),null);
});
test('weekends do not break a weekday-only streak and pending today stays alive',()=>{
  assert.deepEqual(H.series(weekdayHabit,'2026-11-17'),{current:3,best:3});
  assert.deepEqual(H.series(weekdayHabit,'2026-11-18'),{current:0,best:3});
});
test('planned days control denominator, not all calendar days',()=>{
  assert.deepEqual(H.summary([weekdayHabit],'2026-11-12','2026-11-16','2026-11-16'),{done:3,total:3,percent:100});
});
test('creation date and today exclude future and pre-creation checks',()=>{
  const h={created_at:'2026-11-16',days:[0,1,2,3,4,5,6],checks:['2026-11-15','2026-11-16','2026-11-18']};
  assert.deepEqual(H.summary([h],'2026-11-10','2026-11-20','2026-11-17'),{done:1,total:2,percent:50});
  assert.equal(H.scheduled(h,'2026-11-15'),false);
});
test('zero planned habits never produces NaN or fabricated success',()=>{
  assert.deepEqual(H.summary([],'2026-11-16','2026-11-17','2026-11-17'),{done:0,total:0,percent:0});
  assert.deepEqual(H.series({created_at:'2026-11-01',days:[],checks:[]},'2026-11-17'),{current:0,best:0});
});
test('month cells start on Monday and include leap day without phantom dates',()=>{
  const feb=H.monthCells('2024-02');assert.equal(feb.filter(Boolean).length,29);assert.equal(feb[0],null);assert.equal(feb[3],'2024-02-01');assert.equal(feb.at(-1),'2024-02-29');
});
test('a missed scheduled day breaks the series, duplicate checks count once',()=>{
  const h={created_at:'2026-11-10',days:[0,1,2,3,4,5,6],checks:['2026-11-10','2026-11-10','2026-11-12']};
  assert.equal(H.series(h,'2026-11-12').current,1);assert.equal(H.summary([h],'2026-11-10','2026-11-12','2026-11-12').done,2);
});

test('weekly habits cap completion at the weekly target and count successful weeks',()=>{const H=require('../static/habits-core.js');const h={created_at:'2026-11-02',days:[],config:{mode:'weekly',weekly_target:3},checks:['2026-11-02','2026-11-04','2026-11-06','2026-11-07']};assert.equal(H.scheduled(h,'2026-11-03'),true);assert.deepEqual(H.summary([h],'2026-11-02','2026-11-08','2026-11-08'),{done:3,total:3,percent:100});assert.deepEqual(H.series(h,'2026-11-08'),{current:1,best:1});});

test('a newly created flexible habit keeps its weekly quota instead of claiming 100 percent on day one',()=>{const H=require('../static/habits-core.js'),h={created_at:'2026-11-19',days:[],config:{mode:'weekly',weekly_target:3},checks:['2026-11-19']};assert.deepEqual(H.summary([h],'2026-11-13','2026-11-19','2026-11-19'),{done:1,total:3,percent:33});});
