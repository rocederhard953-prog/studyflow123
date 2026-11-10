"""StudyFlow Telegram companion with inline buttons and scheduled reminders."""
import os, time, json, urllib.request, urllib.parse, datetime, threading, traceback, uuid
from zoneinfo import ZoneInfo
import re
import hmac
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from app import (SessionLocal, User, TelegramCode, TelegramLink, NotificationSetting,
                 Reminder, ReminderTiming, CalendarEvent, UserSetting, Habit, HabitCheck, Task, Lesson, Attachment, UPLOAD_DIR, MAX_UPLOAD, ensure_default_reminders)

TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
API=f'https://api.telegram.org/bot{TOKEN}/'
SITE=os.getenv('SITE_URL','https://my-study.bothost.tech').rstrip('/')
ADMIN_ID=os.getenv('ADMIN_TELEGRAM_ID','').strip()
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','').strip()
STOP=threading.Event()

# Conversation state per chat; in-progress drafts are not saved as tasks.
DRAFTS={}
DRAFT_LOCK=threading.Lock()

def tg(method, params=None, timeout=35):
    req=urllib.request.Request(API+method,data=urllib.parse.urlencode(params or {}).encode())
    with urllib.request.urlopen(req,timeout=timeout) as r: data=json.loads(r.read().decode())
    if not data.get('ok'): raise RuntimeError(data.get('description','Telegram API error'))
    return data.get('result')

def keyboard(rows=None):
    rows=list(rows or [])
    rows.append([{'text':'🌐 Открыть My-Study','url':SITE}])
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
            [{'text':'🔔 Напоминания','callback_data':'reminders'}]]

def back(): return [[{'text':'⬅️ Главное меню','callback_data':'menu'}]]

def send_section(chat,section,text,rows=None,message_id=None):
    image_name={'menu':'my-study','today':'today','habits':'habits','reminders':'reminders','homework':'homework','schedule':'schedule'}.get(section)
    image_path=os.path.join(os.path.dirname(__file__),'static','bot_images',(image_name or '')+'.jpg')
    caption=text+'\n\n🌐 '+SITE
    if not image_name or not os.path.isfile(image_path) or len(caption)>1024:
        return send(chat,text,rows,message_id)
    boundary='----mystudy'+uuid.uuid4().hex
    parts=[]
    def part(name,value,filename=None):
        header=f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
        if filename:header+=f'; filename="{filename}"\r\nContent-Type: image/jpeg'
        parts.append((header+'\r\n\r\n').encode()+value+b'\r\n')
    part('chat_id',str(chat).encode())
    part('caption',caption.encode())
    part('reply_markup',keyboard(rows).encode())
    with open(image_path,'rb') as f:part('photo',f.read(),image_name+'.jpg')
    body=b''.join(parts)+f'--{boundary}--\r\n'.encode()
    req=urllib.request.Request(API+'sendPhoto',data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            data=json.loads(response.read().decode())
        if not data.get('ok'):raise RuntimeError(data.get('description','sendPhoto failed'))
        return data.get('result')
    except Exception as exc:
        print('Section photo failed:',repr(exc),flush=True)
        return send(chat,text,rows,message_id)

def admin_authorized(chat):
    if not ADMIN_ID or str(chat)!=ADMIN_ID:return False
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return False
        row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='admin_verified_chat'))
        return bool(row and row.value==str(chat))

def admin_login(chat):
    if not ADMIN_ID or str(chat)!=ADMIN_ID:return send(chat,'Доступ запрещён.')
    if admin_authorized(chat):return admin_panel(chat)
    if not ADMIN_PASSWORD:return send(chat,'Для входа администратор должен задать ADMIN_PASSWORD на сервере.')
    with DRAFT_LOCK:DRAFTS[chat]={'step':'admin_password'}
    return send(chat,'🔐 Введи пароль администратора одним сообщением. После проверки сообщение будет удалено, если Telegram разрешит.')

