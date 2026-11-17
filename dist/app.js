import {api,account,can,initializeAuth,renderAccounts} from './auth.js';
import {fields,sampleData,validateCSV,filterRecords,calculate,trend,group,csv} from './analytics.js';
const $=s=>document.querySelector(s),esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let records=[],imported=false,current=[],criteria;const colors=['#3e7c5b','#91ad77','#c3cf9f','#d9c89e','#94b4b0'];

// Populate dashboard filters from authorized records and label the current dataset source.
function options(){for(const key of ['subject','deweyClass','resourceId','format']){const select=$(`#filters [name=${key}]`);select.innerHTML=`<option value="">All ${key==='resourceId'?'resources':key==='deweyClass'?'classes':key==='subject'?'subjects':'formats'}</option>`+[...new Set(records.map(r=>r[key]))].sort().map(v=>`<option value="${esc(v)}">${esc(key==='resourceId'?records.find(r=>r.resourceId===v).title:v)}</option>`).join('');}$('#dataset-label').textContent=imported?'Your imported dataset':'Exploring sample data';}
// Sort grouped counts and scale each horizontal bar against the largest count.
function bars(id,values,chronological=false){const sorted=Object.entries(values).sort(chronological?((a,b)=>a[0].localeCompare(b[0])):((a,b)=>b[1]-a[1]));const max=Math.max(...sorted.map(x=>x[1]),1);$(id).innerHTML=sorted.map(([key,n],i)=>`<div class="bar-row"><div class="bar-title"><span>${esc(key)}</span><b>${n.toLocaleString()}</b></div><div class="bar-track"><div class="bar-fill" style="width:${n/max*100}%;background:${colors[i%colors.length]}"></div></div></div>`).join('');}
// Calculate KPI cards and render all dashboard charts from the same filtered record set.
function render(){const k=calculate(current);$('#total').textContent=k.total.toLocaleString();$('#readers').textContent=k.readers.toLocaleString();$('#rate').textContent=k.rate===null?'N/A':k.rate.toFixed(1)+'%';$('#empty').hidden=!!k.total;$('#charts').hidden=!k.total;$('#range-label').textContent=`${criteria.start} — ${criteria.end} · ${k.total.toLocaleString()} records`;
 // Convert period counts into SVG points and labels for the borrowing trend.
 const values=trend(current,criteria.grouping),max=Math.max(...values.map(x=>x[1]),1);const w=Math.max(500,values.length*35),step=(w-50)/Math.max(values.length,1),points=values.map(([,n],i)=>`${40+i*step+step/2},${155-n/max*125}`);$('#trend').innerHTML=`<svg viewBox="0 0 ${w} 195" role="img" aria-label="Borrowing activity: ${esc(values.map(([l,n])=>l+': '+n).join(', '))}">${[0,.5,1].map(t=>`<line x1="35" x2="${w}" y1="${155-t*125}" y2="${155-t*125}" stroke="#e9eee6" stroke-dasharray="3 4"/><text x="0" y="${159-t*125}" font-size="9" fill="#9ba795">${Math.round(max*t)}</text>`).join('')}${values.length?`<polygon points="${40+step/2},155 ${points.join(' ')} ${40+(values.length-1)*step+step/2},155" fill="#eff5e9"/><polyline points="${points.join(' ')}" fill="none" stroke="#719268" stroke-width="2.5"/>`:''}${values.map(([l,n],i)=>`<circle cx="${40+i*step+step/2}" cy="${155-n/max*125}" r="3.5" fill="#fff" stroke="#719268"><title>${esc(l)}: ${n} checkouts</title></circle><text x="${40+i*step+step/2}" y="181" font-size="9" text-anchor="middle" fill="#8d9b87">${esc(criteria.grouping==='MONTHLY'?new Date(l+'-01T00:00:00Z').toLocaleDateString('en',{month:'short',timeZone:'UTC'}):l.slice(5))}</text>`).join('')}</svg>`;
 // Convert format counts into donut-chart percentages, then refresh comparison bars and the resource table.
 const formats=Object.entries(group(current,'format')).sort((a,b)=>b[1]-a[1]);let cursor=0;const stops=formats.map(([,n],i)=>{const start=cursor;cursor+=n/(k.total||1)*100;return `${colors[i%5]} ${start}% ${cursor}%`;});$('#format-chart').innerHTML=`<div class="format-wrap"><div class="donut" style="background:conic-gradient(${stops.join(',')||'#eee 0% 100%'})"><div>${formats.length}<small>formats</small></div></div><div class="format-legend">${formats.map(([name,n],i)=>`<div class="format-item"><span><i style="background:${colors[i%5]}"></i>${esc(name)}</span><b>${(n/(k.total||1)*100).toFixed(0)}%</b></div>`).join('')}</div></div>`;bars('#subjects',group(current,'subject'));bars('#segments',group(current,'userSegment'));renderTable();}
