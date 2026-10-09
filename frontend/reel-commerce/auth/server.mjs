import {createServer} from 'node:http';
import {randomBytes, scrypt as scryptCallback, timingSafeEqual, createHash} from 'node:crypto';
import {promisify} from 'node:util';
import {DatabaseSync} from 'node:sqlite';
import {mkdirSync, chmodSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const scrypt = promisify(scryptCallback);
const folder = fileURLToPath(new URL('../.account-data/', import.meta.url));
mkdirSync(folder, {recursive:true, mode:0o700});
const dbFile = process.env.REEL_ACCOUNT_DB || path.join(folder, 'accounts.sqlite');
const db = new DatabaseSync(dbFile);
chmodSync(dbFile, 0o600);
db.exec(`PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, salt TEXT NOT NULL, password_hash TEXT NOT NULL, profile TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS session_expiry ON sessions(expires);`);
const port = Number(process.env.REEL_ACCOUNT_PORT || 3211);
const origins = new Set(['http://localhost:3210', 'http://127.0.0.1:3210']);
const attempts = new Map();
const digest = value => createHash('sha256').update(value).digest('hex');
const publicUser = row => ({id:row.id, name:row.name, email:row.email, profile:JSON.parse(row.profile), createdAt:row.created_at});
const cookie = token => `reel_account=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800`;
const emptyProfile = {location:'', home:[], pantry:[], likes:[], dislikes:[], sizes:{shirt:'', shoes:''}, budget:''};
function json(res, status, value, headers={}) {res.writeHead(status, {'Content-Type':'application/json', 'Cache-Control':'no-store', ...headers});res.end(JSON.stringify(value));}
function currentUser(req) {
  const token = (req.headers.cookie || '').split(';').map(s=>s.trim()).find(s=>s.startsWith('reel_account='))?.slice(13);
  if (!token || !/^[a-f0-9]{64}$/.test(token)) return null;
  return db.prepare('SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?').get(digest(token), Date.now());
}
function newSession(userId) {
  const token=randomBytes(32).toString('hex');
  db.prepare('DELETE FROM sessions WHERE expires<=?').run(Date.now());
  db.prepare('INSERT INTO sessions VALUES (?,?,?)').run(digest(token),userId,Date.now()+7*86400000);
  return token;
}
async function body(req) {
  let total=0,parts=[];
  for await (const part of req) {total+=part.length;if(total>16000) throw new Error('Request too large');parts.push(part);}
  return JSON.parse(Buffer.concat(parts).toString());
}
function cleanProfile(raw={}) {
  const text=v=>typeof v==='string'?v.trim().slice(0,160):'';
  const list=v=>Array.isArray(v)?[...new Set(v.map(text).filter(Boolean))].slice(0,30):[];
  const budget=text(raw.budget);
  if(budget && (!Number.isFinite(Number(budget)) || Number(budget)<0 || Number(budget)>100000)) throw new Error('Invalid budget');
  return {location:text(raw.location),home:list(raw.home),pantry:list(raw.pantry),likes:list(raw.likes),dislikes:list(raw.dislikes),sizes:{shirt:text(raw.sizes?.shirt),shoes:text(raw.sizes?.shoes)},budget};
}
createServer(async(req,res)=>{
  const origin=req.headers.origin;
  if(origin && !origins.has(origin)) return json(res,403,{error:'This origin is not allowed.'});
  if(origin) {res.setHeader('Access-Control-Allow-Origin',origin);res.setHeader('Access-Control-Allow-Credentials','true');res.setHeader('Vary','Origin');}
  if(req.method==='OPTIONS') {res.writeHead(204,{'Access-Control-Allow-Methods':'GET,POST,PUT,OPTIONS','Access-Control-Allow-Headers':'Content-Type'});return res.end();}
  if(req.method!=='GET' && !origins.has(origin)) return json(res,403,{error:'Please use the account page.'});
  const url=new URL(req.url,'http://localhost');
  try {
    if(req.method==='GET' && url.pathname==='/health') return json(res,200,{ok:true,service:'reel-accounts'});
    if(req.method==='GET' && url.pathname==='/api/account') {
      const user=currentUser(req);return user?json(res,200,{user:publicUser(user)}):json(res,401,{error:'Please sign in to continue.'});
    }
    if(req.method==='POST' && ['/api/signup','/api/login'].includes(url.pathname)) {
      const input=await body(req);
      const email=typeof input.email==='string'?input.email.trim().toLowerCase():'';
      const password=typeof input.password==='string'?input.password:'';
      if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length>254 || !password || password.length>200) return json(res,400,{error:'Enter a valid email and password.'});
      const key=digest(req.socket.remoteAddress+email), now=Date.now();
      const tries=attempts.get(key);
      if(tries && now-tries.started<900000 && tries.count>=8) return json(res,429,{error:'Too many attempts. Please try again in 15 minutes.'});
      attempts.set(key,{started:tries && now-tries.started<900000?tries.started:now,count:tries && now-tries.started<900000?tries.count+1:1});
      let user=db.prepare('SELECT * FROM users WHERE email=?').get(email);
      if(url.pathname==='/api/signup') {
        const name=typeof input.name==='string'?input.name.trim().slice(0,80):'';
        if(!name || password.length<10) return json(res,400,{error:'Add your name and a password of at least 10 characters.'});
        if(user) return json(res,409,{error:'An account already exists with that email. Sign in instead.'});
        const salt=randomBytes(16).toString('hex'), hash=(await scrypt(password,salt,64)).toString('hex');
        const id=randomBytes(16).toString('hex');
        const profile=cleanProfile({...emptyProfile,location:input.location || ''});
        db.prepare('INSERT INTO users VALUES (?,?,?,?,?,?,?)').run(id,name,email,salt,hash,JSON.stringify(profile),new Date().toISOString());
        user=db.prepare('SELECT * FROM users WHERE id=?').get(id);
      } else {
        const hash=await scrypt(password,user?.salt || 'invalid-account-salt',64);
        const expected=Buffer.from(user?.password_hash || '00'.repeat(64),'hex');
        if(!user || !timingSafeEqual(hash,expected)) return json(res,401,{error:'The email or password is incorrect.'});
      }
      attempts.delete(key);
      return json(res,200,{user:publicUser(user)},{'Set-Cookie':cookie(newSession(user.id))});
    }
    if(req.method==='POST' && url.pathname==='/api/logout') {
      const token=(req.headers.cookie || '').split(';').map(s=>s.trim()).find(s=>s.startsWith('reel_account='))?.slice(13);
      if(token) db.prepare('DELETE FROM sessions WHERE token_hash=?').run(digest(token));
      return json(res,200,{ok:true},{'Set-Cookie':'reel_account=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'});
    }
    if(req.method==='PUT' && url.pathname==='/api/account') {
      const user=currentUser(req);if(!user)return json(res,401,{error:'Please sign in to continue.'});
      const input=await body(req);
      const name=typeof input.name==='string'?input.name.trim().slice(0,80):user.name;
      if(!name)return json(res,400,{error:'Please enter your name.'});
      const profile=cleanProfile(input.profile);
      db.prepare('UPDATE users SET name=?,profile=? WHERE id=?').run(name,JSON.stringify(profile),user.id);
      return json(res,200,{user:publicUser(db.prepare('SELECT * FROM users WHERE id=?').get(user.id))});
    }
    return json(res,404,{error:'Page not found.'});
  } catch(error) {return json(res,error.message==='Request too large'?413:400,{error:'Could not save that request. Please check your details and try again.'});}
}).listen(port,'127.0.0.1',()=>console.log(`Reel account service ready at http://127.0.0.1:${port}`));
