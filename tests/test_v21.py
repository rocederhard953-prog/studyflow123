"""Regression checks for My-Study 2.1; no real Telegram requests or user database."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory(prefix='my-study-tests-')
os.environ['DATA_DIR'] = TEMP.name
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(TEMP.name) / 'test.db')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import bot
from sqlalchemy import select
from fastapi.testclient import TestClient


def tearDownModule():
    app.engine.dispose()
    TEMP.cleanup()


class V21Tests(unittest.TestCase):
    def setUp(self):
        app.Base.metadata.drop_all(app.engine)
        app.Base.metadata.create_all(app.engine)
        bot.SCREEN_IDS.clear()
        with app.SessionLocal() as db:
            self.user = app.User(email='one@example.com', username='student', password_hash='unused', timezone='UTC')
            self.other = app.User(email='two@example.com', username='other', password_hash='unused', timezone='UTC')
            db.add_all([self.user, self.other]); db.flush()
            db.add(app.TelegramLink(user_id=self.user.id, chat_id='123'))
            db.add_all([app.UserSetting(user_id=self.user.id, key=k, value='1') for k in
                        ('default_reminders_v2_seeded', 'evening_summary_v21_seeded')])
            db.commit()

    def task(self, **fields):
        with app.SessionLocal() as db:
            t = app.Task(user_id=self.user.id, title='Read chapter 14', subject='History',
                         due=date(2026, 11, 14), **fields)
            db.add(t); db.commit(); return t

    def test_native_keyboard_does_not_mutate_input(self):
        import json
        rows = [[{'text': 'Home', 'callback_data': 'menu'}]]
        keys = json.loads(bot.keyboard(rows))['inline_keyboard']
        self.assertTrue(all('style' not in b for r in keys for b in r))
        self.assertNotIn('style', rows[0][0])

    def test_task_notification_contains_subject_date_and_actions(self):
        task = self.task()
        with patch.object(bot, 'tg') as send:
            bot.notify_task('123', task)
        params = send.call_args.args[1]
        self.assertIn('History', params['text'])
        self.assertIn('14.11.2026', params['text'])
        self.assertIn('Read chapter 14', params['text'])
        for action in ('ndone:', 'nsnooze:', 'nphoto:'):
            self.assertIn(action + str(task.id), params['reply_markup'])
        self.assertEqual(bot.SCREEN_IDS, {})

    def test_due_date_filter_works_without_tomorrow_lessons(self):
        tomorrow = date(2026, 11, 14)
        wanted = self.task()
        with app.SessionLocal() as db:
            db.add_all([
                app.Task(user_id=self.user.id, title='Later', subject='History', due=tomorrow+timedelta(days=7)),
                app.Task(user_id=self.user.id, title='Done', subject='History', due=tomorrow, done=True),
                app.Task(user_id=self.other.id, title='Private', subject='History', due=tomorrow),
                app.Task(user_id=self.user.id, title='No date', subject='History', due=None)
            ]); db.commit()
            self.assertEqual([t.id for t in bot.homework_for_day(db, self.user, tomorrow)], [wanted.id])

    def test_complete_is_idempotent_and_cancels_snooze(self):
        task = self.task()
        with patch.object(bot, 'notify'):
            bot.task_notification_action('123', f'nsnooze:{task.id}')
            bot.task_notification_action('123', f'ndone:{task.id}')
            bot.task_notification_action('123', f'ndone:{task.id}')
        with app.SessionLocal() as db:
            self.assertTrue(db.get(app.Task, task.id).done)
            self.assertEqual(db.scalars(select(app.TaskSnooze)).all(), [])

    def test_snooze_survives_sessions_and_does_not_change_due(self):
        task = self.task()
        with patch.object(bot, 'notify'):
            bot.task_notification_action('123', f'nsnooze:{task.id}')
            bot.task_notification_action('123', f'nsnooze:{task.id}')
        with app.SessionLocal() as db:
            rows = db.scalars(select(app.TaskSnooze)).all()
            self.assertEqual(len(rows), 1)
            when = rows[0].send_at
            self.assertGreater(when, datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=59))
            self.assertEqual(db.get(app.Task, task.id).due, task.due)
        with app.SessionLocal() as db, patch.object(bot, 'notify_task') as send:
            bot.snooze_tick(db, when.replace(tzinfo=timezone.utc)+timedelta(seconds=1))
            self.assertEqual(send.call_count, 1)
        with app.SessionLocal() as db:
            self.assertEqual(db.scalars(select(app.TaskSnooze)).all(), [])

    def test_cross_account_callbacks_cannot_change_or_read_task(self):
        task = self.task()
        with app.SessionLocal() as db:
            db.add(app.TelegramLink(user_id=self.other.id, chat_id='456')); db.commit()
        with patch.object(bot, 'notify') as send, patch.object(bot, 'send_task_photo') as photo:
            for action in ('ndone', 'nsnooze', 'nphoto', 'nopen'):
                bot.task_notification_action('456', f'{action}:{task.id}')
            photo.assert_not_called()
            self.assertTrue(all('History' not in c.args[1] for c in send.call_args_list))
        with app.SessionLocal() as db:
            self.assertFalse(db.get(app.Task, task.id).done)
            self.assertEqual(db.scalars(select(app.TaskSnooze)).all(), [])

    def test_evening_summary_has_lessons_homework_and_remaining_habits(self):
        self.task()
        local = datetime(2026, 11, 13, 20, tzinfo=timezone.utc)
        with app.SessionLocal() as db:
            db.add(app.Lesson(user_id=self.user.id, weekday=5, period=1, subject='Math', start='09:00'))
            db.add(app.Habit(user_id=self.user.id, name='Read ten pages', days='4'))
            db.add(app.Habit(user_id=self.user.id, name='Weekend only', days='5,6')); db.commit()
            text, tasks = bot.evening_summary(db, self.user, local)
        self.assertIn('Math', text)
        self.assertIn('Read chapter 14', text)
        self.assertIn('14.11.2026', text)
        self.assertIn('Read ten pages', text)
        self.assertNotIn('Weekend only', text)
        self.assertEqual(len(tasks), 1)

    def test_notification_navigation_preserves_original_message(self):
        bot.SCREEN_IDS['123'] = 222
        with patch.object(bot, 'tg'), patch.object(bot, 'show_visible_menu') as display:
            bot.callback({'id':'q','data':'today','message':{'message_id':111,'chat':{'id':123}}})
        display.assert_called_once_with('123', 'today', 111)

    def test_summary_seed_is_once_and_preserves_custom_reminders(self):
        with app.SessionLocal() as db:
            db.query(app.UserSetting).filter_by(key='evening_summary_v21_seeded').delete()
            original = app.Reminder(user_id=self.user.id, title='My custom reminder', kind='tasks', send_time='18:32')
            db.add(original); db.commit()
            app.ensure_default_reminders(db, self.user.id); db.commit()
            app.ensure_default_reminders(db, self.user.id); db.commit()
            summaries = db.scalars(select(app.Reminder).where(app.Reminder.kind=='evening_summary')).all()
            self.assertEqual(len(summaries), 1)
            self.assertEqual(db.get(app.Reminder, original.id).send_time, '18:32')
            db.delete(summaries[0]); db.commit()
            app.ensure_default_reminders(db, self.user.id); db.commit()
            self.assertEqual(db.scalars(select(app.Reminder).where(app.Reminder.kind=='evening_summary')).all(), [])

    def test_api_register_create_complete_and_reminder(self):
        with TestClient(app.app) as client:
            r = client.post('/api/register', json={'email':'api@example.com','username':'apiuser','password':'a-secure-test-password'})
            self.assertEqual(r.status_code, 200, r.text)
            headers={'X-CSRF-Token':client.cookies.get('sf_csrf')}
            r=client.post('/api/tasks', json={'subject':'Physics','title':'Exercise 10','due':'2026-11-16'}, headers=headers)
            self.assertEqual(r.status_code, 200, r.text)
            task_id=r.json()['id']
            self.assertEqual(client.put(f'/api/tasks/{task_id}',json={'done':True},headers=headers).status_code,200)
            r=client.post('/api/reminders',json={'title':'Evening','kind':'evening_summary','send_time':'20:00','days':[0,1,2,3,4,5,6]},headers=headers)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['kind'],'evening_summary')
            self.assertEqual(client.get('/api/tasks').json()[0]['subject'],'Physics')
            self.assertEqual(client.get('/').status_code,200)


    def test_whiteboard_roundtrip_conflict_validation_and_ownership(self):
        app.app.dependency_overrides[app.current_user]=lambda:self.user
        try:
            with TestClient(app.app) as client:
                client.cookies.set('sf_csrf','board-test')
                headers={'X-CSRF-Token':'board-test'}
                data={'revision':0,'strokes':[{'tool':'pen','color':'#182033','width':4,'points':[[10,20],[30,40]]}]}
                self.assertEqual(client.get('/api/whiteboard').json(),{'revision':0,'strokes':[]})
                self.assertEqual(client.put('/api/whiteboard',json=data).status_code,403)
                self.assertEqual(client.put('/api/whiteboard',json=data,headers=headers).status_code,200)
                self.assertEqual(client.get('/api/whiteboard').json()['strokes'],data['strokes'])
                self.assertEqual(client.put('/api/whiteboard',json=data,headers=headers).status_code,409)
                bad={'revision':1,'strokes':[{'tool':'pen','color':'invalid','width':4,'points':[[10,20]]}]}
                self.assertEqual(client.put('/api/whiteboard',json=bad,headers=headers).status_code,422)
                task=self.task()
                self.assertEqual(client.put('/api/whiteboard?task_id='+str(task.id),json=data,headers=headers).status_code,200)
                app.app.dependency_overrides[app.current_user]=lambda:self.other
                self.assertEqual(client.get('/api/whiteboard').json()['strokes'],[])
                self.assertEqual(client.get('/api/whiteboard?task_id='+str(task.id)).status_code,404)
                self.assertEqual(client.put('/api/whiteboard?task_id='+str(task.id),json=data,headers=headers).status_code,404)
        finally:
            app.app.dependency_overrides.pop(app.current_user,None)


    def test_whiteboard_photos_persist_and_are_private(self):
        import base64
        raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        app.app.dependency_overrides[app.current_user]=lambda:self.user
        try:
            with TestClient(app.app) as client:
                client.cookies.set('sf_csrf','board-test');headers={'X-CSRF-Token':'board-test'}
                self.assertEqual(client.post('/api/whiteboard/images',files={'file':('photo.png',raw,'image/png')}).status_code,403)
                result=client.post('/api/whiteboard/images',files={'file':('photo.png',raw,'image/png')},headers=headers)
                self.assertEqual(result.status_code,200,result.text)
                stored=result.json()['stored_name']
                self.assertEqual(client.get('/api/whiteboard/images/'+stored).content,raw)
                data={'revision':0,'strokes':[],'grid':False,'images':[{'stored_name':stored,'x':100,'y':200,'w':500,'h':400}]}
                self.assertEqual(client.put('/api/whiteboard',json=data,headers=headers).status_code,200)
                saved=client.get('/api/whiteboard').json()
                self.assertEqual(saved['images'],data['images']);self.assertFalse(saved['grid'])
                app.app.dependency_overrides[app.current_user]=lambda:self.other
                self.assertEqual(client.get('/api/whiteboard/images/'+stored).status_code,404)
                self.assertEqual(client.put('/api/whiteboard',json=data,headers=headers).status_code,404)
        finally: app.app.dependency_overrides.pop(app.current_user,None)

    def test_whiteboard_photo_validation_and_legacy_board(self):
        app.app.dependency_overrides[app.current_user]=lambda:self.user
        try:
            with TestClient(app.app) as client:
                client.cookies.set('sf_csrf','board-test');headers={'X-CSRF-Token':'board-test'}
                self.assertEqual(client.post('/api/whiteboard/images',files={'file':('x.svg',b'<svg/>','image/svg+xml')},headers=headers).status_code,415)
                self.assertEqual(client.post('/api/whiteboard/images',files={'file':('x.png',b'not an image','image/png')},headers=headers).status_code,415)
                self.assertEqual(client.put('/api/whiteboard',json={'revision':0,'strokes':[],'grid':'yes'},headers=headers).status_code,422)
                self.assertEqual(client.put('/api/whiteboard',json={'revision':0,'strokes':[],'images':[{'stored_name':'https://external/image.png'}]},headers=headers).status_code,422)
                self.assertEqual(client.put('/api/whiteboard',json={'revision':0,'strokes':[]},headers=headers).status_code,200)
                saved=client.get('/api/whiteboard').json();self.assertTrue(saved['grid']);self.assertEqual(saved['images'],[])
        finally: app.app.dependency_overrides.pop(app.current_user,None)


    def test_homework_multiple_pages_and_personal_board_restriction(self):
        app.app.dependency_overrides[app.current_user]=lambda:self.user
        try:
            task=self.task()
            first={'strokes':[{'tool':'pen','color':'#182033','width':4,'points':[[10,20]]}],'images':[],'grid':True}
            second={'strokes':[{'tool':'line','color':'#2374da','width':8,'points':[[50,60],[70,80]]}],'images':[],'grid':False}
            data={'revision':0,'pages':[first,second]}
            url='/api/whiteboard?task_id='+str(task.id)
            with TestClient(app.app) as client:
                client.cookies.set('sf_csrf','board-test');headers={'X-CSRF-Token':'board-test'}
                self.assertEqual(client.put('/api/whiteboard',json=data,headers=headers).status_code,422)
                self.assertEqual(client.put(url,json=data,headers=headers).status_code,200)
                saved=client.get(url).json();self.assertEqual(saved['pages'],[first,second]);self.assertEqual(saved['strokes'],first['strokes'])
                self.assertEqual(client.put(url,json={'revision':1,'strokes':[]},headers=headers).status_code,409)
                self.assertEqual(client.put(url,json={'revision':1,'pages':[]},headers=headers).status_code,422)
                self.assertEqual(client.put(url,json={'revision':1,'pages':[first]*21},headers=headers).status_code,422)
                self.assertEqual(client.get(url).json()['pages'],[first,second])
                app.app.dependency_overrides[app.current_user]=lambda:self.other
                self.assertEqual(client.get(url).status_code,404)
                self.assertEqual(client.put(url,json=data,headers=headers).status_code,404)
        finally: app.app.dependency_overrides.pop(app.current_user,None)



    def test_large_whiteboard_bounds_and_legacy_sheet_migration(self):
        app.app.dependency_overrides[app.current_user]=lambda:self.user
        try:
            task=self.task()
            with TestClient(app.app) as client:
                client.cookies.set('sf_csrf','board-test');headers={'X-CSRF-Token':'board-test'}
                url='/api/whiteboard?task_id='+str(task.id)
                sheet={'strokes':[],'images':[],'grid':True}
                self.assertEqual(client.put(url,json={'revision':0,'pages':[sheet,sheet]},headers=headers).status_code,200)
                data={'revision':1,'layout':'large-v1','strokes':[{'tool':'pen','color':'#111111','width':4,'points':[[11990,7990]]}],'images':[],'grid':True}
                result=client.put(url,json=data,headers=headers)
                self.assertEqual(result.status_code,200,result.text)
                saved=client.get(url).json()
                self.assertEqual(saved['layout'],'large-v1');self.assertNotIn('pages',saved)
                self.assertEqual(saved['strokes'],data['strokes'])
                self.assertEqual(client.put(url,json={'revision':2,'strokes':[]},headers=headers).status_code,409)
                data['revision']=2;data['strokes'][0]['points']=[[12001,8000]]
                self.assertEqual(client.put(url,json=data,headers=headers).status_code,422)
        finally: app.app.dependency_overrides.pop(app.current_user,None)

class AssistantTests(unittest.TestCase):
    task = V21Tests.task

    def setUp(self):
        V21Tests.setUp(self)
        self.env = patch.dict(os.environ, {'AI_PROVIDER':'openai','OPENAI_API_KEY':'','GEMINI_API_KEY':'','GEMINI_MODEL':'gemini-3.5-flash-lite', 'AI_ENABLED':'1', 'AI_USER_DAILY_LIMIT':'2', 'AI_SITE_DAILY_LIMIT':'4'})
        self.env.start()
        self.addCleanup(self.env.stop)
        app.app.dependency_overrides[app.current_user] = lambda: self.user
        self.addCleanup(app.app.dependency_overrides.clear)
        self.client = TestClient(app.app)
        self.client.cookies.set('sf_csrf','test-csrf')
        self.headers={'X-CSRF-Token':'test-csrf'}
        self.addCleanup(self.client.close)

    def chat(self, **data):
        return self.client.post('/api/assistant/chat',json={'message':'Объясни решение',**data},headers=self.headers)

    def test_navigation_works_without_key_or_paid_request(self):
        with patch.object(app.assistant,'ask_ai') as provider:
            r=self.chat(message='Как изменить время вечерней сводки?',mode='navigation')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['source'],'guide')
        self.assertEqual(r.json()['actions'][0]['page'],'reminders')
        provider.assert_not_called()
        with app.SessionLocal() as db:
            self.assertEqual(db.scalars(select(app.AIUsage)).all(),[])

    def test_missing_key_has_honest_status_and_study_error(self):
        status=self.client.get('/api/assistant/status').json()
        self.assertFalse(status['ai_ready'])
        self.assertTrue(status['navigation_ready'])
        self.assertEqual(self.chat().status_code,503)
        self.assertNotIn('OPENAI_API_KEY',self.client.get('/api/assistant/status').text)

    def test_tutoring_question_is_not_confused_with_site_navigation(self):
        self.assertIsNone(app.assistant.site_guide('Где ошибка в решении домашнего задания?', 'study'))
        response=app.assistant.site_guide('Где настройки напоминаний?', 'navigation')
        self.assertEqual(response['actions'][0]['page'],'reminders')

    def test_chat_needs_auth_and_csrf(self):
        app.app.dependency_overrides.clear()
        self.assertEqual(self.client.get('/api/assistant/status').status_code,401)
        self.assertEqual(self.chat(mode='navigation').status_code,401)
        self.assertEqual(self.client.post('/api/assistant/chat',json={'message':'Где ДЗ?'}).status_code,403)

    def test_cannot_select_another_users_task_even_for_navigation(self):
        with app.SessionLocal() as db:
            t=app.Task(user_id=self.other.id,subject='Private',title='Secret');db.add(t);db.commit();ident=t.id
        with patch.object(app.assistant,'ask_ai') as provider:
            r=self.chat(task_id=ident,mode='navigation')
        self.assertEqual(r.status_code,404)
        self.assertNotIn('Secret',r.text)
        provider.assert_not_called()

    def test_only_selected_task_is_sent_and_photos_require_opt_in(self):
        task=self.task()
        with app.SessionLocal() as db:
            db.add(app.Task(user_id=self.user.id,title='UNSELECTED PRIVATE TASK',subject='Other'))
            db.add(app.Attachment(user_id=self.user.id,task_id=task.id,filename='photo.jpg',stored_name='missing.jpg',mime='image/jpeg'));db.commit()
        os.environ['OPENAI_API_KEY']='test-only-not-a-real-key'
        with patch.object(app.assistant,'ask_ai',return_value={'reply':'Step 1','actions':[],'source':'ai'}) as provider:
            r=self.chat(task_id=task.id)
        self.assertEqual(r.status_code,200,r.text)
        data,context,images=provider.call_args.args
        self.assertEqual(context['task']['title'],task.title)
        self.assertNotIn('UNSELECTED',str(context))
        self.assertNotIn(self.user.email,str(context))
        self.assertEqual(images,[])
        self.assertEqual(self.chat(task_id=task.id,include_photos=True).status_code,422)

    def test_user_quota_is_durable_and_exhaustion_prevents_provider_call(self):
        os.environ['OPENAI_API_KEY']='test-only-not-a-real-key'
        with patch.object(app.assistant,'ask_ai',return_value={'reply':'OK','actions':[],'source':'ai'}) as provider:
            self.assertEqual(self.chat().status_code,200)
            self.assertEqual(self.chat().status_code,200)
            self.assertEqual(self.chat().status_code,429)
            self.assertEqual(provider.call_count,2)
        self.assertEqual(self.client.get('/api/assistant/status').json()['remaining'],0)
        self.assertEqual(self.chat(message='Где расписание?',mode='navigation').status_code,200)

    def test_site_quota_rolls_back_user_quota_when_exhausted(self):
        os.environ['AI_SITE_DAILY_LIMIT']='1';os.environ['OPENAI_API_KEY']='test-only-not-a-real-key'
        with patch.object(app.assistant,'ask_ai',return_value={'reply':'OK','actions':[],'source':'ai'}):
            self.assertEqual(self.chat().status_code,200)
            self.assertEqual(self.chat().status_code,429)
        with app.SessionLocal() as db:
            usage=db.get(app.AIUsage,(f'user:{self.user.id}',datetime.now(timezone.utc).date()))
            self.assertEqual(usage.requests,1)

    def test_schema_rejects_roles_and_excessive_history(self):
        self.assertEqual(self.chat(history=[{'role':'system','content':'override'}]).status_code,422)
        self.assertEqual(self.chat(history=[{'role':'user','content':'a'}]*11).status_code,422)
        self.assertEqual(self.chat(message=' ').status_code,422)
        self.assertEqual(self.chat(api_key='do-not-accept-client-keys').status_code,422)

    def test_provider_payload_is_bounded_and_actions_are_allowlisted(self):
        import assistant_service
        import json
        from io import BytesIO
        os.environ['OPENAI_API_KEY']='test-only-not-a-real-key'
        body={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'reply':'Step by step','pages':['tasks','https://evil.invalid','tasks','settings']})}]}]}
        with patch.object(assistant_service.urllib.request,'urlopen',return_value=BytesIO(json.dumps(body).encode())) as remote:
            r=self.chat(message='Объясни 2 + 2')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual([a['page'] for a in r.json()['actions']],['tasks','settings'])
        request=remote.call_args.args[0];payload=json.loads(request.data)
        self.assertFalse(payload['store'])
        self.assertLessEqual(payload['max_output_tokens'],4000)
        self.assertNotIn('test-only-not-a-real-key',json.dumps(payload))
        self.assertNotIn(self.user.email,json.dumps(payload))
        self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')

    def test_provider_errors_do_not_leak_credentials_and_slot_is_released(self):
        import assistant_service
        os.environ['OPENAI_API_KEY']='test-only-not-a-real-key'
        with patch.object(assistant_service.urllib.request,'urlopen',side_effect=RuntimeError('test-only-not-a-real-key')):
            r=self.chat()
        self.assertEqual(r.status_code,502)
        self.assertNotIn('test-only-not-a-real-key',r.text)
        self.assertNotIn(self.user.id,assistant_service._active_users)


class GeminiTests(unittest.TestCase):
    def setUp(self):
        AssistantTests.setUp(self)
        os.environ['AI_PROVIDER']='gemini'

    chat=AssistantTests.chat
    task=V21Tests.task

    def gemini_response(self,reply='Разберём по шагам',pages=None,finish='STOP'):
        from io import BytesIO
        import json
        return BytesIO(json.dumps({'candidates':[{'finishReason':finish,'content':{'parts':[{'thought':True,'text':'INTERNAL THOUGHT'},{'text':json.dumps({'reply':reply,'pages':pages or []})}]}}]}).encode())

    def test_default_provider_and_no_paid_fallback_when_gemini_key_is_missing(self):
        os.environ.pop('AI_PROVIDER',None)
        os.environ['OPENAI_API_KEY']='available-openai-key-that-must-not-be-used'
        self.assertEqual(app.assistant.ai_provider(),'gemini')
        with patch.object(app.assistant,'ask_openai') as paid:
            self.assertEqual(self.chat().status_code,503)
        paid.assert_not_called()
        status=self.client.get('/api/assistant/status').json()
        self.assertFalse(status['ai_ready'])
        self.assertEqual(status['provider'],'gemini')
        self.assertTrue(status['privacy_notice'])

    def test_gemini_uses_header_secret_schema_and_maps_history_roles(self):
        import json
        os.environ['GEMINI_API_KEY']='fake-gemini-test-key'
        with patch.object(app.assistant.urllib.request,'urlopen',return_value=self.gemini_response(pages=['habits','https://evil.invalid','habits'])) as remote:
            r=self.chat(message='Объясни сложение',history=[{'role':'user','content':'Первый вопрос'},{'role':'assistant','content':'Первый ответ'}])
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual([a['page'] for a in r.json()['actions']],['habits'])
        self.assertNotIn('INTERNAL THOUGHT',r.text)
        req=remote.call_args.args[0];payload=json.loads(req.data)
        self.assertEqual(req.full_url,'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent')
        self.assertNotIn('fake-gemini-test-key',req.full_url)
        self.assertNotIn('fake-gemini-test-key',json.dumps(payload))
        self.assertEqual({k.lower():v for k,v in req.header_items()}['x-goog-api-key'],'fake-gemini-test-key')
        self.assertEqual([x['role'] for x in payload['contents']],['user','model','user'])
        self.assertEqual(payload['generationConfig']['responseMimeType'],'application/json')
        self.assertIn('responseJsonSchema',payload['generationConfig'])
        self.assertNotIn('tools',payload)

    def test_gemini_quota_error_does_not_retry_or_switch_provider(self):
        import urllib.error
        os.environ['GEMINI_API_KEY']='fake-gemini-test-key';os.environ['OPENAI_API_KEY']='do-not-use'
        failure=urllib.error.HTTPError('https://generativelanguage.googleapis.com/',429,'fake-gemini-test-key',None,None)
        with patch.object(app.assistant.urllib.request,'urlopen',side_effect=failure) as remote,patch.object(app.assistant,'ask_openai') as paid:
            r=self.chat()
        self.assertEqual(r.status_code,503)
        self.assertEqual(remote.call_count,1)
        self.assertNotIn('fake-gemini-test-key',r.text)
        paid.assert_not_called()

    def test_gemini_rejects_partial_response_and_non_free_model(self):
        os.environ['GEMINI_API_KEY']='fake-gemini-test-key'
        with patch.object(app.assistant.urllib.request,'urlopen',return_value=self.gemini_response(finish='MAX_TOKENS')):
            self.assertEqual(self.chat().status_code,502)
        os.environ['GEMINI_MODEL']='a-paid-model'
        with patch.object(app.assistant.urllib.request,'urlopen') as remote:
            self.assertEqual(self.chat().status_code,503)
        remote.assert_not_called()

    def test_gemini_accepts_only_inline_owned_photo_payloads(self):
        import json
        os.environ['GEMINI_API_KEY']='fake-gemini-test-key'
        data=app.assistant.AssistantRequest(message='Объясни условие')
        with patch.object(app.assistant.urllib.request,'urlopen',return_value=self.gemini_response()) as remote:
            result=app.assistant.ask_ai(data,{'current_page':'tasks'},['data:image/png;base64,aGVsbG8='])
        self.assertEqual(result['source'],'ai')
        body=json.loads(remote.call_args.args[0].data)
        self.assertEqual(body['contents'][-1]['parts'][1],{'inlineData':{'mimeType':'image/png','data':'aGVsbG8='}})
        with patch.object(app.assistant.urllib.request,'urlopen') as remote:
            with self.assertRaises(app.HTTPException):app.assistant.ask_ai(data,{},['https://private.invalid/image.jpg'])
        remote.assert_not_called()

    def test_gemini_region_denial_is_clear_and_does_not_leak_provider_body(self):
        import urllib.error
        os.environ['GEMINI_API_KEY']='fake-gemini-test-key'
        with patch.object(app.assistant.urllib.request,'urlopen',side_effect=urllib.error.HTTPError('url',403,'secret provider details',None,None)):
            response=self.chat()
        self.assertEqual(response.status_code,503)
        self.assertIn('Google AI Studio',response.json()['detail'])
        self.assertNotIn('secret provider details',response.text)


if __name__ == '__main__':
    unittest.main()


class TelegramAuthTests(unittest.TestCase):
    setUp = V21Tests.setUp

    def signed_data(self,telegram_id=123,age=0):
        import json,hmac,hashlib
        from urllib.parse import urlencode
        fields={'auth_date':str(int(datetime.now(timezone.utc).timestamp())-age),'user':json.dumps({'id':telegram_id})}
        secret=hmac.new(b'WebAppData',b'test-bot-key',hashlib.sha256).digest()
        fields['hash']=hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
        return urlencode(fields)

    def test_signed_telegram_login_rejects_tampering_expiry_and_unlinked_users(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'test-bot-key'}),TestClient(app.app) as client:
            client.cookies.set('sf_csrf','tg-test',domain='testserver.local',path='/');headers={'X-CSRF-Token':'tg-test'}
            self.assertEqual(client.post('/api/auth/telegram',json={'init_data':self.signed_data()}).status_code,403)
            self.assertEqual(client.post('/api/auth/telegram',json={'init_data':self.signed_data()+'x'},headers=headers).status_code,401)
            self.assertEqual(client.post('/api/auth/telegram',json={'init_data':self.signed_data(age=700)},headers=headers).status_code,401)
            self.assertEqual(client.post('/api/auth/telegram',json={'init_data':self.signed_data(456)},headers=headers).status_code,403)
            self.assertEqual(client.post('/api/auth/telegram',json={'init_data':self.signed_data()},headers=headers).status_code,200)
            self.assertEqual(client.get('/api/me').json()['id'],self.user.id)

    def test_bot_auth_links_are_single_use_and_reset_revokes_sessions(self):
        with TestClient(app.app) as client:
            client.cookies.set('sf_csrf','tg-test',domain='testserver.local',path='/');headers={'X-CSRF-Token':'tg-test'}
            with app.SessionLocal() as db: token=app.issue_telegram_auth_link(db,self.user,'login')
            body={'token':token,'purpose':'login'}
            self.assertEqual(client.post('/api/auth/link-info',json=body,headers=headers).json()['username'],'student')
            self.assertEqual(client.post('/api/auth/reset-password',json={'token':token,'password':'replacement-password'},headers=headers).status_code,400)
            self.assertEqual(client.post('/api/auth/link-login',json=body,headers=headers).status_code,200)
            old_cookie=client.cookies.get('sf_session')
            headers={'X-CSRF-Token':client.cookies.get('sf_csrf')}
            self.assertEqual(client.post('/api/auth/link-login',json=body,headers=headers).status_code,400)
            with app.SessionLocal() as db: reset=app.issue_telegram_auth_link(db,self.user,'reset')
            self.assertEqual(client.post('/api/auth/reset-password',json={'token':reset,'password':'short'},headers=headers).status_code,422)
            self.assertEqual(client.post('/api/auth/reset-password',json={'token':reset,'password':'replacement-password'},headers=headers).status_code,200)
            self.assertEqual(client.get('/api/me').status_code,200)
            with app.SessionLocal() as db:
                self.assertTrue(app.verify_password('replacement-password',db.get(app.User,self.user.id).password_hash))
                self.assertIsNone(db.scalar(select(app.AuthSession).where(app.AuthSession.token_hash==app.token_hash(old_cookie))))
            headers={'X-CSRF-Token':client.cookies.get('sf_csrf')}
            self.assertEqual(client.post('/api/auth/reset-password',json={'token':reset,'password':'another-password'},headers=headers).status_code,400)

    def test_auth_link_expiry_and_private_chat_only(self):
        import json
        with app.SessionLocal() as db:
            token=app.issue_telegram_auth_link(db,self.user,'login')
            row=db.scalar(select(app.UserSetting).where(app.UserSetting.key=='auth-link:'+app.token_hash(token)))
            row.value=json.dumps({'purpose':'login','expires':0});db.commit()
        with TestClient(app.app) as client:
            client.cookies.set('sf_csrf','tg-test',domain='testserver.local',path='/')
            self.assertEqual(client.post('/api/auth/link-info',json={'token':token,'purpose':'login'},headers={'X-CSRF-Token':'tg-test'}).status_code,400)
        with patch.object(bot,'send') as send:
            bot.send_auth_link({'chat':{'id':123,'type':'group'},'from':{'id':123}},'reset')
            send.assert_not_called()
