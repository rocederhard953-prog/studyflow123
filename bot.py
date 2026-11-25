"""StudyFlow Telegram companion with inline buttons and scheduled reminders."""
import os, time, json, urllib.request, urllib.parse, datetime, threading, traceback, uuid
from zoneinfo import ZoneInfo
import re
import hmac
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from app import (SessionLocal, User, TelegramCode, TelegramLink, NotificationSetting,
                 Reminder, ReminderTiming, CalendarEvent, UserSetting, Habit, HabitCheck, Task, Lesson, Attachment, TaskSnooze, UPLOAD_DIR, MAX_UPLOAD, ensure_default_reminders, habit_config, feature_get, feature_put, weekly_report_data, record_task_completion, upgrade_channels, upgrade_habit_scheduled)

from bot_support import MediaCache, image_data, signature, reusable_media_error, quick_keyboard, QUICK_ACTIONS, COMMAND_ACTIONS, COMMANDS, notification_loop

TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
API=f'https://api.telegram.org/bot{TOKEN}/'
SITE=os.getenv('SITE_URL','https://my-study.bothost.tech').rstrip('/')
ADMIN_ID=os.getenv('ADMIN_TELEGRAM_ID','').strip()
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','').strip()
STOP=threading.Event()

# Conversation state per chat; in-progress drafts are not saved as tasks.
DRAFTS={}
DRAFT_LOCK=threading.Lock()

# A single persistent interactive message per chat. Notifications are independent.
SCREEN_IDS={}
SCREEN_META={}
SCREEN_LOCK=threading.RLock()
CHAT_MENU_LOCKS={}
QUICK_MENU_VERSION=1
MEDIA_CACHE=MediaCache(UPLOAD_DIR.parent,TOKEN)

def chat_menu_lock(chat):
    with SCREEN_LOCK:return CHAT_MENU_LOCKS.setdefault(str(chat),threading.RLock())

def menu_state(chat):
    chat=str(chat)
    with SCREEN_LOCK:
        if chat in SCREEN_IDS:return SCREEN_META.get(chat,{'message_id':SCREEN_IDS[chat],'photo':False})
        with SessionLocal() as db:
            user=linked_user(db,chat)
            row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='bot-menu')) if user else None
            try:state=json.loads(row.value) if row else {}
            except (ValueError,TypeError):state={}
        if state.get('message_id'):SCREEN_IDS[chat]=state['message_id'];SCREEN_META[chat]=state
        return state

def remember_menu(chat,state):
    chat=str(chat)
    with SCREEN_LOCK:
        SCREEN_IDS[chat]=state['message_id'];SCREEN_META[chat]=state
        with SessionLocal() as db:
            user=linked_user(db,chat)
            if user:
                row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='bot-menu'))
                if not row:row=UserSetting(user_id=user.id,key='bot-menu');db.add(row)
                row.value=json.dumps(state,ensure_ascii=False);db.commit()

def register_screen(chat,result,previous_id=None):
    if isinstance(result,dict) and result.get('message_id'):
        state=menu_state(chat).copy();state.update(message_id=result['message_id'],photo=bool(result.get('photo')))
        remember_menu(chat,state)
    return result

def tg(method,params=None,timeout=35):
    req=urllib.request.Request(API+method,data=urllib.parse.urlencode(params or {}).encode())
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:data=json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        try:description=json.loads(exc.read().decode()).get('description','Telegram API error')
        except Exception:description='Telegram HTTP '+str(exc.code)
        raise RuntimeError(description) from None
    if not data.get('ok'):raise RuntimeError(data.get('description','Telegram API error'))
    return data.get('result')

def keyboard(rows=None):
    rows=[[{key:value for key,value in button.items() if key!='style'} for button in row] for row in (rows or [])]
    rows.append([{'text':'🚀 Открыть My-Study','web_app':{'url':SITE}}])
    rows.append([{'text':'🌐 Открыть в браузере','url':SITE}])
    return json.dumps({'inline_keyboard':rows},ensure_ascii=False)

def menu_chunks(text,limit=850):
    chunks=[]
    while text:
        end=len(text) if len(text)<=limit else text.rfind('\n',0,limit)
        if end<=0:end=limit
        chunks.append(text[:end]);text=text[end:].lstrip('\n')
    return chunks or ['']

