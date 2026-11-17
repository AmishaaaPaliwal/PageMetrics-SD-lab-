export const fields=['circulationId','checkoutDate','returnDate','returnStatus','resourceId','title','subject','deweyClass','format','anonymizedReaderId','userSegment'];
export const statuses=['NOT_RETURNED','RETURNED_ON_TIME','RETURNED_LATE','UNKNOWN'];
export function parseCSV(text){
 const rows=[];let row=[],cell='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(quoted||cell==='')quoted=!quoted;else throw Error('Invalid CSV quoting.');}else if(c===','&&!quoted){row.push(cell);cell='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);if(row.some(x=>x.trim()))rows.push(row);row=[];cell='';}else cell+=c;}
 if(quoted)throw Error('Unclosed quoted field.');row.push(cell);if(row.some(x=>x.trim()))rows.push(row);return rows;
}
export function validDate(s){return /^\d{4}-\d{2}-\d{2}$/.test(s)&&!isNaN(Date.parse(s))&&new Date(s).toISOString().slice(0,10)===s;}
export function validateCSV(text){
 const rows=parseCSV(text.replace(/^\uFEFF/,''));if(rows.length<2)throw Error('INVALID_FILE: Include a header and at least one record.');
 const headers=rows.shift().map(x=>x.trim());
 if(headers.some(x=>!fields.includes(x)))throw Error('PRIVACY_REJECTED: Only template columns are accepted. Remove personal or unrecognized columns.');
 if(new Set(headers).size!==headers.length||fields.some(x=>!headers.includes(x)))throw Error('INVALID_FILE: Required columns are missing or duplicated.');
 const accepted=[],errors=[],seen=new Set();rows.forEach((cells,i)=>{const r=Object.fromEntries(headers.map((h,j)=>[h,(cells[j]||'').trim()]));let reason='';
 if(cells.length!==headers.length)reason='Incorrect column count';
 else if(fields.some(k=>k!=='returnDate'&&!r[k]))reason='Required field is empty';
 else if(!validDate(r.checkoutDate))reason='Invalid checkout date';
 else if(r.returnDate&&(!validDate(r.returnDate)||r.returnDate<r.checkoutDate))reason='Invalid return date or return before checkout';
 else if(!statuses.includes(r.returnStatus))reason='Invalid return status';
 else if(!['STUDENT','FACULTY','STAFF'].includes(r.userSegment))reason='Invalid user segment';
 else if(!['Print','E-book','Journal','Audio','Media'].includes(r.format))reason='Invalid resource format';
 else if(!/^anon-[a-zA-Z0-9_-]+$/.test(r.anonymizedReaderId))reason='Reader ID must be an anonymous token beginning anon-';
 else if(seen.has(r.circulationId))reason='Duplicate circulation ID';
 if(reason)errors.push({row:i+1,reason});else{seen.add(r.circulationId);accepted.push(r);}});
 return {accepted,errors,status:!accepted.length?'REJECTED':errors.length?'PARTIAL_SUCCESS':'SUCCESS'};
}
export function filterRecords(records,c){if(!validDate(c.start)||!validDate(c.end)||c.start>c.end)throw Error('Start date must be on or before end date.');return records.filter(r=>r.checkoutDate>=c.start&&r.checkoutDate<=c.end&&['subject','deweyClass','resourceId','userSegment','format'].every(k=>Array.isArray(c[k])?(!c[k].filter(Boolean).length||c[k].includes(r[k])):(!c[k]||r[k]===c[k])));}
export function group(records,key){return records.reduce((a,r)=>(a[r[key]]=(a[r[key]]||0)+1,a),{});}
export function calculate(records){const returned=records.filter(r=>['RETURNED_ON_TIME','RETURNED_LATE'].includes(r.returnStatus));return {total:records.length,readers:new Set(records.map(r=>r.anonymizedReaderId)).size,rate:returned.length?100*returned.filter(r=>r.returnStatus==='RETURNED_ON_TIME').length/returned.length:null};}
export function trend(records,mode){const counts={};for(const r of records){let label=r.checkoutDate;const d=new Date(label+'T00:00:00Z');if(mode==='MONTHLY')label=label.slice(0,7);else if(mode==='WEEKLY'){d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));label=d.toISOString().slice(0,10);}else if(mode==='SEASONAL'){const m=d.getUTCMonth();label=`${d.getUTCFullYear()} · ${['01 Winter','02 Spring','03 Summer','04 Autumn'][Math.floor(m/3)]}`;}counts[label]=(counts[label]||0)+1;}return Object.entries(counts).sort(([a],[b])=>a.localeCompare(b));}
export function sampleData(){const subjects=['Computer Science','Literature','Engineering','Mathematics','Natural Sciences','History'];const titles=['Introduction to Algorithms','The Great Gatsby','Engineering Mechanics','Linear Algebra Done Right','A Brief History of Time','The Discovery of India','Clean Code','Pride and Prejudice','The Design of Everyday Things','Calculus','The Selfish Gene','Sapiens'];return Array.from({length:864},(_,i)=>{const n=(i*37)%270;const date=new Date(Date.UTC(2026,0,1+n));const returned=i%7!==0;return {circulationId:`C-${i+1}`,checkoutDate:date.toISOString().slice(0,10),returnDate:returned?new Date(+date+86400000*(5+i%16)).toISOString().slice(0,10):'',returnStatus:returned?(i%9===0?'RETURNED_LATE':'RETURNED_ON_TIME'):'NOT_RETURNED',resourceId:`R-${i%12}`,title:titles[i%12],subject:subjects[i%6],deweyClass:['005','800','620','510','500','900'][i%6],format:['Print','Print','E-book','Journal','Print','Audio','E-book'][i%7],anonymizedReaderId:`anon-${(i*13)%217}`,userSegment:['STUDENT','STUDENT','STUDENT','FACULTY','STAFF'][i%5]};});}
export function csv(rows){return [fields,...rows.map(r=>fields.map(k=>r[k]))].map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\n');}
