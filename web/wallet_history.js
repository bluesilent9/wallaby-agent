'use strict';
let walletHistoryView=null;
function closeWalletHistory(){const old=walletHistoryView;if(!old)return;walletHistoryView=null;old.dialog.close();old.dialog.remove();old.card?.classList.remove('wallet-history-selected');old.card?.focus?.({preventScroll:true});}
function walletCopyIcon(){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('aria-hidden','true');path.setAttribute('d','M9 9h11v12H9zM15 9V3H3v12h6');svg.append(path);return svg;}
function walletCopyButton(value,kind){const b=el('button',{type:'button',class:'wallet-history-copy','aria-label':'Copy '+kind,title:'Copy '+kind},walletCopyIcon());b.addEventListener('click',async event=>{event.stopPropagation();event.preventDefault();try{const field=el('textarea',{class:'wallet-copy-field','aria-hidden':'true',tabindex:'-1'});field.value=value;(b.closest('dialog')||document.body).append(field);let copied=false;try{field.select();copied=document.execCommand('copy');}finally{field.remove();}if(!copied)await navigator.clipboard.writeText(value);b.setAttribute('aria-label',kind+' copied');b.title='Copied';}catch(error){notify({message:'The clipboard could not copy this '+kind+'.'});}});return b;}
function walletHistoryValue(value,kind){return el('span',{class:'wallet-history-value'},el('span',{},value),walletCopyButton(value,kind));}
window.openLocalWalletHistory=async function(wallet,card){
 closeWalletHistory();const dialog=el('dialog',{class:'wallet-history-dialog','aria-label':wallet+' transaction history'}),content=el('div',{class:'wallet-history-content'}),feedback=el('p',{role:'status'},'Loading local Core history…'),close=el('button',{type:'button',class:'wallet-history-close','aria-label':'Close wallet history'},'×'),state={dialog,content,feedback,card,mode:'address',data:null};walletHistoryView=state;card?.classList.add('wallet-history-selected');close.addEventListener('click',closeWalletHistory);dialog.append(el('header',{class:'wallet-history-heading'},el('h2',{},wallet),close),content,feedback);document.body.append(dialog);dialog.addEventListener('cancel',e=>{e.preventDefault();closeWalletHistory();});dialog.addEventListener('click',e=>{if(e.target===dialog)closeWalletHistory();});dialog.showModal();
 try{const data=await api('authorise/wallet-history',{wallet});if(walletHistoryView!==state)return;state.data=data;renderLocalWalletHistory(state);}catch(error){if(walletHistoryView===state)feedback.textContent=error.message;}
};
function renderLocalWalletHistory(state){
 const data=state.data;state.content.replaceChildren();state.feedback.textContent=data.notice+' Click the table to switch between addresses and transaction IDs.';
 for(const group of data.groups){
  const body=el('tbody'),table=el('table',{class:'wallet-history-table','aria-label':group.name+' transactions',tabindex:'0'}),heading=el('thead',{},el('tr',{},...['Date UTC','Time UTC',state.mode==='address'?'Address':'TXID','Amount','Balance'].map(label=>el('th',{scope:'col'},label))));
  for(const row of group.rows){const stamp=row.timestamp?new Date(row.timestamp*1000).toISOString():null,amount=BigInt(row.amount_sats),tr=el('tr',{class:'wallet-history-row '+(amount>0n?'receive':amount<0n?'send':'neutral')}),address=el('td',{class:'wallet-history-address'});
   if(state.mode==='txid')address.append(walletHistoryValue(row.txid,'transaction ID'));
   else if(row.addresses.length>1&&amount<0n){const label=el('span',{class:'wallet-multiple-addresses',tabindex:'0'},'Multiple send addresses'),tooltip=el('span',{class:'wallet-addresses-tooltip',role:'tooltip'});for(const a of row.addresses)tooltip.append(walletHistoryValue(a,'address'));const place=()=>{if(!label.getBoundingClientRect)return;const rect=label.getBoundingClientRect();tooltip.style.left=Math.max(12,Math.min(rect.left,innerWidth-440))+'px';tooltip.style.top=Math.max(12,Math.min(rect.bottom+6,innerHeight-250))+'px';};label.addEventListener('pointerenter',place);label.addEventListener('focusin',place);label.append(tooltip);address.append(label);}
   else if(row.addresses.length)for(const a of row.addresses)address.append(walletHistoryValue(a,'address'));
   else address.append(el('span',{},'No standard Bitcoin address'));
   tr.append(el('td',{},stamp?stamp.slice(8,10)+'/'+stamp.slice(5,7)+'/'+stamp.slice(0,4):'Unknown'),el('td',{},stamp?stamp.slice(11,19):'Unknown'),address,el('td',{class:'wallet-history-bitcoin'},(amount>0n?'+':'')+pipe(row.amount_sats)),el('td',{class:'wallet-history-bitcoin'},pipe(row.balance_sats)));body.append(tr);
  }
  if(!group.rows.length)body.append(el('tr',{},el('td',{colspan:'5'},'No transactions are currently recorded for this wallet.')));
  table.append(heading,body);const toggle=()=>{state.mode=state.mode==='address'?'txid':'address';renderLocalWalletHistory(state);};table.addEventListener('click',toggle);table.addEventListener('keydown',e=>{if(e.target===table&&(e.key==='Enter'||e.key===' ')){e.preventDefault();toggle();}});
  if(data.extinct)state.content.append(el('h3',{class:'wallet-history-group'},group.name));state.content.append(el('div',{class:'wallet-history-scroll'},table));
 }
 if(!data.groups.length)state.content.append(el('p',{},'No transactions are currently recorded for this wallet.'));
}
window.closeLocalWalletHistory=closeWalletHistory;
window.watchRetirementEvidence=function(id,box){
 const panel=el('section',{class:'hint retirement-remote-evidence',role:'status'},'Checking connected Agents for optional preserved-history evidence…');box.append(panel);let attempts=0;
 const update=async()=>{if(box.isConnected===false||attempts++>50)return;try{const r=await api('authorise/retirement-evidence',{id});if(box.isConnected===false)return;panel.replaceChildren(el('p',{},r.message||'Optional history comparison'));
  if(r.state==='complete'&&r.evidence?.verified){const e=r.evidence;panel.append(el('h3',{},'Original history matches the directly connected Extinct wallet'),el('p',{},e.archive+' · '+e.address_count.toLocaleString('en-AU')+' addresses · '+e.transaction_count.toLocaleString('en-AU')+' transactions. Every record was compared.'));for(const a of e.address_samples)panel.append(el('p',{},a.address+' · '+a.label));for(const t of e.transaction_samples)panel.append(el('p',{},t.txid+' · block '+blockHeight(t.height)));}
  if(r.state==='checking'&&typeof setTimeout==='function')setTimeout(update,2000);
 }catch(error){panel.replaceChildren(el('p',{},'Optional remote evidence is unavailable. Deletion does not require a direct connection.'));}};if(typeof setTimeout==='function')setTimeout(update,0);
};