def paint_menu(chat,text,rows=None,message_id=None,section=None,page_index=0,photo_image=None):
    # Serialize one chat only: slow network calls must not hold the global state lock.
    with chat_menu_lock(chat):
        state=menu_state(chat).copy();mid=state.get('message_id') or message_id
        pages=menu_chunks(text);page_index=max(0,min(page_index,len(pages)-1));rows=list(rows or [])
        navigation=[]
        if page_index:navigation.append({'text':'← Назад','callback_data':'menupage:'+str(page_index-1)})
        if page_index+1<len(pages):navigation.append({'text':'Далее →','callback_data':'menupage:'+str(page_index+1)})
        visible_rows=([navigation] if navigation else [])+rows
        content=pages[page_index]+(f'\n\n{page_index+1}/{len(pages)}' if len(pages)>1 else '')+'\n\n🌐 '+SITE
        image_name={'menu':'my-study','today':'today','habits':'habits','reminders':'reminders','homework':'homework','schedule':'schedule','tomorrow':'schedule'}.get(section)
        photo=bool(state.get('photo'));desired_image=photo_image or ('/static/bot_images/'+image_name+'.jpg' if image_name else state.get('image'))
        image_hash=None;raw=None
        if desired_image:
            path=UPLOAD_DIR/desired_image.split(':',1)[1] if desired_image.startswith('upload:') else os.path.join(os.path.dirname(__file__),desired_image.lstrip('/'))
            image_hash,raw=image_data(path)
        params={'chat_id':chat,'reply_markup':keyboard(visible_rows)}
        fingerprint=signature(content,params['reply_markup'],image_hash)
        if mid and fingerprint==state.get('signature'):return {'message_id':mid}
        def upload_photo(method,fields):
            boundary='----mystudy'+uuid.uuid4().hex;parts=[]
            for name,value in fields.items():parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode())
            mime='image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg'
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="menu.jpg"\r\nContent-Type: {mime}\r\n\r\n').encode()+raw+b'\r\n')
            req=urllib.request.Request(API+method,data=b''.join(parts)+f'--{boundary}--\r\n'.encode(),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
            try:
                with urllib.request.urlopen(req,timeout=20) as response:result=json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                try:description=json.loads(exc.read().decode()).get('description','Telegram API error')
                except Exception:description='Telegram HTTP '+str(exc.code)
                raise RuntimeError(description) from None
            if not result.get('ok'):raise RuntimeError(result.get('description','Telegram API error'))
            return result['result']
        def photo_request(method,fields):
            file_id=MEDIA_CACHE.get(image_hash)
            if file_id:
                cached=dict(fields)
                if method=='editMessageMedia':
                    media=json.loads(cached['media']);media['media']=file_id;cached['media']=json.dumps(media,ensure_ascii=False)
                else:cached['photo']=file_id
                try:return tg(method,cached,timeout=20)
                except RuntimeError as error:
                    if not reusable_media_error(error):raise
                    MEDIA_CACHE.discard(image_hash)
            result=upload_photo(method,fields)
            photos=result.get('photo',[]) if isinstance(result,dict) else []
            if isinstance(photos,list) and photos and isinstance(photos[-1],dict):MEDIA_CACHE.set(image_hash,photos[-1].get('file_id'))
            return result
        try:
            if mid:
                params['message_id']=mid
                changed=desired_image!=state.get('image') or image_hash!=state.get('image_hash')
                if desired_image and (not photo or changed):
                    params['media']=json.dumps({'type':'photo','media':'attach://photo','caption':content},ensure_ascii=False)
                    result=photo_request('editMessageMedia',params);photo=True
                elif photo:result=tg('editMessageCaption',{**params,'caption':content},timeout=20)
                else:result=tg('editMessageText',{**params,'text':content,'disable_web_page_preview':'true'},timeout=20)
            else:
                if desired_image:result=photo_request('sendPhoto',{**params,'caption':content});photo=True
                else:result=tg('sendMessage',{**params,'text':content,'disable_web_page_preview':'true'},timeout=20)
        except RuntimeError as exc:
            error=str(exc).lower()
            if 'message is not modified' in error:result={'message_id':mid}
            elif mid and any(x in error for x in ('message to edit not found',"message can't be edited",'message_id_invalid')):
                remember_menu(chat,{'message_id':None});return paint_menu(chat,text,rows,section=section,page_index=page_index,photo_image=photo_image)
            else:raise
        mid=result.get('message_id',mid) if isinstance(result,dict) else mid
        remember_menu(chat,{'message_id':mid,'photo':photo,'image':desired_image,'image_hash':image_hash,'signature':fingerprint,'text':text,'rows':rows,'section':section})
        return result


def send(chat,text,rows=None,message_id=None):return paint_menu(chat,text,rows,message_id)

def main_menu():
    return [[{'text':'📅 Мой день','callback_data':'today'},{'text':'📚 Домашка','callback_data':'homework'}],
            [{'text':'✅ Привычки','callback_data':'habits'},{'text':'🗓 Расписание','callback_data':'schedule'}],
            [{'text':'🔔 Напоминания','callback_data':'reminders'},{'text':'🌙 Сводка','callback_data':'summary'}]]

def back():return [[{'text':'⬅️ Главное меню','callback_data':'menu'}]]

def send_section(chat,section,text,rows=None,message_id=None):return paint_menu(chat,text,rows,message_id,section)


def ensure_quick_menu(chat,force=False):
    """One persistent keyboard announcement, not a new message per navigation."""
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return False
        row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='bot-quick-menu'))
        try:installed=json.loads(row.value) if row else {}
        except ValueError:installed={}
        if not force and installed.get('version')==QUICK_MENU_VERSION and installed.get('chat')==str(chat):return False
    result=tg('sendMessage',{'chat_id':chat,'text':'Быстрый доступ — на клавиатуре внизу. Выбери раздел одним нажатием.','disable_notification':'true','reply_markup':quick_keyboard(SITE)},timeout=15)
    with SessionLocal() as db:
        # Recheck the link after the network call; never attach state to a different account.
        linked=linked_user(db,chat)
        if linked and linked.id==user.id:
            feature_put(db,user.id,'bot-quick-menu',{'version':QUICK_MENU_VERSION,'chat':str(chat),'message_id':result.get('message_id') if isinstance(result,dict) else None});db.commit()
    return True