def verify_admin_password(chat,password,message_id=None):
    if message_id:
        try:tg('deleteMessage',{'chat_id':chat,'message_id':message_id},timeout=10)
        except Exception:pass
    if not ADMIN_ID or str(chat)!=ADMIN_ID or not ADMIN_PASSWORD or not hmac.compare_digest(password,ADMIN_PASSWORD):
        return send(chat,'Неверный пароль. Для повторной попытки отправь /admin.')
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return send(chat,'Сначала привяжи Telegram к аккаунту My-Study.')
        row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='admin_verified_chat'))
        if row:row.value=str(chat)
        else:db.add(UserSetting(user_id=user.id,key='admin_verified_chat',value=str(chat)))
        db.commit()
    cancel_draft(chat)
    return admin_panel(chat)

def display(chat,section='menu',message_id=None):
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:
            return send_section(chat,section,'🔒 Привяжи аккаунт: на сайте открой Telegram → Получить код → Перейти в Telegram.',main_menu(),message_id)
        try: today=datetime.datetime.now(ZoneInfo(user.timezone or 'UTC')).date()
        except Exception: today=datetime.datetime.now(datetime.timezone.utc).date()
        wd=today.weekday()
        if section=='menu':
            if admin_authorized(chat):
                return send_section(chat,section,'🛡 My-Study — меню администратора',main_menu()+[[{'text':'🛡 Админ-панель','callback_data':'admin'}]],message_id)
            return send_section(chat,section,'✨ My-Study — твой учебный помощник\n\nВыбери раздел кнопками ниже.',main_menu(),message_id)
        if section=='today':
            hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
            checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            eligible=[h for h in hs if str(wd) in h.days.split(',')]
            tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False)).all()
            return send_section(chat,section,f'📅 Сегодня, {today:%d.%m.%Y}\n\nПривычки: {len([h for h in eligible if h.id in checks])}/{len(eligible)}\nНевыполненных заданий: {len(tasks)}\nНа сегодня: {len([t for t in tasks if t.due==today])}',back(),message_id)
        if section=='habits':
            hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
            hs=[h for h in hs if str(wd) in h.days.split(',')]
            checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            rows=[[{'text':'➕ Добавить привычку','callback_data':'addhabit'}]]+[[{'text':('↩️ ' if h.id in checks else '☑️ ')+h.name[:40], 'callback_data':f'habit:{h.id}'}] for h in hs[:20]]+back()
            return send_section(chat,section,'✅ Привычки на сегодня\n\nНажми на привычку, чтобы изменить отметку.' if hs else 'Сегодня привычек нет.',rows,message_id)
        if section=='homework':
            tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False).order_by(Task.due,Task.id).limit(15)).all()
            rows=[[{'text':'➕ Добавить ДЗ','callback_data':'addhw'}]]+[[{'text':'☑️ '+t.title[:45],'callback_data':f'task:{t.id}'}] for t in tasks]+back()
            return send_section(chat,section,'📚 Невыполненные задания\n\n'+('\n'.join(f'• {t.title} — {t.due or "без срока"}' for t in tasks) if tasks else 'Всё выполнено!'),rows,message_id)
        if section in ('schedule','tomorrow'):
            day=today+(datetime.timedelta(days=1) if section=='tomorrow' else datetime.timedelta())
            lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==day.weekday()).order_by(Lesson.period)).all()
            lines='\n'.join(f'{x.period}. {x.subject} {x.start}–{x.finish} {x.room}' for x in lessons)
            return send_section(chat,section,f'🗓 Расписание на {day:%d.%m.%Y}\n\n'+(lines or 'Уроков нет.'),back(),message_id)
        if section=='reminders':
            items=db.scalars(select(Reminder).where(Reminder.user_id==user.id).order_by(Reminder.send_time)).all()
            text='🔔 Твои напоминания\n\n'+('\n'.join(f'{"🟢" if x.enabled else "⚪"} {x.send_time} — {x.title}' for x in items) if items else 'Напоминаний пока нет.')+'\n\nНастроить время и дни можно на сайте в разделе Telegram.'
            return send_section(chat,section,text,back(),message_id)
        return display(chat,'menu',message_id)

