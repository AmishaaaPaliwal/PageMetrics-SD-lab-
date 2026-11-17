import {test} from 'node:test';import assert from 'node:assert/strict';import {sampleData,csv,validateCSV,filterRecords,calculate,trend,validDate} from '../dist/analytics.js';
// Verify sample CSV round-trip including quoted titles.
test('sample CSV round-trip including quoted titles',()=>{const rows=sampleData().slice(0,5);rows[0].title='A, "quoted" title';assert.deepEqual(validateCSV(csv(rows)).accepted,rows);});
// Verify privacy columns rejected without echoing values.
test('privacy columns rejected without echoing values',()=>assert.throws(()=>validateCSV(csv(sampleData().slice(0,1)).replace('"title"','"email"')),/PRIVACY_REJECTED/));
// Verify duplicate and invalid rows yield partial success.
test('duplicate and invalid rows yield partial success',()=>{const rows=sampleData().slice(0,3);rows[1].circulationId=rows[0].circulationId;rows[2].checkoutDate='2026-02-30';const result=validateCSV(csv(rows));assert.equal(result.status,'PARTIAL_SUCCESS');assert.equal(result.accepted.length,1);assert.equal(result.errors.length,2);});
// Verify AND filtering with inclusive dates.
test('AND filtering with inclusive dates',()=>{const r=sampleData()[0];assert.equal(filterRecords([r],{start:r.checkoutDate,end:r.checkoutDate,subject:r.subject,userSegment:r.userSegment}).length,1);assert.equal(filterRecords([r],{start:r.checkoutDate,end:r.checkoutDate,subject:'Other'}).length,0);});
// Verify KPI rate excludes outstanding and unknown loans.
test('KPI rate excludes outstanding and unknown loans',()=>{const rows=sampleData().slice(0,4);rows.forEach((r,i)=>r.returnStatus=['RETURNED_ON_TIME','RETURNED_LATE','NOT_RETURNED','UNKNOWN'][i]);assert.equal(calculate(rows).rate,50);assert.deepEqual(calculate([]),{total:0,readers:0,rate:null});});
// Verify Monday grouping crosses year boundary.
test('Monday grouping crosses year boundary',()=>{const r=sampleData()[0];r.checkoutDate='2026-01-01';assert.deepEqual(trend([r],'WEEKLY'),[['2025-12-29',1]]);});
// Verify reject malformed dates, reversed ranges and broken quoting.
test('reject malformed dates, reversed ranges and broken quoting',()=>{assert.equal(validDate('2026-02-30'),false);assert.throws(()=>filterRecords([],{start:'2026-02-02',end:'2026-01-01'}));assert.throws(()=>validateCSV('"unclosed'));});

// Verify multi-select uses OR within a field and AND across fields.
test('multi-select uses OR within a field and AND across fields',()=>{const rows=sampleData();const c={start:'2026-01-01',end:'2026-12-31',subject:['Computer Science','Literature'],userSegment:['STUDENT']};const selected=filterRecords(rows,c);assert.ok(selected.length);assert.ok(selected.every(r=>c.subject.includes(r.subject)&&r.userSegment==='STUDENT'));});
