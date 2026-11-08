'use strict';
let transferSignature='',transferSuccess=false;
window.updateTransfer=function(t){
 if(!t)return;
 const enabled=!!(workspace?.connected||t.rows?.length||t.recovery?.running);
 document.querySelector('[data-page="synchronisation"]').disabled=!workspace?.protected?.viewer;

 // Requests never open a browser or change the user's page.
 if(document.activeElement?.closest('#transfer-content form, #transfer-content input'))return;
 const signature=JSON.stringify(t);if(signature===transferSignature)return;transferSignature=signature;
 renderSync(t);
};
function transferCommand(title,command){return el('section',{},el('strong',{},title),el('pre',{class:'policy-code'},command),button('Copy command','secondary',async()=>{await navigator.clipboard.writeText(command);notify({message:'Command copied.'});}));}
function checkBox(label,checked,disabled,onChange){const input=el('input',{type:'checkbox','aria-label':label});input.checked=checked;input.disabled=disabled;input.addEventListener('change',()=>run(()=>onChange(input.checked)));return input;}
function renderSync(t){
 const root=$('#transfer-content'),rows=t.rows||[],list=el('section',{class:'server-card result-card'},el('h3',{},'Wallets awaiting synchronisation'),el('p',{class:'hint'},'Select the wallets to transfer. Click a row to review its public descriptors, funded addresses and vaults. Wallet Server controls this list; unchecking a wallet leaves its request pending.'));
 const table=el('table',{class:'transfer-history sync-queue'}),body=el('tbody');
 table.append(el('thead',{},el('tr',{},...['Send','Sending Agent','Receiving Agent','Wallet Name','Watch Only'].map(x=>el('th',{},x)))));
 for(const r of rows){
  const row=el('tr',{class:r.id===t.id?'selected-row':'','aria-selected':String(r.id===t.id)}),select=checkBox('Send '+r.wallet_name,r.selected,t.busy||r.state!=='pending',selected=>api('synchronisation/selection',{id:r.id,selected,watch_only:r.watch_only})),watch=checkBox('Watch only '+r.wallet_name,r.watch_only,t.busy||r.watch_only_locked||r.state!=='pending',watch_only=>api('synchronisation/selection',{id:r.id,selected:r.selected,watch_only}));
  select.addEventListener('click',e=>e.stopPropagation());watch.addEventListener('click',e=>e.stopPropagation());
  const review=button(r.wallet_name,'row-review',async()=>{await api('synchronisation/review',{id:r.id});transferSignature='';});review.disabled=t.busy;
  const children=r.extinct_group?el('details',{class:'extinct-children'},
    el('summary',{},'Retired wallets ('+(r.extinct_children||[]).length+')'),
    ...(r.extinct_children||[]).map(c=>el('div',{},el('strong',{},c.name),el('small',{},c.addresses.length+' address(es) · '+pipe(c.amount_sats)))),
    el('p',{class:'hint'},r.name_verified?'Children verified from local Core labels.':'Children from the sender’s signed preview; compare its code and identity.')):null;
  row.append(el('td',{},select),el('td',{},r.sender),el('td',{},r.receiver),el('td',{},review,children,el('small',{},r.direction==='send'?(r.name_verified?'Name verified by local Core':'Waiting for local verification'):'Name supplied by Wallet Server'),r.restoration_requested||r.restoring_extinct?el('small',{class:'warning'},'Restore original wallet role via direct SSH — requires local approval'):null,r.state!=='pending'?el('small',{},r.state==='recovery_required'?'Received — history recovery required':r.state):null),el('td',{},watch,r.watch_only_locked?el('small',{},'Source is watch-only'):null));
  children?.addEventListener('click',e=>e.stopPropagation());
  row.addEventListener('click',()=>{if(!t.busy)run(async()=>{await api('synchronisation/review',{id:r.id});transferSignature='';});});body.append(row);
 }
 table.append(body);list.append(table);if(!rows.length)list.append(el('p',{},'No wallet synchronisation requests.'));
 const nodes=el('section',{class:'server-card result-card'},el('h3',{},'Computers in this request list')),seen=new Set();
 for(const r of rows)for(const [name,address]of [[r.sender,r.sender_ipv6],[r.receiver,r.receiver_ipv6]]){const key=name+'|'+address;if(!seen.has(key)){seen.add(key);nodes.append(el('div',{class:'node-address'},el('strong',{},name),el('code',{},address||'IPv6 identity not supplied')));}}
 root.replaceChildren(list);if(seen.size)root.append(nodes);
 if(t.success_until>Date.now()/1000)root.append(el('section',{class:'transfer-success',role:'status'},'Success!'));
 if(t.error)root.append(el('p',{class:'warning',role:'alert'},t.error));
 if(t.proposal)root.append(renderWallet(t));
 root.append(batchControls(t,rows));
 if(t.recovery)root.append(recoveryCard(t.recovery));
}
function renderWallet(t){
 const p=t.proposal,receive=p.direction==='receive',setup=t.setup,box=el('section',{class:'server-card result-card'},el('h3',{},receive?'Receiving wallet details':'Sending wallet details'),el('p',{},'Wallet: '+(t.details?.public_wallet?.wallet_name||p.public_wallet.wallet_name)),el('p',{class:'hint'},'Wallet names are labels. Compare the public descriptors and signed preview code with the other computer using a channel independent of Wallet Server.'));
 if(window.reviewQR)box.append(window.reviewQR(t.id));
 if(t.initial_preview?.preview?.generated_at)box.append(el('p',{class:'hint'},'Signed public snapshot: '+new Date(t.initial_preview.preview.generated_at*1000).toISOString().replace('T',' ').replace('.000Z',' UTC')+'. This is a review snapshot. Both Agents recheck live wallet details before transfer; changed wallet data requires a new review.'));
 if(t.preview_error)box.append(el('p',{class:'warning'},t.preview_error));
 const group=(t.rows||[]).find(r=>r.id===t.id);if(group?.restoration_requested)box.append(el('p',{class:'warning'},'Original-role restoration: the receiver checks its locally recorded private-key assignment. All current and historical policies must match. Other signers are neither required nor copied.'));if(group?.restoration_requested&&receive){box.append(el('h3',{},'Your recorded original wallet accounts'));for(const role of t.original_assignments||[])box.append(el('p',{},role.wallet_name+' · '+(role.had_private?'Original private signer':'Original watch-only copy')));if(!t.original_assignments?.length)box.append(el('p',{class:'warning'},'Original local role evidence is unavailable. Wallet Server cannot provide this authority; receiving restoration is blocked.'));}if(group?.restoring_extinct&&!t.busy)box.append(el('p',{class:'warning'},'This restores an extinct wallet to active status. Only a verified direct SSH transfer from its active original can complete it.'),button('Deny restoration','secondary',async()=>{const result=await api('authorise/deny-lifecycle',{id:t.id});notify({message:result.message});transferSignature='';}),button('Cancel request','secondary',async()=>{const result=await api('authorise/cancel-lifecycle',{id:t.id});notify({message:result.message});transferSignature='';}));if(group?.extinct_group){box.append(el('h3',{},'Retired wallets inside this Extinct archive'));for(const c of group.extinct_children||[])box.append(el('article',{class:'public-fact'},el('strong',{},c.name),el('p',{},c.addresses.length+' address(es) · '+pipe(c.amount_sats)),...c.addresses.map(a=>el('code',{},a))));}
 const descriptors=t.details?.public_wallet?.descriptors||p.public_wallet.descriptors,details=el('details',{},el('summary',{},'Public descriptors ('+descriptors.length+')'));
 for(const d of descriptors)details.append(el('pre',{class:'policy-code'},d.desc),el('p',{},'History timestamp: '+d.timestamp+(d.internal?' · Change branch':' · Receiving branch')));box.append(details);
 if(t.preview_proof?.preview_hash){box.append(el('h3',{},'Independent verification'),el('p',{},'Compare this complete preview code on both computers:'),el('pre',{class:'policy-code'},t.preview_proof.preview_hash),el('p',{},'Sending Agent identity fingerprint — compare directly on the sender:'),el('pre',{class:'policy-code'},t.preview_proof.fingerprint));}
 else box.append(el('p',{class:'warning'},'Waiting for a locally verified and signed preview. Transfer is unavailable until Wallet Server relays the documented Build 8 protocol.'));
 if(t.details){
  box.append(el('h3',{},receive?'Funded outputs in the sender’s signed preview':'Funded outputs verified by your local Core'));
  const table=el('table',{class:'transfer-history'},el('thead',{},el('tr',{},...['Address / output','Amount','Time received (UTC)','Block height'].map(x=>el('th',{},x))))),body=el('tbody');
  for(const r of t.details.funded_outputs)body.append(el('tr',{},el('td',{},r.address,el('small',{},r.txid+':'+r.vout)),el('td',{},pipe(r.amount_sats)),el('td',{},r.time_received?new Date(r.time_received*1000).toISOString():'Unknown'),el('td',{},r.blockheight===null||r.blockheight===undefined?'Unconfirmed':blockHeight(r.blockheight))));table.append(body);box.append(table);
  const labels=t.details.address_labels||[];if(labels.length){const section=el('details',{},el('summary',{},'Addresses and labels ('+labels.length+')'));for(const row of labels)section.append(el('div',{class:'node-address'},el('code',{},row.address),el('span',{},row.label||'No label')));box.append(section);}
  if(!t.details.funded_outputs.length)box.append(el('p',{},'No current funded outputs.'));
  for(const v of t.details.vaults||[])box.append(el('section',{class:'proof'},el('h3',{},'Vault · block '+blockHeight(v.height)),el('p',{},'Address: '+v.address),el('pre',{class:'policy-code'},v.descriptor),el('p',{},'Public key derivation is checked against this wallet. The height condition and monitoring data accompany either transfer mode.')));
 }
 if(t.route)box.append(el('h3',{},'Direct connection route'),el('p',{},t.route.message));
 if(receive&&setup&&!setup.relay){
  box.append(el('h3',{},'Receiving SSH readiness'),el('p',{},'SSH: '+(setup.installed?'Installed':'Not installed')+' · IPv6 port 22: '+(setup.listening?'Listening':'Not listening')),el('p',{},'Receiving username: '+setup.username));
  if(!setup.installed)box.append(transferCommand('Install SSH support',setup.install_command));if(!setup.listening)box.append(transferCommand('Start SSH support',setup.start_command));
  box.append(el('details',{},el('summary',{},'Firewall and modem help'),transferCommand('Check receiving UFW',setup.firewall_check_command),transferCommand('Allow this sender if needed',setup.firewall_rule_command),transferCommand('Remove the exception afterward',setup.firewall_remove_command),el('p',{},setup.network_note)));
  box.append(button('Check receiving firewall','secondary',async()=>{await api('synchronisation/firewall',{id:t.id});transferSignature='';}),el('p',{},t.firewall.message));
  for(const f of setup.fingerprints)box.append(el('pre',{class:'policy-code'},f.type+' · '+f.fingerprint));
  box.append(el('p',{class:'hint'},'Compare a receiving SSH host fingerprint directly on this computer before the sender enters login credentials. If UFW permits SSH but the sender cannot connect, check the receiver’s modem IPv6 firewall. A direct LAN route instead suggests SSH, local firewall, guest Wi-Fi or client isolation. The sender normally needs outbound TCP 22 only.'));
 }
 return box;
}
function batchControls(t,rows){
 const box=el('section',{class:'server-card result-card'},el('h3',{},'Transfer selected wallets'));
 if(t.chain_sync?.message){box.append(el('p',{role:'status'},t.chain_sync.message));if(t.chain_sync.current_height!==undefined)box.append(el('p',{},'SSH blocks: '+blockHeight(t.chain_sync.current_height)+' / '+blockHeight(t.chain_sync.target_height)));if(t.chain_sync.network_paused&&!t.busy)box.append(button('Resume Core Internet connections','secondary',async()=>{await api('synchronisation/resume-network',{});transferSignature='';}));}

 if(t.relay_progress&&(t.relay_progress.sent_bytes||t.relay_progress.received_bytes))box.append(el('p',{role:'status'},'Encrypted stream · sent '+t.relay_progress.sent_bytes.toLocaleString()+' bytes · received '+t.relay_progress.received_bytes.toLocaleString()+' bytes'+(t.relay_progress.paused?' · connection control is waiting; bulk data requires direct SSH.':'')));
 if(t.busy){box.append(el('p',{role:'status'},t.sending?'Sending selected wallets, one at a time…':'Receiving authorisation is active for the selected wallets.'));
  if(!t.sending)box.append(button('End receiving authorisation','secondary',async()=>{await api('synchronisation/end-receiving',{});transferSignature='';}));return box;}
 const receive=rows.filter(r=>r.selected&&r.direction==='receive'&&r.state==='pending'),send=rows.filter(r=>r.selected&&r.direction==='send'&&r.state==='pending');
 if(receive.length){const form=el('form',{id:'peer-authorise-form'},el('h3',{},'Authorise '+receive.length+' receiving wallet(s)'));
  for(const r of receive.filter(r=>!r.encrypted_relay))form.append(el('label',{},r.sender+' · '+r.wallet_name+' · Sender Agent fingerprint',el('input',{name:r.id,required:'',autocomplete:'off',placeholder:'SHA256:…'})));
  form.append(el('button',{type:'submit'},'Authorise selected wallets'));form.addEventListener('submit',e=>{e.preventDefault();e.submitter?.blur();const fingerprints=Object.fromEntries(new FormData(form));run(async()=>{await api('synchronisation/authorise-batch',{fingerprints});notify({message:'Ready to receive the exact selected wallets. Core catches up through the authenticated peer connection while ordinary Internet peers are paused.'});});});box.append(form);
 }
 if(send.length){const form=el('form',{id:'peer-send-form'},el('h3',{},'Send '+send.length+' wallet(s)'),el('p',{},send.every(r=>r.encrypted_relay)?'Authorise each receiver locally first. Your independently QR-paired direct SSH connection carries the transfer. If unreachable, bulk transfer waits; it never uses the Server relay. No peer login password is needed.':'Authorise each receiver first. Existing direct SSH requests retain their original login flow.'));
  const peers=new Map();for(const row of send.filter(r=>!r.encrypted_relay))peers.set(row.peer_id,{address:row.receiver_ipv6,name:row.receiver});
  // Peer identity comes from the server-owned rows, never a free-form target field.
  for(const[id,{address,name}]of peers){const field=el('fieldset',{'data-peer':id},el('legend',{},name+' · '+address));for(const[key,label,type]of [['username','Receiving username','text'],['password','Computer login password','password'],['fingerprint','Receiving SSH fingerprint (compare directly)','text']]){const input=el('input',{name:key,type,required:'',autocomplete:'off'});field.append(el('label',{},label,input));if(key==='password'){const toggle=el('button',{type:'button',class:'secondary','aria-label':'Show computer login password','aria-pressed':'false'},'Show password');toggle.addEventListener('click',()=>{const visible=input.type==='password';input.type=visible?'text':'password';toggle.textContent=visible?'Hide password':'Show password';toggle.setAttribute('aria-pressed',String(visible));toggle.setAttribute('aria-label',visible?'Hide computer login password':'Show computer login password');});field.append(toggle);}}form.append(field);}
  form.append(el('button',{type:'submit'},'Send selected wallets'));form.addEventListener('submit',e=>{e.preventDefault();e.submitter?.blur();const credentials=Object.create(null);for(const field of form.querySelectorAll('fieldset')){const data={};for(const input of field.querySelectorAll('input')){data[input.name]=input.value;if(input.name==='password'){input.value='';input.type='password';}}for(const toggle of field.querySelectorAll('button')){toggle.textContent='Show password';toggle.setAttribute('aria-pressed','false');toggle.setAttribute('aria-label','Show computer login password');}credentials[field.dataset.peer]=data;}run(async()=>{await api('synchronisation/send-batch',{credentials});notify({message:'Selected transfers started. Each wallet is checked independently; passwords remain in memory only.'});});});box.append(form);
 }
 if(!receive.length&&!send.length)box.append(el('p',{},'Tick Send beside the wallets you want to synchronise.'));
 return box;
}
function recoveryCard(r){
 const box=el('section',{class:'server-card result-card node-recovery '+r.colour},el('h3',{},'This Node'));
 for(const [title,colour]of [['Synchronised','green'],['Requires Rescan','amber'],['Requires Blockchain Download','red']])box.append(el('p',{class:'recovery-status '+(r.status===title?colour+' active':'inactive')},el('span',{class:'dot '+(r.status===title?colour:'muted')}),title));
 box.append(el('p',{role:'status'},r.message));if(r.blocks!==undefined)box.append(el('p',{},'Blocks: '+blockHeight(r.blocks)+' / '+blockHeight(r.headers)));if(r.job?.message)box.append(el('p',{},r.job.message));
 const refresh=button('↻','secondary recovery-refresh',async()=>{const plan=await api('synchronisation/recovery-plan',{}),dialog=el('dialog',{'aria-label':'Authorise local history recovery'},el('h2',{},'Recover this node’s history'),el('p',{},plan.message));dialog.append(el('p',{},plan.pruning?.pruned?'Pruning stays enabled at your existing setting and storage limit.':'This node’s existing pruning setting remains unchanged.'));dialog.append(el('p',{},'Only your local approval can start this. Wallet Server cannot start a rescan or restart Core.'),el('div',{class:'actions'},button('Cancel','secondary',()=>{dialog.close();dialog.remove();}),button('Authorise','',async()=>{dialog.close();dialog.remove();await api('synchronisation/recovery-start',{id:plan.id});transferSignature='';})));document.body.append(dialog);dialog.showModal();});
 refresh.setAttribute('aria-label','Recover node history');refresh.title='Review and authorise rescan or blockchain recovery';refresh.disabled=!r.can_refresh||r.running||r.status==='Synchronised';box.append(refresh);return box;
}