def start_notification_worker():
    worker=threading.Thread(target=notification_loop,args=(notification_tick,STOP),kwargs={'on_error':traceback.print_exc},name='studyflow-telegram-reminders',daemon=True)
    worker.start();return worker


def linked_user(db,chat):
    link=db.scalar(select(TelegramLink).where(TelegramLink.chat_id==str(chat)))
    return db.get(User,link.user_id) if link else None

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
            return send_section(chat,section,'✦ My-Study\nТвоё пространство для учёбы и привычек\n\nВыбери, чем займёмся сегодня.',main_menu(),message_id)
        if section=='today':
            hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
            checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            eligible=[h for h in hs if upgrade_habit_scheduled(db,user,h,today)]
            tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False)).all()
            return send_section(chat,section,f'📅 Сегодня, {today:%d.%m.%Y}\n\nПривычки: {len([h for h in eligible if h.id in checks])}/{len(eligible)}\nНевыполненных заданий: {len(tasks)}\nНа сегодня: {len([t for t in tasks if t.due==today])}',back(),message_id)
        if section=='habits':
            hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
            hs=[h for h in hs if upgrade_habit_scheduled(db,user,h,today)]
            checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==today)).all()}
            rows=[[{'text':'➕ Добавить привычку','callback_data':'addhabit'}]]+[[{'text':('↩️ ' if h.id in checks else '☑️ ')+h.name[:40], 'callback_data':f'habit:{h.id}'}] for h in hs[:20]]+back()
            return send_section(chat,section,'✅ Привычки на сегодня\n\nНажми на привычку, чтобы изменить отметку.' if hs else 'Сегодня привычек нет.',rows,message_id)
        if section=='homework':
            tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False).order_by(Task.due,Task.id).limit(15)).all()
            rows=[[{'text':'➕ Добавить ДЗ','callback_data':'addhw'}]]+[[{'text':'☑️ '+t.title[:45],'callback_data':f'task:{t.id}'}] for t in tasks]+back()
            return send_section(chat,section,'📚 Невыполненные задания\n\n'+('\n\n'.join(task_text(t) for t in tasks) if tasks else 'Всё выполнено!'),rows,message_id)
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

