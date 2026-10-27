# 阶段稿与单稿优化

收到含阶段状态的命令、`mode="refine"` 或用户要求围绕阶段稿继续时，使用此流程。探索每轮仍生成 6–10 稿；阶段稿的单独优化每次只生成 1 稿。

## 保存与合并阶段

Dashboard 的“设为阶段”创建 `S-NNN` 阶段；侧边栏“阶段”只查看阶段稿，时间线保留起点标记与各次优化。详情页的同名入口返回 Dashboard 设置阶段。选择和确认先保存为浏览器草稿，完整迭代命令携带阶段 JSON；agent 收到后再同步到项目。

在 `manifest.json` 根级保存 `stages`，在 `project.activeStageId` 保存当前阶段 ID。阶段记录示例：

```json
{
  "id": "S-001",
  "title": "阶段 1",
  "baseId": "P-003",
  "currentId": "P-007",
  "acceptedId": "P-003",
  "status": "refining",
  "revision": 2,
  "createdAt": "2026-10-27T01:00:00Z",
  "updatedAt": "2026-10-27T02:00:00Z"
}
```

- `baseId`：设为阶段时的原稿，固定保留。
- `currentId`：该阶段最新工作稿。
- `acceptedId`：用户最近确认满意的稿，下一轮探索的共同基线。
- `status`：`ready` 表示已确认，此时 currentId 等于 acceptedId；`refining` 表示新优化稿待确认。
- `revision`：阶段记录有变化时递增，包括生成优化稿、用户确认和切换工作版本；单纯选择另一个当前阶段不改阶段记录，更新 project.activeStageId 并递增 project.stageSelectionRevision。

合并命令中的浏览器阶段记录和 manifest 时，保留 revision 较高者；同版本以 manifest 为准，避免重渲染后被旧缓存覆盖。当前阶段指针独立按 stageSelectionRevision 合并（缺省为 0），较高版本优先，同版本以 manifest 为准；防止 agent 更新当前阶段后被旧浏览器选择覆盖。保留其他阶段。若命令目标与更新后的阶段稿冲突，只补问这一处；不要静默回退项目中的较新稿。

## 单独优化

1. 以所选阶段的 currentId 为唯一优化目标，读取其界面、七项元数据、style-history.json 和 design.css。本次只改用户反馈涉及的部分，保持已确定方向。
2. 分配一个新 P-NNN 编号和目录。追加一个独立批次，`mode="refine"`、`stageId="S-NNN"`、`stageBaseId="父稿编号"`、`ids` 仅含新稿；批次与新稿 parentIds 都包含该父稿。记录本次 feedback。
3. 依照正常风格记录流程运行 prepare，可用 `--from 父稿编号` 复制系统；修改、anchor 后编写页面。原稿和原 design.css 保留。单稿仍可包含多个界面，应覆盖这次修改影响的界面。
4. 完成后只把该阶段 currentId 指向新稿，status 改为 refining，revision 加 1，更新 updatedAt；acceptedId 保持为最近已确认稿。运行 render，更新画板、阶段列表与导出包。
5. 交付新稿并等待反馈。用户继续微调时，从最新 currentId 再做一份新版本。单稿优化在时间线作为阶段内版本展示，不计为新一轮探索。

## 确认后继续探索

用户点击“确认阶段稿”或在对话明确表示满意并要求继续时，将 acceptedId 设为 currentId、status 设为 ready、revision 加 1。已有明确确认时直接执行，无需再次确认。

探索从当前阶段 acceptedId 开始，默认沿用最近一次探索的数量（6–10），跳过中间单稿批次。追加探索批次时记录 `mode="explore"`、`stageId`、`stageBaseId=acceptedId`；批次与每份新稿的 parentIds 均包含这一基线。stageBaseId 是当时的快照，后续阶段更新不改历史批次。额外勾选方案只按用户备注提供补充参考，保持阶段已确定的核心风格和结构。

阶段状态为 refining 时，先完成单稿反馈或取得用户明确确认，再开展探索。新探索稿不自动成为阶段；由用户选择满意的一版设置下一阶段，旧阶段仍可独立查看和继续优化。

## 导出

导出元数据保留项目已保存的阶段记录及批次的 mode、stageId、stageBaseId。浏览器中尚未交回 agent 的阶段操作仍属于本地草稿，不改写已生成 ZIP。
