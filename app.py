from __future__ import annotations
import os, re, uuid, hmac, hashlib, secrets, mimetypes, json
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (create_engine, String, Integer, Boolean, DateTime, Date, ForeignKey,
                        Text, Float, UniqueConstraint, select, func, and_)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
from sqlalchemy.exc import IntegrityError
import assistant_service as assistant

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv('DATA_DIR', str(BASE / 'data'))).resolve()
UPLOAD_DIR = DATA_DIR / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_URL = os.getenv('DATABASE_URL', f"sqlite:///{DATA_DIR / 'studyflow.db'}")
if DB_URL.startswith('sqlite'):
    engine = create_engine(DB_URL, connect_args={'check_same_thread': False, 'timeout': 30}, pool_pre_ping=True)
    from sqlalchemy import event
    @event.listens_for(engine, 'connect')
    def _sqlite_fk(dbapi_connection, connection_record):
        cursor=dbapi_connection.cursor(); cursor.execute('PRAGMA foreign_keys=ON'); cursor.execute('PRAGMA journal_mode=WAL'); cursor.close()
else:
    engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
def hash_password(password: str) -> str:
    salt=secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,310000)
    return 'pbkdf2_sha256$310000$'+salt.hex()+'$'+digest.hex()
def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex=encoded.split('$')
        if scheme!='pbkdf2_sha256': return False
        digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt_hex),int(rounds))
        return hmac.compare_digest(digest.hex(),digest_hex)
    except Exception: return False
MAX_UPLOAD = int(os.getenv('MAX_UPLOAD_MB', '8')) * 1024 * 1024
ALLOWED_MIME = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(255), unique=True, index=True)
    username: Mapped[str]=mapped_column(String(40), unique=True, index=True)
    password_hash: Mapped[str]=mapped_column(String(255))
    created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
    display_name: Mapped[str]=mapped_column(String(80), default='')
    timezone: Mapped[str]=mapped_column(String(80), default='Europe/Stockholm')
    sessions: Mapped[list['AuthSession']]=relationship(back_populates='user', cascade='all, delete-orphan')
class AuthSession(Base):
    __tablename__='auth_sessions'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str]=mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime, index=True)
    user: Mapped[User]=relationship(back_populates='sessions')
class Habit(Base):
    __tablename__='habits'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id', ondelete='CASCADE'),index=True)
    name: Mapped[str]=mapped_column(String(120)); days: Mapped[str]=mapped_column(String(20),default='0,1,2,3,4,5,6'); created_at: Mapped[date]=mapped_column(Date,default=date.today)
class HabitCheck(Base):
    __tablename__='habit_checks'; __table_args__=(UniqueConstraint('habit_id','day'),)
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    habit_id: Mapped[int]=mapped_column(ForeignKey('habits.id',ondelete='CASCADE'),index=True); day: Mapped[date]=mapped_column(Date)
class Task(Base):
    __tablename__='tasks'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    title: Mapped[str]=mapped_column(String(240)); subject: Mapped[str]=mapped_column(String(120),default=''); description: Mapped[str]=mapped_column(Text,default='')
    due: Mapped[Optional[date]]=mapped_column(Date,nullable=True); priority: Mapped[str]=mapped_column(String(12),default='normal'); done: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class TaskSnooze(Base):
    __tablename__='task_snoozes'
    __table_args__=(UniqueConstraint('user_id','task_id'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    task_id: Mapped[int]=mapped_column(ForeignKey('tasks.id',ondelete='CASCADE'),index=True)
    send_at: Mapped[datetime]=mapped_column(DateTime,index=True)

class AIUsage(Base):
    __tablename__='ai_usage'
    scope: Mapped[str]=mapped_column(String(64),primary_key=True)
    day: Mapped[date]=mapped_column(Date,primary_key=True)
    requests: Mapped[int]=mapped_column(Integer,default=0)

class Attachment(Base):
    __tablename__='task_attachments'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    task_id: Mapped[int]=mapped_column(ForeignKey('tasks.id',ondelete='CASCADE'),index=True); filename: Mapped[str]=mapped_column(String(255)); stored_name: Mapped[str]=mapped_column(String(255)); mime: Mapped[str]=mapped_column(String(80))
class Lesson(Base):
    __tablename__='lessons'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    weekday: Mapped[int]=mapped_column(Integer); period: Mapped[int]=mapped_column(Integer); subject: Mapped[str]=mapped_column(String(120)); start: Mapped[str]=mapped_column(String(5),default=''); finish: Mapped[str]=mapped_column(String(5),default=''); room: Mapped[str]=mapped_column(String(80),default='')
class Grade(Base):
    __tablename__='grades'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    subject: Mapped[str]=mapped_column(String(120)); grade: Mapped[int]=mapped_column(Integer); day: Mapped[date]=mapped_column(Date)
class CheatSheet(Base):
    __tablename__='cheat_sheets'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    title: Mapped[str]=mapped_column(String(180)); subject: Mapped[str]=mapped_column(String(120),default=''); note: Mapped[str]=mapped_column(Text,default=''); stored_name: Mapped[str]=mapped_column(String(255)); filename: Mapped[str]=mapped_column(String(255)); mime: Mapped[str]=mapped_column(String(80)); created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Deck(Base):
    __tablename__='flashcard_decks'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True); title: Mapped[str]=mapped_column(String(180)); subject: Mapped[str]=mapped_column(String(120),default=''); created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Flashcard(Base):
    __tablename__='flashcards'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True); deck_id: Mapped[int]=mapped_column(ForeignKey('flashcard_decks.id',ondelete='CASCADE'),index=True)
    front: Mapped[str]=mapped_column(Text); back: Mapped[str]=mapped_column(Text); created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class FlashcardReview(Base):
    __tablename__='flashcard_reviews'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True); card_id: Mapped[int]=mapped_column(ForeignKey('flashcards.id',ondelete='CASCADE'),index=True)
    rating: Mapped[str]=mapped_column(String(12)); reviewed_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); next_review: Mapped[date]=mapped_column(Date)
class Goal(Base):
    __tablename__='goals'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True); title: Mapped[str]=mapped_column(String(180)); description: Mapped[str]=mapped_column(Text,default='')
    target: Mapped[float]=mapped_column(Float,default=100); progress: Mapped[float]=mapped_column(Float,default=0); unit: Mapped[str]=mapped_column(String(40),default='%'); deadline: Mapped[Optional[date]]=mapped_column(Date,nullable=True); done: Mapped[bool]=mapped_column(Boolean,default=False)
class CalendarEvent(Base):
    __tablename__='calendar_events'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True); title: Mapped[str]=mapped_column(String(180)); kind: Mapped[str]=mapped_column(String(20),default='event')
    start_at: Mapped[datetime]=mapped_column(DateTime); end_at: Mapped[Optional[datetime]]=mapped_column(DateTime,nullable=True); color: Mapped[str]=mapped_column(String(20),default='violet'); note: Mapped[str]=mapped_column(Text,default='')
class PomodoroSession(Base):
    __tablename__='pomodoro_sessions'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True); subject: Mapped[str]=mapped_column(String(120),default=''); duration_minutes: Mapped[int]=mapped_column(Integer); started_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); completed: Mapped[bool]=mapped_column(Boolean,default=True)
class UserSetting(Base):
    __tablename__='user_settings'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True); key: Mapped[str]=mapped_column(String(80)); value: Mapped[str]=mapped_column(Text,default=''); __table_args__=(UniqueConstraint('user_id','key'),)
class TelegramLink(Base):
    __tablename__='telegram_links'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),unique=True,index=True); chat_id: Mapped[str]=mapped_column(String(80),unique=True); linked_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class TelegramCode(Base):
    __tablename__='telegram_codes'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True); code: Mapped[str]=mapped_column(String(32),unique=True); expires_at: Mapped[datetime]=mapped_column(DateTime)