def send_auth_link(msg,purpose):
    chat=str(msg.get('chat',{}).get('id',''))
    if msg.get('chat',{}).get('type')!='private' or str(msg.get('from',{}).get('id',''))!=chat:return
    from app import issue_telegram_auth_link
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return send(chat,'Этот Telegram ещё не привязан. Войди на сайт с паролем, открой раздел Telegram и привяжи аккаунт. Если пароль забыт до привязки, потребуется помощь владельца платформы.')
        raw=issue_telegram_auth_link(db,user,purpose)
    label='Войти в My-Study' if purpose=='login' else 'Задать новый пароль'
    url=SITE+'/#tg_'+purpose+'='+raw
    return send(chat,label+'\n\nСсылка одноразовая и действует 10 минут. Не пересылай её другим людям.',[[{'text':label,'url':url}]])


def handle(msg):
    chat=str(msg.get('chat',{}).get('id','')); text=(msg.get('text') or '').strip()
    if not chat:return
    command=text.split(maxsplit=1)[0].split('@',1)[0] if text else ''
    payload=text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1))>1 else ''
    if command=='/login' or (command=='/start' and payload=='login'):return send_auth_link(msg,'login')
    if command=='/reset' or (command=='/start' and payload=='reset'):return send_auth_link(msg,'reset')
    if command=='/admin':return admin_login(chat)
    quick_action=QUICK_ACTIONS.get(text) or COMMAND_ACTIONS.get(command)
    if command in ('/quick','/start') and not payload or quick_action:
        cancel_draft(chat)
        try:ensure_quick_menu(chat,force=command=='/quick')
        except Exception:traceback.print_exc()
        return display(chat,quick_action or 'menu')
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
        try:ensure_quick_menu(chat)
        except Exception:traceback.print_exc()
        return send_section(chat,'menu','✅ Аккаунт успешно привязан! Выбирай нужный раздел.',main_menu())
    if cmd=='/admin':return admin_login(chat)
    aliases={'/today':'today','/habits':'habits','/homework':'homework','/schedule':'schedule','/tomorrow':'tomorrow'}
    cancel_draft(chat)
    display(chat,aliases.get(cmd,'menu'))

def callback(q):
    return _callback_impl(q)

def _callback_impl(q):
    chat=str(q.get('message',{}).get('chat',{}).get('id',''))
    mid=q.get('message',{}).get('message_id'); action=q.get('data','')
    screen=menu_state(chat).get('message_id')
    if mid!=screen:mid=None  # Never edit or delete a persistent notification.
    try: tg('answerCallbackQuery',{'callback_query_id':q['id']},timeout=10)
    except Exception: pass
    if not chat:return
    if action.startswith(('ndone:', 'nsnooze:', 'nphoto:', 'nopen:')):return task_notification_action(chat,action,interactive=True)
    if action.startswith('menupage:'):
        state=menu_state(chat)
        try:index=int(action.split(':',1)[1])
        except ValueError:return
        return paint_menu(chat,state.get('text',''),state.get('rows'),section=state.get('section'),page_index=index)
    if action=='summary':
        with SessionLocal() as db:
            user=linked_user(db,chat)
            if not user:return display(chat,'menu',mid)
            content,tasks=evening_summary(db,user,datetime.datetime.now(datetime.timezone.utc).astimezone(ZoneInfo(user.timezone or 'UTC')))
            return send(chat,content,back(),mid)
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
                    progress=feature_get(db,user.id,f'habit-progress:{ident}:{today}',{});progress['amount']=0 if check else habit_config(db,user.id,ident)['target'];feature_put(db,user.id,f'habit-progress:{ident}:{today}',progress)
                    if check: db.delete(check)
                    else: db.add(HabitCheck(user_id=user.id,habit_id=ident,day=today))
                section='habits'
            else:
                t=db.scalar(select(Task).where(Task.id==ident,Task.user_id==user.id))
                if t:record_task_completion(db,t,True);t.done=True
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
        db.add(Habit(user_id=user.id,name=draft['name'],days=days,created_at=local_today(user)));db.commit()
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
        try:notify(recipient,'📢 Новости My-Study\n\n'+draft['text']);sent+=1
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


def task_text(task):
    subject=(task.subject or '').strip() or 'Без предмета'
    due=task.due.strftime('%d.%m.%Y') if task.due else 'Без срока'
    return f'📘 {subject}\n📅 Срок: {due}\n📝 {task.title}'

def task_rows(task):
    return [[{'text':'✅ Выполнено','callback_data':f'ndone:{task.id}'},
             {'text':'⏰ Через час','callback_data':f'nsnooze:{task.id}'}],
            [{'text':'📷 Фото задания','callback_data':f'nphoto:{task.id}'}]]

