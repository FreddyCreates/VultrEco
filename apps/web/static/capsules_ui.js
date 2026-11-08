/* Real CAPSULA file-capable disposable-computer desk, single-admin lane. */
'use strict';
async function loadCapsules(){
  await refreshWorkspaces();
  await refreshAgentCache();
  const select=document.getElementById('capsule-workspace');
  const active=select.value;
  select.innerHTML=workspaceCache.map(w=>'<option value="'+esc(w.slug)+'">'+esc(w.slug)+'</option>').join('');
  if(workspaceCache.some(w=>w.slug===active))select.value=active;
  const agent=document.getElementById('capsule-agent'),keep=agent.value;
  agent.innerHTML='<option value="">Operator-created capsule</option>'+
    agentsCache.filter(a=>a.status==='active'&&a.workspace===select.value&&a.capabilities.includes('python'))
      .map(a=>'<option value="'+esc(a.id)+'">'+esc(a.name)+'</option>').join('');
  if(agentsCache.some(a=>a.id===keep))agent.value=keep;
  await refreshCapsuleList();
}
async function refreshCapsuleList(){
  const workspace=document.getElementById('capsule-workspace').value;
  const list=document.getElementById('capsule-list');
  if(!workspace){list.innerHTML=empty('Create a workspace to begin.');return;}
  const tasks=await api('capsules?'+query({workspace}));
  list.innerHTML=tasks.length?tasks.map(c=>'<article class="list-row" style="display:block">'+
    '<div class="status-row"><strong>'+esc(c.title)+'</strong>'+statusTag(c.state)+'</div>'+
    '<small>'+esc(c.id)+' · '+esc(c.cleanup)+'</small><div class="inline-actions">'+
    (c.state==='draft'?'<button class="small-btn" data-capsule-action="execute" data-capsule-id="'+esc(c.id)+'">Run isolated computer</button>':'')+
    '<button class="small-btn" data-capsule-action="inspect" data-capsule-id="'+esc(c.id)+'">View outputs</button>'+
    (c.state!=='running'?'<button class="small-btn" data-capsule-action="discard" data-capsule-id="'+esc(c.id)+'">Discard</button>':'')+
    '</div></article>').join(''):empty('No capsules yet. Define Python code and optional project files.');
}
async function inspectCapsule(id){
  const c=await api('capsules/'+encodeURIComponent(id)),pane=document.getElementById('capsule-result');
  pane.innerHTML='<h3>'+esc(c.title)+'</h3><div class="status-row"><span>State</span>'+statusTag(c.state)+'</div>'+
    '<div class="status-row"><span>Container destruction</span>'+statusTag(c.cleanup)+'</div>'+
    '<div class="status-row"><span>Worker</span><strong>'+esc(c.worker_id||'Unassigned')+'</strong></div>'+
    (c.reason?'<p class="errorline">'+esc(c.reason)+'</p>':'')+
    '<p class="small muted">Standard output</p><pre class="preline">'+esc(c.stdout||'(none)')+'</pre>'+
    (c.stderr?'<p class="small muted">Diagnostics</p><pre class="preline">'+esc(c.stderr)+'</pre>':'')+
    '<div class="subhead">Verified downloadable files</div>'+
    ((c.artifacts||[]).map(a=>'<div class="status-row"><span>'+esc(a.name)+' · '+a.bytes+' bytes</span>'+
      '<button class="small-btn" data-capsule-action="download" data-capsule-id="'+esc(c.id)+
      '" data-capsule-file="'+esc(a.name)+'">Download ↧</button></div>').join('')||
      empty('No output files. Write to /outputs inside your capsule to save results.'));
}
async function downloadCapsule(id,name){
  const route='/api/capsules/'+encodeURIComponent(id)+'/outputs/'+name.split('/').map(encodeURIComponent).join('/');
  const response=await fetch(route,{headers:{Authorization:'Bearer '+apiKey}});
  if(!response.ok)throw Error('Download rejected ('+response.status+')');
  const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');
  a.href=url;a.download=name.split('/').pop();document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),2000);
}
submitForm('#capsule-form',async form=>{
  const values=formBody(form),payload={
    workspace:values.workspace,title:values.title,code:values.code,
    input_paths:values.input_paths.split('\n').map(x=>x.trim()).filter(Boolean),
    agent_id:values.agent_id||''};
  const created=await api('capsules',{method:'POST',body:JSON.stringify(payload)});
  form.elements.title.value='';form.elements.code.value='';form.elements.input_paths.value='';
  notify('Capsule prepared. Execution requires an approved isolated worker.');
  await refreshCapsuleList();await inspectCapsule(created.id);
});
document.getElementById('capsule-workspace').addEventListener('change',()=>loadCapsules().catch(e=>notify(e.message,true)));
document.getElementById('capsules-refresh').onclick=()=>loadCapsules().catch(e=>notify(e.message,true));
document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-capsule-action]');if(!b)return;
  b.disabled=true;const action=b.dataset.capsuleAction,id=b.dataset.capsuleId;
  try{
    if(action==='execute'){
      const c=await api('capsules/'+encodeURIComponent(id)+'/execute',{method:'POST'});
      notify(c.state==='completed'?'Worker returned verified output':c.reason||'Capsule finished');
      await inspectCapsule(id);await refreshCapsuleList();
    }else if(action==='inspect')await inspectCapsule(id);
    else if(action==='download')await downloadCapsule(id,b.dataset.capsuleFile);
    else if(action==='discard'){
      if(!confirm('Discard encrypted capsule inputs, results and downloads?'))return;
      await api('capsules/'+encodeURIComponent(id),{method:'DELETE'});
      document.getElementById('capsule-result').textContent='Capsule discarded.';
      await refreshCapsuleList();
    }
  }catch(e){notify(e.message,true)}finally{b.disabled=false}
});
