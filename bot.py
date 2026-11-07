"""StudyFlow Telegram companion with inline buttons and scheduled reminders."""
import os, time, json, urllib.request, urllib.parse, datetime, threading, traceback
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app import (SessionLocal, User, TelegramCode, TelegramLink, NotificationSetting,
                 Reminder, Habit, HabitCheck, Task, Lesson)

TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
API=f'https://api.telegram.org/bot{TOKEN}/'
SITE='https://my-study.bothost.tech'
STOP=threading.Event()

def tg(method, params=None, timeout=35):
    req=urllib.request.Request(API+method,data=urllib.parse.urlencode(params or {}).encode())
    with urllib.request.urlopen(req,timeout=timeout) as r: data=json.loads(r.read().decode())
    if not data.get('ok'): raise RuntimeError(data.get('description','Telegram API error'))
    return data.get('result')

def keyboard(rows=None):
    rows=list(rows or [])
    rows.append([{'text':'🌐 Открыть StudyFlow','url':SITE}])
    return json.dumps({'inline_keyboard':rows},ensure_ascii=False)

def send(chat,text,rows=None,message_id=None):
    params={'chat_id':chat,'text':text+'\n\n🌐 '+SITE,'disable_web_page_preview':'true','reply_markup':keyboard(rows)}
    if message_id:
        params['message_id']=message_id
        try: return tg('editMessageText',params,timeout=20)
        except Exception: pass
    return tg('sendMessage',params,timeout=20)

def linked_user(db,chat):
    link=db.scalar(select(TelegramLink).where(TelegramLink.chat_id==str(chat)))
    return db.get(User,link.user_id) if link else None

def main_menu():
    return [[{'text':'📅 Мой день','callback_data':'today'},{'text':'📚 Домашка','callback_data':'homework'}],
            [{'text':'✅ Привычки','callback_data':'habits'},{'text':'🗓 Расписание','callback_data':'schedule'}],
            [{'text':'🔔 Напоминания','callback_data':'reminders'},{'text':'📆 Завтра','callback_data':'tomorrow'}]]

def back(): return [[{'text':'⬅️ Главное меню','callback_data':'menu'}]]

def display(chat,section='menu',message_id=None):
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:
            return send(chat,'🔒 Привяжи аккаунт: на сайте открой Telegram → Получить код → Перейти в Telegram.',main_menu(),message_id)
        try: today=datetime.datetime.now(ZoneInfo(user.timezone or 'UTC')).date()
        except Exception: today=datetime.datetime.now(datetime.timezone.utc).date()
        wd=today.weekday()
        if section=='menu':
            return send(chat,'✨ StudyFlow — твой учебный помощник\n\nВыбери раздел кнопками ниже.',main_menu(),message_id)
        if section=='today':
            hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
            checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            eligible=[h for h in hs if str(wd) in h.days.split(',')]
            tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False)).all()
            return send(chat,f'📅 Сегодня, {today:%d.%m.%Y}\n\nПривычки: {len([h for h in eligible if h.id in checks])}/{len(eligible)}\nНевыполненных заданий: {len(tasks)}\nНа сегодня: {len([t for t in tasks if t.due==today])}',back(),message_id)
        if section=='habits':
            hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
            hs=[h for h in hs if str(wd) in h.days.split(',')]
            checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            rows=[[{'text':('↩️ ' if h.id in checks else '☑️ ')+h.name[:40], 'callback_data':f'habit:{h.id}'}] for h in hs[:20]]+back()
            return send(chat,'✅ Привычки на сегодня\n\nНажми на привычку, чтобы изменить отметку.' if hs else 'Сегодня привычек нет.',rows,message_id)
        if section=='homework':
            tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False).order_by(Task.due,Task.id).limit(15)).all()
            rows=[[{'text':'☑️ '+t.title[:45],'callback_data':f'task:{t.id}'}] for t in tasks]+back()
            return send(chat,'📚 Невыполненные задания\n\n'+('\n'.join(f'• {t.title} — {t.due or "без срока"}' for t in tasks) if tasks else 'Всё выполнено!'),rows,message_id)
        if section in ('schedule','tomorrow'):
            day=today+(datetime.timedelta(days=1) if section=='tomorrow' else datetime.timedelta())
            lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==day.weekday()).order_by(Lesson.period)).all()
            lines='\n'.join(f'{x.period}. {x.subject} {x.start}–{x.finish} {x.room}' for x in lessons)
            return send(chat,f'🗓 Расписание на {day:%d.%m.%Y}\n\n'+(lines or 'Уроков нет.'),back(),message_id)
        if section=='reminders':
            items=db.scalars(select(Reminder).where(Reminder.user_id==user.id).order_by(Reminder.send_time)).all()
            text='🔔 Твои напоминания\n\n'+('\n'.join(f'{"🟢" if x.enabled else "⚪"} {x.send_time} — {x.title}' for x in items) if items else 'Напоминаний пока нет.')+'\n\nНастроить время и дни можно на сайте в разделе Telegram.'
            return send(chat,text,back(),message_id)
        return display(chat,'menu',message_id)

