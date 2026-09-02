from app.executor import exec_kalshi
from app.config_store import load_creds
print('dry :', exec_kalshi(load_creds()['kalshi'], usd=0.25, dry=True))
print('real:', exec_kalshi(load_creds()['kalshi'], usd=0.25))
