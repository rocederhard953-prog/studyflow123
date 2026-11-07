"""StudyFlow Telegram companion. Runs independently or as a daemon thread."""
import os, time, json, urllib.request, urllib.parse, datetime, threading, traceback
from sqlalchemy import select
from app import (SessionLocal, User, TelegramCode, TelegramLink, NotificationSetting,
                 Habit, HabitCheck, Task, Lesson)

TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
API=f'https://api.telegram.org/bot{TOKEN}/'
STOP=threading.Event()

def tg(method, params=None, timeout=40):
    payload=urllib.parse.urlencode(params or {}).encode()
    req=urllib.request.Request(API+method,data=payload)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        data=json.loads(r.read().decode())
    if not data.get('ok'): raise RuntimeError(data.get('description','Telegram API error'))
    return data.get('result')

def send(chat,text):
    return tg('sendMessage',{'chat_id':chat,'text':text,'disable_web_page_preview':'true'},timeout=20)

def linked_user(db,chat):
    link=db.scalar(select(TelegramLink).where(TelegramLink.chat_id==str(chat)))
    return db.get(User,link.user_id) if link else None

def handle(msg):
    chat=str(msg.get('chat',{}).get('id','')); text=(msg.get('text') or '').strip()
    if not chat or not text:return
    with SessionLocal() as db:
        if text.startswith('/link '):
            code=text.split(maxsplit=1)[1].strip().upper()
            row=db.scalar(select(TelegramCode).where(TelegramCode.code==code,TelegramCode.expires_at>datetime.datetime.utcnow()))
            if not row: send(chat,'Код недействителен или истёк. Создай новый в StudyFlow → Telegram.'); return
            old=db.scalar(select(TelegramLink).where(TelegramLink.user_id==row.user_id))
            bychat=db.scalar(select(TelegramLink).where(TelegramLink.chat_id==chat))
            if bychat and bychat.user_id!=row.user_id:
                send(chat,'Этот Telegram уже привязан к другому аккаунту StudyFlow. Сначала отвяжи его в настройках того аккаунта.'); return
            if old: old.chat_id=chat
            elif not bychat: db.add(TelegramLink(user_id=row.user_id,chat_id=chat))
            db.delete(row); db.commit(); send(chat,'✅ Аккаунт StudyFlow привязан! Напиши /help, чтобы увидеть команды.'); return
        user=linked_user(db,chat)
        if text in ('/start','/help'):
            send(chat,'StudyFlow 2.0 📘\n/link КОД — привязать аккаунт\n/today — обзор дня\n/habits — привычки\n/done ID — отметить привычку\n/undo ID — снять отметку\n/homework — домашние задания\n/task ID — выполнить задание\n/schedule — уроки сегодня\n/tomorrow — уроки завтра'); return
        if not user:
            send(chat,'🔒 Сначала привяжи аккаунт: открой StudyFlow → Telegram → Получить код, затем отправь /link КОД.'); return
        today=datetime.date.today(); wd=(today.weekday())
        if text=='/today':
            habits=db.scalars(select(Habit).where(Habit.user_id==user.id)).all(); tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False)).all()
            checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            due=[x for x in tasks if x.due==today]
            send(chat,f'📅 {today.isoformat()}\nПривычек: {len(checks)}/{len([h for h in habits if str(wd) in h.days.split(",")])}\nНевыполненных заданий: {len(tasks)}\nНа сегодня: {len(due)}'); return
        if text=='/habits':
            hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all(); checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            hs=[h for h in hs if str(wd) in h.days.split(',')]
            send(chat,'Привычки на сегодня:\n'+'\n'.join(f"{'✅' if h.id in checks else '⬜'} {h.id}. {h.name}" for h in hs) if hs else 'Сегодня привычек нет.'); return
        if text.startswith(('/done ','/undo ')):
            try: hid=int(text.split()[1])
            except: send(chat,'Укажи ID привычки, например /done 3'); return
            h=db.scalar(select(Habit).where(Habit.id==hid,Habit.user_id==user.id))
            if not h: send(chat,'Привычка не найдена.'); return
            c=db.scalar(select(HabitCheck).where(HabitCheck.habit_id==hid,HabitCheck.day==today, HabitCheck.user_id==user.id))
            if text.startswith('/done ') and not c: db.add(HabitCheck(user_id=user.id,habit_id=hid,day=today))
            if text.startswith('/undo ') and c: db.delete(c)
            db.commit(); send(chat,'Готово! Изменения сохранены в StudyFlow.'); return
        if text=='/homework':
            tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False).order_by(Task.due,Task.id).limit(20)).all()
            send(chat,'Домашние задания:\n'+'\n'.join(f"{t.id}. {t.subject+' — ' if t.subject else ''}{t.title} (до {t.due or 'без срока'})" for t in tasks) if tasks else 'Всё выполнено!'); return
        if text.startswith('/task '):
            try: tid=int(text.split()[1])
            except: send(chat,'Укажи ID задания.'); return
            task=db.scalar(select(Task).where(Task.id==tid,Task.user_id==user.id))
            if not task: send(chat,'Задание не найдено.'); return
            task.done=True; db.commit(); send(chat,'✅ Задание отмечено выполненным.'); return
        if text in ('/schedule','/tomorrow'):
            day=today if text=='/schedule' else today+datetime.timedelta(days=1); w=day.weekday()
            lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==w).order_by(Lesson.period)).all()
            label='сегодня' if text=='/schedule' else 'завтра'
            send(chat,f'Уроки {label} ({day.isoformat()}):\n'+'\n'.join(f'{x.period}. {x.subject} {x.start}–{x.finish} {x.room}' for x in lessons) if lessons else f'Уроков {label} нет.'); return
        send(chat,'Неизвестная команда. Напиши /help.')