def notify(chat,text,rows=None):
    # Notifications stay in chat independently of interactive navigation screens.
    return tg('sendMessage',{'chat_id':chat,'text':text,
              'disable_web_page_preview':'true','reply_markup':keyboard(rows)},timeout=20)

def notify_task(chat,task,title='Домашнее задание'):
    return notify(chat,'🔔 '+title+'\n\n'+task_text(task),task_rows(task))

def send_task_photo(chat,attachment):
    path=(UPLOAD_DIR/attachment.stored_name).resolve()
    if path.parent!=UPLOAD_DIR.resolve() or not path.is_file():return False
    boundary='----studyphoto'+uuid.uuid4().hex
    caption=attachment.filename[:200]
    chunks=[]
    for name,value in [('chat_id',str(chat)),('caption',caption)]:
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode())
    chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="photo"\r\nContent-Type: {attachment.mime}\r\n\r\n').encode()+path.read_bytes()+b'\r\n')
    raw=b''.join(chunks)+f'--{boundary}--\r\n'.encode()
    request=urllib.request.Request(API+'sendPhoto',data=raw,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request,timeout=25) as response:result=json.loads(response.read())
    if not result.get('ok'):raise RuntimeError(result.get('description','Photo failed'))
    return True

def task_notification_action(chat,action,interactive=False):
    respond=send if interactive else notify
    kind,_,value=action.partition(':')
    try:
        values=value.split(':');ident=int(values[0]);photo_index=int(values[1]) if len(values)>1 else 0
    except ValueError:return
    with SessionLocal() as db:
        user=linked_user(db,chat)
        if not user:return respond(chat,'Сначала привяжи аккаунт My-Study.')
        task=db.scalar(select(Task).where(Task.id==ident,Task.user_id==user.id))
        if not task:return respond(chat,'Задание удалено или недоступно.')
        if kind=='nopen':return send(chat,task_text(task),task_rows(task)+back()) if interactive else notify_task(chat,task)
        if kind=='ndone':
            record_task_completion(db,task,True);task.done=True
            db.query(TaskSnooze).filter_by(user_id=user.id,task_id=task.id).delete()
            db.commit()
            return respond(chat,'✅ Выполнено\n\n'+task_text(task))
        if kind=='nsnooze':
            if task.done:return respond(chat,'Это задание уже выполнено.')
            row=db.scalar(select(TaskSnooze).where(TaskSnooze.user_id==user.id,TaskSnooze.task_id==task.id))
            if row is None:row=TaskSnooze(user_id=user.id,task_id=task.id);db.add(row)
            row.send_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)+datetime.timedelta(hours=1)
            db.commit()
            return respond(chat,'⏰ Напомню через час. Срок сдачи не изменён.\n\n'+task_text(task))
        photos=db.scalars(select(Attachment).where(Attachment.task_id==task.id,Attachment.user_id==user.id).order_by(Attachment.id)).all()
        if not photos:return respond(chat,'У этого задания пока нет фотографий.\n\n'+task_text(task))
        if interactive:
            photo_index=max(0,min(photo_index,len(photos)-1));selected=photos[photo_index]
            navigation=[]
            if photo_index:navigation.append({'text':'← Фото','callback_data':f'nphoto:{task.id}:{photo_index-1}'})
            if photo_index+1<len(photos):navigation.append({'text':'Фото →','callback_data':f'nphoto:{task.id}:{photo_index+1}'})
            return paint_menu(chat,task_text(task)+f'\n\nФото {photo_index+1}/{len(photos)}',([navigation] if navigation else [])+task_rows(task)+back(),section='taskphoto',photo_image='upload:'+selected.stored_name)
        sent=0
        for photo in photos:
            try:sent+=bool(send_task_photo(chat,photo))
            except Exception as exc:print('Task photo error:',repr(exc),flush=True)
        if sent<len(photos):notify(chat,'Часть фотографий недоступна. Попробуй ещё раз или открой задание на сайте.')

def homework_for_day(db,user,day):
    # The due date is authoritative, even if a lesson was moved or is absent.
    return db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False,Task.due==day).order_by(Task.id)).all()