def local_today(user):
    try: return datetime.datetime.now(ZoneInfo(user.timezone or 'UTC')).date()
    except Exception: return datetime.datetime.now(datetime.timezone.utc).date()

def cancel_draft(chat):
    with DRAFT_LOCK: DRAFTS.pop(chat,None)

def draft_keyboard():
    return [[{'text':'❌ Отмена','callback_data':'hwcancel'}]]

def start_homework(chat,mid=None):
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return send(chat,'🔒 Сначала привяжи аккаунт My-Study.',main_menu(),mid)
        subjects=list(dict.fromkeys(x.subject.strip() for x in db.scalars(select(Lesson).where(Lesson.user_id==user.id)).all() if x.subject and x.subject.strip()))
    if not subjects:return send(chat,'Сначала добавь уроки в расписание на сайте, чтобы выбрать предмет.',back(),mid)
    with DRAFT_LOCK:DRAFTS[chat]={'step':'subject'}
    rows=[[{'text':subject[:45],'callback_data':'hwsub:'+str(i)}] for i,subject in enumerate(subjects[:20])]
    # Save choices to avoid trusting callback-supplied subject names.
    with DRAFT_LOCK:DRAFTS[chat]['subjects']=subjects[:20]
    
    rows+=draft_keyboard()
    return send(chat,'📚 Добавляем домашнее задание\n\n1/5 — Выбери предмет из расписания кнопкой.',rows,mid)

def homework_subject(chat,subject):
    subject=subject.strip()
    if not subject or len(subject)>120:return send(chat,'Предмет должен содержать от 1 до 120 символов. Попробуй ещё раз.',draft_keyboard())
    with DRAFT_LOCK:
        draft=DRAFTS.get(chat)
        if not draft or draft.get('step')!='subject':return display(chat,'homework')
        draft.update(step='title',subject=subject)
    return send(chat,f'📘 Предмет: {subject}\n\n2/5 — Напиши, что нужно сделать (например, «№ 125–130»).',draft_keyboard())

def homework_title(chat,title):
    title=title.strip()
    if not title or len(title)>240:return send(chat,'Описание задания должно содержать от 1 до 240 символов. Попробуй ещё раз.',draft_keyboard())
    with DRAFT_LOCK:
        draft=DRAFTS.get(chat)
        if not draft or draft.get('step')!='title':return display(chat,'homework')
        draft.update(step='date',title=title)
    return send(chat,'📅 3/5 — На какую дату домашнее задание?\n\nНажми кнопку или введи дату в формате ДД.ММ.ГГГГ.',[[{'text':'Завтра','callback_data':'hwdate:1'},{'text':'Послезавтра','callback_data':'hwdate:2'}]]+draft_keyboard())

def photo_keyboard():
    return [[{'text':'✅ Готово, продолжить','callback_data':'hwphotosdone'},
             {'text':'⏭ Без фото','callback_data':'hwskip'}]]+draft_keyboard()

def confirm_keyboard():
    return [[{'text':'✅ Сохранить ДЗ','callback_data':'hwsave'}],
            [{'text':'⬅️ Назад к фото','callback_data':'hwbackphotos'}]]+draft_keyboard()

def homework_date(chat,day):
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return send(chat,'Сначала привяжи аккаунт.',main_menu())
        now=local_today(user)
    if day<now or day>now+datetime.timedelta(days=365*5):
        return send(chat,'Выбери дату от сегодняшнего дня до пяти лет вперёд.',draft_keyboard())
    with DRAFT_LOCK:
        draft=DRAFTS.get(chat)
        if not draft or draft.get('step')!='date':return display(chat,'homework')
        draft.update(step='photos',due=day,photos=[])
    return send(chat,'📷 4/5 — Пришли фотографии задания (до 5 шт.) по одной.\n\nМожно нажать «Без фото» или «Готово, продолжить».',photo_keyboard())

