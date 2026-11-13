'use strict';
let localWalletLoading=false,localWalletReload=false;
function localWalletIcon(kind){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
 for(const[k,v]of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(k,v);
 path.setAttribute('d',kind==='eye'?'M2 12c5-9 15-9 20 0-5 9-15 9-20 0Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z':'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7');svg.append(path);return svg;
}
async function confirmLocalWalletDeletion(wallet){
 const r=await api('authorise/delete-wallet-review',{wallet}),status=el('p',{role:'alert',class:'warning'}),dialog=el('dialog',{class:'wallet-delete-dialog','aria-labelledby':'wallet-delete-title'}),yes=button('Yes','delete-yes',async()=>{yes.disabled=true;try{const result=await api('authorise/delete-wallet',{token:r.token,confirmed:true});dialog.close();dialog.remove();notify({message:result.message});window.requestLocalWalletRefresh?.();}catch(error){status.textContent=error.message+' Close this dialogue and refresh before trying again.';}}),no=button('No','delete-no',()=>{dialog.close();dialog.remove();});
 dialog.append(el('h2',{id:'wallet-delete-title'},'Delete this local wallet?'),el('strong',{},r.wallet),el('p',{},pipe(r.sats)),el('p',{},r.private_keys_enabled?'This wallet contains private signing keys. Deleting it can make funds inaccessible unless another usable copy exists.':'This is a watch-only wallet. Deleting it removes its local descriptors, addresses, labels and transaction history; it does not delete signing keys.'),el('p',{},'Only this node’s wallet file is deleted. Other nodes and discs are unchanged. No automatic backup is made. Are you sure?'),status,el('div',{class:'actions'},yes,no));
 dialog.addEventListener('cancel',()=>dialog.remove());document.body.append(dialog);dialog.showModal();no.focus();
}
window.loadLocalWallets=async function(){
 if(localWalletLoading){localWalletReload=true;return;}localWalletLoading=true;const list=$('#local-wallets-list');
 try{do{localWalletReload=false;try{
  const result=await api('authorise/local-wallets',{});
  if(localWalletReload)continue;
  list.replaceChildren(...result.wallets.map((r,index)=>{const card=el('article',{class:'wallet-card local-wallet-card '+window.cardColourClass('wallet:'+r.wallet)}),heading=el('h3',{},r.managed?.display_name||r.wallet);if(!window.walletCardIcons&&r.private_keys_enabled===false){const eye=el('span',{class:'wallet-eye',title:'Watch-only wallet','aria-label':'Watch-only wallet'},localWalletIcon('eye'));heading.append(eye);}card.setAttribute('tabindex','0');card.setAttribute('role','button');card.setAttribute('aria-label','Open '+r.wallet+' transaction history');card.addEventListener('click',event=>{if(!event.target.closest?.('.wallet-delete-bin'))window.openLocalWalletHistory?.(r.wallet,card);});card.addEventListener('keydown',event=>{if(event.target===card&&(event.key==='Enter'||event.key===' ')){event.preventDefault();window.openLocalWalletHistory?.(r.wallet,card);}});const bin=button('','wallet-delete-bin',()=>confirmLocalWalletDeletion(r.wallet));bin.addEventListener('click',event=>event.stopPropagation());bin.append(localWalletIcon('bin'));bin.setAttribute('aria-label','Delete local wallet '+r.wallet);bin.disabled=!r.deletable;bin.title=r.reason||'Delete this local wallet';card.append(window.walletCardIcons?.(r.traits||{}),heading,...(r.managed?[el('small',{class:'hint'},'Core account: '+r.wallet),el('p',{class:'hint'},r.managed.kind==='signer'?'Signing account · stays on its assigned Agent or disc':'Shared public policy · monitoring wallet')]:[]),el('p',{class:'local-wallet-balance'},r.sats===null?'Balance unavailable':pipe(r.sats)),bin);if(r.reason)card.append(el('small',{class:'hint'},r.reason));return card;}));
  if(!result.wallets.length)list.append(el('p',{},'No wallets are currently loaded on this node.'));
 }catch(error){if(!localWalletReload)list.replaceChildren(el('p',{class:'warning',role:'status'},error.message));}}while(localWalletReload);}finally{localWalletLoading=false;}
};
window.requestLocalWalletRefresh=function(){void window.loadLocalWallets();};

window.updateLocalWalletsState=function(w){if(!w.connected||w.recovery?.active){window.closeLocalWalletHistory?.();}if(!w.connected||w.recovery?.active)for(const dialog of document.querySelectorAll('.wallet-delete-dialog')){dialog.close();dialog.remove();}};
