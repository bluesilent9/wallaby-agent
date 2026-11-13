'use strict';
window.renderSidebarCounts=function(w){
 const ids={authorise:'approval',burn:'burn',peers:'peers',services:'services',message:'message',synchronisation:'sync',wallets:'wallets'};
 const fallback={authorise:(w.pending?.length||0)+(w.setups?.length||0),synchronisation:w.transfer?.pending_count||0};
 const counts=w.sidebar_counts||fallback;
 for(const [page,id] of Object.entries(ids)){
  const node=document.getElementById(id+'-count');if(!node)continue;
  let value=Number.isSafeInteger(counts[page])&&counts[page]>0?counts[page]:0;if(page==='services'&&w.cleanup_recovery)value=Math.max(1,value);node.textContent=value?value.toLocaleString('en-AU'):'';
  node.title=w.protected?.viewer?'Needs your attention':'Last protected workspace count; may change when reopened';
 }
};