def evening_summary(db,user,local):
    tomorrow=local.date()+datetime.timedelta(days=1)
    lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==tomorrow.weekday()).order_by(Lesson.period)).all()
    tasks=homework_for_day(db,user,tomorrow)
    habits=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
    checks={c.habit_id for c in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==local.date())).all()}
    pending=[h for h in habits if upgrade_habit_scheduled(db,user,h,local.date()) and h.id not in checks]
    lines=[f'🌙 My-Study · Вечерняя сводка',f'📅 Завтра, {tomorrow:%d.%m.%Y}', '\n🗓 Уроки']
    lines.extend([f'{l.period}. {l.subject} · {l.start or "время не указано"}' for l in lessons] or ['Уроков нет.'])
    lines.append('\n📚 Домашнее задание')
    lines.extend([task_text(t)+'\n' for t in tasks] or ['На завтра заданий нет.'])
    lines.append('\n✅ Осталось привычек сегодня')
    lines.extend(['• '+h.name for h in pending] or ['Все привычки выполнены!'])
    return '\n'.join(lines),tasks

def send_long_notification(chat,text):
    # Split on lines and preserve all content within Telegram's 4096 limit.
    while text:
        end=len(text) if len(text)<=3800 else text.rfind('\n',0,3800)
        if end<=0:end=3800
        notify(chat,text[:end])
        text=text[end:].lstrip('\n')

def snooze_tick(db,utc):
    for row in db.scalars(select(TaskSnooze).where(TaskSnooze.send_at<=utc.replace(tzinfo=None))).all():
        task=db.scalar(select(Task).where(Task.id==row.task_id,Task.user_id==row.user_id))
        link=db.scalar(select(TelegramLink).where(TelegramLink.user_id==row.user_id))
        setting=db.scalar(select(NotificationSetting).where(NotificationSetting.user_id==row.user_id))
        if not task or task.done or not link:
            db.delete(row);db.commit();continue
        if setting and not setting.enabled:continue
        try:
            notify_task(link.chat_id,task,'Ты просил напомнить')
            db.delete(row);db.commit()
        except Exception as exc:
            db.rollback();print('Snooze error:',repr(exc),flush=True)

def weekly_report_tick(db,user,link,setting,local):
    prefs=feature_get(db,user.id,'weekly-report-prefs',{})
    if not prefs.get('enabled') or (setting and not setting.enabled):return
    if local.weekday()!=prefs.get('weekday',6) or local.strftime('%H:%M')!=prefs.get('time','19:00'):return
    if setting and in_quiet(local,setting.quiet_start,setting.quiet_end):return
    day=local.date().isoformat()
    if feature_get(db,user.id,'weekly-report-last')==day:return
    report=weekly_report_data(db,user,local.date())
    text=f"📈 Итоги недели · {report['start']} — {report['end']}\n\n📚 Выполнено ДЗ: {report['tasks_done']}\n✅ Привычки: {report['habits_done']}/{report['habits_total']} · {report['habits_percent']}%\n📝 Заданий в работе: {report['tasks_open']}"
    notify(link.chat_id,text,back());feature_put(db,user.id,'weekly-report-last',day);db.commit()

