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

    def test_every_message_has_desktop_inline_navigation_without_duplicate_buttons(self):
        rows=[[{'text':'Мой день','callback_data':'today'}]]
        markup=json.loads(bot.keyboard(rows))['inline_keyboard']
        actions=[b['callback_data'] for row in markup for b in row if 'callback_data' in b]
        self.assertEqual(set(actions),{'menu','today','homework','habits','schedule','reminders'})
        self.assertEqual(len(actions),len(set(actions)))
        self.assertEqual(len(rows),1)

    def test_start_reveals_old_menu_below_notifications_and_coalesces_queued_commands(self):
        digest,_=image_data(Path(bot.__file__).parent/'static/bot_images/my-study.jpg')
        self.cache.set(digest,'main-cover')
        bot.remember_menu('123',{'message_id':10,'photo':True,'image':'/static/bot_images/my-study.jpg','image_hash':digest})
        def telegram(method,params,**kwargs):
            if method=='sendPhoto':return {'message_id':150,'photo':[{'file_id':'main-cover'}]}
            return {'message_id':params.get('message_id',150)}
        with patch.object(bot,'ensure_quick_menu'),patch.object(bot,'tg',side_effect=telegram) as api:
            for mid in range(100,107):bot.handle({'message_id':mid,'chat':{'id':123,'type':'private'},'text':'/start'})
        self.assertEqual(bot.menu_state('123')['message_id'],150)
        calls=[call.args[0] for call in api.call_args_list]
        self.assertEqual(calls.count('sendPhoto'),1)
        self.assertNotIn('deleteMessage',calls)
        retired=[call.args[1]['message_id'] for call in api.call_args_list if call.args[0]=='editMessageReplyMarkup']
        self.assertEqual(retired,[10])

    def test_navigation_inside_active_menu_edits_the_same_message(self):
        bot.remember_menu('123',{'message_id':150,'photo':False})
        with patch.object(bot,'tg'),patch.object(bot,'display') as display,patch.object(bot,'show_visible_menu') as reveal:
            bot.callback({'id':'q','data':'habits','message':{'message_id':150,'chat':{'id':123}}})
        display.assert_called_once_with('123','habits',150);reveal.assert_not_called()

    def test_navigation_from_new_notification_reveals_menu_without_changing_notification(self):
        bot.remember_menu('123',{'message_id':10,'photo':False})
        digest,_=image_data(Path(bot.__file__).parent/'static/bot_images/today.jpg');self.cache.set(digest,'day-cover')
        with patch.object(bot,'tg',return_value={'message_id':90,'photo':[{'file_id':'day-cover'}]}) as api:
            bot.callback({'id':'q','data':'today','message':{'message_id':80,'chat':{'id':123}}})
        self.assertEqual(bot.menu_state('123')['message_id'],90)
        self.assertTrue(any(call.args[0]=='sendPhoto' for call in api.call_args_list))
        self.assertFalse(any(call.args[1].get('message_id')==80 for call in api.call_args_list))

    def test_missing_cover_still_returns_a_visible_text_menu(self):
        bot.remember_menu('123',{'message_id':10,'photo':False})
        with patch.object(bot,'image_data',side_effect=FileNotFoundError('cover')),patch.object(bot,'tg',return_value={'message_id':90}) as api:
            bot.show_visible_menu('123','menu',80)
        self.assertTrue(any(call.args[0]=='sendMessage' for call in api.call_args_list))
        self.assertEqual(bot.menu_state('123')['message_id'],90)

    def test_missing_cover_does_not_prevent_opening_a_section(self):
        bot.remember_menu('123',{'message_id':10,'photo':False})
        with patch.object(bot,'image_data',side_effect=FileNotFoundError('cover')),patch.object(bot,'tg',return_value={'message_id':10}) as api:
            bot.send_section('123','homework','Actual homework content')
        self.assertEqual(api.call_args.args[0],'editMessageText')
        self.assertIn('Actual homework content',api.call_args.args[1]['text'])
        self.assertEqual(bot.menu_state('123')['message_id'],10)

    def test_timeout_while_revealing_menu_keeps_previous_state_and_does_not_retire_it(self):
        bot.remember_menu('123',{'message_id':10,'photo':False})
        digest,_=image_data(Path(bot.__file__).parent/'static/bot_images/my-study.jpg');self.cache.set(digest,'cover')
        with patch.object(bot,'tg',side_effect=TimeoutError('offline')) as api:
            with self.assertRaises(TimeoutError):bot.show_visible_menu('123','menu',80)
        self.assertEqual(bot.menu_state('123')['message_id'],10)
        self.assertEqual(api.call_count,1)
