from app.executor import exec_limitless
from app.config_store import load_creds
cr = load_creds()['limitless']
print('dry :', exec_limitless(cr, usd=0.25, dry=True))
print('real:', exec_limitless(cr, usd=0.25))
