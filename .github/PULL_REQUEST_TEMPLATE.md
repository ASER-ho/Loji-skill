## 这个 PR 做了什么

<!-- 一到三句。不要复述 diff，说明动机和结论。 -->

## 改动类型

- [ ] 人格行为规则（`SKILL.md` / `references/`）
- [ ] 记忆或判断的格式与迁移
- [ ] 工具脚本（`scripts/`）
- [ ] DSH 适配包（`loji-dsh/`）
- [ ] CI / 发布流程
- [ ] 文档
- [ ] 测试

## 本地验证

粘贴实际输出，不要只写「通过了」：

```
$ python scripts/validate_repo.py --strict
$ python scripts/check_docs_consistency.py
$ python -m unittest discover -s tests -p "test_*.py"
$ npm run check:meta
$ npm test
$ npm run check:preset
```

`skills-ref validate .` 的结果：

- [ ] 已跑，通过
- [ ] 不可用，记 `ENV-BLOCKED`（本地 `validate_repo.py` 结果不计作 `skills-ref` PASS）

## 需要对照的约束

- [ ] 没有引入 `ROADMAP.md` 明令排除的东西（数据库、后台服务、向量索引、第三方依赖、GUI 等）
- [ ] 没有在 PR 里顺手 bump 版本号（版本只在发版时由维护者改）
- [ ] 新增或修改的行为规则，配了可机械校验的检查项，或说明了为什么不可机械校验
- [ ] 修 bug 附了在修复前会失败的回归测试
- [ ] 未使用真实用户的记忆、判断账本或对话数据
- [ ] `package.json` 的 `files` 若被改动，安装体积仍在上限内且 `verify-packed-bundle.mjs` 通过

## 未验证或已知限制

<!-- 明确写出这次没有验证的部分。这部分不写，评审会要求补。 -->

## 关联 issue

Closes #
