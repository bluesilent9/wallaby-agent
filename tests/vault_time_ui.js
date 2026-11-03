const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class E{constructor(tag,props,...children){this.tag=tag;this.props=props;this.children=children.flat().filter(x=>x!=null);}append(...c){this.children.push(...c);}addEventListener(){} }
const text=n=>n instanceof E?n.children.map(text).join(' '):String(n),el=(...a)=>new E(...a),node={addEventListener(){}};
const c={window:{},$:()=>node,el,initialPage:'authorise',document:{querySelector:()=>node,querySelectorAll:()=>[]}};vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8'),c);
c.el=el;
const row={height:100,first_spend_block:101,status:'estimated',utc:'2026-11-04T01:10+00:00',local:'2026-11-04T12:10+11:00',local_zone:'AEDT',source:'Local block-header timestamp average',seconds_per_block:590,sample_blocks:157788,sample_days:1077,notice:'Rough estimate only.'};
c.rows=[row];let result=text(vm.runInContext('vaultTimes(rows)',c));for(const s of ['Vault height 100','101','UTC:','AEDT','Rough estimate','Local block-header'])assert(result.includes(s));assert(!result.includes('99%'));
c.rows=[{height:100,status:'unavailable',notice:'No local headers'}];result=text(vm.runInContext('vaultTimes(rows)',c));assert(result.includes('No local headers'));assert(!result.includes('undefined'));console.log('Vault review: local header source, rough estimate, UTC/local zones, CLTV boundary and unavailable state passed.');