class NotificationSetting(Base):
    __tablename__='notification_settings'
    id: Mapped[int]=mapped_column(primary_key=True); user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),unique=True,index=True)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True); interval_minutes: Mapped[int]=mapped_column(Integer,default=1440); send_time: Mapped[str]=mapped_column(String(5),default='19:00'); quiet_start: Mapped[str]=mapped_column(String(5),default='22:00'); quiet_end: Mapped[str]=mapped_column(String(5),default='08:00'); last_sent: Mapped[Optional[datetime]]=mapped_column(DateTime,nullable=True)

class Reminder(Base):
    __tablename__='reminders'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    title: Mapped[str]=mapped_column(String(120),default='Напоминание')
    kind: Mapped[str]=mapped_column(String(20),default='general')
    send_time: Mapped[str]=mapped_column(String(5),default='19:00')
    days: Mapped[str]=mapped_column(String(20),default='0,1,2,3,4,5,6')
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    last_sent: Mapped[Optional[datetime]]=mapped_column(DateTime,nullable=True)

class ReminderTiming(Base):
    __tablename__='reminder_timings'
    reminder_id: Mapped[int]=mapped_column(ForeignKey('reminders.id',ondelete='CASCADE'),primary_key=True)
    mode: Mapped[str]=mapped_column(String(16),default='fixed')  # fixed, eve, before
    event_source: Mapped[str]=mapped_column(String(16),default='schedule')  # schedule, calendar
    event_id: Mapped[Optional[int]]=mapped_column(Integer,nullable=True)
    minutes_before: Mapped[int]=mapped_column(Integer,default=60)
    last_event_key: Mapped[str]=mapped_column(String(120),default='')

Base.metadata.create_all(engine)
app=FastAPI(title='My-Study 2.1',version='2.1.0')
app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')

def dbdep():
    db=SessionLocal()
    try: yield db
    finally: db.close()
def token_hash(token:str)->str: return hashlib.sha256(token.encode()).hexdigest()
def current_user(request:Request, db:Session=Depends(dbdep))->User:
    token=request.cookies.get('sf_session','')
    if not token: raise HTTPException(401,'Требуется вход')
    s=db.scalar(select(AuthSession).where(AuthSession.token_hash==token_hash(token),AuthSession.expires_at>datetime.utcnow()))
    if not s: raise HTTPException(401,'Сессия истекла')
    u=db.get(User,s.user_id)
    if not u: raise HTTPException(401,'Пользователь не найден')
    return u

def owned(db:Session, model, item_id:int, user:User):
    item=db.scalar(select(model).where(model.id==item_id,model.user_id==user.id))
    if not item: raise HTTPException(404,'Запись не найдена')
    return item

def clean_date(v):
    if not v: return None
    try:return date.fromisoformat(str(v)[:10])
    except ValueError: raise HTTPException(422,'Неверная дата')
def clean_dt(v):
    try:
        d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
        return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
    except Exception: raise HTTPException(422,'Неверная дата и время')
def serialize(obj):
    out={c.name:getattr(obj,c.name) for c in obj.__table__.columns}
    for k,v in out.items():
        if isinstance(v,(date,datetime)): out[k]=v.isoformat()
    return out

@app.middleware('http')
async def security_headers(request:Request, call_next):
    if request.method in {'POST','PUT','PATCH','DELETE'} and request.url.path not in {'/api/register','/api/login'} and request.url.path.startswith('/api/'):
        c=request.cookies.get('sf_csrf'); h=request.headers.get('x-csrf-token')
        if not c or not h or not hmac.compare_digest(c,h): return JSONResponse({'detail':'CSRF check failed'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'; response.headers['X-Frame-Options']='DENY'; response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    return response

@app.get('/')
def home(): return FileResponse(BASE/'static'/'index.html')
@app.get('/api/health')
def health(): return {'ok':True,'version':'2.1.0'}
class Credentials(BaseModel): email:str; username:str; password:str=Field(min_length=8,max_length=128); display_name:str=''
class LoginData(BaseModel): login:str; password:str

def set_auth(response:Response, db:Session, user:User):
    raw=secrets.token_urlsafe(36); db.add(AuthSession(user_id=user.id,token_hash=token_hash(raw),expires_at=datetime.utcnow()+timedelta(days=30)))
    csrf=secrets.token_urlsafe(24)
    secure=os.getenv('COOKIE_SECURE','0')=='1'
    response.set_cookie('sf_session',raw,max_age=30*86400,httponly=True,samesite='lax',secure=secure,path='/')
    response.set_cookie('sf_csrf',csrf,max_age=30*86400,httponly=False,samesite='lax',secure=secure,path='/')

@app.post('/api/register')
def register(data:Credentials,response:Response,db:Session=Depends(dbdep)):
    email=data.email.strip().lower(); username=data.username.strip()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email): raise HTTPException(422,'Укажи корректный email')
    if not re.fullmatch(r'[A-Za-z0-9_]{3,40}',username): raise HTTPException(422,'Логин: 3–40 символов, латиница, цифры и _')
    if db.scalar(select(User).where((User.email==email)|(User.username==username))): raise HTTPException(409,'Email или логин уже зарегистрирован')
    u=User(email=email,username=username,password_hash=hash_password(data.password),display_name=(data.display_name.strip() or username)[:80])
    db.add(u); db.flush(); db.add(NotificationSetting(user_id=u.id)); ensure_default_reminders(db,u.id); set_auth(response,db,u); db.commit()
    return {'ok':True,'user':{'id':u.id,'email':u.email,'username':u.username,'display_name':u.display_name}}
@app.post('/api/login')
def login(data:LoginData,response:Response,db:Session=Depends(dbdep)):
    key=data.login.strip().lower(); u=db.scalar(select(User).where((User.email==key)|(func.lower(User.username)==key)))
    if not u or not verify_password(data.password,u.password_hash): raise HTTPException(401,'Неверный логин или пароль')
    ensure_default_reminders(db,u.id);set_auth(response,db,u); db.commit(); return {'ok':True}
def issue_telegram_auth_link(db,user,purpose):
    raw=secrets.token_urlsafe(32)
    db.query(UserSetting).filter(UserSetting.user_id==user.id,UserSetting.key.like('auth-link:%')).delete(synchronize_session=False)
    db.add(UserSetting(user_id=user.id,key='auth-link:'+token_hash(raw),value=json.dumps({'purpose':purpose,'expires':int(datetime.now(timezone.utc).timestamp())+600})))
    db.commit()
    return raw

def find_auth_link(db,token,purpose):
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,60}',token): raise HTTPException(400,'Ссылка недействительна или истекла. Получи новую в боте.')
    row=db.scalar(select(UserSetting).where(UserSetting.key=='auth-link:'+token_hash(token)))
    if not row: raise HTTPException(400,'Ссылка недействительна или уже использована.')
    data=json.loads(row.value)
    if data.get('purpose')!=purpose or data.get('expires',0)<datetime.now(timezone.utc).timestamp(): raise HTTPException(400,'Ссылка недействительна или истекла. Получи новую в боте.')
    user=db.get(User,row.user_id)
    if not user: raise HTTPException(400,'Аккаунт не найден')
    return row,user

_auth_bot_cache={'username':'','expires':0}
@app.get('/api/auth/options')
def auth_options(request:Request,response:Response):
    if not request.cookies.get('sf_csrf'):
        response.set_cookie('sf_csrf',secrets.token_urlsafe(24),max_age=1800,samesite='lax',secure=os.getenv('COOKIE_SECURE','0')=='1',path='/')
    response.headers['Cache-Control']='no-store'
    username=os.getenv('TELEGRAM_BOT_USERNAME','').strip().lstrip('@')
    now=datetime.now(timezone.utc).timestamp()
    if not username and _auth_bot_cache['expires']>now: username=_auth_bot_cache['username']
    if not username and os.getenv('TELEGRAM_BOT_TOKEN','').strip():
        try:
            import urllib.request
            with urllib.request.urlopen('https://api.telegram.org/bot'+os.environ['TELEGRAM_BOT_TOKEN'].strip()+'/getMe',timeout=5) as r: data=json.loads(r.read(16384))
            username=data.get('result',{}).get('username','') if data.get('ok') else ''
            if username: _auth_bot_cache.update(username=username,expires=now+600)
        except Exception: pass
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}',username): username=''
    return {'bot_url':'https://t.me/'+username if username else None}