def receive_homework_photo(chat,msg):
    with DRAFT_LOCK:
        draft=DRAFTS.get(chat)
        if not draft or draft.get('step')!='photos':return
        if len(draft['photos'])>=5:return send(chat,'Максимум 5 фотографий.',photo_keyboard())
    sizes=msg.get('photo') or []
    if not sizes:return
    photo=sizes[-1]
    if photo.get('file_size',0)>MAX_UPLOAD:
        return send(chat,f'Фото слишком большое. Максимум {MAX_UPLOAD//1024//1024} МБ.',photo_keyboard())
    try:
        info=tg('getFile',{'file_id':photo['file_id']},timeout=20)
        path=info.get('file_path','')
        if not path or info.get('file_size',0)>MAX_UPLOAD:raise ValueError('Файл слишком большой или недоступен.')
        url='https://api.telegram.org/file/bot'+TOKEN+'/'+path
        with urllib.request.urlopen(url,timeout=25) as response:
            raw=response.read(MAX_UPLOAD+1)
        if not raw or len(raw)>MAX_UPLOAD or not raw.startswith(b'\xff\xd8\xff'):
            raise ValueError('Не удалось получить корректное JPEG-фото.')
        with DRAFT_LOCK:
            draft=DRAFTS.get(chat)
            if not draft or draft.get('step')!='photos':return
            if len(draft['photos'])>=5:return send(chat,'Максимум 5 фотографий.',photo_keyboard())
            draft['photos'].append(raw)
            count=len(draft['photos'])
        return send(chat,f'📷 Фото {count}/5 добавлено. Пришли следующее или нажми «Готово».',photo_keyboard())
    except Exception as exc:
        print('Homework photo error:',repr(exc),flush=True)
        return send(chat,'Не удалось загрузить фотографию. Попробуй отправить её ещё раз.',photo_keyboard())

def homework_confirm(chat):
    with DRAFT_LOCK:
        draft=DRAFTS.get(chat)
        if not draft or draft.get('step')!='photos':return display(chat,'homework')
        draft['step']='confirm'
        data=draft.copy()
    return send(chat,f'📚 5/5 — Проверь задание\n\n📘 {data["subject"]}\n📝 {data["title"]}\n📅 {data["due"]:%d.%m.%Y}\n📷 Фото: {len(data["photos"])}\n\nСохранить?',confirm_keyboard())

def save_homework(chat):
    with DRAFT_LOCK:
        draft=DRAFTS.get(chat)
        if not draft or draft.get('step')!='confirm':return display(chat,'homework')
        draft=draft.copy()
        DRAFTS[chat]['step']='saving'
    saved=[]
    try:
        with SessionLocal() as db:
            user=linked_user(db,chat)
            if not user:raise ValueError('Аккаунт не привязан.')
            now=local_today(user)
            day=draft['due']
            if day<now or day>now+datetime.timedelta(days=365*5):raise ValueError('Дата больше недействительна.')
            task=Task(user_id=user.id,subject=draft['subject'],title=draft['title'],due=day,priority='normal',done=False)
            db.add(task);db.flush()
            for index,raw in enumerate(draft['photos'],1):
                name=uuid.uuid4().hex+'.jpg'
                (UPLOAD_DIR/name).write_bytes(raw)
                saved.append(name)
                db.add(Attachment(user_id=user.id,task_id=task.id,stored_name=name,mime='image/jpeg',filename=f'homework_{index}.jpg'))
            db.commit()
        cancel_draft(chat)
        return send(chat,f'✅ Домашнее задание сохранено!\n\n📘 {draft["subject"]}\n📝 {draft["title"]}\n📅 {day:%d.%m.%Y}\n📷 Фото: {len(saved)}\n\nЗадание и фото доступны на сайте.',[[{'text':'➕ Добавить ещё','callback_data':'addhw'},{'text':'📚 Все задания','callback_data':'homework'}]]+back())
    except Exception as exc:
        for name in saved:(UPLOAD_DIR/name).unlink(missing_ok=True)
        with DRAFT_LOCK:
            if chat in DRAFTS:DRAFTS[chat]['step']='confirm'
        print('Homework save error:',repr(exc),flush=True)
        return send(chat,'Не удалось сохранить задание. Попробуй ещё раз.',confirm_keyboard())

