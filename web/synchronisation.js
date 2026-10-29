'use strict';
let transferId=null,transferSignature='',transferReviewing=false,transferSuccess=false;
window.updateTransfer=function(t){
 if(!t)return;
 const success=t.success_until>Date.now()/1000,b=document.querySelector('[data-page="synchronisation"]');b.disabled=!t.id&&!success;
 if(success){transferSuccess=true;showPage('synchronisation');$('#transfer-content').replaceChildren(el('section',{class:'transfer-success',role:'status'},'Success!'));return;}
 if(transferSuccess){transferSuccess=false;showPage('services');}
 if(!t.id){transferId=null;transferSignature='';if(page==='synchronisation')showPage('services');return;}
 if(t.id!==transferId){transferId=t.id;transferSignature='';showPage('synchronisation');if(t.proposal.direction==='send'&&!transferReviewing){transferReviewing=true;api('synchronisation/review',{id:t.id}).catch(notify).finally(()=>{transferReviewing=false;});}}
 const signature=JSON.stringify(t);if(signature===transferSignature)return;
 // Do not erase an account/password being entered while the status polls.
 if(document.activeElement?.closest('#peer-send-form, #peer-authorise-form'))return;
 transferSignature=signature;renderTransfer(t);
};
function transferCommand(title,command){return el('section',{},el('strong',{},title),el('pre',{class:'policy-code'},command),button('Copy command','secondary',async()=>{await navigator.clipboard.writeText(command);notify({message:'Command copied.'});}));}
function renderTransfer(t){
 const p=t.proposal,receive=p.direction==='receive',setup=t.setup,box=el('section',{class:'server-card result-card'},el('h3',{},receive?'Receive a wallet':'Send a wallet'),el('p',{},'Wallet: '+p.public_wallet.wallet_name),el('p',{},'Sending IPv6: '+(receive?p.peer.ipv6:setup.ipv6||'No IPv6 route')),el('p',{},'Receiving IPv6: '+(receive?setup.ipv6||'No local IPv6 route detected (request: '+(p.node_ipv6||'not supplied')+')':p.peer.ipv6)),el('p',{},'Peer computer: '+p.peer.hostname),el('p',{class:'hint'},'Other Dashboard requests are refused while synchronisation is active. Wallet files and login passwords travel directly between the two computers over authenticated IPv6 SSH.'));
 if(p.source_has_private_keys)box.append(el('p',{class:'warning'},'This transfers an encrypted wallet containing private keys. Only send to a computer you trust. Wallet encryption and an encrypted disk remain necessary; SSH protects data in transit.'));
 const descriptorBox=el('details',{},el('summary',{},'Public descriptors ('+p.public_wallet.descriptors.length+')'));
 for(const r of p.public_wallet.descriptors)descriptorBox.append(el('pre',{class:'policy-code'},r.desc),el('p',{},'Descriptor history timestamp: '+r.timestamp+(r.internal?' · Change branch':' · Receiving branch')));
 box.append(descriptorBox);
 if(t.route)box.append(el('h3',{},'Connection route'),el('p',{},t.route.message));
 if(!p.preview_challenge)box.append(el('p',{class:'warning'},'Dashboard Build 8 does not relay the initial node-verified wallet preview. Update Dashboard using the supplied integration document. Wallet transfer remains disabled until both sides can review a signed preview.'));
 if(t.preview_error)box.append(el('p',{class:'warning'},t.preview_error));
 if(t.preview_proof?.preview_hash){box.append(el('h3',{},'Verify the initial request independently'),el('p',{},'Compare this complete preview code with the other Agent’s screen:'),el('pre',{class:'policy-code'},t.preview_proof.preview_hash));if(!receive)box.append(el('p',{},'Your Agent identity fingerprint — share directly with the receiving user:'),el('pre',{class:'policy-code'},t.preview_proof.fingerprint));box.append(el('p',{class:'hint'},'The preview is signed by the sending Agent. Compare its identity fingerprint directly on the sending computer, then compare the preview code on both computers. Dashboard cannot replace either without detection when these independent checks are made. Core verifies the sender’s current public descriptors and coins before this preview is signed.'));
 }else if(p.preview_challenge)box.append(el('p',{role:'status'},'Waiting for the sending node’s verified and signed initial wallet preview. Receipt cannot be authorised yet.'));
 if(t.error)box.append(el('p',{class:'warning',role:'alert'},t.error));
 if(t.details){
  box.append(el('h3',{},receive?'Funded outputs in the signed initial preview':'Funded outputs verified by your local Bitcoin Core'));
  const table=el('table',{class:'transfer-history'},el('thead',{},el('tr',{},...['Address / output','Amount','Time received (UTC)','Block height'].map(h=>el('th',{},h))))),body=el('tbody');
  for(const r of t.details.funded_outputs)body.append(el('tr',{},el('td',{},r.address,el('small',{},r.txid+':'+r.vout)),el('td',{},pipe(r.amount_sats)),el('td',{},r.time_received?new Date(r.time_received*1000).toISOString():'Unknown'),el('td',{},r.blockheight??'Unconfirmed')));
  table.append(body);box.append(table);for(const r of t.details.funded_outputs)box.append(transferCommand('Independent public node check for this output','bitcoin-cli gettxout '+r.txid+' '+r.vout+' true'));if(!t.details.funded_outputs.length)box.append(el('p',{},'No current funded outputs were found.'));
 }else if(receive)box.append(el('p',{},'Wait for the sender’s signed initial preview. Authorise stays unavailable until it can be reviewed independently.'));
 if(p.requires_blockchain_redownload)box.append(el('p',{class:'warning'},'Dashboard reports that some wallet history may predate this node’s pruned blocks. The Agent will verify the restored wallet locally. No reindex or blockchain download is started automatically; missing history or an unfinished scan prevents success.'));
 if(receive){
  box.append(el('h3',{},'Receiving SSH readiness'),el('p',{},'SSH support: '+(setup.installed?'Installed':'Not installed')+' · IPv6 port 22: '+(setup.listening?'Listening locally':'Not listening')),el('p',{},'Receiving username: '+setup.username));
  if(!setup.installed)box.append(transferCommand('Install SSH support on this computer',setup.install_command));
  if(!setup.listening)box.append(transferCommand('Start SSH on this computer',setup.start_command));
  box.append(el('details',{},el('summary',{},'Firewall and modem connection help'),transferCommand('Check UFW (administrator approval is required)',setup.firewall_check_command),transferCommand('If UFW is active, allow this sending IPv6 only',setup.firewall_rule_command),transferCommand('Remove that rule after synchronisation',setup.firewall_remove_command),el('p',{},setup.network_note)));
  box.append(button('Check receiving firewall','secondary',async()=>{await api('synchronisation/firewall',{id:t.id});transferSignature='';}),el('p',{},t.firewall.message));
  if(t.firewall.state==='allowed'&&t.route?.direct_lan)box.append(el('p',{class:'hint'},'If the sender still cannot connect over this direct LAN route, check the receiving SSH listener and Wi-Fi guest/client isolation or VLAN restrictions. The sender normally needs only outbound TCP 22. An Internet modem exception is not normally needed for this local path.'));
  if(t.firewall.state==='allowed'&&!t.route?.direct_lan)box.append(el('p',{class:'hint'},'If the sender still cannot connect, a receiving modem/router IPv6 firewall block is suspected. On the receiving network, allow incoming IPv6 TCP 22 to the receiving address above, preferably only from the sending address. The sender normally needs only outgoing TCP 22; check its outbound rules if it uses a restrictive firewall. VPNs, routing and a changed IPv6 address can also cause failure.'));
  box.append(el('h3',{},'Compare this SSH fingerprint on the sending computer'));
  for(const f of setup.fingerprints)box.append(el('pre',{class:'policy-code'},f.type+' · '+f.fingerprint));
  box.append(el('p',{class:'hint'},'Share a fingerprint directly with the sender using a channel you trust. A fingerprint supplied by Dashboard cannot establish the receiver’s identity.'));
  if(!t.ready&&t.state==='pending'&&t.initial_preview){
   const form=el('form',{id:'peer-authorise-form'},el('label',{},'Sender Agent identity fingerprint — copy from the sending computer, not Dashboard',el('input',{name:'sender_fingerprint',required:'',autocomplete:'off',placeholder:'SHA256:…'})),el('button',{type:'submit'},'Authorise'));
   form.addEventListener('submit',e=>{e.preventDefault();e.submitter?.blur();const sender_fingerprint=form.querySelector('input').value.trim();run(async()=>{await api('synchronisation/authorise',{id:t.id,sender_fingerprint});notify({message:'Initial preview verified. Ready for the sender; authorisation expires in 15 minutes.'});});});box.append(form);
  }
  else box.append(el('p',{},t.ready?'Waiting for the sending Agent…':'Attempted transfer: inspect Core before deciding whether to cancel.'));
 }else if(!t.initial_preview){box.append(el('p',{},'Sending is disabled until a signed initial preview has been generated and relayed by the updated Dashboard.'));}else if(t.sending){box.append(el('p',{role:'status'},'Direct synchronisation in progress. The receiver is checking the approved wallet and its local Core restoration.'));}else if(t.state==='pending'){
  box.append(button('Refresh wallet details','secondary',async()=>{await api('synchronisation/review',{id:t.id});transferSignature='';}));
  const form=el('form',{id:'peer-send-form'},el('h3',{},'Send directly to the receiving computer'),el('p',{},'First click Authorise on the receiving Agent. Enter that computer’s login details and compare its displayed SSH fingerprint.'));
  for(const[name,label,type]of[['username','Receiving computer username','text'],['password','Receiving computer login password','password'],['fingerprint','Receiving SSH fingerprint (SHA256:…)','text']])form.append(el('label',{},label,el('input',{name,type,required:'',autocomplete:'off',spellcheck:'false'})));
  form.append(el('button',{type:'submit'},'Send'));form.addEventListener('submit',e=>{e.preventDefault();e.submitter?.blur();const data=Object.fromEntries(new FormData(form));form.querySelector('[name="password"]').value='';run(async()=>{await api('synchronisation/send',{id:t.id,...data});notify({message:'Connecting directly to the authorised receiver. The live wallet manifest will be checked against the approved initial preview before sending the file.'});});});box.append(form);
 }
 box.append(button('Cancel synchronisation','secondary',async()=>{await api('synchronisation/cancel',{id:t.id});transferSignature='';showPage('services');}));$('#transfer-content').replaceChildren(box);
}
