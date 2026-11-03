'use strict';
window.visibleApprovals=function(rows){
 const group=$('#approval-filter').value||'all',query=($('#approval-search').value||'').trim().toLocaleLowerCase();
 const kinds={signing:['sign_psbt_partial','broadcast_transaction'],setup:['wallet_setup','wallet_setup_policy','builder_cancel'],archive:['archive_wallet','archive_cancel','destroy_disc']};
 return rows.filter(p=>{const matches=group==='all'||(group==='management'?!Object.values(kinds).flat().includes(p.kind):kinds[group]?.includes(p.kind));return matches&&(!query||(kindTitle(p.kind)+' '+(p.wallet_name||'')).toLocaleLowerCase().includes(query));});
};
window.updateAuthoriseLayout=function(w){
 const needs=w.pending.filter(p=>p.state==='pending').length,staged=w.pending.filter(p=>p.state==='staged').length,setups=w.setups?.length||0;
 $('#authorise-summary').replaceChildren(...[[needs,'Awaiting review'],[staged,'Staged backups'],[setups,'Setups in progress']].map(([n,label])=>el('article',{},el('strong',{},String(n)),el('span',{},label))));
 $('#queue-count').textContent=String(w.pending.length);$('#authorise-setups').hidden=!setups;
 $('#denial-count').textContent=String((w.exclusions?.length||0)+(w.denied?.length||0)+(w.obsolete_sync_denials?.length||0));
};
for(const [id,event] of [['#approval-search','input'],['#approval-filter','change']])$(id).addEventListener(event,()=>{approvalSignature='';if(workspace)renderApprovals();});