def parse_homework_date(chat,text):
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return send(chat,'Сначала привяжи аккаунт.',main_menu())
        today=local_today(user)
    normalized=text.strip().casefold()
    if normalized=='завтра':day=today+datetime.timedelta(days=1)
    elif normalized=='послезавтра':day=today+datetime.timedelta(days=2)
    else:
        try:day=datetime.datetime.strptime(text.strip(),'%d.%m.%Y').date()
        except ValueError:return send(chat,'Неверная дата. Введи ДД.ММ.ГГГГ (например, 15.11.2026) или нажми «Завтра».',[[{'text':'Завтра','callback_data':'hwdate:1'},{'text':'Послезавтра','callback_data':'hwdate:2'}]]+draft_keyboard())
    return homework_date(chat,day)

def handle(msg):
    chat=str(msg.get('chat',{}).get('id','')); text=(msg.get('text') or '').strip()
    if not chat:return
    if text.split(maxsplit=1)[0].split('@',1)[0]=='/admin':return admin_login(chat)
    with DRAFT_LOCK: photo_step=DRAFTS.get(chat,{}).get('step')
    if msg.get('photo') and photo_step=='photos':return receive_homework_photo(chat,msg)
    if not text:return
    if text.casefold() in ('отмена','/cancel'):
        cancel_draft(chat);return send(chat,'Создание задания отменено.',main_menu())
    with DRAFT_LOCK:step=DRAFTS.get(chat,{}).get('step')
    if step=='admin_password' and not text.startswith('/'):return verify_admin_password(chat,text,msg.get('message_id'))
    if step=='habit_name' and not text.startswith('/'):return habit_name(chat,text)
    if step=='broadcast_text' and not text.startswith('/'):return broadcast_preview(chat,text)
    if step and not text.startswith('/'):
        if step=='subject':return send(chat,'Выбери предмет кнопкой из расписания.',draft_keyboard())
        if step=='title':return homework_title(chat,text)
        if step=='date':return parse_homework_date(chat,text)
        if step=='photos':return send(chat,'Пришли фото или выбери кнопку ниже.',photo_keyboard())
        if step=='confirm':return send(chat,'Подтверди сохранение кнопкой ниже.',confirm_keyboard())
        if step=='saving':return send(chat,'Задание сохраняется, подожди немного.',draft_keyboard())
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
            ensure_default_reminders(db,row.user_id);db.delete(row);db.commit()
        return send(chat,'✅ Аккаунт успешно привязан! Выбирай нужный раздел.',main_menu())
    if cmd=='/admin':return admin_login(chat)
    aliases={'/today':'today','/habits':'habits','/homework':'homework','/schedule':'schedule','/tomorrow':'tomorrow'}
    cancel_draft(chat)
    display(chat,aliases.get(cmd,'menu'))