def handle(msg):
    chat=str(msg.get('chat',{}).get('id','')); text=(msg.get('text') or '').strip()
    if not chat or not text:return
    parts=text.split(maxsplit=1); cmd=parts[0].split('@',1)[0]; payload=parts[1].strip() if len(parts)>1 else ''
    link_code=payload if cmd=='/link' else (payload[5:] if cmd=='/start' and payload.lower().startswith('link_') else '')
    if link_code:
        with SessionLocal() as db:
            row=db.scalar(select(TelegramCode).where(TelegramCode.code==link_code.upper(),TelegramCode.expires_at>datetime.datetime.utcnow()))
            if not row:return send(chat,'Код недействителен или истёк. Получи новый код на сайте.')
            old=db.scalar(select(TelegramLink).where(TelegramLink.user_id==row.user_id))
            bychat=db.scalar(select(TelegramLink).where(TelegramLink.chat_id==chat))
            if bychat and bychat.user_id!=row.user_id:return send(chat,'Этот Telegram уже привязан к другому аккаунту.')
            if old: old.chat_id=chat
            elif not bychat: db.add(TelegramLink(user_id=row.user_id,chat_id=chat))
            db.delete(row);db.commit()
        return send(chat,'✅ Аккаунт успешно привязан! Выбирай нужный раздел.',main_menu())
    aliases={'/today':'today','/habits':'habits','/homework':'homework','/schedule':'schedule','/tomorrow':'tomorrow'}
    display(chat,aliases.get(cmd,'menu'))

def callback(q):
    chat=str(q.get('message',{}).get('chat',{}).get('id',''))
    mid=q.get('message',{}).get('message_id'); action=q.get('data','')
    try: tg('answerCallbackQuery',{'callback_query_id':q['id']},timeout=10)
    except Exception: pass
    if not chat:return
    if action.startswith(('habit:','task:')):
        try: ident=int(action.split(':',1)[1])
        except ValueError:return
        with SessionLocal() as db:
            user=linked_user(db,chat)
            if not user:return display(chat,'menu',mid)
            try: today=datetime.datetime.now(ZoneInfo(user.timezone or 'UTC')).date()
            except Exception: today=datetime.datetime.now(datetime.timezone.utc).date()
            if action.startswith('habit:'):
                h=db.scalar(select(Habit).where(Habit.id==ident,Habit.user_id==user.id))
                if h:
                    check=db.scalar(select(HabitCheck).where(HabitCheck.habit_id==ident,HabitCheck.user_id==user.id,HabitCheck.day==today))
                    if check: db.delete(check)
                    else: db.add(HabitCheck(user_id=user.id,habit_id=ident,day=today))
                section='habits'
            else:
                t=db.scalar(select(Task).where(Task.id==ident,Task.user_id==user.id))
                if t:t.done=True
                section='homework'
            db.commit()
        return display(chat,section,mid)
    display(chat,action if action in ('menu','today','habits','homework','schedule','tomorrow','reminders') else 'menu',mid)

def notification_tick():
    utc=datetime.datetime.now(datetime.timezone.utc)
    with SessionLocal() as db:
        reminders=db.scalars(select(Reminder).where(Reminder.enabled==True)).all()
        for reminder in reminders:
            try:
                user=db.get(User,reminder.user_id)
                link=db.scalar(select(TelegramLink).where(TelegramLink.user_id==reminder.user_id))
                setting=db.scalar(select(NotificationSetting).where(NotificationSetting.user_id==reminder.user_id))
                if not user or not link or (setting and not setting.enabled):continue
                try: local=utc.astimezone(ZoneInfo(user.timezone or 'UTC'))
                except Exception: local=utc
                if str(local.weekday()) not in reminder.days.split(','):continue
                if local.strftime('%H:%M')!=reminder.send_time:continue
                if setting and setting.quiet_start and setting.quiet_end:
                    cur=local.strftime('%H:%M'); a=setting.quiet_start;b=setting.quiet_end
                    if a!=b and ((a<=cur<b) if a<b else (cur>=a or cur<b)):continue
                if reminder.last_sent:
                    last=reminder.last_sent.replace(tzinfo=datetime.timezone.utc).astimezone(local.tzinfo)
                    if last.date()==local.date():continue
                content=reminder.title
                if reminder.kind=='tasks':
                    tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False).order_by(Task.due).limit(5)).all()
                    content+='\n\n'+('\n'.join('• '+t.title for t in tasks) if tasks else 'Все задания выполнены!')
                elif reminder.kind=='habits':
                    hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
                    checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==local.date())).all()}
                    pending=[h for h in hs if str(local.weekday()) in h.days.split(',') and h.id not in checks]
                    content+='\n\n'+('\n'.join('• '+h.name for h in pending[:6]) if pending else 'Все привычки выполнены!')
                elif reminder.kind=='schedule':
                    lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==local.weekday()).order_by(Lesson.period)).all()
                    content+='\n\n'+('\n'.join(f'{x.period}. {x.subject}' for x in lessons) if lessons else 'Сегодня уроков нет.')
                send(link.chat_id,'🔔 '+content,[[{'text':'📅 Мой день','callback_data':'today'}]])
                reminder.last_sent=utc.replace(tzinfo=None);db.commit()
            except Exception as exc:
                db.rollback();print('Reminder error:',repr(exc),flush=True)

def main():
    if not TOKEN:print('TELEGRAM_BOT_TOKEN is missing',flush=True);return
    print('StudyFlow Telegram bot running',flush=True)
    offset=0;last_tick=0
    try: tg('deleteWebhook',{'drop_pending_updates':'false'},timeout=10)
    except Exception as exc:print('Webhook warning:',repr(exc),flush=True)
    while not STOP.is_set():
        try:
            if time.monotonic()-last_tick>=20:
                notification_tick();last_tick=time.monotonic()
            updates=tg('getUpdates',{'offset':offset,'timeout':10,'allowed_updates':json.dumps(['message','callback_query'])},timeout=20)
            for update in updates:
                offset=update['update_id']+1
                try:
                    if 'message' in update:handle(update['message'])
                    elif 'callback_query' in update:callback(update['callback_query'])
                except Exception:traceback.print_exc()
        except Exception:traceback.print_exc();time.sleep(5)

if __name__=='__main__':main()