def in_quiet(now,start,end):
    cur=now.strftime('%H:%M')
    if start==end: return False
    return (start<=cur<end) if start<end else (cur>=start or cur<end)

def notification_tick():
    now=datetime.datetime.utcnow()
    with SessionLocal() as db:
        settings=db.scalars(select(NotificationSetting).where(NotificationSetting.enabled==True)).all()
        for setting in settings:
            link=db.scalar(select(TelegramLink).where(TelegramLink.user_id==setting.user_id))
            if not link: continue
            # User timezone is handled by the website's selected timezone; UTC fallback avoids host-local assumptions.
            user=db.get(User,setting.user_id)
            try:
                from zoneinfo import ZoneInfo
                local=datetime.datetime.now(ZoneInfo(user.timezone or 'UTC'))
            except Exception: local=datetime.datetime.now(datetime.timezone.utc)
            if in_quiet(local,setting.quiet_start,setting.quiet_end): continue
            if setting.last_sent:
                last_local=setting.last_sent.replace(tzinfo=datetime.timezone.utc).astimezone(local.tzinfo)
                if last_local.date()==local.date() and (now-setting.last_sent).total_seconds()<setting.interval_minutes*60: continue
                if last_local.date()!=local.date() and local.strftime('%H:%M')<setting.send_time: continue
            elif local.strftime('%H:%M')<setting.send_time: continue
            today=local.date(); habits=db.scalars(select(Habit).where(Habit.user_id==user.id)).all(); checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            eligible=[h for h in habits if str(today.weekday()) in h.days.split(',')]; pending=[h for h in eligible if h.id not in checks]
            tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False).order_by(Task.due).limit(5)).all()
            if not pending and not tasks: setting.last_sent=now; db.commit(); continue
            lines=['🌌 StudyFlow — небольшой чек-ин']
            if pending: lines.append('Привычки, которые ещё можно выполнить:\n'+'\n'.join('• '+h.name for h in pending[:6]))
            if tasks: lines.append('Открытые задания: '+str(len(db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False)).all())))
            lines.append('Открой сайт, чтобы отметить прогресс.');
            try: send(link.chat_id,'\n\n'.join(lines)); setting.last_sent=now; db.commit()
            except Exception as e: print('Notification error:',repr(e),flush=True)

def main():
    if not TOKEN: print('TELEGRAM_BOT_TOKEN is missing; Telegram bot disabled.',flush=True); return
    print('StudyFlow Telegram bot running',flush=True); offset=0; last_tick=0
    while not STOP.is_set():
        try:
            if time.time()-last_tick>=30:
                notification_tick(); last_tick=time.time()
            updates=tg('getUpdates',{'offset':offset,'timeout':15,'allowed_updates':json.dumps(['message'])},timeout=25)
            for update in updates:
                offset=update['update_id']+1
                if 'message' in update:
                    try: handle(update['message'])
                    except Exception as e: print('Telegram message error:',repr(e),flush=True)
        except Exception as e:
            print('Telegram polling error:',repr(e),flush=True); time.sleep(5)

if __name__=='__main__': main()
