'use strict';
let blockSnapshot='';
async function loadBlockDownload(){
 if(page!=='synchronisation'||!workspace?.protected?.viewer)return;
 const root=$('#block-download-controls');if(!root||document.activeElement?.closest('#block-download-controls select'))return;
 try{
  const s=await api('peers/block-status',{}),stamp=JSON.stringify(s);if(stamp===blockSnapshot&&root.children.length)return;blockSnapshot=stamp;
  root.replaceChildren(el('h3',{},'Blockchain over direct SSH'),el('p',{},'Receive public blocks from a paired Agent without using this Core node’s Internet peers. Existing valid blocks stay in place. A source can be behind or still downloading; Core validates every received block.'));
  root.append(el('label',{class:'block-sharing'},checkBox('Allow paired Agents to download this node’s blocks',s.allowed,false,enabled=>api('peers/block-serve',{enabled})), 'Allow paired Agents to download this node’s blocks'),el('p',{class:'hint'},'Serving uses the paired direct SSH connection in either client/server direction. No wallets or private keys are sent by these block controls. Enable this on your source Agent.'));
  const select=el('select',{'aria-label':'Blockchain source Agent'});select.append(el('option',{value:''},'Choose a paired Agent source'));
  for(const p of s.pairs||[])select.append(el('option',{value:p.id},p.name));select.value=s.source||'';select.disabled=s.running;root.append(el('label',{},'Blockchain source Agent',select));
  const prepare=button('Prepare receiver — pause Internet peers','secondary',async()=>{await api('peers/block-prepare',{id:select.value});blockSnapshot='';await loadBlockDownload();});prepare.disabled=s.running;root.append(prepare);
  root.append(el('p',{class:'hint'},'Prepare first. Then authorise any required history recovery on This Node. Reindexing happens only through that separate local recovery approval. Click Start when ready; it can wait for the source to catch up.'));
  if(s.message)root.append(el('p',{role:'status'},s.message));if(s.chain?.message)root.append(el('p',{role:'status'},s.chain.message));
  if(s.chain?.current_height!==undefined)root.append(el('p',{},'Receiver validated blocks: '+blockHeight(s.chain.current_height)+(s.chain.source_height!==undefined?' · Source available blocks: '+blockHeight(s.chain.source_height):'')+(s.chain.source_syncing?' · Source is still downloading':'')));
  const start=button('Start receiving blocks','',async()=>{await api('peers/block-start',{});blockSnapshot='';await loadBlockDownload();});start.disabled=!s.prepared||s.running;const actions=el('div',{class:'actions'},start);root.append(actions);
  const stop=button('Stop receiving blocks','secondary',async()=>{await api('peers/block-stop',{});blockSnapshot='';await loadBlockDownload();});stop.disabled=!s.running;actions.append(stop);
  if(s.chain?.mode==='ssh_only'){const resume=button('Resume Core Internet connections','secondary',async()=>{await api('synchronisation/resume-network',{});blockSnapshot='';await loadBlockDownload();});resume.disabled=s.running;actions.append(resume);}
 }catch(error){root.replaceChildren(el('h3',{},'Blockchain over direct SSH'),el('p',{},error.message));}
}
setInterval(loadBlockDownload,2000);
window.loadBlockDownload=loadBlockDownload;
