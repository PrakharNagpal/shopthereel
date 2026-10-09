export type Profile={location:string;home:string[];pantry:string[];likes:string[];dislikes:string[];sizes:{shirt:string;shoes:string};budget:string};
export type Account={id:string;name:string;email:string;profile:Profile;createdAt:string};
export async function accountRequest(path:string, options:RequestInit={}) {
  const host=window.location.hostname;
  if(!['localhost','127.0.0.1'].includes(host)) throw new Error('Account access is available on the local app for now.');
  const response=await fetch(`http://${host}:3211${path}`,{...options,credentials:'include',headers:{'Content-Type':'application/json',...options.headers}});
  const data=await response.json();
  if(!response.ok) throw new Error(data.error || 'Please try again.');
  return data;
}
