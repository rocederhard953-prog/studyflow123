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

    def test_blue_keyboard_does_not_mutate_input(self):
        import json
        rows = [[{'text': 'Home', 'callback_data': 'menu'}]]
        keys = json.loads(bot.keyboard(rows))['inline_keyboard']
        self.assertTrue(all(b['style'] == 'primary' for r in keys for b in r))
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
        with patch.object(bot, 'tg'), patch.object(bot, 'display') as display:
            bot.callback({'id':'q','data':'today','message':{'message_id':111,'chat':{'id':123}}})
        display.assert_called_once_with('123', 'today', None)

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


if __name__ == '__main__':
    unittest.main()