class TelegramAuthData(BaseModel):
    init_data:str=Field(min_length=1,max_length=16000)

@app.post('/api/auth/telegram')
def login_telegram(data:TelegramAuthData,response:Response,db:Session=Depends(dbdep)):
    from urllib.parse import parse_qsl
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise HTTPException(503,'Telegram не подключён на сервере')
    try:
        pairs=parse_qsl(data.init_data,keep_blank_values=True,strict_parsing=True)
        fields=dict(pairs)
        if len(fields)!=len(pairs): raise ValueError()
        received=fields.pop('hash')
        signed='\n'.join(k+'='+v for k,v in sorted(fields.items()))
        secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
        expected=hmac.new(secret,signed.encode(),hashlib.sha256).hexdigest()
        now=int(datetime.now(timezone.utc).timestamp()); issued=int(fields['auth_date'])
        if not hmac.compare_digest(expected,received) or not -30<=now-issued<=600: raise ValueError()
        telegram_user=json.loads(fields['user']); telegram_id=telegram_user['id']
        if type(telegram_id) is not int or telegram_id<=0: raise ValueError()
    except Exception: raise HTTPException(401,'Проверка Telegram не пройдена. Закрой и заново открой Mini App.') from None
    link=db.scalar(select(TelegramLink).where(TelegramLink.chat_id==str(telegram_id)))
    user=db.get(User,link.user_id) if link else None
    if not user: raise HTTPException(403,'Сначала войди с паролем и привяжи Telegram в настройках сайта.')
    set_auth(response,db,user);db.commit();return {'ok':True}

class AuthLinkData(BaseModel):
    token:str=Field(min_length=40,max_length=60)
    purpose:str=Field(pattern='^(login|reset)$')

@app.post('/api/auth/link-info')
def auth_link_info(data:AuthLinkData,db:Session=Depends(dbdep)):
    _,user=find_auth_link(db,data.token,data.purpose)
    return {'username':user.username,'display_name':user.display_name}

@app.post('/api/auth/link-login')
def auth_link_login(data:AuthLinkData,response:Response,db:Session=Depends(dbdep)):
    if data.purpose!='login': raise HTTPException(400,'Неверный тип ссылки')
    row,user=find_auth_link(db,data.token,'login')
    count=db.query(UserSetting).filter(UserSetting.id==row.id,UserSetting.value==row.value).delete(synchronize_session=False)
    if count!=1: db.rollback();raise HTTPException(400,'Ссылка уже использована')
    set_auth(response,db,user);db.commit();return {'ok':True}

class ResetPasswordData(BaseModel):
    token:str=Field(min_length=40,max_length=60)
    password:str=Field(min_length=8,max_length=128)

@app.post('/api/auth/reset-password')
def reset_password(data:ResetPasswordData,response:Response,db:Session=Depends(dbdep)):
    row,user=find_auth_link(db,data.token,'reset')
    count=db.query(UserSetting).filter(UserSetting.id==row.id,UserSetting.value==row.value).delete(synchronize_session=False)
    if count!=1: db.rollback();raise HTTPException(400,'Ссылка уже использована')
    user.password_hash=hash_password(data.password)
    db.query(AuthSession).filter(AuthSession.user_id==user.id).delete(synchronize_session=False)
    set_auth(response,db,user);db.commit();return {'ok':True}


@app.post('/api/logout')
def logout(request:Request,response:Response,db:Session=Depends(dbdep)):
    token=request.cookies.get('sf_session','')
    if token:
        s=db.scalar(select(AuthSession).where(AuthSession.token_hash==token_hash(token)))
        if s: db.delete(s); db.commit()
    response.delete_cookie('sf_session',path='/'); response.delete_cookie('sf_csrf',path='/'); return {'ok':True}
@app.get('/api/me')
def me(user:User=Depends(current_user)):
    return {'id':user.id,'email':user.email,'username':user.username,'display_name':user.display_name,'timezone':user.timezone,'created_at':user.created_at.isoformat()}
@app.put('/api/profile')
def update_profile(data:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if 'display_name' in data: user.display_name=str(data['display_name']).strip()[:80]
    if 'timezone' in data: user.timezone=str(data['timezone'])[:80]
    db.commit(); return {'ok':True}

# Generic owned CRUD helpers
@app.get('/api/habits')
def list_habits(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    hs=db.scalars(select(Habit).where(Habit.user_id==user.id).order_by(Habit.id.desc())).all(); today=date.today()
    checks=db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id)).all(); by={}
    for c in checks: by.setdefault(c.habit_id,[]).append(c.day.isoformat())
    return [{**serialize(h),'days':[int(x) for x in h.days.split(',') if x!=''],'checks':by.get(h.id,[]),**habit_details(db,user.id,h.id)} for h in hs]
