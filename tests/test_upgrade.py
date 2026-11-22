import base64
import json
from datetime import datetime, timezone
from unittest.mock import patch
from test_platform import PlatformTests
import test_v21 as fixtures
from upgrade_features import quiet, valid_subscription
from sqlalchemy import select

app=fixtures.app

class UpgradeTests(PlatformTests):
    def test_task_chat_persists_and_is_not_visible_to_another_account(self):
        task=fixtures.V21Tests.task(self)
        with patch.object(app.assistant,'ai_configured',return_value=True),patch.object(app.assistant,'ask_ai',return_value={'reply':'x = 2','actions':[],'source':'ai'}):
            response=self.client.post('/api/assistant/chat',json={'message':'Solve 2x = 4','task_id':task.id},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
        url=f'/api/tasks/{task.id}/chat';self.assertEqual(self.client.get(url).json()[-1]['content'],'x = 2')
        app.app.dependency_overrides[app.current_user]=lambda:self.other
        self.assertEqual(self.client.get(url).status_code,404)

    def test_board_history_is_owned_and_contains_previous_revision(self):
        task=fixtures.V21Tests.task(self);url='/api/whiteboard?task_id='+str(task.id)
        data={'revision':0,'strokes':[],'images':[],'grid':True,'layout':'large-v1'}
        self.assertEqual(self.client.put(url,json=data,headers=self.headers).status_code,200)
        data['revision']=1;data['grid']=False
        self.assertEqual(self.client.put(url,json=data,headers=self.headers).status_code,200)
        history=self.client.get('/api/whiteboard/history?task_id='+str(task.id)).json()
        self.assertEqual(history[-1]['document']['revision'],1);self.assertTrue(history[-1]['document']['grid'])
        app.app.dependency_overrides[app.current_user]=lambda:self.other
        self.assertEqual(self.client.get('/api/whiteboard/history?task_id='+str(task.id)).status_code,404)

    def test_webpush_payload_privacy_and_subscription_expiration(self):
        import os
        import pywebpush
        encode=lambda raw:base64.urlsafe_b64encode(raw).decode().rstrip('=')
        sub={'endpoint':'https://fcm.googleapis.com/fcm/send/test','keys':{'auth':encode(b'a'*16),'p256dh':encode(b'a'*65)}}
        with patch.dict(os.environ,{'VAPID_PUBLIC_KEY':'public','VAPID_PRIVATE_KEY':'private','VAPID_SUBJECT':'mailto:test@example.com'}):
            self.assertEqual(self.client.post('/api/push/subscribe',json=sub,headers=self.headers).status_code,200)
            self.client.put('/api/push/preferences',json={'private':True},headers=self.headers)
            with patch.object(pywebpush,'webpush') as sender:
                result=self.client.post('/api/push/test',headers=self.headers);self.assertEqual(result.status_code,200,result.text)
                payload=json.loads(sender.call_args.kwargs['data']);self.assertEqual(payload['body'],'Новое напоминание');self.assertEqual(payload['title'],'My-Study')
            self.assertEqual(len(self.client.get('/api/push/inbox').json()),1)
            self.client.post('/api/push/read',headers=self.headers)
            self.assertTrue(self.client.get('/api/push/inbox').json()[0]['read'])

    def test_workspace_revision_and_account_isolation(self):
        url='/api/workspace/exams';body={'revision':0,'items':[{'title':'Exam','start':'2026-11-22','date':'2026-12-20','topics':['Topic'],'days':[0]}]}
        self.assertEqual(self.client.put(url,json=body,headers=self.headers).status_code,200)
        self.assertEqual(self.client.put(url,json=body,headers=self.headers).status_code,409)
        app.app.dependency_overrides[app.current_user]=lambda:self.other
        self.assertEqual(self.client.get(url).json()['items'],[])

    def test_deleted_task_restores_board_steps_and_photo_records(self):
        task=fixtures.V21Tests.task(self)
        with app.SessionLocal() as db:
            db.add(app.Attachment(user_id=self.user.id,task_id=task.id,filename='a.png',stored_name='a.png',mime='image/png'))
            app.upgrade_put(db,self.user.id,'whiteboard:'+str(task.id),{'revision':2,'strokes':[]})
            app.upgrade_put(db,self.user.id,'task-steps:'+str(task.id),[{'title':'Read','done':False}]);db.commit()
        response=self.client.delete('/api/tasks/'+str(task.id),headers=self.headers);self.assertEqual(response.status_code,200,response.text)
        trash=response.json()['trash_id'];self.assertEqual(len(self.client.get('/api/trash').json()),1)
        app.app.dependency_overrides[app.current_user]=lambda:self.other
        self.assertEqual(self.client.post('/api/trash/'+trash+'/restore',headers=self.headers).status_code,404)
        app.app.dependency_overrides[app.current_user]=lambda:self.user
        restored=self.client.post('/api/trash/'+trash+'/restore',headers=self.headers);self.assertEqual(restored.status_code,200,restored.text)
        tid=restored.json()['id'];self.assertEqual(self.client.get('/api/whiteboard?task_id='+str(tid)).json()['revision'],2)
        self.assertEqual(self.client.get('/api/tasks/'+str(tid)+'/steps').json()[0]['title'],'Read')
        self.assertEqual(len(self.client.get('/api/tasks').json()[0]['attachments']),1)

    def test_subtasks_reject_other_account_and_invalid_items(self):
        task=fixtures.V21Tests.task(self);url=f'/api/tasks/{task.id}/steps'
        self.assertEqual(self.client.put(url,json={'items':[{'title':'Step','done':False}]},headers=self.headers).status_code,200)
        self.assertEqual(self.client.put(url,json={'items':[{'title':'Step','done':'false'}]},headers=self.headers).status_code,422)
        app.app.dependency_overrides[app.current_user]=lambda:self.other
        self.assertEqual(self.client.get(url).status_code,404)

    def test_push_validation_blocks_arbitrary_network_targets(self):
        encode=lambda raw:base64.urlsafe_b64encode(raw).decode().rstrip('=')
        sub={'endpoint':'https://fcm.googleapis.com/fcm/send/test','keys':{'auth':encode(b'a'*16),'p256dh':encode(b'a'*65)}}
        self.assertTrue(valid_subscription(sub))
        for endpoint in ('http://fcm.googleapis.com/push','https://127.0.0.1/push','https://fcm.googleapis.com.attacker.example/push','https://fcm.googleapis.com:123/push','https://user@fcm.googleapis.com/push'):
            self.assertFalse(valid_subscription({**sub,'endpoint':endpoint}))

    def test_quiet_hours_cross_midnight_and_equal_disables(self):
        self.assertTrue(quiet(datetime(2026,11,22,23,0),'22:00','08:00'))
        self.assertTrue(quiet(datetime(2026,11,22,7,59),'22:00','08:00'))
        self.assertFalse(quiet(datetime(2026,11,22,8,0),'22:00','08:00'))
        self.assertFalse(quiet(datetime(2026,11,22,12,0),'00:00','00:00'))

    def test_pause_keeps_history_and_returns_periods(self):
        habit=self.client.post('/api/habits',json={'name':'Read'},headers=self.headers).json();url=f'/api/habits/{habit["id"]}/pause'
        day=datetime.now(timezone.utc).date().isoformat()
        response=self.client.put(url,json={'until':day},headers=self.headers);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/habits').json()[0]['pause']['periods'][0]['start'],day)
        self.assertEqual(self.client.put(url,json={'until':None},headers=self.headers).status_code,200)

    def test_repeating_templates_do_not_duplicate_next_tick(self):
        with app.SessionLocal() as db:
            app.upgrade_put(db,self.user.id,'upgrade:templates',{'revision':1,'items':[{'title':'Repeat','subject':'Math','description':'','next':'2020-01-01','repeat':7}]});db.commit()
        app.upgrade_tick();app.upgrade_tick()
        self.assertEqual(len(self.client.get('/api/tasks').json()),1)

    def test_note_recycle_restore(self):
        self.client.put('/api/lesson-notes',json={'Math':'hello'},headers=self.headers)
        self.assertEqual(self.client.delete('/api/study-notes/Math',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/lesson-notes').json(),{})
        ident=self.client.get('/api/trash').json()[0]['id']
        self.assertEqual(self.client.post('/api/trash/'+ident+'/restore',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/lesson-notes').json()['Math'],'hello')
