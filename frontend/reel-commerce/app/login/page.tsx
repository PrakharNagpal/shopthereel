'use client';
import {useEffect,useState} from 'react';
import {ArrowRight,ArrowUpRight,Check,Eye,EyeOff,LockKeyhole,Leaf,Sparkles,ChevronLeft} from 'lucide-react';
import {accountRequest} from '../../lib/account';
import s from '../account.module.css';

export default function Login(){
 const [signup,setSignup]=useState(false),[visible,setVisible]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[ready,setReady]=useState(false);
 useEffect(()=>{setReady(true);accountRequest('/api/account').then(()=>window.location.replace('/account/')).catch(()=>{});},[]);
 async function submit(event:React.FormEvent<HTMLFormElement>){event.preventDefault();setBusy(true);setError('');const form=new FormData(event.currentTarget);try{await accountRequest(signup?'/api/signup':'/api/login',{method:'POST',body:JSON.stringify(Object.fromEntries(form))});window.location.assign('/account/');}catch(e){setError(e instanceof Error?e.message:'Could not connect. Please try again.');setBusy(false);}}
 return <main className={s.loginPage}>
  <header className={s.header}><a className={s.logo} href="/">reel<span>✳</span></a><a className={s.textLink} href="/">Back to the experience <ArrowUpRight size={15}/></a></header>
  <section className={s.loginStory}>
   <span className={s.eyebrow}><span className={s.liveDot}/> A LITTLE MORE YOU</span>
   <h1>Good finds.<br/><span>Better for you.</span></h1>
   <p>Your taste. Your home. Your next favourite.<br/>A shopping space that starts with you.</p>
   <div className={s.storyVisual}>
    <div className={s.orbitCircle}/><div className={s.smallOrbit}/>
    <div className={s.storyProduct}><span className={s.miniEyebrow}>THE EVERYDAY EDIT</span><img src="/assets/sneaker.png" alt="Coral and cream running sneaker"/><div><b>A little inspiration.</b><span>From your feed, to your favourites.</span></div></div>
    <div className={s.storyChip}><Leaf size={17}/><div><b>Made for your everyday</b><span>Your preferences, in one place.</span></div></div>
    <div className={s.storyBadge}><Sparkles size={15}/> Your own kind of good.</div>
   </div>
   <div className={s.storyFooter}><span>01 / INSPIRED BY YOU</span><span>LESS SEARCHING. MORE LIVING.</span></div>
  </section>
  <section className={s.loginFormSide}>
   <div className={s.formCard}>
    <div className={s.formMark}>✳</div><span className={s.eyebrow}>YOUR PERSONAL SPACE</span>
    <h2>{signup?'Make yourself at home.':'Welcome back.'}</h2><p>{signup?'A few details, and you’re in.':'Your next favourite is waiting.'}</p>
    <div className={s.authTabs}><button type="button" disabled={!ready} className={!signup?s.selectedTab:''} onClick={()=>{setSignup(false);setError('');}}>Sign in</button><button type="button" disabled={!ready} className={signup?s.selectedTab:''} onClick={()=>{setSignup(true);setError('');}}>Create account</button></div>
    <form method="post" onSubmit={submit}>
     {signup&&<label className={s.field}>Your name<input name="name" autoComplete="name" placeholder="What should we call you?" required maxLength={80}/></label>}
     <label className={s.field}>Email address<input name="email" type="email" autoComplete="email" placeholder="you@example.com" required maxLength={254}/></label>
     <label className={s.field}>Password<div className={s.passwordField}><input name="password" type={visible?'text':'password'} autoComplete={signup?'new-password':'current-password'} placeholder={signup?'At least 10 characters':'Enter your password'} required minLength={signup?10:undefined} maxLength={200}/><button type="button" onClick={()=>setVisible(!visible)} aria-label={visible?'Hide password':'Show password'}>{visible?<EyeOff size={17}/>:<Eye size={17}/>}</button></div></label>
     {error&&<div className={s.error} role="alert">{error}</div>}
     <button className={s.primary} disabled={busy||!ready} type="submit">{busy?'One moment…':signup?'Create my account':'Sign in to Reel'}<ArrowRight size={17}/></button>
    </form>
    <div className={s.formPrivacy}><LockKeyhole size={13}/><span>Your account. Your preferences. Always yours.</span></div>
   </div>
   <div className={s.formBottom}><span>THOUGHTFULLY PERSONAL.</span><span>✳</span></div>
  </section>
 </main>
}