@app.post('/api/habits')
def add_habit(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    name=str(d.get('name','')).strip(); days=d.get('days',list(range(7)))
    if not name or len(name)>120 or not isinstance(days,list) or any(not isinstance(x,int) or x not in range(7) for x in days): raise HTTPException(422,'Проверь название и дни')
    cfg=validate_habit_config(d.get('config',{}))
    x=Habit(user_id=user.id,name=name,created_at=user_local_day(user),days=','.join(map(str,sorted(set(days)))));db.add(x);db.flush();feature_put(db,user.id,'habit-config:'+str(x.id),cfg);db.commit();db.refresh(x);return serialize(x)
@app.put('/api/habits/{hid}/check')
def habit_check(hid:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    h=owned(db,Habit,hid,user); day=clean_date(d.get('day')) or date.today(); cfg=habit_config(db,user.id,h.id)
    progress=feature_get(db,user.id,f'habit-progress:{hid}:{day}',{});progress['amount']=cfg['target'] if d.get('done') else 0;feature_put(db,user.id,f'habit-progress:{hid}:{day}',progress)
    c=db.scalar(select(HabitCheck).where(HabitCheck.habit_id==h.id,HabitCheck.day==day))
    if d.get('done') and not c: db.add(HabitCheck(user_id=user.id,habit_id=h.id,day=day))
    if not d.get('done') and c: db.delete(c)
    db.commit(); return {'ok':True}
@app.delete('/api/habits/{hid}')
def del_habit(hid:int,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    h=owned(db,Habit,hid,user);db.query(HabitCheck).filter_by(habit_id=h.id,user_id=user.id).delete();db.query(UserSetting).filter(UserSetting.user_id==user.id,(UserSetting.key=='habit-config:'+str(hid))|UserSetting.key.like('habit-progress:'+str(hid)+':%')).delete(synchronize_session=False);db.delete(h);db.commit();return {'ok':True}

@app.get('/api/habit-notes')
def habit_notes(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    prefix='habit-note:'
    return {x.key[len(prefix):]:x.value for x in db.scalars(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key.like(prefix+'%'))).all()}
@app.put('/api/habit-notes')
def save_habit_note(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    day=clean_date(d.get('day')); note=str(d.get('note','')).strip()
    if not day or len(note)>1000: raise HTTPException(422,'Проверь дату и заметку (до 1000 символов)')
    key='habit-note:'+day.isoformat(); row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key==key))
    if note:
        if row: row.value=note
        else: db.add(UserSetting(user_id=user.id,key=key,value=note))
    elif row: db.delete(row)
    db.commit(); return {'ok':True}

@app.get('/api/whiteboard')
def get_whiteboard(task_id:int|None=None,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if task_id is not None: owned(db,Task,task_id,user)
    row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='whiteboard:'+str(task_id or 'personal')))
    return json.loads(row.value) if row else {'revision':0,'strokes':[]}

@app.put('/api/whiteboard')
def save_whiteboard(d:dict,task_id:int|None=None,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if task_id is not None: owned(db,Task,task_id,user)
    revision=d.get('revision')
    if d.get('layout') not in (None,'large-v1'): raise HTTPException(422,'Неизвестный формат доски')
    large=d.get('layout')=='large-v1'
    world_w,world_h=(12000,8000) if large else (1600,1000)
    if type(revision) is not int or revision<0: raise HTTPException(422,'Некорректная версия доски')
    def validate_page(data):
        if not isinstance(data,dict): raise HTTPException(422,'Некорректный лист')
        strokes=data.get('strokes'); images=data.get('images',[]); grid=data.get('grid',True)
        if not isinstance(strokes,list) or len(strokes)>(30000 if large else 1500): raise HTTPException(422,'Некорректная доска')
        total=0
        for stroke in strokes:
            if not isinstance(stroke,dict) or stroke.get('tool') not in ('pen','marker','line','eraser','rectangle','ellipse','triangle','parallelogram','arrow','cylinder','box','cone','sphere','pyramid') or not re.fullmatch(r'#[0-9a-fA-F]{6}',str(stroke.get('color',''))): raise HTTPException(422,'Некорректный инструмент')
            width=stroke.get('width'); points=stroke.get('points')
            if type(width) not in (int,float) or not 1<=width<=40 or not isinstance(points,list) or not 1<=len(points)<=4000: raise HTTPException(422,'Некорректная линия')
            total+=len(points)
            if total>(800000 if large else 40000): raise HTTPException(413,'Лист слишком большой. Экспортируй PNG и создай следующий.')
            for point in points:
                if not isinstance(point,list) or len(point)!=2 or any(type(v) not in (int,float) for v in point) or not (0<=point[0]<=world_w and 0<=point[1]<=world_h): raise HTTPException(422,'Некорректная координата')
        if not isinstance(images,list) or len(images)>(160 if large else 8) or type(grid) is not bool: raise HTTPException(422,'Слишком много фото на доске')
        clean_images=[]
        for image in images:
            if not isinstance(image,dict): raise HTTPException(422,'Некорректное фото')
            stored=image.get('stored_name','')
            if not isinstance(stored,str) or not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png|webp)',stored): raise HTTPException(422,'Некорректное фото')
            asset=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='board-image:'+stored))
            if not asset or not (UPLOAD_DIR/stored).is_file(): raise HTTPException(404,'Фото не найдено')
            x,y,w,h=(image.get(k) for k in ('x','y','w','h'))
            if any(type(v) not in (int,float) for v in (x,y,w,h)) or not (0<=x<=world_w-40 and 0<=y<=world_h-40 and 40<=w<=world_w and 40<=h<=world_h and x+w<=world_w+.01 and y+h<=world_h+.01): raise HTTPException(422,'Фото выходит за границы доски')
            clean_images.append({'stored_name':stored,'x':x,'y':y,'w':w,'h':h})
        return {'strokes':strokes,'images':clean_images,'grid':grid}
    pages=d.get('pages')
    if pages is not None:
        if task_id is None: raise HTTPException(422,'Несколько листов доступны только для ДЗ')
        if not isinstance(pages,list) or not 1<=len(pages)<=20: raise HTTPException(422,'В доске ДЗ должно быть от 1 до 20 листов')
        pages=[validate_page(p) for p in pages]
        page=pages[0]
    else: page=validate_page(d)
    key='whiteboard:'+str(task_id or 'personal'); row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key==key))
    old=json.loads(row.value) if row else {'revision':0}
    if old['revision']!=revision: raise HTTPException(409,'Доска изменена в другом окне. Экспортируй PNG и перезагрузи страницу.')
    if (old.get('pages') and pages is None and not large) or (old.get('layout')=='large-v1' and not large): raise HTTPException(409,'Обнови страницу для сохранения всех листов')
    result={'revision':revision+1,**page}
    if large:
        if pages is not None: raise HTTPException(422,'Большая доска не использует отдельные листы')
        result['layout']='large-v1';result['canvas']={'width':12000,'height':8000}
    if pages is not None: result['pages']=pages
    value=json.dumps(result,separators=(',',':'))
    if len(value)>(32000000 if large else (4000000 if task_id is not None else 1000000)): raise HTTPException(413,'Доска слишком большая. Экспортируй PNG.')
    if row and old.get('strokes') is not None:
        history_key='board-history:'+str(task_id or 'personal')
        history=upgrade_get(db,user.id,history_key,[])
        history.append({'at':datetime.now(timezone.utc).isoformat(),'document':old})
        while len(history)>12 or len(json.dumps(history))>4000000:
            if not history:break
            history.pop(0)
        upgrade_put(db,user.id,history_key,history)
    if row:
        count=db.query(UserSetting).filter(UserSetting.id==row.id,UserSetting.value==row.value).update({'value':value},synchronize_session=False)
        if count!=1: db.rollback(); raise HTTPException(409,'Доска изменена в другом окне')
    else: db.add(UserSetting(user_id=user.id,key=key,value=value))
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409,'Доска изменена в другом окне') from None
    return {'revision':revision+1}


