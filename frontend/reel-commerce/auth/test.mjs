import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
const directory=mkdtempSync(path.join(tmpdir(),'reel-account-test-'));
const server=spawn(process.execPath,['auth/server.mjs'],{env:{...process.env,REEL_ACCOUNT_DB:path.join(directory,'test.sqlite'),REEL_ACCOUNT_PORT:'3221'},stdio:['ignore','pipe','pipe']});
const base='http://127.0.0.1:3221';
let count=0;
async function request(route,method='GET',value,session='',origin='http://127.0.0.1:3210'){
 const r=await fetch(base+route,{method,headers:{Origin:origin,'Content-Type':'application/json',...(session?{Cookie:session}:{})},body:value?JSON.stringify(value):undefined});return {status:r.status,data:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0]};
}
try{
 await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('error',reject);server.once('exit',()=>reject(new Error('Test service failed to start')));});
 assert.equal((await request('/api/account')).status,401);count++;
 const signup=await request('/api/signup','POST',{name:'Account Test',email:'account-test@example.invalid',password:'temporary-test-only-password'});
 assert.equal(signup.status,200);assert.ok(signup.cookie);count++;
 assert.equal((await request('/api/signup','POST',{name:'Duplicate',email:'account-test@example.invalid',password:'temporary-test-only-password'})).status,409);count++;
 assert.equal((await request('/api/login','POST',{email:'account-test@example.invalid',password:'incorrect-test-password'})).status,401);count++;
 const profile={home:['oven'],pantry:['salt','basil'],likes:['home cooking'],sizes:{shirt:'M',shoes:'EU 42'},budget:'100',location:'Singapore'};
 const updated=await request('/api/account','PUT',{name:'Account Test',profile},signup.cookie);
 assert.equal(updated.status,200);assert.deepEqual(updated.data.user.profile.pantry,['salt','basil']);count++;
 const login=await request('/api/login','POST',{email:'account-test@example.invalid',password:'temporary-test-only-password'});
 assert.equal(login.status,200);assert.equal((await request('/api/account','GET',null,login.cookie)).data.user.profile.sizes.shoes,'EU 42');count++;
 assert.equal((await request('/api/account','PUT',{profile:{pantry:['changed']}},signup.cookie,'http://untrusted.invalid')).status,403);count++;
 const second=await request('/api/signup','POST',{name:'Other Account',email:'other-test@example.invalid',password:'temporary-test-only-password'});
 assert.deepEqual((await request('/api/account','GET',null,second.cookie)).data.user.profile.pantry,[]);count++;
 await request('/api/logout','POST',{},login.cookie);
 assert.equal((await request('/api/account','GET',null,login.cookie)).status,401);count++;
 console.log(`${count} account checks passed: auth, profile persistence, isolation and logout.`);
}finally{server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve));rmSync(directory,{recursive:true,force:true});}
