# 任务 A6:按 astra 审阅重写出图提示词、场景字段、自审与预检

仓库 `E:\我的文件\桌面\miravia-listing`,分支 `feat/auto`。先读 `AGENTS.md`、`SKILL.md`、`references/` 四份规则,
再读审阅意见 `docs/tasks/A6_astra_review.md`(下面称"审阅")。本任务实施审阅里**被采纳**的部分;**你可以改 references/ 和 SKILL.md**。

## 店主已定的方向(不要改回去)
- 卖点要像淘宝/亚马逊爆款一样大胆:同类爆款普遍宣传的好处,本商品看得出有对应部件就能写(带滤芯 → filtra cloro y cal、agua más suave)。
  **不采纳审阅第 3 条"未确认功效不写"**。只禁:认证标志、医疗/治疗说法、别家品牌。只采纳其中一句:看不见的内部结构(剖面、彩色颗粒)不要画。
- 不准 emoji(标题、描述、图上文字)。标题 55～128 字符(速卖通上限 128)。

## 要做
1. **提示词重写(审阅第 1 条 + 文末 01～08 模板)**:
   - `image_workflow.make_plan` 改为收集 `{path, role, use}` 参考图列表,筛选去重后编号;同一列表生成 API 附件顺序和提示词里的"参考图用途"
     (例:"图1锁定商品外观;图2提供人物身份和姿态,背景按本图场景生成")。
   - `image_prompts.make_prompt` 按审阅模板重写 01～08,顺序:本图目标 → 参考图角色 → 当前变体事实 → 动作/连接/结果 → 镜头构图 → 西语排版。
     删掉文件路径、来源登记、重试次数、JPG/字节限制、其他槽位要求、重复 JSON(这些留在程序/规则里)。空占位整句删除。
     目标每条约 300 中文字符以内(西语原文不截断)。重做备注替换冲突指令,不只追加。zoom 只在 03 展开。
   - 软管这类"必要连接"写进场景,不被"不新增配件"误删(审阅 04 的说明)。
2. **场景字段(审阅第 2 条)**:content.json 新增 `scene_briefs`:`{"04": {"location","action","connections","visible_result"}, "05": {...}, "08": {...}}`
   (中文);07 继续用 `image_scenes07` 但每项写清位置/动作/连接/结果。`use_scene`、`hero_feature`、`scene_briefs`(04/05/08)在 `check`
   和 seedream 付费前都校验非空;B 组继承。人物素材附件按每张/每格是否有人决定(含 07,审阅第 8 条前半)。
3. **AI 自审(审阅第 4 条)**:`references/出图规则.md`"AI 自审"一节换成审阅给的标准(原尺寸 + 320px 缩略图;任一硬伤不通过;02/03 要能指出主卖点,
   04/05/08 要能指出动作、连接、结果;**两次失败保留失败状态,不发布**)。`images-review` 增加可选 `--checks`/`--evidence`/`--severity` 记录。
   publish/finalize:有失败图的组只出草稿(不进可上传表),其他组照常;报告里列出。
4. **预检(审阅第 5 条)**:新命令 `mlist preflight --batch <批次>`(只读):供应商在 shop.json 且制造商/欧盟负责人都在模板下拉、模板存在、
   图床已配置、ARK_API_KEY 已设(只判断有无,不读值)、预算余额。SKILL.md 规定付费出图前必须跑,组级问题只跳过该组,账户级问题停止付费步骤。
   `seedream`:某个 job 有 blocker 只跳过该 job(记进结果),不让整批退出。
5. **描述插图顺序(审阅第 6 条)**:改为 开场利益句 → 结果图 → 卖点 → 03 细节图 → 用法/内容/兼容 → 其余图 → `PALABRAS CLAVE` 段(保持在最后)。
   content 可选 `description_images`(槽位顺序,默认 `["08","03","04","07"]`,第一个是"结果图")。实现方式自定(例如按段落插入点),
   总长 ≤ 3000,超长先压缩其余图、保留结果图和细节图;删了哪些图写进 fill 的 warnings。
6. **规则统一(审阅第 7 条)**:文案规则/电商经验里标题长度统一为 55～128;keywords 的"最多人搜"改成"两边都出现的说法优先",不推导搜索量;
   PALABRAS CLAVE 只放相关去重词,不硬凑数量;替换旧毛毯完整例子为带新字段(use_scene/hero_feature/scene_briefs/description_images)的例子,例子里不出现 emoji。

## 做完的标准
- 全部测试 OK(`PYTHONIOENCODING=utf-8`):smoke_test、regress_legacy、auxiliary_test、test_yollgo、test_images、test_publish、test_auto、test_keywords;
  为新行为补测试(提示词含参考图角色且不含路径/字节限制、缺 scene_briefs 报错、blocker 只跳过单个 job、两次失败不发布、描述插图顺序与超长裁剪、preflight)。
- 打印一个示例:用测试数据跑 `images-plan` 后,把 04 和 02 的最终提示词原文贴在最后回复里,便于 Claude 检查。
- 不联网、不调真实 Seedream/友购/GitHub,不碰 `E:\文档\Miravia工作区`。**不要 git commit,不要动 .git。**
- 最后中文列出改了哪些文件。
