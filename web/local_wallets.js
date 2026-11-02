'use strict';
let localWalletLoading=false;
function localWalletIcon(kind){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
 for(const[k,v]of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(k,v);
 path.setAttribute('d',kind==='eye'?'M2 12c5-9 15-9 20 0-5 9-15 9-20 0Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z':'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7');svg.append(path);return svg;
}
async function confirmLocalWalletDeletion(wallet){
 const r=await api('authorise/delete-wallet-review',{wallet}),status=el('p',{role:'alert',class:'warning'}),dialog=el('dialog',{class:'wallet-delete-dialog','aria-labelledby':'wallet-delete-title'}),yes=button('Yes','delete-yes',async()=>{yes.disabled=true;try{const result=await api('authorise/delete-wallet',{token:r.token,confirmed:true});dialog.close();dialog.remove();notify({message:result.message});await window.loadLocalWallets();}catch(error){status.textContent=error.message+' Close this dialogue and refresh before trying again.';}}),no=button('No','delete-no',()=>{dialog.close();dialog.remove();});
 dialog.append(el('h2',{id:'wallet-delete-title'},'Delete this local wallet?'),el('strong',{},r.wallet),el('p',{},pipe(r.sats)),el('p',{},r.private_keys_enabled?'This wallet contains private signing keys. Deleting it can make funds inaccessible unless another usable copy exists.':'This is a watch-only wallet. Deleting it removes its local descriptors, addresses, labels and transaction history; it does not delete signing keys.'),el('p',{},'Only this node’s wallet file is deleted. Other nodes and discs are unchanged. No automatic backup is made. Are you sure?'),status,el('div',{class:'actions'},yes,no));
 dialog.addEventListener('cancel',()=>dialog.remove());document.body.append(dialog);dialog.showModal();no.focus();
}
window.loadLocalWallets=async function(){
 if(localWalletLoading)return;localWalletLoading=true;const list=$('#local-wallets-list');
 try{
  const result=await api('authorise/local-wallets',{});
  list.replaceChildren(...result.wallets.map((r,index)=>{const card=el('article',{class:'wallet-card local-wallet-card',style:'--wallet-hue:'+((index*137.508+160)%360)}),heading=el('h3',{},r.wallet);if(r.private_keys_enabled===false){const eye=el('span',{class:'wallet-eye',title:'Watch-only wallet','aria-label':'Watch-only wallet'},localWalletIcon('eye'));heading.append(eye);}const bin=button('','wallet-delete-bin',()=>confirmLocalWalletDeletion(r.wallet));bin.append(localWalletIcon('bin'));bin.setAttribute('aria-label','Delete local wallet '+r.wallet);bin.disabled=!r.deletable;bin.title=r.reason||'Delete this local wallet';card.append(heading,el('p',{},r.sats===null?'Balance unavailable':pipe(r.sats)),bin);if(r.reason)card.append(el('small',{class:'hint'},r.reason));return card;}));
  if(!result.wallets.length)list.append(el('p',{},'No wallets are currently loaded on this node.'));
 }catch(error){list.replaceChildren(el('p',{class:'warning',role:'status'},error.message));}finally{localWalletLoading=false;}
};
$('#local-wallets-refresh').addEventListener('click',()=>run(window.loadLocalWallets));

window.updateLocalWalletsState=function(w){if(!w.connected||w.recovery?.active)for(const dialog of document.querySelectorAll('.wallet-delete-dialog')){dialog.close();dialog.remove();}};
