/* Signed Mini App data or a one-time link from a previously linked private chat. */
async function authTelegramOptions(){return api('/auth/options');}
async function startTelegramLogin(){
 try{
    const data=window.Telegram?.WebApp?.initData;
    await authTelegramOptions();
    if(data){await api('/auth/telegram',{method:'POST',body:JSON.stringify({init_data:data})});await boot();return;}
    await showTelegramAuthHelp('login');
 }catch(e){document.getElementById('authError').textContent=e.message;}
}
async function showTelegramAuthHelp(purpose){
 try{
    const {bot_url}=await authTelegramOptions();
    const reset=purpose==='reset',cmd=reset?'/reset':'/login';
    openModal(reset?'Восстановить пароль':'Вход через Telegram',`<p>Используй Telegram, который уже привязан к твоему аккаунту My-Study.</p><p>Открой бота и отправь <b>${cmd}</b>. Бот выдаст одноразовую ссылку на 10 минут.</p>${bot_url?`<a class="primary full auth-tg-link" href="${bot_url}?start=${purpose}" target="_blank" rel="noopener noreferrer">Открыть бота →</a>`:'<p class="muted">Открой своего бота My-Study в Telegram.</p>'}<p class="muted small">Если Telegram ещё не привязан и пароль забыт, обратись к владельцу платформы. Отправка писем по email пока не подключена.</p>`);
 }catch(e){document.getElementById('authError').textContent=e.message;}
}
async function handleTelegramAuthFragment(){
 const params=new URLSearchParams(location.hash.slice(1));
 const purpose=params.has('tg_reset')?'reset':params.has('tg_login')?'login':null;
 if(!purpose)return;
 const token=params.get('tg_'+purpose);history.replaceState(null,'',location.pathname+location.search);
 try{
    await authTelegramOptions();
    const identity=await api('/auth/link-info',{method:'POST',body:JSON.stringify({token,purpose})});
    const name=esc(identity.display_name||identity.username);
    if(purpose==='login'){
      openModal('Подтверди вход',`<p>Войти в аккаунт <b>${name}</b> (@${esc(identity.username)})?</p><p class="muted small">Продолжай, если это твой аккаунт и ты сам запросил ссылку в боте.</p><button class="primary full" id="telegramConfirmLogin">Войти</button>`);
      document.getElementById('telegramConfirmLogin').onclick=async e=>{e.target.disabled=true;try{await api('/auth/link-login',{method:'POST',body:JSON.stringify({token,purpose})});closeModal();await boot();}catch(error){toast(error.message);e.target.disabled=false;}};
    }else{
      openModal('Новый пароль',`<p>Аккаунт: <b>${name}</b> (@${esc(identity.username)})</p><form id="resetPasswordForm"><label>Новый пароль<input name="password" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><label>Повтори пароль<input name="repeat" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><button class="primary">Сохранить пароль</button></form>`);
      document.getElementById('resetPasswordForm').onsubmit=async e=>{e.preventDefault();const form=new FormData(e.target);if(form.get('password')!==form.get('repeat')){toast('Пароли не совпадают');return;}const button=e.target.querySelector('button');button.disabled=true;try{await api('/auth/reset-password',{method:'POST',body:JSON.stringify({token,password:form.get('password')})});closeModal();toast('Пароль обновлён. Старые сеансы завершены.');await boot();}catch(error){toast(error.message);button.disabled=false;}};
    }
 }catch(e){document.getElementById('authError').textContent=e.message;toast(e.message);}
}
document.getElementById('telegramLoginButton').onclick=startTelegramLogin;
document.getElementById('forgotPasswordButton').onclick=()=>showTelegramAuthHelp('reset');
handleTelegramAuthFragment();
