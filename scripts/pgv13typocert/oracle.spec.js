const test=require('node:test'),assert=require('node:assert/strict');
const {assess}=require('./measure.js');
const base=()=>({outer:{scrollWidth:2480,clientWidth:2480,scrollHeight:3508,clientHeight:3508},
 slot:{scrollWidth:2196,clientWidth:2196,scrollHeight:3000,clientHeight:3000},
 footerTop:3190,contentBottom:3142,minTextPt:8.5});
test('control: a fitting 300 ppi page passes',()=>assert.equal(assess(base()).passed,true));
test('negative control: inner content hits footer while outer size fits',()=>{
 const m=base();m.slot.scrollHeight=3090;m.contentBottom=3232;
 assert.equal(assess(m).passed,false);assert.equal(assess(m).outer_guard_accepts,true);
});
test('negative control: internal horizontal truncation while outer size fits',()=>{
 const m=base();m.slot.scrollWidth=2300;assert.equal(assess(m).passed,false);
});
test('negative control: old 12px text at 300 ppi is unreadable',()=>{
 const m=base();m.minTextPt=12*72/300;assert.equal(assess(m).passed,false);
});
test('control: explicit outer overflow is a refusal, not a clipped success',()=>{
 const m=base();m.outer.scrollHeight=6000;m.slot.scrollHeight=6000;m.contentBottom=6200;
 assert.equal(assess(m).passed,true);assert.equal(assess(m).outer_guard_accepts,false);
});
test('negative control: missing DOM measurements cannot pass',()=>assert.equal(assess({}).passed,false));
