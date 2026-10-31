"use strict";
document.querySelector('#save-logs').addEventListener('click',async()=>{
 const button=document.querySelector('#save-logs'),status=document.querySelector('#logs-status');button.disabled=true;
 try{
  if(!token)await session();
  let response;
  for(let attempt=0;attempt<2;attempt++){
   response=await fetch('/api/logs',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
   if(response.status!==403||attempt)break;await session();
  }
  if(!response.ok)throw Error('Could not read the diagnostic log. Check ordinary Agent log storage.');
  const url=URL.createObjectURL(new Blob([await response.text()],{type:'text/plain;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download='Wallaby_Agent.log';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  status.textContent='Log download prepared. Protected events are included after safe workspace closure.';
 }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
});
