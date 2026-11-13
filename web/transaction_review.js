'use strict';
(() => {
 const paths={wallet:'M20 8V5a1 1 0 0 0-1-1H6a3 3 0 0 0 0 6h14v10H6a3 3 0 0 1-3-3V7m17 6h-5v4h5m-3-2h.01',vault:'M4 3h16v18H4Zm4 4h8v10H8Zm4 3v4m-2-2h4M6 6h.01M6 18h.01',multisig:'M8 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM8 6h14m-3 0v3m-4-3v2M8 17a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm0 0h14m-3 0v3m-4-3v2',watch:'M2 12c5-9 15-9 20 0-5 9-15 9-20 0Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',disc:'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM5 8l3-3m8 14 3-3'};
 paths.smsf='M16 3a2 2 0 1 1-4 0 2 2 0 0 1 4 0ZM13 6c-3-1-6 2-6 6l3 3-2 7m3-8 3 3 1 5M9 9l5 3h4m0 10V12a1.5 1.5 0 0 1 3 0';
 paths.extinct='M2 42C19 44 24 36 39 32C50 27 61 32 69 34L78 23 81 16 97 10 114 14 123 23 122 34 114 34 111 31 108 35 104 31 100 35 96 31 92 33 100 39 112 39 117 36 115 44 101 47 90 43 83 52 78 58 86 63 91 62 92 66 89 70 85 69 83 66 74 64 69 68 65 75 67 82 78 84 80 89 62 89 57 78 59 66 52 67 46 78 42 84 48 85 50 89 29 89 30 84 36 80 38 69 44 59C33 56 23 54 14 50ZM96 20a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8Z';
 const labels={wallet:'Wallet · transaction input or output; names and properties are identified locally when available',vault:'Vault · mandatory block-height policy verified locally; this icon does not indicate whether its height has been reached',multisig:'Multisig · the local public policy requires more than one signature',watch:'Watch only · no private signing account for this address is available on this Agent',disc:'Disc · a local copy is loaded from an archival disc'};
 labels.smsf='SMSF · wallet name contains SMSF';labels.extinct='Extinct historical wallet';
 window.walletCardIcons=function(traits={},order=['wallet','vault','multisig','watch','disc']){
  const strip=el('div',{class:'wallet-card-icons','aria-label':'Locally verified wallet properties'});
  for(const name of order){
   if(name!=='wallet'&&traits[name]!==true)continue;
   const slot=el('span',{class:'wallet-card-icon',title:labels[name],'aria-label':labels[name],tabindex:'0','data-wallet-icon':name});
   const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
   for(const[k,v]of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(k,v);
   if(name==='extinct'){svg.setAttribute('viewBox','0 0 132 96');svg.setAttribute('fill','currentColor');svg.setAttribute('stroke','none');}path.setAttribute('d',paths[name]);svg.append(path);slot.append(svg);strip.append(slot);
  }
  return strip;
 };
 window.syncWalletIcons=traits=>{const strip=window.walletCardIcons(traits,['wallet','smsf','vault','multisig','extinct','disc']);strip.setAttribute('aria-label','Wallet and source properties; discovery hints are checked during review');for(const icon of strip.children){const name=icon.getAttribute('data-wallet-icon');if(name==='disc'){icon.title='Disc · source Agent reports a disc-loaded wallet; checked against its signed review';icon.setAttribute('aria-label',icon.title);}}return strip;};
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
   const broadcast=row.kind==='broadcast_transaction',error=broadcast&&row.status==='error',heading=error?'Broadcast needs attention':broadcast?(row.state==='acknowledged'?'Wallet Server acknowledged broadcast':'Core confirmed broadcast · waiting for Wallet Server'):(row.state==='acknowledged'?'Wallet Server acknowledged signed transaction':'Signed · waiting for Wallet Server');
   const message=error?row.message:broadcast?'The completed transaction was submitted or independently found on Core. Continue tracking its TXID on Wallet Server.':row.state==='acknowledged'?'Wallet Server acknowledged receipt of this signing result. Continue in Transaction Builder. No transaction was broadcast by signing.':'The signature result is queued in this protected workspace. Keep it open. The Agent retries delivery of this same result; do not sign again.';
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
