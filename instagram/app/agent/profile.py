"""Instagram-owned context. Every chat starts empty, with no Telegram demo facts."""
import json
import re
import sqlite3
from app.config import settings

FIELDS = {'home', 'not_owned', 'pantry', 'likes', 'dislikes', 'sizes', 'background'}

def sensitive_text(text: str) -> bool:
    return bool(re.search(r'(?:\d[ -]?){13,19}|\b(?:cvv|otp|password|api[_ ]?key|bot[_ ]?token)\b|\bsk_[A-Za-z0-9_-]+', text, re.I))

def _db():
    c = sqlite3.connect(settings.db_path)
    c.execute('CREATE TABLE IF NOT EXISTS instagram_profiles (uid TEXT PRIMARY KEY, data TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS instagram_context (uid TEXT PRIMARY KEY, data TEXT)')
    return c

def _read(table, uid):
    if not uid or not uid.startswith('web-ig-'):return {}
    with _db() as c:row=c.execute(f'SELECT data FROM {table} WHERE uid=?',(uid,)).fetchone()
    return json.loads(row[0]) if row else {}

def _write(table, uid, data):
    if not uid.startswith('web-ig-'):raise ValueError('Invalid Instagram profile')
    with _db() as c:c.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)',(uid,json.dumps(data)))

def load_profile(uid):
    if not uid or not uid.startswith('web-ig-'):return {}
    return _read('instagram_profiles',uid) or {**{f:[] for f in FIELDS},'background':'','sizes':{},'inventory_facts':{},'sample_fields':[]}

def save_profile(uid, data):_write('instagram_profiles',uid,data)
def read_context(uid):return _read('instagram_context',uid)
def write_context(uid, data):_write('instagram_context',uid,data)

def clear_profile(uid):
    with _db() as c:
        c.execute('DELETE FROM instagram_profiles WHERE uid=?',(uid,))
        c.execute('DELETE FROM instagram_context WHERE uid=?',(uid,))

def update_profile(uid, field, value):
    if field not in FIELDS:raise ValueError('Use home, not_owned, pantry, likes, dislikes, sizes or background.')
    if sensitive_text(value):raise ValueError('Keep card details and secrets out of your shopping profile.')
    p=load_profile(uid);value=value.strip()[:1000]
    if field=='sizes':
        sizes={}
        for pair in value.split(','):
            k,sep,v=pair.partition('=')
            if not sep or not k.strip() or not v.strip():raise ValueError('Use profile set sizes shirt=M, shoes=EU42. Sizes are preferences; you still choose the variant.')
            sizes[k.strip().lower()]=v.strip()
        p[field]=sizes
    elif field=='background':p[field]=value
    else:
        p[field]=[v.strip() for v in value.split(',') if v.strip()]
        if field in ('home','not_owned'):
            other='not_owned' if field=='home' else 'home'
            p[other]=[v for v in p.get(other,[]) if v.casefold() not in {x.casefold() for x in p[field]}]
        if field in ('home','pantry'):
            p.setdefault('inventory_facts',{})[field]={item.casefold():True for item in p[field]}
        if field=='not_owned':
            facts=p.setdefault('inventory_facts',{}).setdefault('home',{})
            for item in p[field]:facts[item.casefold()]=False
    save_profile(uid,p)

def describe_profile(uid):
    p=load_profile(uid);lines=['Your shopping profile (only what you told me)']
    for field in ('home','not_owned','pantry','likes','dislikes','sizes','background'):
        value=p.get(field,[])
        text=', '.join(f'{k}={v}' for k,v in value.items()) if isinstance(value,dict) else value if isinstance(value,str) else ', '.join(value)
        lines.append(field.replace('_',' ').title()+': '+(text or 'not provided'))
    return '\n'.join(lines)+ '\n\nEdit: profile set home oven, blender\nOr tell me "I have basil" and confirm it.\nDelete saved context: profile clear. Sizes are never chosen automatically.'

def excluded(candidate_name, profile):
    name=candidate_name.casefold()
    if re.search(r'\b(tray|dish|pan|rack|liner|accessory|mitt|glove|cover|filter|recipe|cookbook)\b',name):return False
    return any(re.search(r'\b'+re.escape(item.casefold())+r'\b',name) for item in profile.get('home',[]) if len(item)>=4)
