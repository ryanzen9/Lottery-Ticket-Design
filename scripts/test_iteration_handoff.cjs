const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeDraft, composeCommand, promoteStage, acceptStage } = require('../assets/iteration-handoff.js');

test('command keeps selected feedback bound to its design and omits deselected notes', () => {
  const command = composeCommand({
    projectPath: '/design project/', ids: ['P-001', 'P-003'], count: 8,
    notes: { 'P-001': '保留布局\n减弱装饰', 'P-002': '不应被带入', 'P-003': '采用其导航交互' },
    general: '统一移动端体验',
  });
  assert.match(command, /参考编号：P-001, P-003/);
  assert.ok(command.includes('【P-001】\n保留布局\n减弱装饰'));
  assert.ok(command.includes('【P-003】\n采用其导航交互'));
  assert.ok(command.includes('整体迭代要求：\n统一移动端体验'));
  assert.ok(!command.includes('不应被带入'));
  assert.match(command, /生成 8 份/);
});

test('restoring a draft retains unchecked notes while dropping missing designs', () => {
  const saved = {
    version: 1, selectedIds: ['P-009', 'P-003', 'P-001', 'P-003'],
    notes: { 'P-001': '布局', 'P-002': '稍后参考', 'P-009': '旧数据' }, general: '整体要求',
  };
  const restored = normalizeDraft(JSON.parse(JSON.stringify(saved)), ['P-001', 'P-002', 'P-003']);
  assert.deepEqual(restored.selectedIds, ['P-001', 'P-003']);
  assert.deepEqual(restored.notes, { 'P-001': '布局', 'P-002': '稍后参考' });
  assert.equal(restored.general, '整体要求');
});

test('empty or invalid drafts do not prevent opening the dashboard', () => {
  for (const saved of [null, [], { version: 1, selectedIds: 'P-001', notes: { 'P-001': 12 }, general: false }]) {
    assert.deepEqual(normalizeDraft(saved, ['P-001']), { version: 2, selectedIds: [], notes: {}, general: '', stages: [], activeStageId: null, iterationMode: 'explore', stageSelectionRevision: 0 });
  }
  const command = composeCommand({ projectPath: '/', ids: ['P-001'], notes: {}, general: '', count: 4 });
  assert.match(command, /生成 6 份/);
  assert.ok(!command.includes('逐份方案备注：'));
  assert.ok(!command.includes('整体迭代要求：'));
  assert.equal(composeCommand({ ids: [] }), '请先勾选一份或多份原型。');
});

test('stage promotion preserves previous checkpoints and reuses existing stages', () => {
  const first = promoteStage({ stages: [], activeStageId: null }, 'P-001', '2026-10-27T01:00:00Z');
  const second = promoteStage(first, 'P-003', '2026-10-27T02:00:00Z');
  assert.equal(second.stages.length, 2);
  assert.equal(second.activeStageId, 'S-002');
  assert.equal(second.stages[0].acceptedId, 'P-001');
  const reused = promoteStage(second, 'P-001', '2026-10-27T03:00:00Z');
  assert.equal(reused.activeStageId, 'S-001'); assert.equal(reused.stages.length, 2);
});

test('new agent refinement supersedes stale browser state after rerender', () => {
  const initial = promoteStage({ stages: [], activeStageId: null }, 'P-001', '2026-10-27T01:00:00Z');
  const cached = { version: 2, ...initial, iterationMode: 'explore', selectedIds: ['P-001'], notes: { 'P-001': '保留布局' } };
  const manifest = { stages: [{ ...initial.stages[0], currentId: 'P-007', status: 'refining', revision: 2 }], activeStageId: 'S-001' };
  const restored = normalizeDraft(cached, ['P-001', 'P-007'], manifest);
  assert.equal(restored.stages[0].currentId, 'P-007');
  assert.equal(restored.iterationMode, 'refine'); assert.equal(restored.notes['P-001'], '保留布局');
});

test('single refinement always targets the current stage draft and one output', () => {
  const initial = promoteStage({ stages: [], activeStageId: null }, 'P-001', '2026-10-27T01:00:00Z');
  const state = { ...initial, stages: [{ ...initial.stages[0], currentId: 'P-007', status: 'refining', revision: 2 }] };
  const command = composeCommand({ projectPath: '/', ids: ['P-003'], notes: { 'P-003': '无关备注', 'P-007': '微调按钮' }, general: '', count: 10, ...state, mode: 'refine' });
  assert.match(command, /参考编号：P-007\n/);
  assert.match(command, /本次只生成 1 份/);
  assert.ok(command.includes('微调按钮')); assert.ok(!command.includes('无关备注'));
  assert.ok(!command.includes('再生成 10 份'));
  assert.match(command, /保留 acceptedId/);
});

test('next exploration requires acceptance and includes the accepted baseline', () => {
  const state = promoteStage({ stages: [], activeStageId: null }, 'P-001', '2026-10-27T01:00:00Z');
  state.stages[0] = { ...state.stages[0], currentId: 'P-007', status: 'refining', revision: 2 };
  assert.equal(composeCommand({ ...state, mode: 'explore' }), '请先确认当前阶段稿，再进入下一轮探索。');
  const accepted = acceptStage(state, 'S-001', '2026-10-27T02:00:00Z');
  assert.equal(accepted.stages[0].acceptedId, 'P-007'); assert.equal(accepted.stages[0].revision, 3);
  const command = composeCommand({ ...accepted, projectPath: '/', ids: ['P-003'], notes: {}, general: '', count: 6 });
  assert.match(command, /参考编号：P-007, P-003/); assert.match(command, /再生成 6 份/);
  assert.match(command, /stageBaseId="P-007"/);
  assert.equal(state.stages[0].acceptedId, 'P-001');
});

test('active stage selection merges independently from draft revisions', () => {
  const first = promoteStage({ stages: [], activeStageId: null }, 'P-001', '2026-10-27T01:00:00Z');
  const server = promoteStage(first, 'P-003', '2026-10-27T02:00:00Z');
  const saved = { version: 2, ...first, selectedIds: ['P-001'], iterationMode: 'refine' };
  const updated = normalizeDraft(saved, ['P-001', 'P-003'], server);
  assert.equal(updated.activeStageId, 'S-002'); assert.equal(updated.iterationMode, 'explore'); assert.deepEqual(updated.selectedIds, []);
  const switched = { version: 2, ...server, activeStageId: 'S-001', stageSelectionRevision: 3 };
  assert.equal(normalizeDraft(switched, ['P-001', 'P-003'], server).activeStageId, 'S-001');
});

test('agent acceptance exits a stale refine mode and clears the previous baseline selection', () => {
  const state = promoteStage({ stages: [], activeStageId: null }, 'P-001', '2026-10-27T01:00:00Z');
  state.stages[0] = { ...state.stages[0], currentId: 'P-007', status: 'refining', revision: 2 };
  const saved = { version: 2, ...state, iterationMode: 'refine', selectedIds: ['P-001'] };
  const accepted = acceptStage(state, 'S-001', '2026-10-27T02:00:00Z');
  const restored = normalizeDraft(saved, ['P-001', 'P-007'], accepted);
  assert.equal(restored.iterationMode, 'explore'); assert.deepEqual(restored.selectedIds, []);
  assert.equal(restored.stages[0].acceptedId, 'P-007');
});
