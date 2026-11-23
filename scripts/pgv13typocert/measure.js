// Independent acceptance oracle; does not change the product's overflow gate.
function assess(m) {
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 const valid=r=>r&&['scrollWidth','clientWidth','scrollHeight','clientHeight'].every(k=>finite(r[k])&&r[k]>0);
 if(!valid(m.outer)||!valid(m.slot)||![m.footerTop,m.contentBottom,m.minTextPt].every(finite))return {passed:false,reason:'missing_measurements'};
 const over=r=>r.scrollWidth>r.clientWidth+1||r.scrollHeight>r.clientHeight+1;
 const outer_guard_accepts=!over(m.outer),internal_overflow=over(m.slot),footer_collision=m.contentBottom>m.footerTop+1;
 return {passed:!outer_guard_accepts||(!internal_overflow&&!footer_collision&&m.minTextPt>=8-0.01),
   outer_guard_accepts,internal_overflow,footer_collision,legible:m.minTextPt>=8-0.01};
}
// Executed read-only inside the renderer page. No DOM mutations or network I/O.
function measureDocument() {
 const surface=document.querySelector('[data-testid="print-page-surface"]');
 const target=surface.querySelector('[data-testid="print-probe-content"]')||surface;
 const frame=target.querySelector('[data-testid="print-page-body"]');
 const footer=frame.querySelector('[data-testid="print-footer"]');
 const slot=[...frame.children].find(el=>el.tagName==='DIV');
 const metrics=el=>({scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight});
 const visible=[...slot.children].filter(el=>getComputedStyle(el).display!=='none');
 const text=[];const walker=document.createTreeWalker(target,NodeFilter.SHOW_TEXT);
 while(walker.nextNode()) {
   const n=walker.currentNode,el=n.parentElement;if(!n.textContent.trim()||['STYLE','SCRIPT'].includes(el.tagName))continue;
   const r=document.createRange();r.selectNodeContents(n);const rect=r.getBoundingClientRect();
   if(rect.width<=0||rect.height<=0)continue;
   text.push({pt:parseFloat(getComputedStyle(el).fontSize)*72/300,text:n.textContent.trim().slice(0,60)});
 }
 return {outer:metrics(target),slot:metrics(slot),footerTop:footer.getBoundingClientRect().top,
   contentBottom:Math.max(slot.getBoundingClientRect().top,...visible.map(el=>el.getBoundingClientRect().bottom)),
   minTextPt:Math.min(...text.map(t=>t.pt)),text_nodes:text.length,
   bodyFontPx:parseFloat(getComputedStyle(target.querySelector('table')).fontSize),
   pageWidth:target.clientWidth,pageHeight:target.clientHeight};
}
module.exports={assess,measureDocument};
