// Copyright 2026 向金涛
// Affiliation: 吉林大学
// 在最小 DOM 替身中验证审核与过期响应；不代替浏览器视觉验收。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map(), requests = [];
function element() {
  return {value:'', checked:false, disabled:true, hidden:true, children:[],
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; }, focus() {}};
}
const $ = id => {
  if (!elements.has(id)) elements.set(id, element());
  return elements.get(id);
};
const context = vm.createContext({$, node: (tag, text) => ({tag, text}),
  api: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject}))});
const html = fs.readFileSync(path.join(__dirname, '../workbench.html'), 'utf8');
vm.runInContext(html.slice(html.indexOf('let diagnosticSchema'), html.indexOf('async function loadDiagnosis')), context);
vm.runInContext('diagnosticSchema = {observations:{stuck:"钻柱运动受限"}}', context);

const result = {observations:{stuck:'yes'}, evidence:[{field:'stuck', value:'yes', quotes:['钻柱无法旋转。']}],
  conflicts:[], duration_seconds:1, note:'请核对原句'};

(async () => {
  $('observation-stuck').value = 'unknown';
  $('incident-text').value = '钻柱无法旋转。';
  const first = $('extract-submit').onclick();
  requests[0].resolve(result); await first;
  assert.equal($('observation-stuck').value, 'unknown', '模型结果不得自动成为观测');
  assert.equal($('apply-extraction').disabled, true, '未核对不能应用草稿');
  $('apply-extraction').onclick();
  assert.equal($('observation-stuck').value, 'unknown');
  $('extraction-confirm').checked = true; $('extraction-confirm').onchange();
  assert.equal($('apply-extraction').disabled, false);
  $('apply-extraction').onclick();
  assert.equal($('observation-stuck').value, 'yes');
  assert.equal($('extraction-review').hidden, true);
  assert.equal(requests.length, 1, '应用草稿不得自动发起诊断');

  $('observation-stuck').value = 'unknown';
  const stale = $('extract-submit').onclick();
  $('incident-text').value = '已更换事件描述'; $('incident-text').oninput();
  requests[1].resolve(result); await stale;
  assert.equal($('extraction-review').hidden, true, '描述更改后旧响应应作废');
  assert.equal($('apply-extraction').disabled, true);
  assert.equal($('observation-stuck').value, 'unknown');

  const failed = $('extract-submit').onclick();
  requests[2].reject(new Error('服务未完成')); await failed;
  assert.equal($('extraction-review').hidden, true);
  assert.equal($('apply-extraction').disabled, true);
  assert.equal($('extract-submit').disabled, false, '失败后允许重试');
  assert.ok(requests.every(request => request.url === '/api/diagnosis/extract'));
  console.log('Review gating, explicit apply, stale response and failure recovery: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