// Rank resource checkout counts and display each title’s share of filtered circulation.
function renderTable(){const counts=group(current,'resourceId'),rows=Object.entries(counts).sort((a,b)=>$('#rank').value==='most'?b[1]-a[1]:a[1]-b[1]);$('#resource-rows').innerHTML=rows.map(([id,n])=>{const r=current.find(r=>r.resourceId===id);return `<tr><td>${esc(r.title)}</td><td>${esc(r.subject)}</td><td><span class="tag">${esc(r.format)}</span></td><td><b>${n}</b></td><td>${(n/current.length*100).toFixed(1)}%</td></tr>`;}).join('')||'<tr><td colspan="5">No matching resources</td></tr>';}
// Read form selections; getAll preserves multiple selected values for comparison.
function readCriteria(form){const data=new FormData(form),c=Object.fromEntries(data);for(const key of ['subject','resourceId','userSegment','format','deweyClass'])c[key]=data.getAll(key).filter(Boolean);return c;}
// Expose loading, empty and error feedback while keeping the interface state explicit.
function dashboardState(state){$('#analytics-page').dataset.state=state;$('#dashboard-state').textContent=({LOADING:'Loading library data…',UPDATING:'Updating filters…',EMPTY:'No matching records.',ERROR:'Unable to update. Previous results are retained.'})[state]||'';}
// Validate selected filters, update the current dataset and redraw the dashboard.
function apply(){dashboardState('UPDATING');try{const next=readCriteria($('#filters'));const result=filterRecords(records,next);criteria=next;current=result;$('#message').innerHTML='';render();dashboardState(current.length?'READY':'EMPTY');}catch(e){dashboardState('ERROR');$('#message').innerHTML=`<div class="notice">${esc(e.message)} Previous results are retained.</div>`;}}
// Apply dashboard filters on submit and restore defaults when reset is clicked.
$('#filters').onsubmit=e=>{e.preventDefault();apply();};$('#clear').onclick=()=>{$('#filters').reset();if(account?.role==='faculty')$('#filters [name=subject]').value=account.subject;apply();};$('#rank').onchange=renderTable;
// Check the requested page’s capability, show its panel and load any page-specific content.
function page(name){
 const permission={overview:'explore',resources:'explore',imports:'import',accounts:'approve_accounts',reports:'reports',audit:'audit'}[name];
 if(!account || (permission&&!can(permission)))return;
 $('#analytics-page').hidden=!['overview','resources'].includes(name);
 for(const item of ['imports','accounts','reports','audit'])$(`#${item}-page`).hidden=name!==item;
 if(name==='accounts')renderAccounts();
 if(name==='reports')prepareReport();
 if(name==='audit')loadAudit();
 if(name==='imports')loadImportHistory();
 const titles={overview:'Library overview',resources:'Resource insights',imports:'Import circulation data',accounts:'Account approvals',reports:'Library usage reports',audit:'Activity history'};
 $('#page-title').textContent=titles[name];$('#breadcrumb').textContent=titles[name];
 $('#page-subtitle').textContent=({audit:'Review user access and import outcomes.',reports:'Monitor library usage through aggregate reports.',resources:'Understand resource usage to support collection decisions.',accounts:'Verify staff roles before granting access.'})[name]||'Turn everyday circulation into a clearer picture of your library.';
 $('.demo-banner').hidden=name==='audit'||name==='accounts';
 document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.page===name));
 if(name==='resources')$('.resources').scrollIntoView({behavior:'smooth',block:'start'});else window.scrollTo(0,0);
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>page(b.dataset.page));$('#import-shortcut').onclick=()=>page('imports');
// Create a temporary Blob URL, trigger a file download, then release the URL.
function download(content,name,type='text/csv'){const url=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
// Download a small example CSV and display the required import schema.
$('#template').onclick=()=>download(csv(sampleData().slice(0,3)),'pagemetrics-template.csv');$('#schema').textContent=fields.join(', ');
// Fetch authorized circulation rows, set faculty subject restrictions and apply dashboard filters.
async function loadRecords(){dashboardState('LOADING');const data=await api('/api/records');records=data.records;imported=data.imported;options();if(account?.role==='faculty'){$('#filters [name=subject]').value=account.subject;$('#filters [name=subject]').disabled=true;}else $('#filters [name=subject]').disabled=false;apply();}
// Read the selected CSV, submit it for server validation and refresh data after import.
$('#upload').onclick=async()=>{const file=$('#file').files[0],out=$('#import-result');try{if(!file||!file.name.toLowerCase().endsWith('.csv'))throw Error('Choose a CSV file first.');if(file.size>5*1024*1024)throw Error('Files must be smaller than 5 MB.');$('#upload').disabled=true;out.textContent='Validating file…';const result=await api('/api/import',{csv:await file.text()});if(result.importedCount){reportPrepared=false;await loadRecords();const dates=records.map(r=>r.checkoutDate).sort();$('#filters [name=start]').value=dates[0];$('#filters [name=end]').value=dates.at(-1);apply();}out.innerHTML=`<div class="notice ${result.importedCount?'success':''}"><b>${result.status.replaceAll('_',' ')}</b><p>${result.importedCount} imported · ${result.rejectedCount} rejected. ${result.importedCount?'Shared dataset replaced.':'Previous dataset retained.'}</p>${result.errors.map(e=>`<div>Data row ${e.row}: ${esc(e.reason)}</div>`).join('')}${result.rejectedCount>100?'<p>Showing the first 100 validation errors.</p>':''}</div>`;}catch(e){out.innerHTML=`<div class="notice">${esc(e.message)}</div>`;}finally{$('#upload').disabled=false;loadImportHistory();}};
// Request the sample dataset and refresh the dashboard with reset filters.
$('#restore').onclick=async()=>{try{await api('/api/restore',{});reportPrepared=false;$('#filters').reset();await loadRecords();$('#import-result').innerHTML='<div class="notice success">Sample dataset restored.</div>';}catch(error){$('#import-result').textContent=error.message;}};
// Download subject checkout counts from the currently filtered records.
$('#export').onclick=()=>{const summary=Object.entries(group(current,'subject'));download('Subject,Checkouts\n'+summary.map(([s,n])=>'"'+s.replaceAll('"','""')+'",'+n).join('\n'),'pagemetrics-subject-summary.csv');};
// Load the appropriate dashboard after authentication and clear data from any previous account.
document.addEventListener('pagemetrics:login',async()=>{reportPrepared=false;records=[];current=[];$('#message').textContent='';$('#filters').reset();if(can('explore')){page('overview');try{await loadRecords();}catch(error){dashboardState('ERROR');$('#message').textContent=error.message;}}else if(can('reports'))page('reports');});
// Invalidate pending report responses and clear all account-specific data from the browser.
document.addEventListener('pagemetrics:logout',()=>{dashboardState('CLOSED');reportRequest++;report=null;reportPrepared=false;records=[];current=[];$('#import-result').textContent='';$('#account-list').replaceChildren();$('#audit-list').replaceChildren();$('#report-kpis').replaceChildren();for(const key of ['months','formats','subjects','segments','resources'])$('#report-'+key).replaceChildren();$('#file').value='';});
let report=null,reportPrepared=false,reportRequest=0;
// Request filtered aggregates; ignore older responses when a newer request has started.
async function loadReport(){
 // A sequence number prevents a slower previous response from replacing newer results.
 const request=++reportRequest;$('#export-report').disabled=true;$('#report-message').textContent='Loading report…';
 try{const params=new URLSearchParams();for(const [key,value] of Object.entries(readCriteria($('#report-filters')))){for(const item of Array.isArray(value)?value:[value])if(item)params.append(key,item);}const result=await api('/api/reports?'+params);if(!can('reports')||request!==reportRequest)return;report=result;
 $('#dataset-label').textContent=report.imported?'Shared imported dataset':'Exploring sample data';
 $('#report-period').textContent=report.dateFrom?`${report.dateFrom} — ${report.dateTo} · Matching circulation data`:'No circulation data available';
 $('#report-kpis').innerHTML=[['Total checkouts',report.totalCheckouts],['Unique readers',report.uniqueReaders],['Resources used',report.resourcesUsed],['On-time return rate',report.onTimeRate===null?'N/A':report.onTimeRate.toFixed(1)+'%']].map(([label,value])=>`<article class="panel"><p>${label}</p><strong>${esc(typeof value==='number'?value.toLocaleString():value)}</strong></article>`).join('');
 for(const key of ['months','formats','subjects','segments','resources'])bars('#report-'+key,report[key],key==='months');
 $('#report-message').textContent=report.totalCheckouts?'':'No circulation data available.';$('#export-report').disabled=false;
 }catch(error){if(request!==reportRequest)return;$('#report-message').textContent=error.message+(report?' Previous results are retained.':'');$('#export-report').disabled=!report;}
}
// Refresh the server-generated aggregate report.
$('#refresh-report').onclick=loadReport;
// Export the active report with its applied filter criteria.
$('#export-report').onclick=()=>{if(!can('reports')||!report)return;const rows=[['Metric','Value'],['Total checkouts',report.totalCheckouts],['Unique readers',report.uniqueReaders],['Resources used',report.resourcesUsed],['On-time return rate (%)',report.onTimeRate??'N/A'],['Applied criteria',JSON.stringify(report.criteria)],['Period start',report.dateFrom??''],['Period end',report.dateTo??'']];for(const key of ['months','formats','subjects','segments','resources'])for(const [label,count] of Object.entries(report[key]))rows.push([key+' / '+label,count]);download(rows.map(row=>row.map(value=>'"'+String(value).replaceAll('"','""')+'"').join(',')).join('\n'),'pagemetrics-library-report.csv');};
// Load authorized filter choices and initialize the reporting view.
async function prepareReport(){
 if(!reportPrepared){
 try{const {options}=await api('/api/report-options');
 $('#report-filter-fields').innerHTML='<label>From<input name="start" type="date"></label><label>To<input name="end" type="date"></label>'+Object.entries(options).map(([key,values])=>`<label>${esc({subject:'Subjects',resourceId:'Resources',userSegment:'Reader groups',deweyClass:'Dewey classes',format:'Formats'}[key])}<select name="${key}" multiple size="3">${values.map(value=>`<option value="${esc(value.value??value)}">${esc(value.label??value)}</option>`).join('')}</select></label>`).join('')+'<label>Time grouping<select name="grouping"><option value="MONTHLY">Monthly</option><option value="WEEKLY">Weekly</option><option value="DAILY">Daily</option><option value="SEASONAL">Seasonal</option></select></label>';
 if(account?.role==='faculty'){const select=$('#report-filters [name=subject]');select.value=account.subject;select.disabled=true;}
 reportPrepared=true;
 }catch(error){$('#report-message').textContent=error.message;return;}}
 await loadReport();
}
// Submit report criteria for server-side validation and aggregation.
$('#report-filters').onsubmit=event=>{event.preventDefault();loadReport();};
$('#report-reset').onclick=()=>{$('#report-filters').reset();loadReport();};
// Display the server’s recent import results and state transitions.
async function loadImportHistory(){
 if(!can('import_history'))return;
 try{const {jobs}=await api('/api/import-history');const html=jobs.map(job=>`<div class="history-item"><b>Import #${job.id} · ${esc(job.state)}</b><p>${esc(job.states.join(' → '))}</p><small>${job.imported_count} imported · ${job.rejected_count} rejected</small></div>`).join('')||'<p>No imports yet.</p>';$('#import-history').innerHTML=html;$('#admin-import-history').innerHTML=html;}catch(error){$('#import-history').textContent=error.message;$('#admin-import-history').textContent=error.message;}
}
let auditOffset=0;
// Fetch and display administrator audit events, optionally appending the next page.
async function loadAudit(append=false){
 if(!can('audit'))return;
 if(!append){auditOffset=0;$('#audit-list').replaceChildren();}
 try{const {events,nextOffset}=await api('/api/audit?offset='+auditOffset);$('#audit-list').insertAdjacentHTML('beforeend',events.map(item=>`<div class="history-item"><b>${esc(item.event)} · ${esc(item.outcome)}</b><p>${esc(new Date(item.occurred_at*1000).toLocaleString())} · ${esc(item.actor_role)} · Account ${item.actor_id??'unknown'}</p><small>${esc(item.details)}</small></div>`).join('')||'<p>No activity recorded.</p>');auditOffset=nextOffset;$('#audit-more').hidden=nextOffset===null;if(!append)loadImportHistory();}catch(error){$('#audit-list').textContent=error.message;}
}
$('#audit-refresh').onclick=()=>loadAudit();$('#audit-more').onclick=()=>loadAudit(true);
initializeAuth();
