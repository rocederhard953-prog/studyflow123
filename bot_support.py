"""Persistent Telegram media IDs and native, theme-aware quick navigation."""
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid
from functools import lru_cache

QUICK_ACTIONS={'⌂ Главное меню':'menu','📅 Мой день':'today','📚 Домашка':'homework','✓ Привычки':'habits','🗓 Расписание':'schedule','🔔 Напоминания':'reminders'}
COMMAND_ACTIONS={'/menu':'menu','/today':'today','/habits':'habits','/homework':'homework','/schedule':'schedule','/tomorrow':'tomorrow','/reminders':'reminders'}
INLINE_NAVIGATION=[[{'text':'⌂ Главное меню','callback_data':'menu'},{'text':'📅 Мой день','callback_data':'today'}],
                   [{'text':'📚 Домашка','callback_data':'homework'},{'text':'✓ Привычки','callback_data':'habits'}],
                   [{'text':'🗓 Расписание','callback_data':'schedule'},{'text':'🔔 Напоминания','callback_data':'reminders'}]]
COMMANDS=[{'command':name[1:],'description':label} for name,label in [('/menu','Главное меню'),('/today','Мой день'),('/homework','Домашние задания'),('/habits','Привычки'),('/schedule','Расписание'),('/reminders','Напоминания'),('/quick','Показать быстрое меню'),('/cancel','Отменить ввод')]]

def quick_keyboard(site):
    labels=list(QUICK_ACTIONS)
    rows=[[{'text':label} for label in labels[i:i+2]] for i in range(0,len(labels),2)]
    rows.append([{'text':'◉ Открыть сайт','web_app':{'url':site}}])
    return json.dumps({'keyboard':rows,'resize_keyboard':True,'is_persistent':True,'one_time_keyboard':False,'input_field_placeholder':'Выбери раздел или напиши сообщение'},ensure_ascii=False)

@lru_cache(maxsize=32)
def _read_image(path,modified,size):
    raw=Path(path).read_bytes()
    return hashlib.sha256(raw).hexdigest(),raw

def image_data(path):
    path=Path(path);stat=path.stat()
    # Cache small interface covers, not dozens of large private homework photos.
    if stat.st_size>256*1024:
        raw=path.read_bytes();return hashlib.sha256(raw).hexdigest(),raw
    return _read_image(str(path),stat.st_mtime_ns,stat.st_size)

class MediaCache:
    def __init__(self,directory,token):
        self.path=Path(directory)/('bot-media-'+hashlib.sha256(token.encode()).hexdigest()[:16]+'.json')
        self.lock=threading.RLock();self.loaded=False;self.items={}
    def _load(self):
        if self.loaded:return
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            self.items={k:v for k,v in list(data.items())[-256:] if isinstance(k,str) and isinstance(v,str)} if isinstance(data,dict) else {}
        except (OSError,ValueError):self.items={}
        self.loaded=True
    def get(self,digest):
        with self.lock:self._load();return self.items.get(digest)
    def set(self,digest,file_id):
        if not isinstance(file_id,str) or not file_id:return
        with self.lock:
            self._load();self.items[digest]=file_id;self.items=dict(list(self.items.items())[-256:]);self._save()
    def discard(self,digest):
        with self.lock:self._load();self.items.pop(digest,None);self._save()
    def _save(self):
        temporary=self.path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary.write_text(json.dumps(self.items),encoding='utf-8');os.replace(temporary,self.path)
        except OSError:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass

def signature(content,markup,image_hash):
    return hashlib.sha256(json.dumps([content,markup,image_hash],ensure_ascii=False).encode()).hexdigest()

def reusable_media_error(error):
    return any(value in str(error).lower() for value in ('wrong file identifier','file_reference_expired','file reference expired','invalid file_id','wrong remote file identifier'))

def notification_loop(tick,stop,interval=20,on_error=None):
    while not stop.is_set():
        try:tick()
        except Exception:
            if on_error:on_error()
        stop.wait(interval)
