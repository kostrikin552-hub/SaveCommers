import os,time,json,uuid,sqlite3,threading,logging,hmac,hashlib,traceback
from datetime import datetime,timedelta
from http.server import HTTPServer,BaseHTTPRequestHandler
from collections import Counter
import requests
from dotenv import load_dotenv
logging.basicConfig(level=logging.INFO,format='%(asctime)s - %(levelname)s - %(message)s')
logger=logging.getLogger(__name__)
load_dotenv()
TOKEN=os.getenv("BOT_TOKEN")
if not TOKEN:raise ValueError("BOT_TOKEN not set")
ADMIN_ID=int(os.getenv("ADMIN_ID","5629144056"))
BASE_URL=os.getenv("BASE_URL","https://your-bot.onrender.com")
YOOKASSA_SHOP_ID=os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY=os.getenv("YOOKASSA_SECRET_KEY")
WEBAPP_URL=os.getenv("WEBAPP_URL","https://example.com")
SECRET_KEY=os.getenv("SECRET_KEY","your-secret-key-change-me")
BOT_API=f"https://api.telegram.org/bot{TOKEN}"
offset=0;DB_PATH="data.db";db_lock=threading.Lock();user_states={}
def send_error_to_admin(t):
 try:send_msg(ADMIN_ID,f"🚨 Ошибка:\n{t[:4000]}")
 except:pass
