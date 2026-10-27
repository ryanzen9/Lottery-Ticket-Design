/* Shared by the generated dashboard and the command regression tests. */
((root, factory) => {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LotteryTicketHandoff = api;
})(globalThis, () => {
  'use strict';
  function normalizeStages(values, ids) {
    const known = new Set(ids), used = new Set();
    return (Array.isArray(values) ? values : []).filter(stage => {
      if (!stage || typeof stage.id !== 'string' || !/^S-\d{3,}$/.test(stage.id) || used.has(stage.id) || !['baseId', 'currentId', 'acceptedId'].every(key => known.has(stage[key]))) return false;
      if (!['ready', 'refining'].includes(stage.status) || (stage.status === 'ready' && stage.currentId !== stage.acceptedId)) return false;
      if (stage.status === 'refining' && stage.currentId === stage.acceptedId) return false;
      used.add(stage.id); return true;
    }).map(stage => ({ ...stage, title: typeof stage.title === 'string' && stage.title.trim() ? stage.title : stage.id, revision: Number.isInteger(stage.revision) && stage.revision > 0 ? stage.revision : 1 }));
  }
  function mergeStages(manifest, cached, ids) {
    const merged = new Map(normalizeStages(manifest, ids).map(stage => [stage.id, stage]));
    normalizeStages(cached, ids).forEach(stage => {
      if (!merged.has(stage.id) || stage.revision > merged.get(stage.id).revision) merged.set(stage.id, stage);
    });
    return [...merged.values()].sort((a, b) => a.id.localeCompare(b.id));
  }
  function promoteStage(state, prototypeId, now) {
    const existing = state.stages.find(stage => [stage.baseId, stage.currentId, stage.acceptedId].includes(prototypeId));
    if (existing) return { ...state, activeStageId: existing.id, stageSelectionRevision: (state.stageSelectionRevision || 0) + Number(state.activeStageId !== existing.id) };
    const number = Math.max(0, ...state.stages.map(stage => Number(stage.id.slice(2)))) + 1;
    const stage = { id: `S-${String(number).padStart(3, '0')}`, title: `阶段 ${number}`, baseId: prototypeId, currentId: prototypeId, acceptedId: prototypeId, status: 'ready', revision: 1, createdAt: now, updatedAt: now };
    return { ...state, stages: [...state.stages, stage], activeStageId: stage.id, stageSelectionRevision: (state.stageSelectionRevision || 0) + 1 };
  }
  function acceptStage(state, stageId, now) {
    return { ...state, activeStageId: stageId, stageSelectionRevision: (state.stageSelectionRevision || 0) + Number(state.activeStageId !== stageId), stages: state.stages.map(stage => stage.id === stageId ? { ...stage, acceptedId: stage.currentId, status: 'ready', revision: stage.revision + 1, updatedAt: now } : stage) };
  }
  function normalizeDraft(value, ids, manifest = {}) {
    const draft = value && typeof value === 'object' && [1, 2].includes(value.version) ? value : {};
    const selected = new Set(Array.isArray(draft.selectedIds) ? draft.selectedIds : []);
    const notes = {};
    for (const id of ids) {
      if (draft.notes && typeof draft.notes[id] === 'string') notes[id] = draft.notes[id];
    }
    const stages = mergeStages(manifest.stages, draft.stages, ids);
    const localRevision = Number.isInteger(draft.stageSelectionRevision) && draft.stageSelectionRevision >= 0 ? draft.stageSelectionRevision : 0;
    const manifestRevision = Number.isInteger(manifest.stageSelectionRevision) && manifest.stageSelectionRevision >= 0 ? manifest.stageSelectionRevision : 0;
    const candidates = localRevision > manifestRevision ? [draft.activeStageId, manifest.activeStageId] : [manifest.activeStageId, draft.activeStageId];
    const activeStageId = [...candidates, stages.at(-1)?.id].find(id => stages.some(stage => stage.id === id)) || null;
    const active = stages.find(stage => stage.id === activeStageId);
    const cachedActive = normalizeStages(draft.stages, ids).find(stage => stage.id === activeStageId);
    const keepMode = active && cachedActive && draft.activeStageId === activeStageId && cachedActive.revision >= active.revision;
    const resetReferences = active && (!cachedActive || draft.activeStageId !== activeStageId || (active.revision > cachedActive.revision && active.acceptedId !== cachedActive.acceptedId));
    return {
      version: 2,
      selectedIds: resetReferences ? [] : ids.filter(id => selected.has(id)),
      notes,
      general: typeof draft.general === 'string' ? draft.general : '',
      stages, activeStageId, iterationMode: active && (active.status === 'refining' || (keepMode && draft.iterationMode === 'refine')) ? 'refine' : 'explore',
      stageSelectionRevision: Math.max(localRevision, manifestRevision),
    };
  }
  function composeCommand({ projectPath, ids = [], notes = {}, general = '', count, stages = [], activeStageId = null, stageSelectionRevision = 0, mode = 'explore' }) {
    const active = stages.find(stage => stage.id === activeStageId);
    if (mode === 'refine' && !active) return '请先设置阶段稿，再单独优化。';
    if (active && mode === 'explore' && active.status !== 'ready') return '请先确认当前阶段稿，再进入下一轮探索。';
    if (active) ids = mode === 'refine' ? [active.currentId] : [...new Set([active.acceptedId, ...ids])];
    if (!ids.length) return '请先勾选一份或多份原型。';
    const total = Number.isInteger(count) && count >= 6 && count <= 10 ? count : 6;
    const lines = [
      `使用 $lottery-ticket-design 继续这个原型项目：${projectPath}`,
      `参考编号：${ids.join(', ')}`,
    ];
    if (active) {
      lines.push(`当前阶段：${active.id} · ${active.title}`, `阶段基线：${mode === 'refine' ? active.currentId : active.acceptedId}`, `迭代模式：${mode === 'refine' ? 'refine（单稿优化，1 份）' : 'explore（阶段内继续探索）'}`,
        '', '阶段状态（阶段按 revision 合并；当前阶段按 stageSelectionRevision 合并，分别写入 stages 与 project.activeStageId / project.stageSelectionRevision，保留更高版本记录）：', JSON.stringify({ activeStageId, stageSelectionRevision, stages }, null, 2));
    }
    const annotated = ids.filter(id => typeof notes[id] === 'string' && notes[id].trim());
    if (annotated.length) {
      lines.push('', '逐份方案备注：');
      annotated.forEach(id => lines.push(`【${id}】`, notes[id].trim()));
    }
    if (general.trim()) lines.push('', '整体迭代要求：', general.trim());
    lines.push('', '请先查看所选方案的界面、style-history.json 与 design.css，按编号理解各自备注，并将逐份备注与整体要求记录到新批次的 feedback。先记录风格演化并锚定新 design.css，保留旧批次与原始界面。');
    if (active && mode === 'refine') {
      lines.push(`本次只生成 1 份单独优化稿，以 ${active.currentId} 为直接父稿，在新编号与新目录中完善界面、细节和交互。新批次设 mode="refine"、stageId="${active.id}"、stageBaseId="${active.currentId}"，parentIds 包含该父稿。完成后将该阶段 currentId 更新为新稿、status 设为 "refining"、revision 加 1，保留 acceptedId。等待用户确认满意后再进入下一轮探索；继续单稿优化时从该阶段最新 currentId 继续。`);
    } else {
      lines.push(`再生成 ${total} 份有足够差异的原型，新稿标明实际参考的 parentIds。`);
      if (active) lines.push(`全部新稿以阶段已确认稿 ${active.acceptedId} 为共同基线，保留其已确定风格与核心结构；额外勾选方案只作为有备注依据的补充参考。新批次设 mode="explore"、stageId="${active.id}"、stageBaseId="${active.acceptedId}"，该批次及每份新稿的 parentIds 均包含阶段基线。阶段已确认稿保持不变，等待用户选择下一阶段。`);
    }
    return lines.join('\n');
  }
  return { normalizeDraft, composeCommand, normalizeStages, mergeStages, promoteStage, acceptStage };
});
