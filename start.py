"""Single-process launcher for StudyFlow web app and optional Telegram worker."""
import os, threading
import uvicorn

def run_bot():
    from bot import main
    main()

if __name__=='__main__':
    if os.getenv('TELEGRAM_BOT_TOKEN','').strip():
        threading.Thread(target=run_bot,daemon=True,name='studyflow-telegram').start()
    else:
        print('TELEGRAM_BOT_TOKEN is not set; web app will run without Telegram.',flush=True)
    uvicorn.run('app:app',host='0.0.0.0',port=int(os.getenv('PORT','8000')),workers=1,proxy_headers=True)
