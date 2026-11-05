'use strict';
(() => {
 const paths={wallet:'M20 8V5a1 1 0 0 0-1-1H6a3 3 0 0 0 0 6h14v10H6a3 3 0 0 1-3-3V7m17 6h-5v4h5m-3-2h.01',vault:'M4 3h16v18H4Zm4 4h8v10H8Zm4 3v4m-2-2h4M6 6h.01M6 18h.01',multisig:'M8 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM8 6h14m-3 0v3m-4-3v2M8 17a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm0 0h14m-3 0v3m-4-3v2',watch:'M2 12c5-9 15-9 20 0-5 9-15 9-20 0Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',disc:'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM5 8l3-3m8 14 3-3'};
 const labels={wallet:'Wallet · transaction input or output; names and properties are identified locally when available',vault:'Vault · mandatory block-height policy verified locally; this icon does not indicate whether its height has been reached',multisig:'Multisig · the local public policy requires more than one signature',watch:'Watch only · no private signing account for this address is available on this Agent',disc:'Disc · a local copy is loaded from an archival disc'};
 window.walletCardIcons=function(traits={}){
  const strip=el('div',{class:'wallet-card-icons','aria-label':'Locally verified wallet properties'});
  for(const name of ['wallet','vault','multisig','watch','disc']){
   if(name!=='wallet'&&traits[name]!==true)continue;
   const slot=el('span',{class:'wallet-card-icon',title:labels[name],'aria-label':labels[name],tabindex:'0','data-wallet-icon':name});
   const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
   for(const[k,v]of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(k,v);
   path.setAttribute('d',paths[name]);svg.append(path);slot.append(svg);strip.append(slot);
  }
  return strip;
 };
 let timer=null;
 window.transactionClock=()=>window.performance?.now?.()??Date.now();
 window.clearTransactionReviewTimer=()=>{if(timer!==null)window.clearInterval(timer);timer=null;};
 window.armTransactionReview=function({id,seconds,started,sign,box,valid,reviewAgain}){
  window.clearTransactionReviewTimer();
  const now=window.transactionClock,remaining=Number(seconds),deadline=(started??now())+Math.max(0,Math.min(600,Number.isFinite(remaining)?remaining:0))*1000;
  const digits=el('strong',{class:'transaction-countdown',role:'timer','aria-label':'Time left to authorise this transaction'}),message=el('p',{class:'hint'},'Complete authorisation within ten minutes of review. Password entry does not pause this timer.'),again=button('Review again','secondary',reviewAgain),status=el('section',{class:'transaction-review-time'});
  again.hidden=true;status.append(el('h3',{},'Transaction countdown'),digits,message,again);box.prepend(status);
  function expire(error){window.clearTransactionReviewTimer();sign.disabled=true;digits.textContent='00:00 · Review expired';status.classList.add('review-expired');message.textContent=error?.message||'The ten-minute transaction review period has expired. Review this transaction again before signing or broadcasting. No action was authorised by this timer.';message.setAttribute('role','status');again.hidden=false;}
  function tick(){if(!valid()){window.clearTransactionReviewTimer();return;}const left=Math.max(0,Math.ceil((deadline-now())/1000));digits.textContent=String(Math.floor(left/60)).padStart(2,'0')+':'+String(left%60).padStart(2,'0');if(left===0)expire();}
  tick();if(!sign.disabled)timer=window.setInterval(tick,1000);
  return {expire,current:()=>{tick();return !sign.disabled;},clear:window.clearTransactionReviewTimer};
 };
 window.renderTransactionDeliveries=function(w){
  const root=document.querySelector('#transaction-deliveries');if(!root)return;
  root.replaceChildren(...(w.transaction_deliveries||[]).map(row=>{
   const broadcast=row.kind==='broadcast_transaction',error=broadcast&&row.status==='error',heading=error?'Broadcast needs attention':broadcast?(row.state==='acknowledged'?'Dashboard acknowledged broadcast':'Core confirmed broadcast · waiting for Dashboard'):(row.state==='acknowledged'?'Dashboard acknowledged signed transaction':'Signed · waiting for Dashboard');
   const message=error?row.message:broadcast?'The completed transaction was submitted or independently found on Core. Continue tracking its TXID on Dashboard.':row.state==='acknowledged'?'Dashboard acknowledged receipt of this signing result. Continue in Transaction Builder. No transaction was broadcast by signing.':'The signature result is queued in this protected workspace. Keep it open. The Agent retries delivery of this same result; do not sign again.';
   return el('section',{class:'proof transaction-delivery',role:'status'},el('h3',{},heading),el('strong',{},row.wallet),el('p',{},message),broadcast&&row.txid?el('code',{},row.txid):null,el('small',{},'Request '+row.id.slice(0,12)));
  }));
 };
 let etaTimer=null,etaSample=null,etaStarted=0;
 window.trackDiscEta=function(b){
  if(!b||!['burning','verifying'].includes(b.phase)){etaSample=null;if(etaTimer!==null)window.clearInterval(etaTimer);etaTimer=null;return;}
  etaSample={};for(const key of ['phase','estimated_remaining_seconds','eta_waiting_for_progress','writer_status','written_bytes','total_bytes'])etaSample[key]=b[key];etaStarted=window.transactionClock();
  if(etaTimer===null&&typeof window.setInterval==='function')etaTimer=window.setInterval(()=>{const node=document.querySelector('[data-burn-eta]');if(!node||!etaSample)return;const shown={...etaSample},seconds=shown.estimated_remaining_seconds;if(seconds!==null&&seconds!==undefined)shown.estimated_remaining_seconds=Math.max(0,seconds-(window.transactionClock()-etaStarted)/1000);node.textContent=discEta(shown);},1000);
 };
})();