def callback(q):
    chat=str(q.get('message',{}).get('chat',{}).get('id',''))
    mid=q.get('message',{}).get('message_id'); action=q.get('data','')
    try: tg('answerCallbackQuery',{'callback_query_id':q['id']},timeout=10)
    except Exception: pass
    if not chat:return
    if action=='addhw':return start_homework(chat,mid)
    if action=='addhabit':return start_habit(chat,mid)
    if action.startswith('habitdays:'):return habit_days(chat,action,mid)
    if action=='habitcancel':cancel_draft(chat);return display(chat,'habits',mid)
    if action=='admin':return admin_login(chat)
    if action=='broadcast':return broadcast_start(chat,mid)
    if action=='broadcastsend':return broadcast_send(chat,mid)
    if action=='broadcastcancel':cancel_draft(chat);return admin_panel(chat,mid)
    if action=='hwcancel':
        cancel_draft(chat);return display(chat,'homework',mid)
    if action=='hwphotosdone' or action=='hwskip':
        with DRAFT_LOCK: step=DRAFTS.get(chat,{}).get('step')
        if step=='photos':return homework_confirm(chat)
        return display(chat,'homework',mid)
    if action=='hwbackphotos':
        with DRAFT_LOCK:
            draft=DRAFTS.get(chat)
            if draft and draft.get('step')=='confirm':draft['step']='photos'
        return send(chat,'📷 Пришли дополнительные фото или нажми «Готово».',photo_keyboard(),mid)
    if action=='hwsave':return save_homework(chat)
    if action=='hwmanual':return start_homework(chat,mid)
    if action.startswith('hwsub:'):
        try:i=int(action.split(':',1)[1])
        except ValueError:return
        with DRAFT_LOCK:
            draft=DRAFTS.get(chat)
            subject=draft.get('subjects',[])[i] if draft and draft.get('step')=='subject' and 0<=i<len(draft.get('subjects',[])) else None
        if subject:return homework_subject(chat,subject)
        return display(chat,'homework',mid)
    if action.startswith('hwdate:'):
        with DRAFT_LOCK:step=DRAFTS.get(chat,{}).get('step')
        if step!='date':return display(chat,'homework',mid)
        try:days=int(action.split(':',1)[1])
        except ValueError:return
        if days not in (1,2):return
        with SessionLocal() as db:
            user=linked_user(db,chat)
            if not user:return display(chat,'menu',mid)
            day=local_today(user)+datetime.timedelta(days=days)
        return homework_date(chat,day)
    if action in ('menu','today','habits','homework','schedule','tomorrow','reminders'):cancel_draft(chat)
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


def start_habit(chat,mid=None):
    with SessionLocal() as db:
        if not linked_user(db,chat):return send(chat,'Сначала привяжи аккаунт.',main_menu(),mid)
    with DRAFT_LOCK:DRAFTS[chat]={'step':'habit_name'}
    return send(chat,'➕ Новая привычка\n\nНапиши название привычки.',[[{'text':'Отмена','callback_data':'habitcancel'}]],mid)

def habit_name(chat,name):
    name=name.strip()
    if not 1<=len(name)<=120:return send(chat,'Название должно содержать 1–120 символов.')
    with DRAFT_LOCK:DRAFTS[chat]={'step':'habit_days','name':name}
    rows=[[{'text':'Каждый день','callback_data':'habitdays:all'}],[{'text':'Будни','callback_data':'habitdays:weekdays'}],[{'text':'Выходные','callback_data':'habitdays:weekend'}],[{'text':'Отмена','callback_data':'habitcancel'}]]
    return send(chat,'Когда выполнять привычку?',rows)

def habit_days(chat,action,mid=None):
    days={'all':'0,1,2,3,4,5,6','weekdays':'0,1,2,3,4','weekend':'5,6'}.get(action.split(':')[-1])
    with DRAFT_LOCK:draft=DRAFTS.get(chat,{}).copy()
    if not days or draft.get('step')!='habit_days':return display(chat,'habits',mid)
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return send(chat,'Аккаунт не привязан.')
        db.add(Habit(user_id=user.id,name=draft['name'],days=days));db.commit()
    cancel_draft(chat)
    return send(chat,'✅ Привычка добавлена!',[[{'text':'➕ Ещё привычка','callback_data':'addhabit'}]]+back(),mid)

