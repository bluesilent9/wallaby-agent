'use strict';
let transferSignature='',transferSuccess=false,syncView='wallets';
window.updateTransfer=function(t){
 if(!t)return;
 const enabled=!!(workspace?.connected||t.rows?.length||t.recovery?.running);
 document.querySelector('[data-page="synchronisation"]').disabled=!workspace?.protected?.viewer;

 // Requests never open a browser or change the user's page.
 if(document.activeElement?.closest('#transfer-content form, #transfer-content input, #transfer-content select'))return;
 const signature=JSON.stringify(t);if(signature===transferSignature)return;transferSignature=signature;
 renderSync(t);
};
function transferCommand(title,command){return el('section',{},el('strong',{},title),el('pre',{class:'policy-code'},command),button('Copy command','secondary',async()=>{await navigator.clipboard.writeText(command);notify({message:'Command copied.'});}));}
function checkBox(label,checked,disabled,onChange){const input=el('input',{type:'checkbox','aria-label':label});input.checked=checked;input.disabled=disabled;input.addEventListener('change',()=>{input.blur();run(()=>onChange(input.checked));});return input;}
const syncOfferMessages={peer_changed:'Wallet Server must renew this stale connection request. Your direct pairing is retained.',secure_pairing_required:'Waiting for Wallet Server to observe the paired connection.',peer_offline:'The advertised source is offline.',permissions_pending:'Waiting for the current receive permission to reach Wallet Server.',discovery_pending:'Waiting for Wallet Server to prepare the transfer request.',review_paused:'Wallet Server has paused this transfer review.',history_recovery:'Finish the existing wallet history recovery before another transfer.',local_outcome:'A previous transfer outcome needs review in Wallet Server.',earlier_operation:'An earlier transfer must be reconciled first.',preview_changed:'Wallet Server must prepare a new review of the changed wallet.',preview_expired:'Wallet Server must renew the expired wallet review.',invalid_pair:'Wallet Server must repair the incomplete paired request.',disabled:'Receiving is disabled for this wallet.',ready:'Waiting for the executable transfer request from Wallet Server.'};
const syncPeerChoices=new Map();
function renderSync(t){
 const target=$('#transfer-content'),root=el('div',{'data-sync-panel':'wallets'}),rows=t.rows||[],list=el('section',{class:'server-card result-card',id:'sync-wallet-table'},el('h3',{},'Wallet synchronisation'),el('p',{class:'hint'},'Sending wallets appear when a recipient is directly connected. Missing receiving wallets and your denied wallets stay listed while waiting for a sender. Select and review receiving wallets to start their transfers. Trusted directly paired senders respond automatically.'));
 const table=el('table',{class:'transfer-history sync-queue'}),body=el('tbody');
 table.append(el('thead',{},el('tr',{},...['Wallet Name','Signer','Send to','Receive from','Watch Only','Select','Status / Actions'].map(x=>el('th',{},x)))));
 const wallets=[...(t.wallets||[])].sort((a,b)=>a.wallet_name.localeCompare(b.wallet_name,undefined,{sensitivity:'base'})||a.policy_id.localeCompare(b.policy_id));
 const chosenIds=new Set();
 for(const w of wallets){
  const tr=el('tr',{'data-wallet':w.policy_id}),actions=el('td'),menus={},chosen={};
  for(const direction of ['send','receive']){
   const options=(w[direction]||[]).filter(r=>r.direct_ready&&r.state==='pending'&&!(direction==='receive'&&w.denied));
   const key=w.policy_id+'|'+direction,previous=syncPeerChoices.get(key),current=options.find(r=>r.selected)||options.find(r=>r.id===previous)||options[0];
   const select=el('select',{'aria-label':(direction==='send'?'Send to ':'Receive from ')+w.wallet_name});
   const notices=(w.offers||[]).filter(o=>o.direction===direction&&o.peer);
   if(!options.length)select.append(el('option',{value:''},notices.length?notices.map(o=>o.peer.hostname).join(', ')+' — waiting for transfer request':'No Agent Detected'));
   for(const r of options)select.append(el('option',{value:r.id},direction==='send'?r.receiver:r.sender));
   select.disabled=!!t.busy||!options.length;select.classList.toggle('no-agent',!options.length&&!notices.length);select.classList.toggle('waiting-route',!options.length&&!!notices.length);
   if(current){select.value=current.id;chosen[direction]=current;syncPeerChoices.set(key,current.id);}
   select.addEventListener('change',()=>{const target=options.find(r=>r.id===select.value);if(!target)return;select.blur();syncPeerChoices.set(key,target.id);run(async()=>{await api('synchronisation/route',{id:target.id,selected:!!current?.selected,watch_only:target.watch_only});transferSignature='';});});menus[direction]=select;
  }
  const active=chosen.receive||chosen.send,checks=el('td'),watchCell=el('td');
  for(const direction of ['send','receive']){
   const r=chosen[direction];if(!r)continue;chosenIds.add(r.id);
   if(direction==='send'&&r.encrypted_relay){checks.append(el('small',{},'Receiver starts transfer'));watchCell.append(el('small',{},'Chosen by receiver'));const review=button('Review send','secondary',async()=>{await api('synchronisation/review',{id:r.id});transferSignature='';});review.disabled=!!t.busy;actions.append(review);continue;}
   const select=checkBox((direction==='send'?'Send ':'Receive ')+w.wallet_name,!!r.selected,!!t.busy,selected=>api('synchronisation/route',{id:r.id,selected,watch_only:r.watch_only}));
   checks.append(el('label',{},select,direction==='send'?'Send':'Receive'));
   const watch=checkBox('Watch only '+direction+' '+w.wallet_name,!!r.watch_only,!!t.busy||r.watch_only_locked,watch_only=>api('synchronisation/route',{id:r.id,selected:!!r.selected,watch_only}));watchCell.append(el('label',{},watch,direction==='send'?'Send':'Receive'));if(r.watch_only_locked)watchCell.append(el('small',{},'Source is watch-only'));
   const review=button('Review '+(direction==='send'?'send':'receive'),'secondary',async()=>{await api('synchronisation/review',{id:r.id});transferSignature='';});review.disabled=!!t.busy;actions.append(review);
  }
  if(!active){const watch=checkBox('Watch only '+w.wallet_name,!!w.local_wallets?.length&&!w.local_private,true,()=>{});watchCell.append(watch);}
  if(w.denied){actions.append(el('p',{class:'warning'},'Incoming synchronisation disabled'),button('Enable receiving','secondary',async()=>{await api('authorise/enable-sync',{id:w.policy_id});transferSignature='';}));}
  else if(w.deny_id){const deny=button('Deny receiving','secondary',async()=>{await api('authorise/disable-sync',{id:w.deny_id});transferSignature='';});deny.disabled=!!t.busy;actions.append(deny);}
  if(w.local_wallets?.length)actions.append(el('small',{},'On this Agent'));
  if(w.pending&&!active&&!w.denied){const offers=(w.offers||[]).filter(o=>o.direction==='receive');if(offers.length)for(const o of offers)actions.append(el('small',{class:'sync-offer-status'},(o.peer?.hostname?o.peer.hostname+': ':'')+(syncOfferMessages[o.status]||'Waiting for an authorised transfer request.')));else actions.append(el('small',{class:'warning'},'No Agent Detected'),el('small',{},'Connect a suitable Agent in Peer Connections.'));}
  for(const r of [...(w.send||[]),...(w.receive||[])].filter(r=>r.state!=='pending')){actions.append(el('p',{},r.state==='recovery_required'?'Received — history recovery required':r.state));const inspect=button('Inspect previous transfer','secondary',async()=>{await api('synchronisation/review',{id:r.id});transferSignature='';});inspect.disabled=!!t.busy;actions.append(inspect);}
  const nameCell=el('td',{},el('strong',{},w.wallet_name),...(w.local_wallets||[]).filter(name=>name!==w.wallet_name).map(name=>el('small',{},name)));
  const grouped=[...(w.send||[]),...(w.receive||[])].find(r=>r.extinct_group&&r.extinct_children?.length);if(grouped)nameCell.append(el('details',{},el('summary',{},'Retired wallets ('+grouped.extinct_children.length+')'),...grouped.extinct_children.map(c=>el('div',{},el('strong',{},c.name),el('small',{},c.addresses.length+' address(es) · '+pipe(c.amount_sats)))),el('p',{class:'hint'},grouped.name_verified?'Children verified from local Core labels.':'Children from the sender’s signed preview; compare its code and identity.')));
  const signer=el('td');if(w.multisig){for(const s of w.signers||[])signer.append(el('strong',{},s.label),s.account!==s.label?el('small',{},s.account):null);if(chosen.receive)signer.append(el('small',{},chosen.receive.signer_label?'Source account: '+chosen.receive.signer_label:'Source signer details require signed review'));if(!(w.signers||[]).length&&!chosen.receive)signer.append(el('small',{},'No local signing account'));}else signer.append(el('small',{},w.local_wallets?.length?(w.local_private?'Single-signature':'Watch-only'):active?.watch_only_locked?'Watch-only source':'Checked during review'));
  tr.append(nameCell,signer,el('td',{},menus.send),el('td',{},menus.receive),watchCell,checks,actions);body.append(tr);
 }
 table.append(body);list.append(el('div',{class:'sync-table-scroll'},table));
 if(!wallets.length)list.append(el('p',{},'No wallets awaiting synchronisation.'));
 if(t.offer_server_support===false)list.append(el('p',{role:'status'},'Update Wallet Server to receive discovered wallet offers. Denied receiving wallets remain listed.'));
 list.append(batchControls(t,rows.filter(r=>chosenIds.has(r.id))));root.replaceChildren(list);
 if(t.success_until>Date.now()/1000)root.append(el('section',{class:'transfer-success',role:'status'},'Success!'));
 if(t.error)root.append(el('p',{class:'warning',role:'alert'},t.error));
 if(t.proposal)root.append(renderWallet(t));
 const walletPanel=root;
 const blockPanel=el('section',{'data-sync-panel':'blockchain',id:'block-download-controls',class:'server-card result-card'}),historyPanel=el('section',{'data-sync-panel':'history',class:'sync-history'});
 if(t.recovery)historyPanel.append(recoveryCard(t.recovery,!!t.clone_running));else historyPanel.append(el('p',{},'Local Core history status is not available yet.'));
 const navigation=el('nav',{class:'sync-navigation','aria-label':'Synchronisation operations'}),panels={wallets:walletPanel,blockchain:blockPanel,history:historyPanel};
 for(const [key,title]of [['wallets','Wallets'],['blockchain','Blockchain'],['history','Local history']]){const item=button(title,'secondary',()=>{syncView=key;for(const [name,panel]of Object.entries(panels))panel.hidden=name!==key;for(const b of navigation.children)b.setAttribute('aria-pressed',String(b===item));});item.setAttribute('aria-pressed',String(syncView===key));navigation.append(item);}
 for(const [key,panel]of Object.entries(panels))panel.hidden=syncView!==key;
 target.replaceChildren(el('p',{class:'hint sync-intro'},'Wallets transfers wallet data. Blockchain receives blocks or a trusted clone. Local history checks and repairs this node’s wallet history.'),navigation,walletPanel,blockPanel,historyPanel);window.loadBlockDownload?.();
}
function renderWallet(t){
 const p=t.proposal,receive=p.direction==='receive',setup=t.setup,box=el('section',{class:'server-card result-card'},el('h3',{},receive?'Receiving wallet details':'Sending wallet details'),el('p',{},'Wallet: '+(t.details?.public_wallet?.wallet_name||p.public_wallet.wallet_name)),el('p',{class:'hint'},'Wallet names are labels. The signed preview and public descriptors are checked against the authenticated direct Agent connection.'));
 if(window.reviewQR)box.append(window.reviewQR(t.id));
 if(t.initial_preview?.preview?.generated_at)box.append(el('p',{class:'hint'},'Signed public snapshot: '+new Date(t.initial_preview.preview.generated_at*1000).toISOString().replace('T',' ').replace('.000Z',' UTC')+'. This is a review snapshot. Both Agents recheck live wallet details before transfer; changed wallet data requires a new review.'));
 if(t.preview_error)box.append(el('p',{class:'warning'},t.preview_error));
 const group=(t.rows||[]).find(r=>r.id===t.id);if(group?.restoration_requested)box.append(el('p',{class:'warning'},'Original-role restoration: the receiver checks its locally recorded private-key assignment. All current and historical policies must match. Other signers are neither required nor copied.'));if(group?.restoration_requested&&receive){box.append(el('h3',{},'Your recorded original wallet accounts'));for(const role of t.original_assignments||[])box.append(el('p',{},role.wallet_name+' · '+(role.had_private?'Original private signer':'Original watch-only copy')));if(!t.original_assignments?.length)box.append(el('p',{class:'warning'},'Original local role evidence is unavailable. Wallet Server cannot provide this authority; receiving restoration is blocked.'));}if(group?.restoring_extinct&&!t.busy)box.append(el('p',{class:'warning'},'This restores an extinct wallet to active status. Only a verified direct SSH transfer from its active original can complete it.'),button('Deny restoration','secondary',async()=>{const result=await api('authorise/deny-lifecycle',{id:t.id});notify({message:result.message});transferSignature='';}),button('Cancel request','secondary',async()=>{const result=await api('authorise/cancel-lifecycle',{id:t.id});notify({message:result.message});transferSignature='';}));if(group?.extinct_group){box.append(el('p',{class:'hint'},'Extinct history is verified and merged over direct SSH. Existing history and LOST information are retained. Previously unknown retired history can be imported after this direct transfer approval. Addresses still owned by an active local wallet must first be retired here. Conflicting labels stop the update.'),el('h3',{},'Retired wallets inside this Extinct archive'));for(const c of group.extinct_children||[])box.append(el('article',{class:'public-fact'},el('strong',{},c.name),el('p',{},c.addresses.length+' address(es) · '+pipe(c.amount_sats)),...c.addresses.map(a=>el('code',{},a))));}
 const descriptors=t.details?.public_wallet?.descriptors||p.public_wallet.descriptors,details=el('details',{},el('summary',{},'Public descriptors ('+descriptors.length+')'));
 for(const d of descriptors)details.append(el('pre',{class:'policy-code'},d.desc),el('p',{},'History timestamp: '+d.timestamp+(d.internal?' · Change branch':' · Receiving branch')));box.append(details);
 if(t.preview_proof?.preview_hash)box.append(el('p',{class:'hint'},'The signed wallet preview is verified against the paired Agent identity before transfer.'));
 else box.append(el('p',{class:'warning'},'Waiting for a signed wallet preview from the paired Agent.'));
 if(t.details){
  box.append(el('h3',{},receive?'Funded outputs in the sender’s signed preview':'Funded outputs verified by your local Core'));
  const table=el('table',{class:'transfer-history'},el('thead',{},el('tr',{},...['Address / output','Amount','Time received (UTC)','Block height'].map(x=>el('th',{},x))))),body=el('tbody');
  for(const r of t.details.funded_outputs)body.append(el('tr',{},el('td',{},r.address,el('small',{},r.txid+':'+r.vout)),el('td',{},pipe(r.amount_sats)),el('td',{},r.time_received?new Date(r.time_received*1000).toISOString():'Unknown'),el('td',{},r.blockheight===null||r.blockheight===undefined?'Unconfirmed':blockHeight(r.blockheight))));table.append(body);box.append(table);
  const labels=t.details.address_labels||[];if(labels.length){const section=el('details',{},el('summary',{},'Addresses and labels ('+labels.length+')'));for(const row of labels)section.append(el('div',{class:'node-address'},el('code',{},row.address),el('span',{},row.label||'No label')));box.append(section);}
  if(!t.details.funded_outputs.length)box.append(el('p',{},'No current funded outputs.'));
  for(const v of t.details.vaults||[])box.append(el('section',{class:'proof'},el('h3',{},'Vault · block '+blockHeight(v.height)),el('p',{},'Address: '+v.address),el('pre',{class:'policy-code'},v.descriptor),el('p',{},'Public key derivation is checked against this wallet. The height condition and monitoring data accompany either transfer mode.')));
 }
 if(t.route)box.append(el('h3',{},'Direct connection route'),el('p',{},t.route.message));
 if(receive&&setup&&!setup.relay)box.append(el('p',{class:'warning'},'This older transfer needs a current direct-sync request. Pair and connect both Agents in Peer Connections, then select Receive again.'));
 return box;
}
function batchControls(t,rows){
 const box=el('section',{class:'server-card result-card'},el('h3',{},'Transfer selected wallets'));
 if(t.chain_sync?.message){box.append(el('p',{role:'status'},t.chain_sync.message));if(t.chain_sync.current_height!==undefined)box.append(el('p',{},'SSH blocks: '+blockHeight(t.chain_sync.current_height)+' / '+blockHeight(t.chain_sync.target_height)));if(t.chain_sync.network_paused&&t.chain_sync.mode!=='ssh_only'&&!t.busy)box.append(button('Resume Core Internet connections','secondary',async()=>{await api('synchronisation/resume-network',{});transferSignature='';}));}

 if(t.relay_progress&&(t.relay_progress.sent_bytes||t.relay_progress.received_bytes))box.append(el('p',{role:'status'},'Encrypted stream · sent '+t.relay_progress.sent_bytes.toLocaleString()+' bytes · received '+t.relay_progress.received_bytes.toLocaleString()+' bytes'+(t.relay_progress.paused?' · connection control is waiting; bulk data requires direct SSH.':'')));
 if(t.clone_running){box.append(el('p',{role:'status'},'Trusted blockchain cloning is active. View progress in Blockchain; wallet transfers and history recovery will be available after Core restarts and checks finish.'));return box;}
 if(t.busy){box.append(el('p',{role:'status'},t.sending?'Sending selected wallets, one at a time…':'Receiving authorisation is active for the selected wallets.'));
  if(!t.sending)box.append(button('End receiving authorisation','secondary',async()=>{await api('synchronisation/end-receiving',{});transferSignature='';}));return box;}
 const receive=rows.filter(r=>r.selected&&r.direction==='receive'&&r.state==='pending'),send=rows.filter(r=>r.selected&&r.direction==='send'&&r.state==='pending');
 if(receive.length){const form=el('form',{id:'peer-authorise-form'},el('h3',{},'Authorise '+receive.length+' receiving wallet(s)'));
  form.append(el('button',{type:'submit'},'Authorise selected wallets'));form.addEventListener('submit',e=>{e.preventDefault();e.submitter?.blur();run(async()=>{await api('synchronisation/authorise-batch',{});notify({message:'Ready to receive the exact selected wallets. Core catches up through the authenticated peer connection while ordinary Internet peers are paused.'});});});box.append(form);
 }
 if(send.some(r=>r.encrypted_relay))box.append(el('p',{class:'hint'},'Trusted paired receivers start these transfers automatically after approving Receive. No approval or Send click is required here.'));
 if(send.some(r=>!r.encrypted_relay))box.append(el('p',{class:'warning'},'Pair and connect these Agents in Peer Connections, then request a current direct wallet sync. Login credentials and manual identity checks are not used.'));
 if(!receive.length&&!send.length)box.append(el('p',{},'Select Send or Receive beside the wallets you want to synchronise.'));
 return box;
}
function recoveryCard(r,blocked=false){
 const box=el('section',{class:'server-card result-card node-recovery '+r.colour},el('h3',{},'This Node'));
 box.append(el('p',{class:'hint'},'To replace a pending or running Extinct history download with a trusted local clone, open Blockchain and choose Switch pending/running recovery to a trusted clone. Pending jobs stay in place until the source history is verified.'));
 for(const [title,colour]of [['Synchronised','green'],['Requires Rescan','amber'],['Requires Blockchain Download','red'],['Paused for trusted clone','amber']])box.append(el('p',{class:'recovery-status '+(r.status===title?colour+' active':'inactive')},el('span',{class:'dot '+(r.status===title?colour:'muted')}),title));
 box.append(el('p',{role:'status'},r.message));if(r.blocks!==undefined)box.append(el('p',{},'Blocks: '+blockHeight(r.blocks)+' / '+blockHeight(r.headers)));if(r.job?.message)box.append(el('p',{},r.job.message));
 const refresh=button('↻','secondary recovery-refresh',async()=>{const plan=await api('synchronisation/recovery-plan',{}),dialog=el('dialog',{'aria-label':'Authorise local history recovery'},el('h2',{},'Recover this node’s history'),el('p',{},plan.message));dialog.append(el('p',{},plan.pruning?.pruned?'Pruning stays enabled at your existing setting and storage limit.':'This node’s existing pruning setting remains unchanged.'));dialog.append(el('p',{},'Only your local approval can start this. Wallet Server cannot start a rescan or restart Core.'),el('div',{class:'actions'},button('Cancel','secondary',()=>{dialog.close();dialog.remove();}),button('Authorise','',async()=>{dialog.close();dialog.remove();await api('synchronisation/recovery-start',{id:plan.id});transferSignature='';})));document.body.append(dialog);dialog.showModal();});
 refresh.setAttribute('aria-label','Recover node history');refresh.title='Review and authorise rescan or blockchain recovery';refresh.disabled=blocked||!r.can_refresh||r.running||r.status==='Synchronised';box.append(refresh);return box;
}