def notification_tick():
    utc=datetime.datetime.now(datetime.timezone.utc)
    with SessionLocal() as db:
        for user in db.scalars(select(User).join(TelegramLink,TelegramLink.user_id==User.id)).all():
            ensure_default_reminders(db,user.id)
            try:
                link=db.scalar(select(TelegramLink).where(TelegramLink.user_id==user.id))
                setting=db.scalar(select(NotificationSetting).where(NotificationSetting.user_id==user.id))
                weekly_report_tick(db,user,link,setting,utc.astimezone(ZoneInfo(user.timezone or 'UTC')))
            except Exception as exc:
                db.rollback();print('Weekly report error:',repr(exc),flush=True)
        db.commit()
        snooze_tick(db,utc)
        reminders=db.scalars(select(Reminder).where(Reminder.enabled==True)).all()
        for reminder in reminders:
            try:
                user=db.get(User,reminder.user_id)
                link=db.scalar(select(TelegramLink).where(TelegramLink.user_id==reminder.user_id))
                setting=db.scalar(select(NotificationSetting).where(NotificationSetting.user_id==reminder.user_id))
                if not user or not link or (setting and not setting.enabled):continue
                preferences=upgrade_channels(db,user.id)
                channel='tasks' if reminder.kind in ('tasks','homework_eve') else 'habits' if reminder.kind=='habits' else 'general'
                if preferences[channel] not in ('telegram','both'):continue
                try: local=utc.astimezone(ZoneInfo(user.timezone or 'UTC'))
                except Exception: local=utc
                from upgrade_features import quiet
                if quiet(local,preferences['quiet_start'],preferences['quiet_end']):continue
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
                        notify(link.chat_id,'🔔 '+reminder.title+'\n\n'+content,[[{'text':'📅 Мой день','callback_data':'today'}]])
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
                if reminder.kind in ('tasks','homework_eve'):
                    if reminder.kind=='tasks':
                        tasks=db.scalars(select(Task).where(Task.user_id==user.id,Task.done==False).order_by(Task.id)).all()
                    else:
                        tasks=homework_for_day(db,user,local.date()+datetime.timedelta(days=1))
                    for task in tasks:notify_task(link.chat_id,task,reminder.title)
                    if not tasks and reminder.kind=='tasks':notify(link.chat_id,'✅ Все задания выполнены!')
                    reminder.last_sent=utc.replace(tzinfo=None);db.commit()
                    continue
                elif reminder.kind=='evening_summary':
                    content,tasks=evening_summary(db,user,local)
                    send_long_notification(link.chat_id,content)
                    if tasks:notify(link.chat_id,'Действия с домашним заданием',[[{'text':(t.subject or 'ДЗ')[:20]+' · '+t.title[:25],'callback_data':f'nopen:{t.id}'}] for t in tasks])
                    reminder.last_sent=utc.replace(tzinfo=None);db.commit()
                    continue
                elif reminder.kind=='habits':
                    hs=db.scalars(select(Habit).where(Habit.user_id==user.id)).all()
                    checks={x.habit_id for x in db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day==local.date())).all()}
                    pending=[h for h in hs if upgrade_habit_scheduled(db,user,h,local.date()) and h.id not in checks]
                    content+='\n\n'+('\n'.join('• '+h.name for h in pending[:6]) if pending else 'Все привычки выполнены!')
                elif reminder.kind in ('schedule','schedule_tomorrow'):
                    target_day=local.date()+datetime.timedelta(days=1) if reminder.kind=='schedule_tomorrow' else local.date()
                    lessons=db.scalars(select(Lesson).where(Lesson.user_id==user.id,Lesson.weekday==target_day.weekday()).order_by(Lesson.period)).all()
                    content+='\n\n'+('\n'.join(f'{x.period}. {x.subject} {x.start}' for x in lessons) if lessons else 'Уроков нет.')
                notify(link.chat_id,'🔔 '+content,[[{'text':'📅 Мой день','callback_data':'today'}]])
                reminder.last_sent=utc.replace(tzinfo=None);db.commit()
            except Exception as exc:
                db.rollback();print('Reminder error:',repr(exc),flush=True)

def in_quiet(now,start,end):
    if not start or not end or start==end:return False
    cur=now.strftime('%H:%M')
    return start<=cur<end if start<end else cur>=start or cur<end

def main():
    if not TOKEN:print('TELEGRAM_BOT_TOKEN is missing',flush=True);return
    try:
        tg('setChatMenuButton',{'menu_button':json.dumps({'type':'web_app','text':'My-Study','web_app':{'url':SITE}},ensure_ascii=False)},timeout=10)
    except Exception:print('Could not configure Mini App menu; retry on next restart',flush=True)
    print('StudyFlow Telegram bot running',flush=True)
    offset=0
    try:tg('setMyCommands',{'commands':json.dumps(COMMANDS,ensure_ascii=False)},timeout=10)
    except Exception:print('Could not update bot command menu',flush=True)
    start_notification_worker()
    try: tg('deleteWebhook',{'drop_pending_updates':'false'},timeout=10)
    except Exception as exc:print('Webhook warning:',repr(exc),flush=True)
    while not STOP.is_set():
        try:
            updates=tg('getUpdates',{'offset':offset,'timeout':10,'allowed_updates':json.dumps(['message','callback_query'])},timeout=20)
            for update in updates:
                offset=update['update_id']+1
                try:
                    if 'message' in update:handle(update['message'])
                    elif 'callback_query' in update:callback(update['callback_query'])
                except Exception:traceback.print_exc()
        except Exception:traceback.print_exc();STOP.wait(5)

if __name__=='__main__':main()

