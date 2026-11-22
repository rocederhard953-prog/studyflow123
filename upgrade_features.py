"""Owned workspace documents and Web Push. Existing database needs no migration."""
import base64
import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

DEFAULT_CHANNELS = {'tasks':'both','habits':'both','goals':'both','general':'both','quiet_start':'22:00','quiet_end':'08:00','private':False}

def quiet(now, start, end):
    value=now.strftime('%H:%M')
    return start!=end and (start<=value<end if start<end else value>=start or value<end)

def valid_subscription(d):
    try:
        u=urlparse(d['endpoint']); host=u.hostname or ''
        allowed=('push.apple.com','fcm.googleapis.com','updates.push.services.mozilla.com','notify.windows.com')
        if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or not any(host==h or host.endswith('.'+h) for h in allowed):return False
        if len(d['endpoint'])>2048:return False
        for name,length in [('auth',16),('p256dh',65)]:
            raw=d['keys'][name]
            if not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',raw):return False
            if len(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))!=length:return False
        return True
    except (KeyError,ValueError,TypeError):return False

def install(c):
    app=c['app']; Setting=c['UserSetting']; User=c['User']; dep=c['dbdep']; auth=c['current_user']; Session=c['SessionLocal']
    def get(db,uid,key,default=None):
        row=db.scalar(select(Setting).where(Setting.user_id==uid,Setting.key==key))
        try:return json.loads(row.value) if row else default
        except ValueError:return default
    def put(db,uid,key,value):
        db.flush()
        row=db.scalar(select(Setting).where(Setting.user_id==uid,Setting.key==key))
        if row is None:row=Setting(user_id=uid,key=key);db.add(row)
        row.value=json.dumps(value,ensure_ascii=False,allow_nan=False)
    def channels(db,uid):return {**DEFAULT_CHANNELS,**get(db,uid,'push:preferences',{})}
    def scheduled(db,user,habit,day):
        periods=get(db,user.id,'habit-pause:'+str(habit.id),{'periods':[]}).get('periods',[])
        return not any(p['start']<=str(day)<=p['end'] for p in periods) and (c['habit_config'](db,user.id,habit.id)['mode']=='weekly' or str(day.weekday()) in habit.days.split(','))
    def ready():return all(os.getenv(x) for x in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT'))

    def trash(db,user,kind,obj):
        import uuid
        data=c['serialize'](obj);children=[];settings=[]
        if kind=='task':
            children=[c['serialize'](a) for a in db.scalars(select(c['Attachment']).where(c['Attachment'].task_id==obj.id,c['Attachment'].user_id==user.id)).all()]
            for key in ('whiteboard:','board-history:','task-steps:','task-completed:','task-chat:'):
                row=db.scalar(select(Setting).where(Setting.user_id==user.id,Setting.key==key+str(obj.id)))
                if row:settings.append([key,json.loads(row.value)]);db.delete(row)
            db.query(c['Attachment']).filter(c['Attachment'].task_id==obj.id).delete(synchronize_session=False)
        if kind=='goal':
            for key in ('goal-blocks:','goal-history:'):
                row=db.scalar(select(Setting).where(Setting.user_id==user.id,Setting.key==key+str(obj.id)))
                if row:settings.append([key,json.loads(row.value)]);db.delete(row)
        ident=uuid.uuid4().hex
        put(db,user.id,'trash:'+ident,{'id':ident,'kind':kind,'record':data,'attachments':children,'settings':settings,'deleted':datetime.now(timezone.utc).isoformat()})
        db.delete(obj);db.commit();return {'ok':True,'trash_id':ident}
    @app.get('/api/trash')
    def list_trash(user=Depends(auth),db=Depends(dep)):
        return [json.loads(row.value) for row in db.scalars(select(Setting).where(Setting.user_id==user.id,Setting.key.like('trash:%'))).all()]
    @app.post('/api/trash/{ident}/restore')
    def restore(ident:str,user=Depends(auth),db=Depends(dep)):
        row=db.scalar(select(Setting).where(Setting.user_id==user.id,Setting.key=='trash:'+ident))
        if row is None:raise HTTPException(404)
        d=json.loads(row.value)
        if d['kind']=='note':
            notes=get(db,user.id,'lesson_notes',{});title=d['record']['title']
            if title in notes:raise HTTPException(409,'Заметка с таким названием уже существует')
            notes[title]=d['record']['note'];put(db,user.id,'lesson_notes',notes);db.delete(row);db.commit();return {'ok':True}
        model={'task':c['Task'],'goal':c['Goal'],'cheat':c['CheatSheet']}[d['kind']]
        values={k:v for k,v in d['record'].items() if k in model.__table__.columns.keys() and k not in ('id','user_id')}
        for column in model.__table__.columns:
            if values.get(column.name) and isinstance(column.type,c['DateTime']):values[column.name]=datetime.fromisoformat(values[column.name])
            elif values.get(column.name) and isinstance(column.type,c['Date']):values[column.name]=c['date'].fromisoformat(values[column.name])
        obj=model(user_id=user.id,**values);db.add(obj);db.flush()
        for photo in d['attachments']:
            db.add(c['Attachment'](user_id=user.id,task_id=obj.id,**{k:photo[k] for k in ('filename','stored_name','mime')}))
        for key,value in d.get('settings',[]):put(db,user.id,key+str(obj.id),value)
        db.delete(row);db.commit();return {'id':obj.id}

    @app.delete('/api/study-notes/{title}')
    def trash_note(title:str,user=Depends(auth),db=Depends(dep)):
        import uuid
        notes=get(db,user.id,'lesson_notes',{})
        if title not in notes:raise HTTPException(404)
        ident=uuid.uuid4().hex;put(db,user.id,'trash:'+ident,{'id':ident,'kind':'note','record':{'title':title,'note':notes.pop(title)},'deleted':datetime.now(timezone.utc).isoformat()})
        put(db,user.id,'lesson_notes',notes);db.commit();return {'ok':True}

    @app.get('/api/whiteboard/history')
    def board_history(task_id:int|None=None,user=Depends(auth),db=Depends(dep)):
        if task_id is not None:c['owned'](db,c['Task'],task_id,user)
        return get(db,user.id,'board-history:'+str(task_id or 'personal'),[])
    @app.post('/api/tasks/{tid}/recognize')
    def recognize(tid:int,user=Depends(auth),db=Depends(dep)):
        task=c['owned'](db,c['Task'],tid,user)
        if not c['assistant'].ai_configured():raise HTTPException(503,'Распознавание требует настроенного сервиса ИИ')
        c['reserve_ai_request'](db,user.id)
        request=c['assistant'].AssistantRequest(message='Распознай текст задания на фотографии. Верни только условие, сохрани формулы. Не решай. Неразборчивые места пометь [неразборчиво].',task_id=tid,include_photos=True)
        c['assistant'].acquire_slot(user.id)
        try:return c['assistant'].ask_ai(request,{'current_page':'tasks'},c['assistant_images'](db,user,task))
        finally:c['assistant'].release_slot(user.id)

    @app.get('/manifest.webmanifest')
    def manifest():return FileResponse(c['BASE']/'static'/'manifest.webmanifest',media_type='application/manifest+json')
    @app.get('/sw.js')
    def worker():return FileResponse(c['BASE']/'static'/'sw.js',media_type='application/javascript',headers={'Service-Worker-Allowed':'/','Cache-Control':'no-cache'})

    @app.get('/api/workspace/{kind}')
    def read_document(kind:str,user=Depends(auth),db=Depends(dep)):
        if kind not in ('exams','templates','topics','preferences'):raise HTTPException(404)
        return get(db,user.id,'upgrade:'+kind,{'revision':0,'items':[]})
    @app.put('/api/workspace/{kind}')
    def save_document(kind:str,d:dict,user=Depends(auth),db=Depends(dep)):
        if kind not in ('exams','templates','topics','preferences'):raise HTTPException(404)
        if not isinstance(d.get('items'),list) or len(d['items'])>500 or len(json.dumps(d))>250000:raise HTTPException(422,'Слишком много записей')
        for item in d['items']:
            if not isinstance(item,dict):raise HTTPException(422,'Некорректная запись')
            if kind!='preferences' and (not isinstance(item.get('title'),str) or not 1<=len(item['title'])<=240):raise HTTPException(422,'Укажи название')
            if kind=='exams':
                try:
                    c['date'].fromisoformat(item['date']);c['date'].fromisoformat(item['start'])
                    if not isinstance(item['topics'],list) or not 1<=len(item['topics'])<=100 or any(not isinstance(t,str) or not 1<=len(t)<=240 for t in item['topics']):raise ValueError()
                    if not isinstance(item['days'],list) or not item['days'] or any(type(day) is not int or not 0<=day<=6 for day in item['days']):raise ValueError()
                    if item['date']<item['start']:raise ValueError()
                except (KeyError,TypeError,ValueError):raise HTTPException(422,'Проверь дату, темы и дни подготовки')
            if kind=='templates':
                try:
                    c['date'].fromisoformat(item['next'])
                    if type(item['repeat']) is not int or not 0<=item['repeat']<=365:raise ValueError()
                except (KeyError,TypeError,ValueError):raise HTTPException(422,'Проверь дату и интервал повторения')
            if kind=='topics' and (type(item.get('level')) is not int or not 0<=item['level']<=3):raise HTTPException(422,'Проверь уровень темы')
        old=get(db,user.id,'upgrade:'+kind,{'revision':0})
        if d.get('revision')!=old['revision']:raise HTTPException(409,'Данные изменились. Открой раздел заново.')
        result={'revision':old['revision']+1,'items':d['items']}
        row=db.scalar(select(Setting).where(Setting.user_id==user.id,Setting.key=='upgrade:'+kind))
        if row:
            count=db.query(Setting).filter(Setting.id==row.id,Setting.value==row.value).update({'value':json.dumps(result,ensure_ascii=False,allow_nan=False)},synchronize_session=False)
            if count!=1:db.rollback();raise HTTPException(409,'Данные изменились. Открой раздел заново.')
        else:put(db,user.id,'upgrade:'+kind,result)
        try:db.commit()
        except c['IntegrityError']:db.rollback();raise HTTPException(409,'Данные изменились. Открой раздел заново.') from None
        return result

    @app.get('/api/tasks/{tid}/steps')
    def task_steps(tid:int,user=Depends(auth),db=Depends(dep)):
        c['owned'](db,c['Task'],tid,user);return get(db,user.id,'task-steps:'+str(tid),[])
    @app.get('/api/tasks/{tid}/chat')
    def task_chat(tid:int,user=Depends(auth),db=Depends(dep)):
        c['owned'](db,c['Task'],tid,user);return get(db,user.id,'task-chat:'+str(tid),[])
    @app.put('/api/tasks/{tid}/steps')
    def save_steps(tid:int,d:dict,user=Depends(auth),db=Depends(dep)):
        c['owned'](db,c['Task'],tid,user);items=d.get('items')
        if not isinstance(items,list) or len(items)>100 or any(not isinstance(i,dict) or not isinstance(i.get('title'),str) or not 1<=len(i['title'])<=240 or type(i.get('done')) is not bool for i in items):raise HTTPException(422,'Проверь шаги задания')
        put(db,user.id,'task-steps:'+str(tid),items);db.commit();return items

    @app.get('/api/habits/{hid}/pause')
    def habit_pause(hid:int,user=Depends(auth),db=Depends(dep)):
        c['owned'](db,c['Habit'],hid,user);return get(db,user.id,'habit-pause:'+str(hid),{'until':None})
    @app.put('/api/habits/{hid}/pause')
    def save_pause(hid:int,d:dict,user=Depends(auth),db=Depends(dep)):
        c['owned'](db,c['Habit'],hid,user);until=d.get('until');day=str(c['user_local_day'](user))
        if until:c['clean_date'](until)
        old=get(db,user.id,'habit-pause:'+str(hid),{'periods':[]});periods=old.get('periods',[])
        if until:
            if until<day:raise HTTPException(422,'Выбери сегодняшнюю или будущую дату')
            periods.append({'start':day,'end':until})
        elif periods:
            for period in periods:
                if period['start']<=day<=period['end']:period['end']=str(c['user_local_day'](user)-timedelta(days=1))
        value={'until':until,'periods':periods[-100:]};put(db,user.id,'habit-pause:'+str(hid),value);db.commit();return value

    @app.get('/api/push/status')
    def push_status(user=Depends(auth),db=Depends(dep)):
        return {'ready':ready(),'public_key':os.getenv('VAPID_PUBLIC_KEY',''),'preferences':channels(db,user.id)}
    @app.put('/api/push/preferences')
    def save_preferences(d:dict,user=Depends(auth),db=Depends(dep)):
        old=channels(db,user.id)
        for key in ('tasks','habits','goals','general'):
            if d.get(key,old[key]) not in ('web','telegram','both','off'):raise HTTPException(422,'Некорректный канал')
            old[key]=d.get(key,old[key])
        for key in ('quiet_start','quiet_end'):
            value=d.get(key,old[key])
            if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise HTTPException(422,'Некорректное время')
            old[key]=value
        old['private']=bool(d.get('private',old['private']));put(db,user.id,'push:preferences',old);db.commit();return old
    @app.post('/api/push/subscribe')
    def subscribe(d:dict,user=Depends(auth),db=Depends(dep)):
        if not ready():raise HTTPException(503,'На сервере ещё не настроены ключи Web Push')
        if not valid_subscription(d):raise HTTPException(422,'Некорректная подписка')
        key='push:sub:'+hashlib.sha256(d['endpoint'].encode()).hexdigest()[:48]
        # One device subscription belongs to the currently authenticated account only.
        db.query(Setting).filter(Setting.key==key,Setting.user_id!=user.id).delete(synchronize_session=False)
        put(db,user.id,key,{'endpoint':d['endpoint'],'keys':d['keys']});db.commit();return {'ok':True}
    @app.post('/api/push/unsubscribe')
    def unsubscribe(d:dict,user=Depends(auth),db=Depends(dep)):
        key='push:sub:'+hashlib.sha256(str(d.get('endpoint','')).encode()).hexdigest()[:48]
        db.query(Setting).filter(Setting.key==key,Setting.user_id==user.id).delete(synchronize_session=False);db.commit();return {'ok':True}
    @app.get('/api/push/inbox')
    def inbox(user=Depends(auth),db=Depends(dep)):return get(db,user.id,'push:inbox',[])
    @app.post('/api/push/read')
    def mark_read(user=Depends(auth),db=Depends(dep)):
        items=get(db,user.id,'push:inbox',[])
        for item in items:item['read']=True
        put(db,user.id,'push:inbox',items);db.commit();return {'ok':True}

    def send(db,user,title,body,url,tag,test=False):
        prefs=channels(db,user.id);items=get(db,user.id,'push:inbox',[])
        previous=next((i for i in items if i['id']==tag),None)
        if previous and previous.get('delivered') and not test:return 0
        item={'id':tag,'title':title,'body':body,'url':url,'read':False,'created':datetime.now(timezone.utc).isoformat()}
        items=([item]+[i for i in items if i['id']!=tag])[:100];put(db,user.id,'push:inbox',items)
        if not ready():return 0
        from pywebpush import webpush, WebPushException
        count=0
        for row in db.scalars(select(Setting).where(Setting.user_id==user.id,Setting.key.like('push:sub:%'))).all():
            try:
                webpush(subscription_info=json.loads(row.value),data=json.dumps({'title':'My-Study' if prefs['private'] else title,'body':'Новое напоминание' if prefs['private'] else body,'url':url,'tag':tag,'badge':sum(not i['read'] for i in items)},ensure_ascii=False),vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],vapid_claims={'sub':os.environ['VAPID_SUBJECT']},ttl=3600,timeout=8)
                count+=1
            except WebPushException as error:
                if error.response is not None and error.response.status_code in (404,410):db.delete(row)
                else:logging.warning('Web Push delivery failed (%s)',type(error).__name__)
            except Exception as error:logging.warning('Web Push failed (%s)',type(error).__name__)
        item['delivered']=bool(count);put(db,user.id,'push:inbox',items);return count
    @app.post('/api/push/test')
    def test_push(user=Depends(auth),db=Depends(dep)):
        if not ready():raise HTTPException(503,'Настрой ключи Web Push на хостинге')
        count=send(db,user,'My-Study','Уведомления подключены','/','test:'+str(datetime.now().timestamp()),True);db.commit()
        if not count:raise HTTPException(409,'Нет доступной подписки или сервис доставки не ответил')
        return {'sent':count}

    def tick():
        with Session() as db:
            now=datetime.now(timezone.utc)
            for user in db.scalars(select(User)).all():
                try:local=now.astimezone(ZoneInfo(user.timezone or 'UTC'))
                except Exception:local=now
                prefs=channels(db,user.id)
                templates=get(db,user.id,'upgrade:templates',{'revision':0,'items':[]});changed=False
                for template in templates['items']:
                    try:
                        repeat=int(template.get('repeat',0));next_day=c['date'].fromisoformat(template.get('next',''))
                        if not 1<=repeat<=365 or next_day>local.date():continue
                        title=str(template.get('title','')).strip()[:240]
                        if not title:continue
                        db.add(c['Task'](user_id=user.id,title=title,subject=str(template.get('subject',''))[:120],description=str(template.get('description',''))[:5000],due=local.date(),priority='normal'))
                        while next_day<=local.date():next_day+=timedelta(days=repeat)
                        template['next']=str(next_day);changed=True
                    except (TypeError,ValueError):continue
                if changed:templates['revision']+=1;put(db,user.id,'upgrade:templates',templates)
                if quiet(local,prefs['quiet_start'],prefs['quiet_end']):continue
                if local.strftime('%H:%M')=='09:00' and prefs['goals']!='off':
                    goals=db.scalars(select(c['Goal']).where(c['Goal'].user_id==user.id,c['Goal'].done==False)).all()
                    if goals:
                        if prefs['goals'] in ('web','both'):send(db,user,'Следующий шаг к цели',goals[0].title,'/orbit/rhythm/goals','goals:'+str(local.date()))
                        if prefs['goals'] in ('telegram','both') and not get(db,user.id,'goal-notify:'+str(local.date()),False):
                            link=db.scalar(select(c['TelegramLink']).where(c['TelegramLink'].user_id==user.id))
                            if link:
                                try:
                                    from bot import notify
                                    notify(link.chat_id,'Следующий шаг к цели\n\n'+goals[0].title)
                                    put(db,user.id,'goal-notify:'+str(local.date()),True)
                                except Exception:logging.warning('Goal Telegram reminder failed')
                for reminder in db.scalars(select(c['Reminder']).where(c['Reminder'].user_id==user.id,c['Reminder'].enabled==True)).all():
                    kind='tasks' if reminder.kind in ('tasks','homework_eve') else 'habits' if reminder.kind=='habits' else 'general'
                    if prefs[kind] not in ('web','both') or str(local.weekday()) not in reminder.days.split(','):continue
                    timing=db.get(c['ReminderTiming'],reminder.id)
                    if timing and timing.mode!='fixed':
                        from bot import event_targets
                        for event_time,content,event_key in event_targets(db,user,local,timing.event_source,timing.event_id):
                            if timing.mode=='eve':
                                hour,minute=map(int,reminder.send_time.split(':'))
                                target=datetime.combine(event_time.date()-timedelta(days=1),c['datetime'].min.time(),tzinfo=local.tzinfo).replace(hour=hour,minute=minute)
                            else:target=event_time-timedelta(minutes=timing.minutes_before)
                            if 0<=(local-target).total_seconds()<60:
                                send(db,user,reminder.title,content[:900],'/orbit/rhythm/calendar' if timing.event_source=='calendar' else '/orbit/study/schedule',f'relative:{reminder.id}:{event_key}:{target.isoformat()}')
                        continue
                    if local.strftime('%H:%M')!=reminder.send_time:continue
                    body=reminder.title;url='/orbit/preferences/reminders'
                    if kind=='tasks':
                        target=local.date()+timedelta(days=1) if reminder.kind=='homework_eve' else local.date()
                        tasks=db.scalars(select(c['Task']).where(c['Task'].user_id==user.id,c['Task'].done==False,c['Task'].due<=target)).all()
                        body='; '.join(f'{t.subject or "ДЗ"} · {t.due} · {t.title}' for t in tasks) or 'Все задания выполнены'
                        url='/orbit/study/tasks'
                        if tasks:
                            for task in tasks:send(db,user,reminder.title,f'{task.subject or "ДЗ"} · {task.due} · {task.title}',url+'?task='+str(task.id),f'reminder:{reminder.id}:{local.date()}:{task.id}')
                            continue
                    elif kind=='habits':
                        habits=db.scalars(select(c['Habit']).where(c['Habit'].user_id==user.id)).all()
                        checks={x.habit_id for x in db.scalars(select(c['HabitCheck']).where(c['HabitCheck'].user_id==user.id,c['HabitCheck'].day==local.date())).all()}
                        pending=[h.name for h in habits if scheduled(db,user,h,local.date()) and h.id not in checks]
                        body=' · '.join(pending) or 'Все запланированные привычки выполнены';url='/orbit/rhythm/habits'
                    send(db,user,reminder.title,body[:900],url,f'reminder:{reminder.id}:{local.date()}')
                db.commit()
            db.commit()
    stop=threading.Event()
    def loop():
        while not stop.is_set():
            try:tick()
            except Exception:logging.exception('Web Push scheduler failed')
            stop.wait(20)
    @app.on_event('startup')
    def start_push():
        stop.clear();threading.Thread(target=loop,name='studyflow-webpush',daemon=True).start()
    @app.on_event('shutdown')
    def stop_push():stop.set()
    return {'upgrade_get':get,'upgrade_put':put,'upgrade_channels':channels,'upgrade_trash':trash,'upgrade_tick':tick,'upgrade_habit_scheduled':scheduled}
