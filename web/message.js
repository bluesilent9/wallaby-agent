'use strict';
let messageReview=null;
async function loadMessageWallets(){
 const refreshButton=$('#message-refresh'),list=$('#message-wallets');
 const selected=new Set([...list.querySelectorAll('input:checked')].map(x=>x.value));
 messageReview=null;$('#message-review-box').replaceChildren();$('#message-result').replaceChildren();
 refreshButton.disabled=true;refreshButton.textContent='Refreshing signing accounts…';
 list.replaceChildren(el('p',{role:'status'},'Reading signing accounts from Bitcoin Core and loaded optical archives…'));
 try{
  const items=await api('message/wallets',{});
  if(!Array.isArray(items))throw Error('The local signing-account response was invalid.');
  list.replaceChildren(...items.map(w=>{const input=el('input',{type:'checkbox',value:w.name});input.checked=selected.has(w.name);return el('label',{},input,w.name+(w.disc?' · optical archive in protected RAM':''));}));
  if(!items.length)list.append(el('p',{role:'status'},'No signing accounts are available. Load a wallet with private keys in Bitcoin Core, or load an archival wallet in Disc Operations, then refresh.'));
 }catch(error){list.replaceChildren(el('p',{role:'alert'},error.message));throw error;}
 finally{refreshButton.disabled=false;refreshButton.textContent='Refresh Signing Accounts';}
}
$('#message-refresh').addEventListener('click',()=>run(loadMessageWallets));

for(const input of ['message-address','message-text','message-partial'])$('#'+input).addEventListener('input',()=>{messageReview=null;$('#message-review-box').replaceChildren();$('#message-result').replaceChildren();});
$('#message-wallets').addEventListener('change',()=>{messageReview=null;$('#message-review-box').replaceChildren();$('#message-result').replaceChildren();});
$('#message-review').addEventListener('click',()=>run(async()=>{const wallets=[...$('#message-wallets').querySelectorAll('input:checked')].map(x=>x.value);const r=await api('message/prepare',{wallets,address:$('#message-address').value,message:$('#message-text').value,partial:$('#message-partial').value.trim()});messageReview=r.id;$('#message-result').replaceChildren();$('#message-review-box').replaceChildren(el('section',{class:'server-card result-card'},el('h2',{},'Review the exact message'),el('p',{},'Address: '+r.address),el('p',{},'Signing accounts: '+r.wallets.join(', ')),el('p',{},r.threshold+' signature(s) required'+(r.height?' · block-height condition '+r.height:'')),el('pre',{class:'public-proof'},r.message),el('details',{},el('summary',{},'Verified local address policy'),el('pre',{class:'policy-code'},r.policy)),el('p',{},r.notice),button('Sign reviewed message','',async()=>{if(messageReview!==r.id)throw Error('Message changed. Review it again.');messageReview=null;const result=await api('message/sign',{id:r.id});$('#message-review-box').replaceChildren();const text=el('textarea',{rows:'5',readonly:'',class:'public-proof','aria-label':result.complete?'Public message signature':'Partial message proof PSBT'});text.value=result.complete?result.signature:result.psbt;$('#message-result').replaceChildren(el('section',{class:'server-card result-card'},el('h2',{},result.complete?'Message signature ready':'Partial message proof'),el('p',{},result.complete?result.notice:result.message),!result.complete?el('p',{},result.signatures_present+' of '+result.required+' valid signatures collected.'):null,text,el('p',{class:'hint'},'Select and copy the public result deliberately. It is not stored by this page. A recipient needs a compatible BIP-322 verifier.')));})));
}));
