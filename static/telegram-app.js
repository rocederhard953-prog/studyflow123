/* Telegram is an optional container. Account access still uses the site's login. */
(()=>{
  const tg=window.Telegram?.WebApp;
  if(!tg?.initData)return;
  document.documentElement.classList.add('telegram-mini-app');
  function syncViewport(){
    const s=tg.safeAreaInset||{},c=tg.contentSafeAreaInset||{};
    const root=document.documentElement;
    for(const edge of ['top','bottom','left','right'])root.style.setProperty('--tg-inset-'+edge,((s[edge]||0)+(c[edge]||0))+'px');
    root.style.setProperty('--tg-app-height',(tg.viewportStableHeight||window.innerHeight)+'px');
  }
  function syncColors(){
    const color=getComputedStyle(document.documentElement).getPropertyValue('--theme-back').trim()||'#090d1c';
    try{if(tg.isVersionAtLeast('6.1')){tg.setHeaderColor(color);tg.setBackgroundColor(color);}if(tg.isVersionAtLeast('7.10'))tg.setBottomBarColor(color);}catch{}
  }
  tg.ready();tg.expand();syncViewport();syncColors();
  ['viewportChanged','safeAreaChanged','contentSafeAreaChanged'].forEach(event=>tg.onEvent(event,syncViewport));
  tg.onEvent('themeChanged',syncColors);
  new MutationObserver(syncColors).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  /* Never trust initDataUnsafe for account authentication or linking. */
})();