def admin_panel(chat,mid=None):
    if not admin_authorized(chat):return send(chat,'Доступ запрещён. Используй /admin.')
    with SessionLocal() as db:count=len(db.scalars(select(TelegramLink.chat_id)).all())
    return send(chat,f'🛡 Админ-панель My-Study\n\nПривязано Telegram: {count}',[[{'text':'📢 Новая рассылка','callback_data':'broadcast'}]]+back(),mid)

def broadcast_start(chat,mid=None):
    if not admin_authorized(chat):return send(chat,'Доступ запрещён. Используй /admin.')
    with DRAFT_LOCK:DRAFTS[chat]={'step':'broadcast_text'}
    return send(chat,'Отправь текст объявления (до 3000 символов).',[[{'text':'Отмена','callback_data':'broadcastcancel'}]],mid)

def broadcast_preview(chat,text):
    if not admin_authorized(chat):return
    if not 1<=len(text)<=3000:return send(chat,'Длина текста должна быть от 1 до 3000 символов.')
    with DRAFT_LOCK:DRAFTS[chat]={'step':'broadcast_confirm','text':text}
    with SessionLocal() as db:count=len(db.scalars(select(TelegramLink.chat_id)).all())
    return send(chat,f'Предпросмотр рассылки ({count} получателей):\n\n{text}',[[{'text':'✅ Отправить всем','callback_data':'broadcastsend'}],[{'text':'❌ Отмена','callback_data':'broadcastcancel'}]])

def broadcast_send(chat,mid=None):
    if not admin_authorized(chat):return
    with DRAFT_LOCK:draft=DRAFTS.get(chat,{}).copy()
    if draft.get('step')!='broadcast_confirm':return admin_panel(chat,mid)
    cancel_draft(chat)
    with SessionLocal() as db:chats=list(dict.fromkeys(db.scalars(select(TelegramLink.chat_id)).all()))
    sent=failed=0
    for recipient in chats:
        try:send(recipient,'📢 Новости My-Study\n\n'+draft['text']);sent+=1
        except Exception as exc:failed+=1;print('Broadcast error:',repr(exc),flush=True)
        time.sleep(.08)
    return send(chat,f'Рассылка завершена. Доставлено: {sent}; ошибок: {failed}.',back(),mid)

