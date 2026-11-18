"""Personal day plans, flexible habits and weekly summaries; no schema migration."""
import json
import math
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from fastapi import Depends, HTTPException


def install(core):
    app=core['app']; User=core['User']; Session=core['Session']; current_user=core['current_user']; dbdep=core['dbdep']
    Setting=core['UserSetting']; Habit=core['Habit']; Check=core['HabitCheck']; Task=core['Task']; Lesson=core['Lesson']; Focus=core['PomodoroSession']; Goal=core['Goal']
    owned=core['owned']; clean_date=core['clean_date']; serialize=core['serialize']

    def get(db,uid,key,default=None):
        row=db.scalar(select(Setting).where(Setting.user_id==uid,Setting.key==key))
        try:return json.loads(row.value) if row else default
        except (ValueError,TypeError):return default

    def put(db,uid,key,value):
        row=db.scalar(select(Setting).where(Setting.user_id==uid,Setting.key==key))
        if not row:row=Setting(user_id=uid,key=key);db.add(row)
        row.value=json.dumps(value,ensure_ascii=False,allow_nan=False)

    def local_day(user):
        try:return datetime.now(ZoneInfo(user.timezone or 'UTC')).date()
        except Exception:return datetime.now(timezone.utc).date()

    def config(db,uid,hid):
        return get(db,uid,'habit-config:'+str(hid),{'mode':'days','weekly_target':3,'target':1,'unit':'раз'})

    def habit_details(db,uid,hid):
        records=db.scalars(select(Setting).where(Setting.user_id==uid,Setting.key.like('habit-progress:'+str(hid)+':%'))).all()
        values={}
        for row in records:
            try:values[row.key.rsplit(':',1)[1]]=json.loads(row.value)
            except ValueError:pass
        return {'config':config(db,uid,hid),'progress':values}

    def validate_config(d):
        if not isinstance(d,dict):raise HTTPException(422,'Некорректные параметры привычки')
        mode=d.get('mode','days');weekly=d.get('weekly_target',3);target=d.get('target',1);unit=str(d.get('unit','раз')).strip()
        if mode not in ('days','weekly') or type(weekly) is not int or not 1<=weekly<=7 or type(target) not in (int,float) or not math.isfinite(target) or not 1<=target<=100000 or not 1<=len(unit)<=24:raise HTTPException(422,'Проверь ритм, цель и единицу измерения')
        return {'mode':mode,'weekly_target':weekly,'target':target,'unit':unit}

    @app.put('/api/habits/{hid}/config')
    def set_habit_config(hid:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
        owned(db,Habit,hid,user);value=validate_config(d);put(db,user.id,'habit-config:'+str(hid),value);db.commit();return value

    @app.put('/api/habits/{hid}')
    def edit_habit(hid:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
        h=owned(db,Habit,hid,user);name=str(d.get('name',h.name)).strip();days=d.get('days',[int(x) for x in h.days.split(',') if x])
        if not name or len(name)>120 or not isinstance(days,list) or any(type(x) is not int or not 0<=x<=6 for x in days):raise HTTPException(422,'Проверь название и дни')
        cfg=validate_config(d.get('config',config(db,user.id,hid)));h.name=name;h.days=','.join(map(str,sorted(set(days))));put(db,user.id,'habit-config:'+str(hid),cfg);db.commit();return serialize(h)

    def goal_details(db,uid,gid):
        value=get(db,uid,'goal-blocks:'+str(gid),{'revision':0,'blocks':[]})
        return {**value,'history':get(db,uid,'goal-history:'+str(gid),[])}

    def validate_blocks(blocks):
        if not isinstance(blocks,list) or len(blocks)>30:raise HTTPException(422,'До 30 блоков в цели')
        cleaned=[];ids=set();total=0
        for block in blocks:
            if not isinstance(block,dict) or not isinstance(block.get('items'),list):raise HTTPException(422,'Некорректный блок')
            bid=block.get('id');title=str(block.get('title','')).strip();items=[]
            if not isinstance(bid,str) or not 1<=len(bid)<=48 or bid in ids or not 1<=len(title)<=180:raise HTTPException(422,'Проверь название и номер блока')
            ids.add(bid)
            for item in block['items']:
                if not isinstance(item,dict):raise HTTPException(422,'Некорректный пункт')
                ident=item.get('id');text=str(item.get('title','')).strip();done=item.get('done',False);total+=1
                if not isinstance(ident,str) or not 1<=len(ident)<=48 or ident in ids or not 1<=len(text)<=240 or type(done) is not bool or total>500:raise HTTPException(422,'Проверь пункты цели (до 500)')
                ids.add(ident);items.append({'id':ident,'title':text,'done':done})
            if not items:raise HTTPException(422,'Добавь хотя бы один пункт в каждый блок')
            cleaned.append({'id':bid,'title':title,'items':items})
        return cleaned

    def store_goal_blocks(db,user,goal,blocks,revision):
        flat=[item for block in blocks for item in block['items']]
        goal.target=max(1,len(flat));goal.progress=sum(item['done'] for item in flat);goal.unit='пунктов';goal.done=bool(flat) and goal.progress>=goal.target
        put(db,user.id,'goal-blocks:'+str(goal.id),{'revision':revision,'blocks':blocks})
        history=get(db,user.id,'goal-history:'+str(goal.id),[]);point={'day':str(local_day(user)),'done':int(goal.progress),'total':int(goal.target)}
        if history and history[-1]['day']==point['day']:history[-1]=point
        else:history.append(point)
        put(db,user.id,'goal-history:'+str(goal.id),history[-366:])

    def initialize_goal_blocks(db,user,goal,data):
        if 'blocks' in data:
            blocks=validate_blocks(data['blocks'])
            if not blocks:raise HTTPException(422,'Добавь блоки и пункты')
            store_goal_blocks(db,user,goal,blocks,1)

    @app.put('/api/goals/{gid}/blocks')
    def set_goal_blocks(gid:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
        goal=owned(db,Goal,gid,user);current=goal_details(db,user.id,gid)
        if type(d.get('revision')) is not int or d['revision']!=current['revision']:raise HTTPException(409,'Цель изменена в другом окне. Обнови раздел.')
        blocks=validate_blocks(d.get('blocks'))
        if not blocks:raise HTTPException(422,'Добавь хотя бы один блок')
        store_goal_blocks(db,user,goal,blocks,current['revision']+1);db.commit();return {**serialize(goal),**goal_details(db,user.id,gid)}

    @app.put('/api/goals/{gid}/steps/{sid}')
    def set_goal_step(gid:int,sid:str,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
        goal=owned(db,Goal,gid,user);current=goal_details(db,user.id,gid)
        if type(d.get('done')) is not bool:raise HTTPException(422,'Некорректная отметка')
        if type(d.get('revision')) is not int or d['revision']!=current['revision']:raise HTTPException(409,'Цель изменена в другом окне. Обнови раздел.')
        item=next((item for block in current['blocks'] for item in block['items'] if item['id']==sid),None)
        if not item:raise HTTPException(404,'Пункт не найден')
        item['done']=d['done'];store_goal_blocks(db,user,goal,current['blocks'],current['revision']+1);db.commit();return {**serialize(goal),**goal_details(db,user.id,gid)}

    @app.put('/api/habits/{hid}/progress')
    def habit_progress(hid:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
        h=owned(db,Habit,hid,user);day=clean_date(d.get('day'));amount=d.get('amount',0);note=str(d.get('note','')).strip()
        if not day or day>local_day(user) or day<h.created_at or type(amount) not in (int,float) or not math.isfinite(amount) or not 0<=amount<=100000 or len(note)>1000:raise HTTPException(422,'Проверь дату, количество и заметку')
        cfg=config(db,user.id,hid)
        if cfg['mode']=='days' and str(day.weekday()) not in h.days.split(','):raise HTTPException(422,'Привычка не запланирована на этот день')
        value={'amount':amount,'note':note};put(db,user.id,f'habit-progress:{hid}:{day}',value)
        check=db.scalar(select(Check).where(Check.habit_id==hid,Check.day==day,Check.user_id==user.id))
        done=amount>=cfg['target']
        if done and not check:db.add(Check(user_id=user.id,habit_id=hid,day=day))
        elif not done and check:db.delete(check)
        db.commit();return {**value,'done':done}

    @app.get('/api/day-plan')
    def day_plan(day:str='',user:User=Depends(current_user),db:Session=Depends(dbdep)):
        selected=clean_date(day) if day else local_day(user)
        if not selected:raise HTTPException(422,'Некорректная дата')
        return get(db,user.id,'day-plan:'+str(selected),{'items':[]})

    @app.put('/api/day-plan')
    def save_day_plan(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
        day=clean_date(d.get('day'));items=d.get('items')
        if not day or not isinstance(items,list) or len(items)>50:raise HTTPException(422,'Проверь план дня')
        cleaned=[];keys=set();stars=0
        for item in items:
            if not isinstance(item,dict):raise HTTPException(422,'Некорректное дело')
            kind=item.get('kind');ident=item.get('id');minutes=item.get('minutes',25);star=item.get('important',False)
            if kind not in ('task','habit','lesson','custom') or type(minutes) is not int or not 0<=minutes<=720 or type(star) is not bool:raise HTTPException(422,'Некорректный тип или время дела')
            title=str(item.get('title','')).strip()[:240]
            if kind=='custom':
                if not isinstance(ident,str) or not 1<=len(ident)<=48 or not title:raise HTTPException(422,'Напиши название дела')
            else:
                if type(ident) is not int:raise HTTPException(422,'Некорректный номер записи')
                owned(db,{'task':Task,'habit':Habit,'lesson':Lesson}[kind],ident,user)
            key=(kind,ident)
            if key in keys:raise HTTPException(422,'Дело уже есть в плане')
            keys.add(key);stars+=star
            cleaned.append({'kind':kind,'id':ident,'title':title,'minutes':minutes,'important':star,'done':bool(item.get('done')) if kind=='custom' else False})
        if stars>3:raise HTTPException(422,'Выбери не больше трёх главных дел')
        value={'items':cleaned};put(db,user.id,'day-plan:'+str(day),value);db.commit();return value

    def record_task_completion(db,task,done):
        key='task-completed:'+str(task.id);row=db.scalar(select(Setting).where(Setting.user_id==task.user_id,Setting.key==key))
        if done and not task.done:put(db,task.user_id,key,datetime.now(timezone.utc).isoformat())
        elif not done and row:db.delete(row)

    def report(db,user,end=None):
        end=end or local_day(user);start=end-timedelta(days=6)
        tasks={t.id:t for t in db.scalars(select(Task).where(Task.user_id==user.id)).all()};completed=0
        try:zone=ZoneInfo(user.timezone or 'UTC')
        except Exception:zone=timezone.utc
        for row in db.scalars(select(Setting).where(Setting.user_id==user.id,Setting.key.like('task-completed:%'))).all():
            try:
                task=tasks.get(int(row.key.split(':')[1]));stamp=datetime.fromisoformat(json.loads(row.value)).astimezone(zone).date()
                if task and task.done and start<=stamp<=end:completed+=1
            except (ValueError,TypeError):pass
        habits=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
        checks=db.scalars(select(Check).where(Check.user_id==user.id,Check.day>=start,Check.day<=end)).all();by={}
        for check in checks:by.setdefault(check.habit_id,set()).add(check.day)
        done=total=0;rows=[]
        for h in habits:
            cfg=config(db,user.id,h.id);d=start;buckets={}
            while d<=end:
                if d>=h.created_at and (cfg['mode']=='weekly' or str(d.weekday()) in h.days.split(',')):
                    wk=d-timedelta(days=d.weekday());bucket=buckets.setdefault(wk,[0,0]);bucket[1]+=1;bucket[0]+=d in by.get(h.id,set())
                d+=timedelta(days=1)
            target=sum(min(cfg['weekly_target'],7-max(0,min(6,(h.created_at-wk).days))) if cfg['mode']=='weekly' else v[1] for wk,v in buckets.items())
            hits=sum(min(v[0],cfg['weekly_target']) if cfg['mode']=='weekly' else v[0] for v in buckets.values());done+=hits;total+=target
            rows.append({'name':h.name,'done':hits,'total':target})
        minutes=0
        for session in db.scalars(select(Focus).where(Focus.user_id==user.id,Focus.completed==True)).all():
            stamp=session.started_at.replace(tzinfo=timezone.utc).astimezone(zone).date()
            if start<=stamp<=end:minutes+=session.duration_minutes
        return {'start':str(start),'end':str(end),'tasks_done':completed,'tasks_open':sum(not t.done for t in tasks.values()),'habits_done':done,'habits_total':total,'habits_percent':round(done/total*100) if total else 0,'habits':rows,'focus_minutes':minutes}

    @app.get('/api/weekly-report')
    def weekly_report(user:User=Depends(current_user),db:Session=Depends(dbdep)):return report(db,user)

    @app.get('/api/weekly-report/preferences')
    def weekly_preferences(user:User=Depends(current_user),db:Session=Depends(dbdep)):
        return get(db,user.id,'weekly-report-prefs',{'enabled':False,'time':'19:00','weekday':6})

    @app.put('/api/weekly-report/preferences')
    def save_weekly_preferences(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
        import re
        if type(d.get('enabled')) is not bool or type(d.get('weekday')) is not int or not 0<=d['weekday']<=6 or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',str(d.get('time',''))):raise HTTPException(422,'Проверь день и время отчёта')
        value={k:d[k] for k in ('enabled','time','weekday')};put(db,user.id,'weekly-report-prefs',value);db.commit();return value

    return {'goal_details':goal_details,'initialize_goal_blocks':initialize_goal_blocks,'user_local_day':local_day,'validate_habit_config':validate_config,'habit_details':habit_details,'habit_config':config,'record_task_completion':record_task_completion,'weekly_report_data':report,'feature_get':get,'feature_put':put}
