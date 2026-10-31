'use strict';
const initialPage=location.hash.slice(1).split('|')[1]||new URLSearchParams(location.search).get('page')||'services';
let token='',sessionPromise=null,state,initialized=false,busy=false,saving=false,saveTimer=null,saveError=false;
let nodeFeedback=null;
const $=s=>document.querySelector(s),message=$('#message'),dirty=new Map(),ids={hostname:'hostname','ssh_user':'ssh-user','ssh_port':'ssh-port',identity_file:'identity',cookie:'cookie',rpc_port:'rpc-port'};
history.replaceState(null,'',location.pathname);sessionStorage.removeItem('wallaby-access');
async function session(){if(!sessionPromise)sessionPromise=(async()=>{const r=await fetch('/api/session',{headers:{'X-Wallaby-UI':'1'},cache:'no-store'});if(!r.ok)throw Error('Could not establish the local Agent page session. Reload this page.');token=(await r.json()).token;})().finally(()=>sessionPromise=null);return sessionPromise;}
async function api(path,body){if(!token)await session();let r;for(let attempt=0;attempt<2;attempt++){r=await fetch('/api/'+path,{method:body?'POST':'GET',cache:'no-store',headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});if(r.status!==403||attempt)break;await session();}const data=await r.json();if(!r.ok)throw Error(data.error||'Request failed.');return data;}
function notify(error){message.textContent=error?error.message:'';}
function prerequisiteCommands(parent,support){
 let panel=parent.querySelector('.prerequisite-commands');
 if(!panel){panel=document.createElement('div');panel.className='prerequisite-commands';parent.append(panel);}
 const commands=support?.available===false?support.commands||[]:[];
 const signature=JSON.stringify(commands);if(panel.dataset.signature===signature)return;
 panel.dataset.signature=signature;panel.replaceChildren();panel.hidden=!commands.length;
 for(const command of commands){
  const box=document.createElement('div'),pre=document.createElement('pre'),code=document.createElement('code'),copy=document.createElement('button'),feedback=document.createElement('span');
  box.className='install-command';code.textContent=command;pre.append(code);copy.type='button';copy.textContent='Copy command';feedback.setAttribute('role','status');
  copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(command);feedback.textContent='Copied';}catch(_){const selection=window.getSelection(),range=document.createRange();range.selectNodeContents(code);selection.removeAllRanges();selection.addRange(range);feedback.textContent='Select and copy the command with Ctrl+C.';}});
  box.append(pre,copy,feedback);panel.append(box);
 }
}
function render(next){state=next;window.updateWorkspace?.(state.workspace);const c=state.config;for(const[key,id]of Object.entries(ids)){const input=$('#'+id);if(!dirty.has(key)&&!saving&&String(input.value)!==String(c[key]))input.value=c[key];}$('#page-services').disabled=!!state.workspace?.protected?.viewer;initialized=true;$('#server-dot').className='dot '+state.status.server.color;$('#server-status').textContent=state.status.server.message;if(['hostname','ssh_user','ssh_port','identity_file'].some(k=>dirty.has(k))){$('#server-dot').className='dot '+(saveError?'red':'amber');$('#server-status').textContent=saveError?'Connection edit not saved. Correct it before connecting.':'Applying connection settings…';}for(const row of document.querySelectorAll('[data-service]')){const id=row.dataset.service,on=c.enabled[id],button=row.querySelector('.switch'),s=state.status[id];button.setAttribute('aria-checked',String(on));button.querySelector('.switch-label').textContent=on?'ON':'OFF';const feedback=id==='node'?nodeFeedback:null;row.querySelector('.dot').className='dot '+(feedback?feedback.color:on?s.color:'red');const unavailable=id==='node'&&!on&&next.node_support?.available===false;button.setAttribute('aria-disabled',String(unavailable));button.classList.toggle('unavailable',unavailable);button.title=unavailable?next.node_support.message:'';row.querySelector('.status-text').textContent=feedback?feedback.message:unavailable?next.node_support.message:on||id==='node'&&s.preparation_failed?s.message:'Off';if(id==='node')prerequisiteCommands(row.querySelector('.service-copy'),unavailable?next.node_support:null);let previous=row.querySelector('.last-error');if(!previous){previous=document.createElement('p');previous.className='hint last-error';row.querySelector('.service-copy').append(previous);}previous.textContent=on&&s.color==='amber'&&s.last_error?'Previous failure: '+s.last_error.message:'';previous.hidden=!previous.textContent;const link=row.querySelector('a');if(link)link.hidden=!(on&&s.color==='green');}}
async function refresh(force=false){if(!force&&(busy||window.workspaceChanging))return;try{const next=await api('state');if(!saving)render(next);}catch(e){notify(e);if(!initialized){$('#server-status').textContent='Saved configuration could not be loaded. Reconnecting to the local Agent…';$('#server-dot').className='dot amber';}}}
function edited(key){saveError=false;dirty.set(key,$('#'+ids[key]).value);$('#save-status').textContent='Saving…';clearTimeout(saveTimer);saveTimer=setTimeout(()=>flush().catch(notify),350);}
async function flush(){clearTimeout(saveTimer);while(saving)await new Promise(r=>setTimeout(r,30));if(!dirty.size)return;saving=true;const sent=new Map(dirty),patch={};try{for(const[key,value]of sent){const input=$('#'+ids[key]);if(!input.checkValidity())throw Error('Check '+input.labels[0].textContent.trim()+'. This edit has not been saved.');patch[key]=key.endsWith('_port')?Number(value):value;}await api('patch',patch);for(const[key,value]of sent)if(dirty.get(key)===value)dirty.delete(key);$('#save-status').textContent=dirty.size?'Saving…':'All settings saved.';notify();}catch(e){saveError=true;$('#save-status').textContent='Edit not saved. Correct the highlighted field and try again.';throw e;}finally{saving=false;}if(dirty.size)await flush();await refresh();}
for(const key of Object.keys(ids)){const input=$('#'+ids[key]);input.addEventListener('input',()=>edited(key));input.addEventListener('change',()=>edited(key));}
async function change(path,body,button){
 if(busy)return;busy=true;button.disabled=true;
 const nodeChange=path==='toggle'&&body.service==='node',startingWorkspace=nodeChange&&body.enabled&&!state?.workspace?.protected?.running;
 if(nodeChange)nodeFeedback={color:'amber',message:body.enabled?(startingWorkspace?'Starting protected workspace. Approve the local administrator dialogue if requested.':'Connecting Bitcoin Core and Wallaby Dashboard…'):'Disconnecting node interface…'};
 else notify();
 try{
  if(state)render(state);await flush();
  if(startingWorkspace)window.setWorkspaceAction?.('starting');
  await api(path,body);if(nodeChange)nodeFeedback=null;else notify();
 }catch(e){if(nodeChange)nodeFeedback={color:'red',message:e.message};else notify(e);}
 finally{busy=false;button.disabled=false;if(startingWorkspace)window.setWorkspaceAction?.(null);await refresh(true);}
}

$('#host-form').addEventListener('submit',e=>{e.preventDefault();change('connect',{},e.submitter);});
$('#settings-form').addEventListener('submit',e=>{e.preventDefault();flush().catch(notify);});
for(const row of document.querySelectorAll('[data-service]'))row.querySelector('.switch').addEventListener('click',e=>{if(state&&row.dataset.service==='node'&&!state.config.enabled.node&&state.node_support?.available===false){nodeFeedback={color:'red',message:state.node_support.message};render(state);return;}if(state)change('toggle',{service:row.dataset.service,enabled:!state.config.enabled[row.dataset.service]},e.currentTarget);});
$('#browse').addEventListener('click',async e=>{const b=e.currentTarget;b.disabled=true;try{const r=await api('pick-cookie',{});if(r.path){$('#cookie').value=r.path;edited('cookie');await flush();}}catch(error){notify(error);}finally{b.disabled=false;}});
refresh();setInterval(refresh,2000);
