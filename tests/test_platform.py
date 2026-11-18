"""Behaviour checks for personal planning and the persistent Telegram menu."""
import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
import test_v21 as fixtures
from fastapi.testclient import TestClient
from sqlalchemy import select

app=fixtures.app
bot=fixtures.bot


class PlatformTests(unittest.TestCase):
    def setUp(self):
        fixtures.V21Tests.setUp(self);bot.SCREEN_META.clear()
        app.app.dependency_overrides[app.current_user]=lambda:self.user
        self.client=TestClient(app.app);self.client.cookies.set('sf_csrf','platform-test');self.headers={'X-CSRF-Token':'platform-test'}

    def tearDown(self):
        self.client.close();app.app.dependency_overrides.pop(app.current_user,None);bot.SCREEN_IDS.clear();bot.SCREEN_META.clear()

    def test_day_plan_validates_owned_records_and_three_priorities(self):
        task=fixtures.V21Tests.task(self)
        item={'kind':'task','id':task.id,'minutes':30,'important':True}
        data={'day':'2026-11-19','items':[item]}
        self.assertEqual(self.client.put('/api/day-plan',json=data,headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/day-plan?day=2026-11-19').json()['items'][0]['minutes'],30)
        data['items']=[{'kind':'custom','id':str(i),'title':'Study','minutes':20,'important':True} for i in range(4)]
        self.assertEqual(self.client.put('/api/day-plan',json=data,headers=self.headers).status_code,422)
        app.app.dependency_overrides[app.current_user]=lambda:self.other
        self.assertEqual(self.client.get('/api/day-plan?day=2026-11-19').json()['items'],[])
        self.assertEqual(self.client.put('/api/day-plan',json={'day':'2026-11-19','items':[item]},headers=self.headers).status_code,404)

    def test_quantitative_weekly_habit_progress_and_checkbox_share_state(self):
        cfg={'mode':'weekly','weekly_target':3,'target':20,'unit':'страниц'}
        result=self.client.post('/api/habits',json={'name':'Читать','days':[],'config':cfg},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text);hid=result.json()['id'];day=datetime.now(timezone.utc).date().isoformat()
        url=f'/api/habits/{hid}/progress'
        response=self.client.put(url,json={'day':day,'amount':12,'note':'Начало'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['done'])
        self.assertTrue(self.client.put(url,json={'day':day,'amount':20},headers=self.headers).json()['done'])
        h=self.client.get('/api/habits').json()[0];self.assertEqual(h['config'],cfg);self.assertIn(day,h['checks'])
        self.client.put(f'/api/habits/{hid}/check',json={'day':day,'done':False},headers=self.headers)
        h=self.client.get('/api/habits').json()[0];self.assertEqual(h['progress'][day]['amount'],0);self.assertNotIn(day,h['checks'])
        app.app.dependency_overrides[app.current_user]=lambda:self.other
        self.assertEqual(self.client.put(url,json={'day':day,'amount':20},headers=self.headers).status_code,404)

    def test_weekly_reports_count_actual_completion_and_undo(self):
        task=fixtures.V21Tests.task(self)
        self.assertEqual(self.client.get('/api/weekly-report').json()['tasks_done'],0)
        for _ in range(2):self.client.put(f'/api/tasks/{task.id}',json={'done':True},headers=self.headers)
        self.assertEqual(self.client.get('/api/weekly-report').json()['tasks_done'],1)
        self.client.put(f'/api/tasks/{task.id}',json={'done':False},headers=self.headers)
        self.assertEqual(self.client.get('/api/weekly-report').json()['tasks_done'],0)

    def test_menu_reuses_message_after_restart_and_does_not_delete(self):
        with patch.object(bot,'tg',return_value={'message_id':42}) as tg:
            bot.send('123','First');bot.send('123','Second')
            bot.SCREEN_IDS.clear();bot.SCREEN_META.clear();bot.send('123','Third')
        methods=[call.args[0] for call in tg.call_args_list]
        self.assertEqual(methods,['sendMessage','editMessageText','editMessageText'])
        self.assertEqual(tg.call_args.args[1]['message_id'],42)

    def test_unchanged_edit_and_network_error_do_not_send_duplicate(self):
        bot.remember_menu('123',{'message_id':42,'photo':False})
        with patch.object(bot,'tg',side_effect=RuntimeError('Bad Request: message is not modified')) as tg:
            bot.send('123','Same');self.assertEqual(tg.call_count,1)
        with patch.object(bot,'tg',side_effect=TimeoutError('offline')) as tg:
            with self.assertRaises(TimeoutError):bot.send('123','Same')
            self.assertEqual(tg.call_count,1)

    def test_photo_sections_edit_media_in_same_message(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'ok':True,'result':{'message_id':42,'photo':[{}]}}).encode()
        bot.remember_menu('123',{'message_id':42,'photo':True,'image':'/static/bot_images/my-study.jpg'})
        with patch.object(bot.urllib.request,'urlopen',return_value=Response()) as request:
            bot.send_section('123','habits','Habits')
        self.assertTrue(request.call_args.args[0].full_url.endswith('editMessageMedia'))
        self.assertIn(b'name="message_id"\r\n\r\n42',request.call_args.args[0].data)
        self.assertEqual(bot.SCREEN_IDS['123'],42)

    def test_menu_pagination_preserves_all_text_and_uses_caption(self):
        bot.remember_menu('123',{'message_id':42,'photo':True,'image':'/static/bot_images/my-study.jpg'})
        text=('Задание\n'*300)+'Последнее'
        with patch.object(bot,'tg',return_value={'message_id':42}) as tg:
            bot.send('123',text,bot.back())
            state=bot.menu_state('123');bot.paint_menu('123',state['text'],state['rows'],page_index=2)
        self.assertEqual(tg.call_args.args[0],'editMessageCaption')
        self.assertLessEqual(len(tg.call_args.args[1]['caption']),1024)
        self.assertIn('Последнее',tg.call_args.args[1]['caption'])
        self.assertEqual(bot.menu_state('123')['text'],text)

    def test_weekly_telegram_report_opt_in_and_no_duplicate(self):
        local=datetime.now(timezone.utc)
        with app.SessionLocal() as db:
            user=db.get(app.User,self.user.id);link=db.scalar(select(app.TelegramLink).where(app.TelegramLink.user_id==user.id))
            prefs={'enabled':True,'weekday':local.weekday(),'time':local.strftime('%H:%M')};app.feature_put(db,user.id,'weekly-report-prefs',prefs);db.commit()
            with patch.object(bot,'notify') as send:
                bot.weekly_report_tick(db,user,link,None,local);bot.weekly_report_tick(db,user,link,None,local)
                self.assertEqual(send.call_count,1)

    def test_goal_blocks_compute_progress_reject_conflicts_and_enforce_owner(self):
        blocks=[{'id':'b1','title':'Задачи ЕГЭ','items':[{'id':'s'+str(i),'title':'Задача '+str(i),'done':False} for i in range(1,28)]}]
        response=self.client.post('/api/goals',json={'title':'27 задач','blocks':blocks},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);goal=response.json();gid=goal['id']
        self.assertEqual(goal['target'],27);self.assertEqual(goal['progress'],0);self.assertEqual(goal['revision'],1)
        url=f'/api/goals/{gid}/steps/s1'
        response=self.client.put(url,json={'done':True,'revision':1},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);saved=response.json();self.assertEqual(saved['progress'],1)
        self.assertEqual(saved['history'][-1]['done'],1)
        self.assertEqual(self.client.put(url,json={'done':False,'revision':1},headers=self.headers).status_code,409)
        self.assertEqual(self.client.put(f'/api/goals/{gid}',json={'progress':27},headers=self.headers).status_code,409)
        app.app.dependency_overrides[app.current_user]=lambda:self.other
        self.assertEqual(self.client.put(url,json={'done':True,'revision':2},headers=self.headers).status_code,404)
        self.assertEqual(self.client.get('/api/goals').json(),[])

    def test_goal_completion_and_undo_are_derived_from_steps(self):
        blocks=[{'id':'b','title':'Блок','items':[{'id':'s','title':'Пример','done':False}]}]
        goal=self.client.post('/api/goals',json={'title':'Одна задача','blocks':blocks},headers=self.headers).json();url=f"/api/goals/{goal['id']}/steps/s"
        self.assertTrue(self.client.put(url,json={'done':True,'revision':1},headers=self.headers).json()['done'])
        self.assertFalse(self.client.put(url,json={'done':False,'revision':2},headers=self.headers).json()['done'])

    def test_volume_shapes_roundtrip_and_deep_links_load_app(self):
        for i,shape in enumerate(('parallelogram','cylinder','box','cone','sphere','pyramid')):
            data={'layout':'large-v1','revision':i,'grid':True,'images':[],'strokes':[{'tool':shape,'color':'#111111','width':4,'points':[[10,10],[300,300]]}]}
            response=self.client.put('/api/whiteboard',json=data,headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.client.get('/api/whiteboard').json()['strokes'][0]['tool'],shape)
        response=self.client.get('/orbit/rhythm/goals');self.assertEqual(response.status_code,200);self.assertIn('orbit-router.js',response.text)

    def test_deleted_goal_cannot_leak_old_steps_into_a_reused_id(self):
        goal=self.client.post('/api/goals',json={'title':'Old','blocks':[{'id':'b','title':'Block','items':[{'id':'s','title':'Step','done':True}]}]},headers=self.headers).json()
        self.assertEqual(self.client.delete('/api/goals/'+str(goal['id']),headers=self.headers).status_code,200)
        new=self.client.post('/api/goals',json={'title':'New','target':5},headers=self.headers).json()
        self.assertEqual(new['blocks'],[]);self.assertEqual(new['history'],[])

