/* Text-first rendering: user HTML is never interpreted. KaTeX runs with trust off. */
function renderStudyText(element,text){
 element.replaceChildren();const chunks=String(text||'').split(/(```[\s\S]*?```)/g);
 for(const chunk of chunks){if(chunk.startsWith('```')){const block=document.createElement('pre'),code=document.createElement('code'),newline=chunk.indexOf('\n');code.textContent=chunk.slice(newline>=0?newline+1:3,-3);block.append(code);element.append(block);}else{const span=document.createElement('span');span.textContent=chunk;element.append(span);}}
 if(typeof renderMathInElement==='function')renderMathInElement(element,{delimiters:[{left:'$$',right:'$$',display:true},{left:'\\[',right:'\\]',display:true},{left:'\\(',right:'\\)',display:false},{left:'$',right:'$',display:false}],throwOnError:false,trust:false,strict:'ignore',maxExpand:500,maxSize:20});
}
function renderRichContent(root=document){root.querySelectorAll('.ai-message-text,.workspace-ai-message p,.material-condition,.subject-config p').forEach(el=>{if(el.dataset.richRendered)return;el.dataset.richRendered='1';renderStudyText(el,el.textContent);});}
document.addEventListener('DOMContentLoaded',()=>{const observer=new MutationObserver(()=>renderRichContent());observer.observe(document.getElementById('content'),{childList:true,subtree:true});observer.observe(document.getElementById('modalBody'),{childList:true});});