def event_targets(db,user,local,source,event_id=None):
    """Upcoming lesson-day or calendar events in the user's timezone."""
    today=local.date()
    if source=='calendar':
        events=db.scalars(select(CalendarEvent).where(CalendarEvent.user_id==user.id)).all()
        for ev in events:
            if event_id is not None and ev.id!=event_id:continue
            # Calendar start_at is stored as UTC naive by the web frontend.
            when=ev.start_at.replace(tzinfo=datetime.timezone.utc).astimezone(local.tzinfo)
            if today-datetime.timedelta(days=1)<=when.date()<=today+datetime.timedelta(days=8):
                yield when, f'📌 {ev.title}',f'event:{ev.id}:{when.isoformat()}'
    else:
        for shift in range(0,9):
            day=today+datetime.timedelta(days=shift)
            lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==day.weekday()).order_by(Lesson.period)).all()
            valid=[x for x in lessons if re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',x.start or '')]
            if not valid:continue
            first=min(x.start for x in valid)
            hour,minute=map(int,first.split(':'))
            when=datetime.datetime.combine(day,datetime.time(hour,minute),tzinfo=local.tzinfo)
            lines=[f'🗓 Занятия {day.strftime("%d.%m")} (начало {first}):']
            lines += [f'• {x.period}. {x.subject} {x.start or ""}' for x in lessons]
            yield when,'\n'.join(lines),f'lessons:{day.isoformat()}'

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
                timing=db.get(ReminderTiming,reminder.id)
                mode=timing.mode if timing else 'fixed'
                if mode!='fixed':
                    for event_time,content,event_key in event_targets(db,user,local,timing.event_source,timing.event_id):
                        if mode=='eve':
                            h,m=map(int,reminder.send_time.split(':'))
                            target=datetime.datetime.combine(event_time.date()-datetime.timedelta(days=1),datetime.time(h,m),tzinfo=local.tzinfo)
                        else:
                            target=event_time-datetime.timedelta(minutes=timing.minutes_before)
                        # Catch a minute-level scheduler tick without duplicate sends.
                        if not (target<=local<target+datetime.timedelta(minutes=1)):continue
                        if str(local.weekday()) not in reminder.days.split(','):continue
                        key=f'{event_key}:{mode}:{target.isoformat()}'
                        if timing.last_event_key==key:continue
                        # Event-relative reminders are explicitly scheduled and bypass generic quiet hours.
                        send(link.chat_id,'🔔 '+reminder.title+'\n\n'+content,[[{'text':'📅 Мой день','callback_data':'today'}]])
                        timing.last_event_key=key
                        reminder.last_sent=utc.replace(tzinfo=None)
                        db.commit()
                    continue
                if str(local.weekday()) not in reminder.days.split(','):continue
                if local.strftime('%H:%M')!=reminder.send_time:continue
                # Explicit per-reminder time takes precedence over legacy quiet hours.
                if reminder.last_sent:
                    last=reminder.last_sent.replace(tzinfo=datetime.timezone.utc).astimezone(local.tzinfo)
                    if last.date()==local.date():continue
                content=reminder.title
                if reminder.kind=='tasks':
                    tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False).order_by(Task.due).limit(5)).all()
                    content+='\n\n'+('\n'.join('• '+t.title for t in tasks) if tasks else 'Все задания выполнены!')
                elif reminder.kind=='homework_eve':
                    tomorrow=local.date()+datetime.timedelta(days=1)
                    lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==tomorrow.weekday()).order_by(Lesson.period)).all()
                    subjects={x.subject.strip().casefold() for x in lessons if x.subject and x.subject.strip()}
                    if not subjects:continue
                    tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False)).all()
                    pending=[t for t in tasks if (t.subject or '').strip().casefold() in subjects]
                    if not pending:continue
                    lines=[f'📚 Домашнее задание на завтра ({tomorrow.strftime("%d.%m")})']
                    for lesson in lessons:
                        related=[t for t in pending if (t.subject or '').strip().casefold()==lesson.subject.strip().casefold()]
                        if related:
                            lines.append(f'\n📖 {lesson.subject}:')
                            lines.extend('• '+t.title for t in related[:10])
                    content='\n'.join(lines)
                elif reminder.kind=='habits':
                    hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
                    checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==local.date())).all()}
                    pending=[h for h in hs if str(local.weekday()) in h.days.split(',') and h.id not in checks]
                    content+='\n\n'+('\n'.join('• '+h.name for h in pending[:6]) if pending else 'Все привычки выполнены!')
                elif reminder.kind in ('schedule','schedule_tomorrow'):
                    target_day=local.date()+datetime.timedelta(days=1) if reminder.kind=='schedule_tomorrow' else local.date()
                    lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==target_day.weekday()).order_by(Lesson.period)).all()
                    content+='\n\n'+('\n'.join(f'{x.period}. {x.subject} {x.start}' for x in lessons) if lessons else 'Уроков нет.')
                send(link.chat_id,'🔔 '+content,[[{'text':'📅 Мой день','callback_data':'today'}]])
                reminder.last_sent=utc.replace(tzinfo=None);db.commit()
            except Exception as exc:
                db.rollback();print('Reminder error:',repr(exc),flush=True)

def in_quiet(now,start,end):
    if not start or not end or start==end:return False
    cur=now.strftime('%H:%M')
    return start<=cur<end if start<end else cur>=start or cur<end

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
