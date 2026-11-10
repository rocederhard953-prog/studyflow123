"""Start web server and optional Telegram worker in one process."""
import os,threading,traceback,uvicorn

def run_bot():
    try:
        from bot import main
        main()
    except Exception:traceback.print_exc()

if __name__=='__main__':
    if os.getenv('TELEGRAM_BOT_TOKEN','').strip():
        threading.Thread(target=run_bot,daemon=True,name='studyflow-telegram').start()
    else:print('TELEGRAM_BOT_TOKEN not configured',flush=True)
    uvicorn.run('app:app',host='0.0.0.0',port=int(os.getenv('PORT','3000')),workers=1,proxy_headers=True)
