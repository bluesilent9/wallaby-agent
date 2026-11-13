'use strict';
// External CSS classes work under the protected viewer's strict style policy.
const cardColourNames=new Map(),cardColourOrder=Array.from({length:128},(_,i)=>i);
for(let i=cardColourOrder.length-1;i>0;i--){const n=new Uint32Array(1);crypto.getRandomValues(n);const j=n[0]%(i+1);[cardColourOrder[i],cardColourOrder[j]]=[cardColourOrder[j],cardColourOrder[i]];}
window.cardColourClass=function(key){if(!cardColourNames.has(key))cardColourNames.set(key,cardColourOrder[cardColourNames.size%cardColourOrder.length]);return 'card-colour-'+cardColourNames.get(key);};