def init_db():
 with db_lock:
  conn=sqlite3.connect(DB_PATH);conn.execute("PRAGMA journal_mode=WAL");c=conn.cursor()
  c.execute('''CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,last_name TEXT,referrer_id INTEGER DEFAULT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,plan_type TEXT,status TEXT,start_date TIMESTAMP,end_date TIMESTAMP,is_active INTEGER DEFAULT 1)''')
  c.execute('''CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,payment_id TEXT UNIQUE,amount INTEGER,currency TEXT,status TEXT,plan_type TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
  c.execute('''CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,owner_id INTEGER,invite_code TEXT UNIQUE)''')
  c.execute('''CREATE TABLE IF NOT EXISTS company_members(id INTEGER PRIMARY KEY AUTOINCREMENT,company_id INTEGER,user_id INTEGER,role TEXT DEFAULT 'member',UNIQUE(company_id,user_id))''')
  c.execute('''CREATE TABLE IF NOT EXISTS analysis_history(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,score INTEGER,markers_found INTEGER DEFAULT 0,positives TEXT,negatives TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
  c.execute('''CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY AUTOINCREMENT,inviter_id INTEGER,invited_id INTEGER UNIQUE,status TEXT DEFAULT 'pending',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,reward_given INTEGER DEFAULT 0)''')
  c.execute('''CREATE TABLE IF NOT EXISTS user_balances(user_id INTEGER PRIMARY KEY,balance INTEGER DEFAULT 0)''')
  c.execute('''CREATE TABLE IF NOT EXISTS withdraw_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,amount_cents INTEGER,details TEXT,status TEXT DEFAULT 'pending',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
  try:c.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
  except:pass
  conn.commit();conn.close()
init_db()
def db():conn=sqlite3.connect(DB_PATH);conn.row_factory=sqlite3.Row;return conn
def db_execute(q,p=(),r=3):
 with db_lock:
  for a in range(r):
   conn=db()
   try:c=conn.cursor();c.execute(q,p);conn.commit();return
   except sqlite3.OperationalError as e:
    if "database is locked"in str(e)and a<r-1:time.sleep(0.1*(a+1));continue
    conn.rollback();raise
   finally:conn.close()
def db_fetchone(q,p=()):
 with db_lock:
  conn=db()
  try:c=conn.cursor();c.execute(q,p);return c.fetchone()
  finally:conn.close()
def db_fetchall(q,p=()):
 with db_lock:
  conn=db()
  try:c=conn.cursor();c.execute(q,p);return c.fetchall()
  finally:conn.close()
def db_execute_lastrowid(q,p=()):
 with db_lock:
  conn=db()
  try:c=conn.cursor();c.execute(q,p);conn.commit();return c.lastrowid
  except:conn.rollback();raise
  finally:conn.close()
def get_sub(uid):return db_fetchone("SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 AND end_date>datetime('now') ORDER BY end_date DESC",(uid,))
def create_sub(uid,plan,days):
 db_execute("UPDATE subscriptions SET is_active=0 WHERE user_id=?",(uid,))
 db_execute("INSERT INTO subscriptions(user_id,plan_type,status,start_date,end_date,is_active) VALUES(?,?,'active',datetime('now'),datetime('now','+'||?||' days'),1)",(uid,plan,days))
def upsert_user(uid,un,fn,ln):db_execute("INSERT OR REPLACE INTO users(user_id,username,first_name,last_name) VALUES(?,?,?,?)",(uid,un,fn,ln))
def create_company(oid,name):
 name=name.strip()
 if len(name)<2:return None
 code=str(uuid.uuid4())[:8].upper()
 cid=db_execute_lastrowid("INSERT INTO companies(name,owner_id,invite_code) VALUES(?,?,?)",(name,oid,code))
 if cid is None:return None
 db_execute("INSERT INTO company_members(company_id,user_id,role) VALUES(?,?,'admin')",(cid,oid));return{"id":cid,"invite_code":code}
def get_company_by_user(uid):return db_fetchone("SELECT c.* FROM companies c JOIN company_members cm ON c.id=cm.company_id WHERE cm.user_id=?",(uid,))
def get_company_members(cid):return db_fetchall("SELECT u.first_name,u.username FROM company_members cm JOIN users u ON cm.user_id=u.user_id WHERE cm.company_id=?",(cid,))
def add_company_member(cid,uid):db_execute("INSERT INTO company_members(company_id,user_id,role) VALUES(?,?,'member')",(cid,uid))
def get_user_balance(uid):r=db_fetchone("SELECT balance FROM user_balances WHERE user_id=?",(uid,));return r["balance"] if r else 0
def apply_referral_bonus(uid,pid,amount_cents):
 inv=db_fetchone("SELECT referrer_id FROM users WHERE user_id=?",(uid,))
 if not inv or not inv["referrer_id"]:return
 inv_id=inv["referrer_id"];bonus_days=5
 if get_sub(inv_id):
  db_execute("UPDATE subscriptions SET end_date = datetime(end_date, '+' || ? || ' days') WHERE user_id=? AND is_active=1",(bonus_days,inv_id))
  send_msg(inv_id,f"🎉 Друг оплатил! +{bonus_days} дней (продление).")
 else:
  create_sub(inv_id,"bonus",bonus_days)
  send_msg(inv_id,f"🎉 Друг оплатил! Активировано {bonus_days} бесплатных дней.")
 bonus_cents=int(amount_cents*0.2)
 if bonus_cents>0:
  db_execute("INSERT INTO user_balances(user_id,balance) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?",(inv_id,bonus_cents,bonus_cents))
  send_msg(inv_id,f"💰 +{bonus_cents/100:.2f}₽ (20%). Баланс: {get_user_balance(inv_id)/100:.2f}₽")
 logger.info(f"Реферальный бонус: {inv_id} получил {bonus_days} дней и {bonus_cents/100:.2f}₽ за {uid}")
def withdraw_balance(uid,amount_cents):
 if get_user_balance(uid)<amount_cents:return False
 db_execute("UPDATE user_balances SET balance = balance - ? WHERE user_id = ?",(amount_cents,uid));return True
def use_balance_for_subscription(uid,amount_cents):return withdraw_balance(uid,amount_cents)
def create_withdraw_request(uid,amount_cents,details):
 db_execute('''CREATE TABLE IF NOT EXISTS withdraw_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,amount_cents INTEGER,details TEXT,status TEXT DEFAULT 'pending',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
 db_execute("INSERT INTO withdraw_requests(user_id,amount_cents,details,status) VALUES(?,?,?,'pending')",(uid,amount_cents,details))
def get_pending_withdraw_requests():
 db_execute('''CREATE TABLE IF NOT EXISTS withdraw_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,amount_cents INTEGER,details TEXT,status TEXT DEFAULT 'pending',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
 return db_fetchall("SELECT * FROM withdraw_requests WHERE status='pending' ORDER BY created_at")
def generate_signed_url(uid,hs):
 ts=int(time.time());sig=hmac.new(SECRET_KEY.encode(),f"{uid}:{ts}:{hs}".encode(),hashlib.sha256).hexdigest();return f"{WEBAPP_URL}?user_id={uid}&ts={ts}&sub={hs}&sig={sig}"
def send_msg(cid,t,kb=None):
 p={"chat_id":cid,"text":t,"parse_mode":"HTML"}
 if kb:p["reply_markup"]=json.dumps(kb)
 try:requests.post(f"{BOT_API}/sendMessage",json=p)
 except Exception as e:logger.error(f"Ошибка отправки: {e}")
def answer_cb(cb_id,t=""):
 try:requests.post(f"{BOT_API}/answerCallbackQuery",json={"callback_query_id":cb_id,"text":t})
 except Exception as e:logger.error(f"Ошибка callback: {e}")
def main_menu():
 return{"keyboard":[[{"text":"🚀 Новый анализ"},{"text":"📊 Статистика"}],[{"text":"💎 Тарифы"},{"text":"👥 B2B"}],[{"text":"👥 Пригласить друга"},{"text":"💰 Баланс"}],[{"text":"❓ Поддержка"}]],"resize_keyboard":True}
def tariffs_kb():
 return{"inline_keyboard":[[{"text":"🔓 Pro 990₽/мес","callback_data":"tariff_pro"}],[{"text":"👑 Premium 1990₽/мес","callback_data":"tariff_premium"}],[{"text":"🏢 B2B 4990₽/мес (до 10 чел)","callback_data":"tariff_b2b"}],[{"text":"🎁 Активировать 3 дня бесплатно","callback_data":"trial"}]]}
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=="/":self.send_response(200);self.end_headers();self.wfile.write(b"SaleFlow bot is running")
  else:self.send_response(404);self.end_headers()
 def do_HEAD(self):self.send_response(200);self.end_headers()
 def do_OPTIONS(self):self.send_response(200);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Methods','POST, OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type');self.end_headers()
 def do_POST(self):
  logger.info(f"POST {self.path}")
  if self.path=="/webhook/yookassa":
   try:
    length=int(self.headers.get('Content-Length',0));data=json.loads(self.rfile.read(length))
    if data.get("event")=="payment.succeeded":
     obj=data.get("object",{});uid=int(obj.get("metadata",{}).get("user_id",0));plan=obj.get("metadata",{}).get("plan_type","pro");pid=obj.get("id");amount_cents=int(float(obj.get("amount",{}).get("value",0))*100)
     if uid:create_sub(uid,plan,30);apply_referral_bonus(uid,pid,amount_cents);db_execute("UPDATE payments SET status='succeeded' WHERE payment_id=?",(pid,))
    self.send_response(200);self.send_header('Access-Control-Allow-Origin','*');self.end_headers();self.wfile.write(b"OK")
   except Exception as e:logger.error(f"Вебхук: {e}");self.send_response(500);self.end_headers()
  elif self.path=="/api/save_analysis":
   try:
    length=int(self.headers.get('Content-Length',0));data=json.loads(self.rfile.read(length));uid=data.get("user_id");score=data.get("score");pos=data.get("positives","");neg=data.get("negatives","")
    if uid and score is not None:db_execute("INSERT INTO analysis_history(user_id,score,positives,negatives) VALUES(?,?,?,?)",(uid,score,pos,neg));logger.info(f"Анализ сохранён {uid} {score}")
    self.send_response(200);self.send_header('Access-Control-Allow-Origin','*');self.end_headers();self.wfile.write(b"OK")
   except Exception as e:logger.error(f"Сохранение анализа: {e}");self.send_response(500);self.send_header('Access-Control-Allow-Origin','*');self.end_headers()
  else:self.send_response(404);self.end_headers()
threading.Thread(target=lambda:HTTPServer(('',int(os.getenv("PORT",10000))),Handler).serve_forever(),daemon=True).start()
def check_pending_payments():
 while True:
  try:
   pending=db_fetchall("SELECT * FROM payments WHERE status='pending' AND created_at < datetime('now', '-10 minutes')")
   for p in pending:
    pid=p["payment_id"];url=f"https://api.yookassa.ru/v3/payments/{pid}";auth=(YOOKASSA_SHOP_ID,YOOKASSA_SECRET_KEY);resp=requests.get(url,auth=auth)
    if resp.status_code==200:
     data=resp.json();status=data.get("status")
     if status=="succeeded":db_execute("UPDATE payments SET status='succeeded' WHERE payment_id=?",(pid,));create_sub(p["user_id"],p["plan_type"],30);apply_referral_bonus(p["user_id"],pid,p["amount"])
     elif status in ("canceled","expired"):db_execute("UPDATE payments SET status='failed' WHERE payment_id=?",(pid,))
  except Exception as e:logger.error(f"Платежи: {e}");send_error_to_admin(f"Ошибка платежей: {e}")
  time.sleep(3600)
threading.Thread(target=check_pending_payments,daemon=True).start()
def weekly_report_loop():
 while True:
  try:
   now=datetime.utcnow();days=(6-now.weekday())%7
   if days==0 and now.hour>=9:days=7
   next_monday=now+timedelta(days=days);next_monday=next_monday.replace(hour=9,minute=0,second=0,microsecond=0);time.sleep((next_monday-now).total_seconds())
   users=db_fetchall("SELECT DISTINCT user_id FROM analysis_history WHERE created_at > datetime('now', '-7 days')")
   for u in users:
    uid=u["user_id"];history=db_fetchall("SELECT * FROM analysis_history WHERE user_id=? AND created_at > datetime('now', '-7 days')",(uid,))
    if history:total=len(history);avg=sum(h["score"] for h in history)/total;send_msg(uid,f"📊 Отчёт за неделю:\nАнализов: {total}\nСредний балл: {avg:.1f}\nПродолжайте!")
   time.sleep(60)
  except Exception as e:logger.error(f"Отчёт: {e}");time.sleep(86400)
threading.Thread(target=weekly_report_loop,daemon=True).start()
def notif_loop():
 while True:
  try:
   expiring=db_fetchall("SELECT * FROM subscriptions WHERE is_active=1 AND end_date <= datetime('now','+3 days') AND end_date > datetime('now')")
   for s in expiring:
    try:days=(datetime.strptime(s["end_date"],"%Y-%m-%d %H:%M:%S")-datetime.utcnow()).days;send_msg(s["user_id"],f"⏳ Подписка истекает через {days} дн.");time.sleep(0.5)
    except Exception as e:logger.error(f"Уведомление: {e}")
   expired=db_fetchall("SELECT * FROM subscriptions WHERE is_active=1 AND end_date <= datetime('now')")
   for s in expired:
    try:db_execute("UPDATE subscriptions SET is_active=0 WHERE id=?",(s["id"],));send_msg(s["user_id"],"❌ Подписка истекла");time.sleep(0.5)
    except Exception as e:logger.error(f"Деактивация: {e}")
  except Exception as e:logger.error(f"Цикл уведомлений: {e}");send_error_to_admin(f"Ошибка уведомлений: {e}")
  time.sleep(86400)
threading.Thread(target=notif_loop,daemon=True).start()
def process_update(update):
 try:
  if "message" in update:
   msg=update["message"];chat_id=msg["chat"]["id"];user_id=msg["from"]["id"];username=msg["from"].get("username","");first_name=msg["from"].get("first_name","");last_name=msg["from"].get("last_name","")
   upsert_user(user_id,username,first_name,last_name);text=msg.get("text","")
   if user_id in user_states:
    state=user_states[user_id]
    if state=='creating_company':
     name=text.strip()
     if len(name)<2:send_msg(chat_id,"❌ Минимум 2 символа");return
     res=create_company(user_id,name)
     if res:send_msg(chat_id,f"🏢 Компания «{name}» создана! Код: <code>{res['invite_code']}</code>")
     else:send_msg(chat_id,"❌ Ошибка")
     user_states.pop(user_id,None);return
    if state=='joining_company':
     code=text.strip().upper()
     if len(code)!=8:send_msg(chat_id,"❌ Код должен быть 8 символов");return
     company=db_fetchone("SELECT * FROM companies WHERE invite_code=?",(code,))
     if company:
      existing=db_fetchone("SELECT * FROM company_members WHERE user_id=? AND company_id=?",(user_id,company["id"]))
      if existing:send_msg(chat_id,"❌ Вы уже в этой компании")
      else:add_company_member(company["id"],user_id);send_msg(chat_id,f"✅ Вы присоединились к {company['name']}!")
     else:send_msg(chat_id,"❌ Компания не найдена")
     user_states.pop(user_id,None);return
    if state=='withdraw_amount':
     try:
      amount_rub=float(text.replace(',','.'));amount_cents=int(amount_rub*100)
      if amount_cents<50000:send_msg(chat_id,"❌ Минимум 500₽");return
      balance=get_user_balance(user_id)
      if amount_cents>balance:send_msg(chat_id,f"❌ Недостаточно. Баланс: {balance/100:.2f}₽");return
      user_states[user_id]={'state':'withdraw_method','amount_cents':amount_cents}
      kb={"inline_keyboard":[[{"text":"💳 На карту","callback_data":"withdraw_card"}],[{"text":"📱 На телефон","callback_data":"withdraw_phone"}]]}
      send_msg(chat_id,"Выберите способ получения средств:",kb)
     except ValueError:send_msg(chat_id,"❌ Введите число")
     return
    if isinstance(state,dict) and state.get('state')=='withdraw_details':
     details=text.strip()
     if len(details)<5:send_msg(chat_id,"❌ Короткие реквизиты");return
     user_states[user_id]={'state':'withdraw_fio','amount_cents':state['amount_cents'],'method':state['method'],'details':details}
     send_msg(chat_id,"Введите ваше полное ФИО:")
     return
    if isinstance(state,dict) and state.get('state')=='withdraw_fio':
     fio=text.strip()
     if len(fio)<5:send_msg(chat_id,"❌ Слишком короткое ФИО");return
     amount_cents=state['amount_cents'];method=state['method'];details=state['details']
     if method=='card':req_details=f"Способ: карта\nНомер: {details}\nФИО: {fio}"
     else:req_details=f"Способ: телефон\nНомер: {details}\nФИО: {fio}"
     create_withdraw_request(user_id,amount_cents,req_details)
     send_msg(chat_id,f"✅ Заявка на вывод {amount_cents/100:.2f}₽ создана. Админ свяжется.")
     send_msg(ADMIN_ID,f"📩 Заявка на вывод\nПользователь: {first_name} {last_name} (@{username}) [ID: {user_id}]\nСумма: {amount_cents/100:.2f}₽\nРеквизиты:\n{req_details}\nДля подтверждения: /payout {user_id} {amount_cents/100:.2f}")
     user_states.pop(user_id,None);return
   if text.startswith("/start"):
    ref_id=None
    if " " in text:
     parts=text.split()
     if len(parts)>1 and parts[1].startswith("ref_"):
      try:ref_id=int(parts[1].replace("ref_",""))
      except:pass
    if ref_id and ref_id!=user_id:
     existing_ref=db_fetchone("SELECT referrer_id FROM users WHERE user_id=?",(user_id,))
     if not existing_ref or existing_ref["referrer_id"] is None:
      db_execute("UPDATE users SET referrer_id=? WHERE user_id=?",(ref_id,user_id))
      send_msg(ref_id,f"👥 Пользователь {first_name} перешёл по ссылке! При оплате получите +5 дней и 20%.")
      send_msg(chat_id,"🔗 Вы перешли по ссылке друга! После оплаты ваш друг получит бонус.")
    sub=get_sub(user_id)
    if not sub:create_sub(user_id,"trial",3);sub=get_sub(user_id)
    trial_msg=""
    if sub and sub["plan_type"]=="trial":
     days=(datetime.strptime(sub["end_date"],"%Y-%m-%d %H:%M:%S")-datetime.utcnow()).days
     trial_msg=f"🎁 Осталось {days} дн.\n" if days>0 else "⛔ Пробный период истёк\n"
    elif sub:trial_msg=f"🔓 Подписка {sub['plan_type'].upper()} до {sub['end_date']}\n"
    else:trial_msg="⛔ Нет активной подписки\n"
    send_msg(chat_id,f"🌊 Привет, {first_name}!\n{trial_msg}Нажми 'Новый анализ' и вставь переписку.",main_menu())
   elif text=="🚀 Новый анализ":
    sub=get_sub(user_id);has_sub=1 if sub else 0;signed_url=generate_signed_url(user_id,has_sub);kb={"inline_keyboard":[[{"text":"📂 Открыть анализатор","web_app":{"url":signed_url}}]]};send_msg(chat_id,"🔓 Открываю...",kb)
   elif text=="💎 Тарифы":send_msg(chat_id,"💰 Выбери тариф:\n🔓 Pro 990₽/мес\n👑 Premium 1990₽/мес\n🏢 B2B 4990₽/мес",tariffs_kb())
   elif text=="📊 Статистика":
    history=db_fetchall("SELECT * FROM analysis_history WHERE user_id=? ORDER BY created_at DESC",(user_id,))
    if not history:send_msg(chat_id,"📊 У вас пока нет анализов. Проведите первый анализ!",main_menu());return
    total=len(history);avg=sum(h["score"] for h in history)/total;pos=[];neg=[]
    for h in history:
     if h["positives"]:pos.extend(h["positives"].split(','))
     if h["negatives"]:neg.extend(h["negatives"].split(','))
    pc=Counter(pos);nc=Counter(neg);top_pos=pc.most_common(3);top_neg=nc.most_common(3)
    ans=f"📊 <b>Статистика</b>\nВсего: {total}\nСредний: {avg:.1f}/100\n✅ Лучшее: {', '.join([p[0] for p in top_pos]) if top_pos else '—'}\n❌ Улучшить: {', '.join([n[0] for n in top_neg]) if top_neg else '—'}\n📋 Последние 5:\n"+'\n'.join(f"• {h['created_at'][:10]}: {h['score']}/100" for h in history[:5])
    send_msg(chat_id,ans,main_menu())
   elif text=="👥 B2B":
    company=get_company_by_user(user_id)
    if company:
     members=get_company_members(company["id"])
     ans=f"🏢 {company['name']}\nКод: {company['invite_code']}\nСотрудников: {len(members)}\n"+"\n".join(f"• {m['first_name']} @{m['username'] or 'нет'}" for m in members)
     send_msg(chat_id,ans,main_menu())
    else:
     kb={"inline_keyboard":[[{"text":"Создать компанию","callback_data":"create_company"}],[{"text":"Ввести код","callback_data":"join_company"}]]}
     send_msg(chat_id,"👥 Создай компанию или введи код",kb)
   elif text=="👥 Пригласить друга":
    ref_link=f"https://t.me/SaveCommers_bot?start=ref_{user_id}"
    balance=get_user_balance(user_id)
    send_msg(chat_id,f"👥 Пригласи друга!\n🔗 <code>{ref_link}</code>\n💰 За оплату друга: +5 дней и 20% на баланс.\n💳 Баланс: {balance/100:.2f}₽\n📣 Приведи 6 друзей → 30 дней бесплатно!",main_menu())
   elif text=="💰 Баланс" or text=="/balance":
    balance=get_user_balance(user_id);txt=f"💰 Ваш баланс: {balance/100:.2f}₽"
    if balance>=50000:
     kb={"inline_keyboard":[[{"text":"💸 Вывести средства","callback_data":"withdraw_start"}]]}
     txt+="\n\nНажмите кнопку для вывода."
     send_msg(chat_id,txt,kb)
    else:
     txt+=f"\n\n💳 Для вывода нужно 500₽. Осталось: {(50000-balance)/100:.2f}₽"
     send_msg(chat_id,txt,main_menu())
   elif text=="❓ Поддержка":
    send_msg(chat_id,"📩 Напиши сообщение, я перешлю @LyokhaPatron",{"inline_keyboard":[[{"text":"Написать","callback_data":"support"}]]})
   elif text.startswith("/"):
    if user_id==ADMIN_ID:
     parts=text.split()
     if parts[0]=="/activate" and len(parts)>=3:
      target=int(parts[1]);plan=parts[2];days=int(parts[3]) if len(parts)>3 else 30;create_sub(target,plan,days);send_msg(chat_id,f"✅ Активирован {plan} на {days} дней для {target}")
     elif parts[0]=="/status":
      target=int(parts[1]) if len(parts)>1 else user_id;sub=get_sub(target);send_msg(chat_id,f"Статус {target}: {sub['plan_type'] if sub else 'Нет'} до {sub['end_date'] if sub else '---'}")
     elif parts[0]=="/deactivate" and len(parts)>1:
      target=int(parts[1]);db_execute("UPDATE subscriptions SET is_active=0 WHERE user_id=?",(target,));send_msg(chat_id,f"✅ Деактивировано для {target}")
     elif parts[0]=="/set_balance" and len(parts)>=3:
      target=int(parts[1]);amount_cents=int(parts[2]);db_execute("INSERT INTO user_balances(user_id,balance) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?",(target,amount_cents,amount_cents));send_msg(chat_id,f"✅ Баланс {target} изменён на {amount_cents/100:.2f}₽")
     elif parts[0]=="/payout" and len(parts)>=3:
      target=int(parts[1]);amount_rub=float(parts[2]);amount_cents=int(amount_rub*100)
      if withdraw_balance(target,amount_cents):
       send_msg(chat_id,f"✅ Вывод {amount_rub:.2f}₽ для {target} подтверждён.")
       send_msg(target,f"💰 Ваш запрос на вывод {amount_rub:.2f}₽ одобрен.")
       db_execute("UPDATE withdraw_requests SET status='completed' WHERE user_id=? AND amount_cents=? AND status='pending'",(target,amount_cents))
      else:send_msg(chat_id,f"❌ Недостаточно средств у {target}")
     elif parts[0]=="/withdraw_list":
      requests_list=get_pending_withdraw_requests()
      if not requests_list:send_msg(chat_id,"📭 Нет новых заявок.");return
      ans="📋 Заявки:\n"+"\n".join(f"ID:{r['id']} | {r['user_id']} | {r['amount_cents']/100:.2f}₽ | {r['details']}" for r in requests_list)
      send_msg(chat_id,ans)
     else:pass
    else:send_msg(ADMIN_ID,f"📩 От {user_id}: {text}");send_msg(chat_id,"✅ Отправлено в поддержку")
  elif "callback_query" in update:
   cb=update["callback_query"];user_id=cb["from"]["id"];data=cb["data"];chat_id=cb["message"]["chat"]["id"]
   if data=="support":send_msg(chat_id,"📩 Напиши сообщение, я перешлю");answer_cb(cb["id"],"")
   elif data=="trial":
    active=get_sub(user_id)
    if active:send_msg(chat_id,"❌ У вас уже есть подписка")
    else:create_sub(user_id,"trial",3);send_msg(chat_id,"✅ 3 дня бесплатно активированы!")
    answer_cb(cb["id"],"")
   elif data=="create_company":user_states[user_id]='creating_company';send_msg(chat_id,"Введи название компании");answer_cb(cb["id"],"")
   elif data=="join_company":user_states[user_id]='joining_company';send_msg(chat_id,"Введи код приглашения (8 символов)");answer_cb(cb["id"],"")
   elif data=="withdraw_card":
    state=user_states.get(user_id)
    if state and isinstance(state,dict) and state.get('state')=='withdraw_method':
     user_states[user_id]={'state':'withdraw_details','amount_cents':state['amount_cents'],'method':'card'}
     send_msg(chat_id,"Введите номер карты (16 цифр):")
    else:send_msg(chat_id,"❌ Ошибка: попробуйте /balance")
    answer_cb(cb["id"],"")
   elif data=="withdraw_phone":
    state=user_states.get(user_id)
    if state and isinstance(state,dict) and state.get('state')=='withdraw_method':
     user_states[user_id]={'state':'withdraw_details','amount_cents':state['amount_cents'],'method':'phone'}
     send_msg(chat_id,"Введите номер телефона +7XXXXXXXXXX:")
    else:send_msg(chat_id,"❌ Ошибка: попробуйте /balance")
    answer_cb(cb["id"],"")
   elif data=="withdraw_start":
    balance=get_user_balance(user_id)
    if balance<50000:send_msg(chat_id,f"❌ Недостаточно. Баланс: {balance/100:.2f}₽");answer_cb(cb["id"],"");return
    user_states[user_id]='withdraw_amount'
    send_msg(chat_id,f"💰 Ваш баланс: {balance/100:.2f}₽\nВведите сумму для вывода (минимум 500₽):")
    answer_cb(cb["id"],"")
   elif data.startswith("tariff_"):
    plan=data.replace("tariff_","");amount={"pro":990,"premium":1990,"b2b":4990}[plan];amount_cents=amount*100;balance=get_user_balance(user_id)
    if balance>=amount_cents:
     kb={"inline_keyboard":[[{"text":f"💳 Оплатить из баланса ({amount}₽)","callback_data":f"pay_balance_{plan}"}],[{"text":"💳 Оплатить картой","callback_data":f"pay_card_{plan}"}]]}
     send_msg(chat_id,f"💰 У вас {balance/100:.2f}₽. Оплатить {plan} за {amount}₽ из баланса или картой?",kb)
    else:
     payment_id=str(uuid.uuid4());url="https://api.yookassa.ru/v3/payments";auth=(YOOKASSA_SHOP_ID,YOOKASSA_SECRET_KEY);resp=requests.post(url,json={"amount":{"value":f"{amount:.2f}","currency":"RUB"},"confirmation":{"type":"redirect","return_url":f"{BASE_URL}/payment-success"},"capture":True,"description":f"SaleFlow {plan}","metadata":{"user_id":user_id,"plan_type":plan}},auth=auth,headers={"Idempotence-Key":payment_id,"Content-Type":"application/json"})
     if resp.status_code in (200,201):
      r=resp.json();db_execute("INSERT INTO payments(user_id,payment_id,amount,currency,status,plan_type) VALUES(?,?,?,'RUB','pending',?)",(user_id,r["id"],amount_cents,plan));kb={"inline_keyboard":[[{"text":"💳 Оплатить","url":r["confirmation"]["confirmation_url"]}]]};send_msg(chat_id,f"💳 Оплата {plan}: {amount}₽",kb)
     else:send_msg(chat_id,"❌ Ошибка оплаты")
    answer_cb(cb["id"],"")
   elif data.startswith("pay_balance_"):
    plan=data.replace("pay_balance_","");amount={"pro":990,"premium":1990,"b2b":4990}[plan];amount_cents=amount*100
    if use_balance_for_subscription(user_id,amount_cents):
     create_sub(user_id,plan,30);send_msg(chat_id,f"✅ Подписка {plan} активирована на 30 дней! Остаток: {get_user_balance(user_id)/100:.2f}₽")
    else:send_msg(chat_id,"❌ Недостаточно средств")
    answer_cb(cb["id"],"")
   elif data.startswith("pay_card_"):
    plan=data.replace("pay_card_","");amount={"pro":990,"premium":1990,"b2b":4990}[plan];amount_cents=amount*100
    payment_id=str(uuid.uuid4());url="https://api.yookassa.ru/v3/payments";auth=(YOOKASSA_SHOP_ID,YOOKASSA_SECRET_KEY);resp=requests.post(url,json={"amount":{"value":f"{amount:.2f}","currency":"RUB"},"confirmation":{"type":"redirect","return_url":f"{BASE_URL}/payment-success"},"capture":True,"description":f"SaleFlow {plan}","metadata":{"user_id":user_id,"plan_type":plan}},auth=auth,headers={"Idempotence-Key":payment_id,"Content-Type":"application/json"})
    if resp.status_code in (200,201):
     r=resp.json();db_execute("INSERT INTO payments(user_id,payment_id,amount,currency,status,plan_type) VALUES(?,?,?,'RUB','pending',?)",(user_id,r["id"],amount_cents,plan));kb={"inline_keyboard":[[{"text":"💳 Оплатить","url":r["confirmation"]["confirmation_url"]}]]};send_msg(chat_id,f"💳 Оплата {plan}: {amount}₽",kb)
    else:send_msg(chat_id,"❌ Ошибка оплаты")
    answer_cb(cb["id"],"")
 except Exception as e:
  error_text=f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
  logger.error(error_text);send_msg(ADMIN_ID,f"🚨 Ошибка: {error_text[:4000]}")
def get_updates(offset):
 r=requests.get(f"{BOT_API}/getUpdates",params={"offset":offset,"timeout":30})
 if r.status_code==200 and r.json()["ok"]:
  for u in r.json()["result"]:offset=u["update_id"]+1;process_update(u)
 return offset
if __name__=="__main__":
 logger.info("SaleFlow бот запущен")
 while True:
  try:offset=get_updates(offset)
  except Exception as e:logger.error(f"Основной цикл: {e}");time.sleep(5)
