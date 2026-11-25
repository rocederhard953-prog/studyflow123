import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import test_platform as setup
import test_v21 as fixtures
from bot_support import MediaCache, image_data, QUICK_ACTIONS, quick_keyboard, notification_loop

bot=fixtures.bot;app=fixtures.app

class Response:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps({'ok':True,'result':{'message_id':42,'photo':[{'file_id':'telegram-file-id'}]}}).encode()

class BotFastTests(unittest.TestCase):
    def setUp(self):
        setup.PlatformTests.setUp(self)
        self.temp=tempfile.TemporaryDirectory()
        self.cache=MediaCache(self.temp.name,'test-token')
        self.media_patch=patch.object(bot,'MEDIA_CACHE',self.cache);self.media_patch.start()
    def tearDown(self):
        self.media_patch.stop();self.temp.cleanup();setup.PlatformTests.tearDown(self)

    def test_same_screen_skips_api_even_after_menu_state_reload(self):
        with patch.object(bot,'tg',return_value={'message_id':42}) as send:
            bot.send('123','Stable');bot.send('123','Stable')
            bot.SCREEN_IDS.clear();bot.SCREEN_META.clear();bot.send('123','Stable')
        self.assertEqual(send.call_count,1)

    def test_images_are_uploaded_once_and_then_reused_by_file_id(self):
        with patch.object(bot.urllib.request,'urlopen',return_value=Response()) as upload,patch.object(bot,'tg',return_value={'message_id':42}) as edit:
            bot.send_section('123','homework','Tasks')
            bot.send_section('123','habits','Habits')
            bot.send_section('123','homework','Tasks again')
        self.assertEqual(upload.call_count,2);self.assertEqual(edit.call_count,1)
        self.assertEqual(edit.call_args.args[0],'editMessageMedia')
        self.assertEqual(json.loads(edit.call_args.args[1]['media'])['media'],'telegram-file-id')

    def test_media_cache_survives_restart_and_is_scoped_to_bot_token(self):
        self.cache.set('hash','file-id')
        self.assertEqual(MediaCache(self.temp.name,'test-token').get('hash'),'file-id')
        self.assertIsNone(MediaCache(self.temp.name,'another-bot').get('hash'))

    def test_old_menu_state_refreshes_the_replaced_cover(self):
        bot.remember_menu('123',{'message_id':42,'photo':True,'image':'/static/bot_images/my-study.jpg'})
        with patch.object(bot.urllib.request,'urlopen',return_value=Response()) as upload:
            bot.send_section('123','menu','New interface')
        self.assertEqual(upload.call_count,1)
        self.assertTrue(upload.call_args.args[0].full_url.endswith('editMessageMedia'))

    def test_unchanged_cover_uses_caption_edit_for_checkbox_updates(self):
        with patch.object(bot.urllib.request,'urlopen',return_value=Response()) as upload,patch.object(bot,'tg',return_value={'message_id':42}) as edit:
            bot.send_section('123','habits','Before')
            bot.send_section('123','habits','After')
        self.assertEqual(upload.call_count,1);self.assertEqual(edit.call_args.args[0],'editMessageCaption')

    def test_invalid_cached_id_reuploads_but_network_timeout_does_not(self):
        digest,_=image_data(Path(bot.__file__).parent/'static/bot_images/habits.jpg')
        self.cache.set(digest,'expired');bot.remember_menu('123',{'message_id':42,'photo':True,'image':'/static/bot_images/my-study.jpg'})
        with patch.object(bot,'tg',side_effect=RuntimeError('Bad Request: wrong file identifier')),patch.object(bot.urllib.request,'urlopen',return_value=Response()) as upload:
            bot.send_section('123','habits','Habits');self.assertEqual(upload.call_count,1)
        self.assertEqual(self.cache.get(digest),'telegram-file-id')
        bot.remember_menu('123',{'message_id':42,'photo':True,'image':'/static/bot_images/my-study.jpg'})
        with patch.object(bot,'tg',side_effect=TimeoutError('offline')),patch.object(bot.urllib.request,'urlopen') as upload:
            with self.assertRaises(TimeoutError):bot.send_section('123','habits','Changed')
            upload.assert_not_called()

    def test_different_chats_do_not_share_network_lock(self):
        bot.remember_menu('123',{'message_id':42,'photo':False})
        bot.remember_menu('456',{'message_id':43,'photo':False})
        entered=threading.Event();release=threading.Event();done=threading.Event();errors=[]
        def remote(method,params,**kwargs):
            if params['chat_id']=='123':entered.set();release.wait(3)
            return {'message_id':params['message_id']}
        def first():
            try:bot.send('123','One')
            except Exception as error:errors.append(error)
        def second():
            try:bot.send('456','Two');done.set()
            except Exception as error:errors.append(error)
        with patch.object(bot,'tg',side_effect=remote):
            a=threading.Thread(target=first);a.start();self.assertTrue(entered.wait(1))
            b=threading.Thread(target=second);b.start()
            try:self.assertTrue(done.wait(1),'A slow chat blocked another chat')
            finally:release.set();a.join(3);b.join(3)
        self.assertEqual(errors,[])

    def test_quick_keyboard_is_persistent_and_has_no_forced_bright_style(self):
        data=json.loads(quick_keyboard('https://example.com'))
        self.assertTrue(data['is_persistent']);self.assertTrue(data['resize_keyboard']);self.assertFalse(data['one_time_keyboard'])
        self.assertEqual({b['text'] for row in data['keyboard'] for b in row if 'web_app' not in b},set(QUICK_ACTIONS))
        self.assertTrue(all('style' not in b for row in data['keyboard'] for b in row))

    def test_quick_menu_installs_once_and_can_be_requested_again(self):
        with patch.object(bot,'tg',return_value={'message_id':99}) as send:
            self.assertTrue(bot.ensure_quick_menu('123'));self.assertFalse(bot.ensure_quick_menu('123'))
            self.assertTrue(bot.ensure_quick_menu('123',force=True));self.assertEqual(send.call_count,2)
            self.assertTrue(json.loads(send.call_args.args[1]['reply_markup'])['is_persistent'])
        self.assertIsNone(bot.menu_state('123').get('message_id'))

    def test_quick_navigation_is_not_consumed_as_homework_text(self):
        bot.DRAFTS['123']={'step':'title'}
        with patch.object(bot,'ensure_quick_menu'),patch.object(bot,'display') as display,patch.object(bot,'homework_title') as title:
            bot.handle({'chat':{'id':123,'type':'private'},'text':'📅 Мой день'})
        display.assert_called_once_with('123','today');title.assert_not_called();self.assertNotIn('123',bot.DRAFTS)

    def test_background_notifications_do_not_run_on_polling_thread(self):
        stop=threading.Event();started=threading.Event();released=threading.Event()
        def tick():started.set();released.wait(2)
        worker=threading.Thread(target=notification_loop,args=(tick,stop),daemon=True);worker.start()
        try:self.assertTrue(started.wait(1));self.assertTrue(worker.is_alive())
        finally:stop.set();released.set();worker.join(2)