@app.get('/api/tasks')
def list_tasks(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    ts=db.scalars(select(Task).where(Task.user_id==user.id).order_by(Task.done,Task.due,Task.id.desc())).all()
    return [{**serialize(t),'attachments':[serialize(a) for a in db.scalars(select(Attachment).where(Attachment.task_id==t.id,Attachment.user_id==user.id)).all()]} for t in ts]
@app.post('/api/tasks')
def add_task(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    title=str(d.get('title','')).strip()
    if not title or len(title)>240: raise HTTPException(422,'Название задания обязательно')
    t=Task(user_id=user.id,title=title,subject=str(d.get('subject',''))[:120],description=str(d.get('description',''))[:5000],due=clean_date(d.get('due')),priority=d.get('priority','normal') if d.get('priority') in {'low','normal','high'} else 'normal')
    db.add(t); db.commit(); db.refresh(t); return serialize(t)
@app.put('/api/tasks/{tid}')
def update_task(tid:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    t=owned(db,Task,tid,user)
    for k in ('title','subject','description','priority'):
        if k in d: setattr(t,k,str(d[k])[:{'title':240,'subject':120,'description':5000,'priority':12}[k]])
    if 'due' in d:t.due=clean_date(d['due'])
    if 'done' in d:
        record_task_completion(db,t,bool(d['done']));t.done=bool(d['done'])
    db.commit(); return {'ok':True}
@app.delete('/api/tasks/{tid}')
def del_task(tid:int,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    t=owned(db,Task,tid,user)
    return upgrade_trash(db,user,'task',t)
async def store_image(file:UploadFile):
    mime=file.content_type or mimetypes.guess_type(file.filename or '')[0]
    if mime not in ALLOWED_MIME: raise HTTPException(415,'Разрешены JPG, PNG, WEBP и GIF')
    raw=await file.read(MAX_UPLOAD+1)
    if not raw or len(raw)>MAX_UPLOAD: raise HTTPException(413,f'Максимальный размер файла {MAX_UPLOAD//1024//1024} МБ')
    signatures={'image/jpeg':raw.startswith(b'\xff\xd8\xff'),'image/png':raw.startswith(b'\x89PNG\r\n\x1a\n'),'image/gif':raw.startswith((b'GIF87a',b'GIF89a')),'image/webp':raw.startswith(b'RIFF') and raw[8:12]==b'WEBP'}
    if not signatures.get(mime,False): raise HTTPException(415,'Файл не соответствует типу изображения')
    ext={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif'}[mime]; stored=uuid.uuid4().hex+ext
    (UPLOAD_DIR/stored).write_bytes(raw); return stored,mime,(file.filename or 'image'+ext)[:255]
@app.post('/api/whiteboard/images')
async def upload_whiteboard_image(file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if file.content_type not in ('image/jpeg','image/png','image/webp'): raise HTTPException(415,'Разрешены JPG, PNG и WEBP')
    if db.scalar(select(func.count()).select_from(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key.like('board-image:%')))>=200:
        raise HTTPException(413,'Достигнут лимит изображений аккаунта (200)')
    stored,mime,name=await store_image(file)
    db.add(UserSetting(user_id=user.id,key='board-image:'+stored,value=json.dumps({'mime':mime,'filename':name})))
    try: db.commit()
    except Exception:
        db.rollback();(UPLOAD_DIR/stored).unlink(missing_ok=True);raise
    return {'stored_name':stored}

@app.get('/api/whiteboard/images/{stored_name}')
def whiteboard_image(stored_name:str,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png|webp)',stored_name): raise HTTPException(404,'Фото не найдено')
    row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='board-image:'+stored_name))
    if not row or not (UPLOAD_DIR/stored_name).is_file(): raise HTTPException(404,'Фото не найдено')
    return FileResponse(UPLOAD_DIR/stored_name,media_type=json.loads(row.value)['mime'],headers={'Cache-Control':'private, no-store'})


@app.post('/api/tasks/{tid}/attachments')
async def add_attachment(tid:int,file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(dbdep)):
    owned(db,Task,tid,user); stored,mime,name=await store_image(file); a=Attachment(user_id=user.id,task_id=tid,stored_name=stored,mime=mime,filename=name); db.add(a); db.commit(); db.refresh(a); return serialize(a)
@app.delete('/api/attachments/{aid}')
def del_attachment(aid:int,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    a=owned(db,Attachment,aid,user); (UPLOAD_DIR/a.stored_name).unlink(missing_ok=True); db.delete(a); db.commit(); return {'ok':True}
@app.get('/api/files/{stored_name}')
def get_file(stored_name:str,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    a=db.scalar(select(Attachment).where(Attachment.stored_name==stored_name,Attachment.user_id==user.id)); s=db.scalar(select(CheatSheet).where(CheatSheet.stored_name==stored_name,CheatSheet.user_id==user.id))
    obj=a or s
    if not obj: raise HTTPException(404,'Файл не найден')
    path=UPLOAD_DIR/obj.stored_name
    if not path.is_file(): raise HTTPException(404,'Файл отсутствует')
    safe_name=re.sub(r'[^A-Za-z0-9._-]','_',obj.filename)[:120] or 'image'
    return FileResponse(path,media_type=obj.mime,headers={'Content-Disposition':f'inline; filename="{safe_name}"'})

@app.get('/api/lessons')
def lessons(user:User=Depends(current_user),db:Session=Depends(dbdep)): return [serialize(x) for x in db.scalars(select(Lesson).where(Lesson.user_id==user.id).order_by(Lesson.weekday,Lesson.period)).all()]
@app.post('/api/lessons')
def add_lesson(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    try: w=int(d.get('weekday')); p=int(d.get('period'))
    except: raise HTTPException(422,'Неверный день или номер урока')
    subject=str(d.get('subject','')).strip()
    if w not in range(7) or p not in range(1,21) or not subject: raise HTTPException(422,'Проверьте поля урока')
    x=Lesson(user_id=user.id,weekday=w,period=p,subject=subject[:120],start=str(d.get('start',''))[:5],finish=str(d.get('finish',''))[:5],room=str(d.get('room',''))[:80]); db.add(x); db.commit(); db.refresh(x); return serialize(x)
@app.put('/api/lessons/{id}')
def update_lesson(id:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    x=owned(db,Lesson,id,user)
    try:
        weekday=int(d.get('weekday',x.weekday)); period=int(d.get('period',x.period))
    except (TypeError,ValueError):
        raise HTTPException(422,'Неверный день или номер урока')
    subject=str(d.get('subject',x.subject)).strip()
    if weekday not in range(7) or period not in range(1,21) or not subject:
        raise HTTPException(422,'Проверьте поля урока')
    start=str(d.get('start',x.start) or '').strip()
    finish=str(d.get('finish',x.finish) or '').strip()
    if any(v and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v) for v in (start,finish)):
        raise HTTPException(422,'Время должно быть в формате ЧЧ:ММ')
    if start and finish and finish<=start:
        raise HTTPException(422,'Окончание урока должно быть позже начала')
    x.weekday=weekday; x.period=period; x.subject=subject[:120]
    x.start=start; x.finish=finish; x.room=str(d.get('room',x.room) or '').strip()[:80]
    db.commit(); db.refresh(x)
    return serialize(x)

@app.get('/api/public/developer')
def developer_profile():
    # Public profile details configured by the site owner, never bot credentials.
    return {'username':'saywest',
            'telegram_id':os.getenv('DEVELOPER_TELEGRAM_ID','').strip(),
            'avatar_url':os.getenv('DEVELOPER_AVATAR_URL','').strip()}

@app.delete('/api/lessons/{id}')
def del_lesson(id:int,user:User=Depends(current_user),db:Session=Depends(dbdep)): x=owned(db,Lesson,id,user); db.delete(x); db.commit(); return {'ok':True}
@app.get('/api/grades')
def grades(user:User=Depends(current_user),db:Session=Depends(dbdep)): return [serialize(x) for x in db.scalars(select(Grade).where(Grade.user_id==user.id).order_by(Grade.day.desc())).all()]
@app.post('/api/grades')
def add_grade(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    g=int(d.get('grade',0)); subject=str(d.get('subject','')).strip()
    if g not in range(1,6) or not subject: raise HTTPException(422,'Оценка должна быть от 1 до 5')
    x=Grade(user_id=user.id,subject=subject[:120],grade=g,day=clean_date(d.get('day')) or date.today()); db.add(x); db.commit(); db.refresh(x); return serialize(x)
@app.delete('/api/grades/{id}')
def del_grade(id:int,user:User=Depends(current_user),db:Session=Depends(dbdep)): x=owned(db,Grade,id,user); db.delete(x); db.commit(); return {'ok':True}

@app.get('/api/cheatsheets')
def cheats(user:User=Depends(current_user),db:Session=Depends(dbdep)): return [serialize(x) for x in db.scalars(select(CheatSheet).where(CheatSheet.user_id==user.id).order_by(CheatSheet.created_at.desc())).all()]
@app.post('/api/cheatsheets')
async def add_cheat(title:str=Form(...),subject:str=Form(''),note:str=Form(''),file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if not title.strip(): raise HTTPException(422,'Укажи название шпаргалки')
    stored,mime,name=await store_image(file); x=CheatSheet(user_id=user.id,title=title[:180],subject=subject[:120],note=note[:3000],stored_name=stored,filename=name,mime=mime); db.add(x); db.commit(); db.refresh(x); return serialize(x)
@app.delete('/api/cheatsheets/{id}')
def del_cheat(id:int,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    x=owned(db,CheatSheet,id,user); return upgrade_trash(db,user,'cheat',x)

@app.get('/api/decks')
def decks(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    ds=db.scalars(select(Deck).where(Deck.user_id==user.id).order_by(Deck.id.desc())).all(); return [{**serialize(x),'cards':[serialize(c) for c in db.scalars(select(Flashcard).where(Flashcard.deck_id==x.id,Flashcard.user_id==user.id)).all()]} for x in ds]
@app.post('/api/decks')
def add_deck(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    title=str(d.get('title','')).strip()
    if not title: raise HTTPException(422,'Укажи название колоды')
    x=Deck(user_id=user.id,title=title[:180],subject=str(d.get('subject',''))[:120]); db.add(x); db.commit(); db.refresh(x); return serialize(x)
@app.post('/api/decks/{deck_id}/cards')
def add_card(deck_id:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    deck=owned(db,Deck,deck_id,user); front=str(d.get('front','')).strip(); back=str(d.get('back','')).strip()
    if not front or not back: raise HTTPException(422,'Заполни вопрос и ответ')
    x=Flashcard(user_id=user.id,deck_id=deck.id,front=front[:3000],back=back[:3000]); db.add(x); db.commit(); db.refresh(x); return serialize(x)
@app.post('/api/cards/{card_id}/review')
def review_card(card_id:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    c=owned(db,Flashcard,card_id,user); rating=d.get('rating','again'); days={'again':0,'hard':1,'good':3,'easy':7}.get(rating,1)
    db.add(FlashcardReview(user_id=user.id,card_id=c.id,rating=rating,next_review=date.today()+timedelta(days=days))); db.commit(); return {'ok':True,'next_review':(date.today()+timedelta(days=days)).isoformat()}
@app.delete('/api/cards/{id}')
def del_card(id:int,user:User=Depends(current_user),db:Session=Depends(dbdep)): x=owned(db,Flashcard,id,user); db.delete(x); db.commit(); return {'ok':True}
@app.delete('/api/decks/{id}')
def del_deck(id:int,user:User=Depends(current_user),db:Session=Depends(dbdep)): x=owned(db,Deck,id,user); db.delete(x); db.commit(); return {'ok':True}

@app.get('/api/goals')
def goals(user:User=Depends(current_user),db:Session=Depends(dbdep)): return [{**serialize(x),**goal_details(db,user.id,x.id)} for x in db.scalars(select(Goal).where(Goal.user_id==user.id).order_by(Goal.done,Goal.id.desc())).all()]
@app.post('/api/goals')
def add_goal(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    title=str(d.get('title','')).strip()
    if not title: raise HTTPException(422,'Укажи цель')
    for key in ('target','progress'):
        if key in d and (type(d[key]) not in (int,float) or not __import__('math').isfinite(d[key])):raise HTTPException(422,'Некорректное числовое значение')
    x=Goal(user_id=user.id,title=title[:180],description=str(d.get('description',''))[:3000],target=max(0.01,float(d.get('target',100))),progress=max(0,float(d.get('progress',0))),unit=str(d.get('unit','%'))[:40],deadline=clean_date(d.get('deadline'))); x.done=x.progress>=x.target;db.add(x);db.flush();initialize_goal_blocks(db,user,x,d);db.commit();db.refresh(x);return {**serialize(x),**goal_details(db,user.id,x.id)}
@app.put('/api/goals/{id}')
def update_goal(id:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    x=owned(db,Goal,id,user)
    if 'progress' in d:
        if goal_details(db,user.id,id)['blocks']:raise HTTPException(409,'Прогресс этой цели считается по пунктам')
        value=d['progress']
        if type(value) not in (int,float) or not __import__('math').isfinite(value):raise HTTPException(422,'Некорректный прогресс')
        x.progress=max(0,value);x.done=x.progress>=x.target
    if 'title' in d: x.title=str(d['title'])[:180]
    if 'description' in d:x.description=str(d['description'])[:3000]
    if 'deadline' in d:x.deadline=clean_date(d['deadline'])
    db.commit(); return {'ok':True}
@app.delete('/api/goals/{id}')
def del_goal(id:int,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    x=owned(db,Goal,id,user); return upgrade_trash(db,user,'goal',x)

@app.get('/api/events')
def events(user:User=Depends(current_user),db:Session=Depends(dbdep)): return [serialize(x) for x in db.scalars(select(CalendarEvent).where(CalendarEvent.user_id==user.id).order_by(CalendarEvent.start_at)).all()]
@app.post('/api/events')
def add_event(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    title=str(d.get('title','')).strip()
    if not title: raise HTTPException(422,'Укажи название события')
    x=CalendarEvent(user_id=user.id,title=title[:180],kind=str(d.get('kind','event'))[:20],start_at=clean_dt(d.get('start_at')),end_at=clean_dt(d.get('end_at')) if d.get('end_at') else None,color=str(d.get('color','violet'))[:20],note=str(d.get('note',''))[:2000]); db.add(x); db.commit(); db.refresh(x); return serialize(x)
@app.delete('/api/events/{id}')
def del_event(id:int,user:User=Depends(current_user),db:Session=Depends(dbdep)): x=owned(db,CalendarEvent,id,user); db.delete(x); db.commit(); return {'ok':True}

@app.get('/api/pomodoro')
def pomodoro(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    xs=db.scalars(select(PomodoroSession).where(PomodoroSession.user_id==user.id).order_by(PomodoroSession.started_at.desc()).limit(100)).all(); return [serialize(x) for x in xs]
@app.post('/api/pomodoro')
def save_pomodoro(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    mins=int(d.get('duration_minutes',25))
    if mins not in range(1,241): raise HTTPException(422,'Неверная длительность')
    x=PomodoroSession(user_id=user.id,subject=str(d.get('subject',''))[:120],duration_minutes=mins,completed=bool(d.get('completed',True))); db.add(x); db.commit(); db.refresh(x); return serialize(x)

@app.get('/api/settings')
def settings(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    vals={x.key:x.value for x in db.scalars(select(UserSetting).where(UserSetting.user_id==user.id)).all()}; return {'widgets':vals.get('widgets','overview,tasks,habits,schedule,pomodoro,goals'),'theme':'deep-space'}
@app.put('/api/settings')
def save_settings(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    for k,v in d.items():
        key=str(k)[:80]; val=str(v)[:4000]; x=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key==key))
        if x:x.value=val
        else:db.add(UserSetting(user_id=user.id,key=key,value=val))
    db.commit(); return {'ok':True}
@app.get('/api/notifications')
def get_notifications(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    x=db.scalar(select(NotificationSetting).where(NotificationSetting.user_id==user.id))
    if not x: x=NotificationSetting(user_id=user.id); db.add(x); db.commit(); db.refresh(x)
    return serialize(x)
@app.put('/api/notifications')
def put_notifications(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    x=db.scalar(select(NotificationSetting).where(NotificationSetting.user_id==user.id))
    if not x:x=NotificationSetting(user_id=user.id); db.add(x)
    if 'enabled' in d:x.enabled=bool(d['enabled'])
    if 'interval_minutes' in d:
        n=int(d['interval_minutes']);
        if n<15 or n>10080: raise HTTPException(422,'Интервал должен быть от 15 минут до 7 дней')
        x.interval_minutes=n
    for k in ('send_time','quiet_start','quiet_end'):
        if k in d and re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',str(d[k])): setattr(x,k,d[k])
    db.commit(); return serialize(x)

# Individually scheduled reminders (all times in the user's configured timezone).
@app.get('/api/reminders')
def list_reminders(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    ensure_default_reminders(db,user.id); db.commit()
    return [reminder_data(db,x) for x in db.scalars(select(Reminder).where(Reminder.user_id==user.id).order_by(Reminder.send_time,Reminder.id)).all()]

def reminder_data(db,obj):
    out=serialize(obj)
    timing=db.get(ReminderTiming,obj.id)
    out.update({'mode':timing.mode if timing else 'fixed',
                'event_source':timing.event_source if timing else 'schedule',
                'event_id':timing.event_id if timing else None,
                'minutes_before':timing.minutes_before if timing else 60})
    return out

def save_reminder_timing(db,obj,d):
    mode=d.get('mode','fixed')
    source=d.get('event_source','schedule')
    if mode not in ('fixed','eve','before'): raise HTTPException(422,'Неверный способ напоминания')
    if source not in ('schedule','calendar'): raise HTTPException(422,'Неверный источник событий')
    try: minutes=int(d.get('minutes_before',60))
    except (ValueError,TypeError): raise HTTPException(422,'Неверный интервал')
    if minutes<1 or minutes>10080: raise HTTPException(422,'Интервал: от 1 минуты до 7 дней')
    event_id=d.get('event_id')
    if event_id in ('',None): event_id=None
    else:
        try: event_id=int(event_id)
        except (ValueError,TypeError): raise HTTPException(422,'Неверное событие')
        if event_id<=0: raise HTTPException(422,'Неверное событие')
    if source=='calendar' and event_id is not None:
        if not db.scalar(select(CalendarEvent.id).where(CalendarEvent.id==event_id,CalendarEvent.user_id==obj.user_id)):
            raise HTTPException(404,'Событие не найдено')
    timing=db.get(ReminderTiming,obj.id)
    if timing is None: timing=ReminderTiming(reminder_id=obj.id);db.add(timing)
    timing.mode=mode;timing.event_source=source;timing.event_id=event_id;timing.minutes_before=minutes
    timing.last_event_key=''

def reminder_fields(d, obj):
    if 'title' in d:
        title=str(d['title']).strip()
        if not 1<=len(title)<=120: raise HTTPException(422,'Название: от 1 до 120 символов')
        obj.title=title
    if 'kind' in d:
        if d['kind'] not in ('general','tasks','homework_eve','habits','schedule','schedule_tomorrow','goals','evening_summary'): raise HTTPException(422,'Неизвестный тип')
        obj.kind=d['kind']
    if 'send_time' in d:
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',str(d['send_time'])): raise HTTPException(422,'Неверное время')
        obj.send_time=d['send_time']
    if 'days' in d:
        days=d['days']
        if not isinstance(days,list) or not days or any(type(x)!=int or x not in range(7) for x in days):
            raise HTTPException(422,'Выбери хотя бы один день недели')
        obj.days=','.join(str(x) for x in sorted(set(days)))
    if 'enabled' in d:
        if not isinstance(d['enabled'],bool): raise HTTPException(422,'enabled должен быть boolean')
        obj.enabled=d['enabled']

@app.post('/api/reminders')
def create_reminder(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if db.scalar(select(func.count(Reminder.id)).where(Reminder.user_id==user.id))>=30:
        raise HTTPException(422,'Максимум 30 напоминаний')
    obj=Reminder(user_id=user.id); reminder_fields(d,obj)
    db.add(obj); db.flush(); save_reminder_timing(db,obj,d); db.commit(); db.refresh(obj); return reminder_data(db,obj)

@app.put('/api/reminders/{reminder_id}')
def update_reminder(reminder_id:int,d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    obj=owned(db,Reminder,reminder_id,user); reminder_fields(d,obj)
    if any(k in d for k in ('mode','event_source','event_id','minutes_before')):
        current=reminder_data(db,obj)
        save_reminder_timing(db,obj,{**current,**d})
    if any(k in d for k in ('send_time','days','enabled','mode','event_source','event_id','minutes_before')): obj.last_sent=None
    db.commit(); return reminder_data(db,obj)

@app.delete('/api/reminders/{reminder_id}')
def delete_reminder(reminder_id:int,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    obj=owned(db,Reminder,reminder_id,user); timing=db.get(ReminderTiming,obj.id)
    if timing: db.delete(timing)
    db.delete(obj); db.commit(); return {'ok':True}

@app.post('/api/reminders/test')
def test_reminder(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    link=db.scalar(select(TelegramLink).where(TelegramLink.user_id==user.id))
    if not link: raise HTTPException(400,'Сначала привяжи Telegram')
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise HTTPException(503,'Telegram-бот не настроен')
    import urllib.request,urllib.parse,json
    payload=urllib.parse.urlencode({'chat_id':link.chat_id,'text':'🔔 Тестовое напоминание StudyFlow\n\nУведомления подключены!\n\n🌐 https://my-study.bothost.tech','disable_web_page_preview':'true'}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=payload),timeout=12) as response:
            result=json.loads(response.read())
        if not result.get('ok'): raise ValueError(result.get('description','Telegram API error'))
    except Exception as exc:
        raise HTTPException(502,'Telegram не принял сообщение. Проверь привязку и запусти бота через /start.') from exc
    return {'ok':True}

@app.get('/api/telegram/link-code')
def telegram_code(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    code=secrets.token_urlsafe(6).replace('-','').replace('_','')[:8].upper(); db.query(TelegramCode).filter_by(user_id=user.id).delete(); db.add(TelegramCode(user_id=user.id,code=code,expires_at=datetime.utcnow()+timedelta(minutes=10))); db.commit(); return {'code':code,'expires_minutes':10,'telegram_url':f'https://t.me/StudyFlowGolub_bot?start=link_{code}'}
@app.get('/api/telegram/status')
def telegram_status(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    x=db.scalar(select(TelegramLink).where(TelegramLink.user_id==user.id)); return {'linked':bool(x),'chat_id':x.chat_id if x else None,'bot_configured':bool(os.getenv('TELEGRAM_BOT_TOKEN'))}
@app.delete('/api/telegram/link')
def telegram_unlink(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    x=db.scalar(select(TelegramLink).where(TelegramLink.user_id==user.id))
    if x: db.delete(x); db.commit()
    return {'ok':True}

@app.get('/api/stats')
def stats(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    today=date.today(); since=today-timedelta(days=29)
    habits=db.scalars(select(Habit).where(Habit.user_id==user.id)).all(); checks=db.scalars(select(HabitCheck).where(HabitCheck.user_id==user.id,HabitCheck.day>=since)).all()
    tasks=db.scalars(select(Task).where(Task.user_id==user.id)).all(); grades=db.scalars(select(Grade).where(Grade.user_id==user.id)).all(); pom=db.scalars(select(PomodoroSession).where(PomodoroSession.user_id==user.id,PomodoroSession.completed==True,PomodoroSession.started_at>=datetime.combine(since,datetime.min.time()))).all()
    history=[]
    checkset={(x.habit_id,x.day) for x in checks}
    for n in range(29,-1,-1):
        day=since+timedelta(days=n); eligible=[h for h in habits if str(day.weekday()) in h.days.split(',') and h.created_at<=day]; done=sum((h.id,day) in checkset for h in eligible)
        history.append({'day':day.isoformat(),'done':done,'total':len(eligible),'percent':round(done/len(eligible)*100) if eligible else 0})
    by={}
    for g in grades:by.setdefault(g.subject,[]).append(g.grade)
    return {'history':history,'tasks':{'total':len(tasks),'done':sum(t.done for t in tasks),'open':sum(not t.done for t in tasks)},'grades':[{'subject':k,'average':round(sum(v)/len(v),2)} for k,v in by.items()],'pomodoro_minutes':sum(p.duration_minutes for p in pom),'goals':{'total':len(db.scalars(select(Goal).where(Goal.user_id==user.id)).all()),'done':db.scalar(select(func.count(Goal.id)).where(Goal.user_id==user.id,Goal.done==True)) or 0}}

@app.get('/api/calendar/month')
def calendar_month(month:str,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    try:y,m=map(int,month.split('-')); start=date(y,m,1); end=date(y+1,1,1) if m==12 else date(y,m+1,1)
    except: raise HTTPException(422,'Месяц должен быть YYYY-MM')
    xs=db.scalars(select(CalendarEvent).where(CalendarEvent.user_id==user.id,CalendarEvent.start_at>=datetime.combine(start,datetime.min.time()),CalendarEvent.start_at<datetime.combine(end,datetime.min.time()))).all()
    return [serialize(x) for x in xs]

@app.on_event('startup')
def startup():
    # Remove expired sessions and one-time Telegram codes.
    with SessionLocal() as db:
        db.query(AuthSession).filter(AuthSession.expires_at<datetime.utcnow()).delete(); db.query(TelegramCode).filter(TelegramCode.expires_at<datetime.utcnow()).delete(); db.commit()

# AI assistance is read-only. Only the explicitly selected, owned task is sent.
def reserve_ai_request(db, user_id):
    day=datetime.now(timezone.utc).date()
    limits=[('site',assistant.positive_setting('AI_SITE_DAILY_LIMIT',200,10000)),
            (f'user:{user_id}',assistant.positive_setting('AI_USER_DAILY_LIMIT',20,500))]
    for scope,limit in limits:
        if db.get(AIUsage,(scope,day)) is None:
            try:
                with db.begin_nested():
                    db.add(AIUsage(scope=scope,day=day,requests=0));db.flush()
            except IntegrityError:
                pass
        changed=db.query(AIUsage).filter(AIUsage.scope==scope,AIUsage.day==day,AIUsage.requests<limit).update(
            {AIUsage.requests:AIUsage.requests+1},synchronize_session=False)
        if not changed:
            db.rollback()
            raise HTTPException(429,'Дневной лимит ИИ исчерпан. Попробуй после 00:00 UTC. Навигация по сайту работает без лимита.')
    db.commit()

def assistant_images(db,user,task):
    import base64
    photos=db.scalars(select(Attachment).where(Attachment.user_id==user.id,Attachment.task_id==task.id).order_by(Attachment.id).limit(2)).all()
    if not photos:raise HTTPException(422,'У выбранного задания нет фотографий. Добавь фото или отключи их отправку.')
    images=[]
    for photo in photos:
        if photo.mime not in ('image/jpeg','image/png','image/webp'):
            raise HTTPException(422,'Для ИИ подходят JPG, PNG и WEBP. Перепиши условие из GIF или загрузи другое фото.')
        path=(UPLOAD_DIR/photo.stored_name).resolve()
        if path.parent!=UPLOAD_DIR.resolve() or not path.is_file():
            raise HTTPException(422,'Фотография недоступна. Загрузи её ещё раз или отключи отправку фото.')
        if path.stat().st_size>4*1024*1024:
            raise HTTPException(413,'Для ИИ каждое фото должно быть не больше 4 МБ.')
        with path.open('rb') as source:raw=source.read(4*1024*1024+1)
        if not raw or len(raw)>4*1024*1024:raise HTTPException(413,'Некорректный размер фотографии.')
        images.append('data:'+photo.mime+';base64,'+base64.b64encode(raw).decode())
    return images

@app.get('/api/assistant/status')
def assistant_status(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    day=datetime.now(timezone.utc).date()
    used=db.get(AIUsage,(f'user:{user.id}',day))
    site_used=db.get(AIUsage,('site',day))
    limit=assistant.positive_setting('AI_USER_DAILY_LIMIT',20,500)
    site_limit=assistant.positive_setting('AI_SITE_DAILY_LIMIT',200,10000)
    return {'ai_ready':assistant.ai_configured(),'provider':assistant.ai_provider(),'privacy_notice':assistant.provider_notice(),'daily_limit':limit,
            'remaining':max(0,min(limit-(used.requests if used else 0),site_limit-(site_used.requests if site_used else 0))),
            'reset_at':datetime.combine(day+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc).isoformat(),
            'navigation_ready':True}

@app.post('/api/assistant/chat')
def assistant_chat(data:assistant.AssistantRequest,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if not data.message.strip():raise HTTPException(422,'Напиши вопрос.')
    if sum(len(x.content) for x in data.history)>16000:
        raise HTTPException(422,'Переписка слишком длинная. Начни новый диалог.')
    task=owned(db,Task,data.task_id,user) if data.task_id is not None else None
    if data.include_photos and task is None:raise HTTPException(422,'Сначала выбери задание с фотографиями.')
    guide=assistant.site_guide(data.message,data.mode)
    if guide:return guide
    if not assistant.ai_configured():
        raise HTTPException(503,'Помощь по ДЗ ещё не подключена. Навигация по сайту уже работает.')
    context={'current_page':data.page if data.page in assistant.PAGES else 'home'}
    if task:
        context['task']={'subject':task.subject,'title':task.title,'description':task.description,
                         'due':task.due.isoformat() if task.due else None}
    images=assistant_images(db,user,task) if data.include_photos else []
    assistant.acquire_slot(user.id)
    try:
        reserve_ai_request(db,user.id)
        result=assistant.ask_ai(data,context,images)
        if task:
            key='task-chat:'+str(task.id)
            history=upgrade_get(db,user.id,key,[])
            history.extend([{'role':'user','content':data.message},{'role':'assistant','content':str(result.get('reply',''))[:16000]}])
            upgrade_put(db,user.id,key,history[-40:]);db.commit()
        return result
    finally:
        assistant.release_slot(user.id)


if __name__=='__main__':
    import uvicorn
    uvicorn.run('app:app',host='0.0.0.0',port=int(os.getenv('PORT','8000')),workers=1)


DEFAULT_REMINDERS=[('Расписание на сегодня','schedule','07:00'),('Привычки утром','habits','09:00'),('Привычки днём','habits','13:00'),('Домашка на завтра','homework_eve','17:00'),('Привычки вечером','habits','19:00'),('Расписание на завтра','schedule_tomorrow','19:00')]
def ensure_default_reminders(db,user_id):
    # Never overwrite existing user-configured reminders or re-create after linking.
    key=db.scalar(select(UserSetting).where(UserSetting.user_id==user_id,UserSetting.key=='default_reminders_v2_seeded'))
    summary_key=db.scalar(select(UserSetting).where(UserSetting.user_id==user_id,UserSetting.key=='evening_summary_v21_seeded'))
    if not summary_key:
        if not db.scalar(select(Reminder.id).where(Reminder.user_id==user_id,Reminder.kind=='evening_summary')):
            db.add(Reminder(user_id=user_id,title='Вечерняя сводка',kind='evening_summary',send_time='20:00',days='0,1,2,3,4,5,6',enabled=True))
        db.add(UserSetting(user_id=user_id,key='evening_summary_v21_seeded',value='1'))
    if key:return
    # One-time backfill for existing accounts: keep all custom reminders unchanged.
    # Once marked, deleted defaults are never recreated.
    existing={(r.kind,r.send_time) for r in db.scalars(select(Reminder).where(Reminder.user_id==user_id)).all()}
    for title,kind,clock in DEFAULT_REMINDERS:
        if (kind,clock) not in existing:
            db.add(Reminder(user_id=user_id,title=title,kind=kind,send_time=clock,days='0,1,2,3,4,5,6',enabled=True))
    db.add(UserSetting(user_id=user_id,key='default_reminders_v2_seeded',value='1'))

@app.get('/api/public/stats')
def public_stats(db:Session=Depends(dbdep)):
    return {'total_users':db.scalar(select(func.count(User.id))) or 0}

@app.get('/api/subject-colors')
def get_subject_colors(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='subject_colors'))
    try:return json.loads(row.value) if row else {}
    except Exception:return {}

@app.put('/api/subject-colors')
def put_subject_colors(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    if len(d)>100:raise HTTPException(422,'Слишком много предметов')
    colors={str(k)[:120]:v for k,v in d.items() if isinstance(v,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',v)}
    row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='subject_colors'))
    if not row:row=UserSetting(user_id=user.id,key='subject_colors');db.add(row)
    row.value=json.dumps(colors,ensure_ascii=False);db.commit();return colors

@app.get('/api/lesson-notes')
def get_lesson_notes(user:User=Depends(current_user),db:Session=Depends(dbdep)):
    row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='lesson_notes'))
    try:return json.loads(row.value) if row else {}
    except Exception:return {}

@app.put('/api/lesson-notes')
def put_lesson_notes(d:dict,user:User=Depends(current_user),db:Session=Depends(dbdep)):
    notes={str(k)[:120]:str(v)[:2000] for k,v in list(d.items())[:100]}
    row=db.scalar(select(UserSetting).where(UserSetting.user_id==user.id,UserSetting.key=='lesson_notes'))
    if not row:row=UserSetting(user_id=user.id,key='lesson_notes');db.add(row)
    row.value=json.dumps(notes,ensure_ascii=False);db.commit();return notes




from platform_features import install as install_platform_features
globals().update(install_platform_features(globals()))



@app.get('/orbit/{group}')
@app.get('/orbit/{group}/{section}')
@app.get('/assistant')
@app.get('/search')
def orbit_entry(group:str='',section:str=''):
    return FileResponse(BASE/'static'/'index.html',headers={'Cache-Control':'no-cache'})

from upgrade_features import install as install_upgrade_features
globals().update(install_upgrade_features(globals()))
