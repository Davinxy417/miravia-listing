# 任务 A3:文案/出图规则整理 + 出图步骤命令

## 背景
本仓库 `E:\我的文件\桌面\miravia-listing` 是米拉维亚上架 skill(先读 `AGENTS.md`、`references/数据格式.md`、
`references/店铺配置.md`、`python scripts/mlist.py --help`)。A1 搭了工作区/批次/定价/填表,A2 加了友购抓取和 `build`。
旧项目 `E:\我的文件\桌面\Miravia` 只读,里面是这一批货做图时攒下的规则和脚本。

skill 要给用户和他妹妹用,**她的电脑上没有旧项目、也没有下面那些规则文件**,所以规则必须整理进本仓库。
出图本身由 agent 做(Codex 用自带的图像生成;Claude 不能出图,会把出图活转给 Codex;额度用完用 Seedream 付费补)。
本任务做的是:规则文档 + 让 agent 照着干活的命令(列清单、Seedream 批量出图、后处理、审阅拼图、记录通过/重做)。
**不做**:图床、推送、SKILL.md(下个任务)。

## 1. 规则文档(写进 `references/`)
读这些,整理成本仓库自己的规则(中文,写给 agent 看,短而准,能直接照做;西语原文术语保留):
- 用户给的主规则:`E:\我的文件\文档\Codex\2026-10-07\p\outputs\INSTRUCCIONES_IA_MIRAVIA_GPSR.md`、`FUENTES_Y_CRITERIOS.md`、`EJEMPLOS_ENTRENAMIENTO.jsonl`
- 用户的图片项目:`E:\我的文件\文档\HiperYang电商\电商商品图片规则.md`、`商品图片批量制作流程.md`、`商品图片Agent套件\AGENTS.md`、`Prompt-Library.md`
- 旧项目做图任务包:`docs\codex_img_common.md`、`codex_img_v2.md`、`codex_img_people.md`、`codex_img_pilot.md`、`codex_img_set.md`、
  `codex_task_04_gpsr_labels.md`、`codex_task_07_infografia.md`、`docs\图片叠字.md`、`scripts\seedream_jobs.py`(里面的 prompt 写法)
- 旧项目 `docs\交接.md`(用户拍板过的事,**以它为准**,见下)、`docs\电商经验.md`、`data\content.json`(现成文案的样子)、`scripts\fill_template.py` 的 `validate_content`

产出:
- `references/出图规则.md`:每链接 8 张展示图各是什么(01 白底主图用主推变体 / 02 卖点图标 / 03 细节+放大圈(只给好货)/ 04 露手场景 /
  05 半身场景 / 06 尺寸 / 07 用途拼图 / 08 正脸模特)、每个变体一张 `variante.jpg`、组合装(B 组)只做自己的 01/02/06 且画面里正好 N 件、
  规格(1200×1200 sRGB JPG < 3 MB)、颜色如实不美化、不编尺寸、参考图上的中文/价格/水印不要、真人用 Pexels/Unsplash 素材合成并记来源、
  每张最多重做几次、文字怎么出(见下)、GPSR(标签是脚本画的平面图,打印贴货;"贴在商品上"的效果图单独做,不得伪造成真实照片;非电器不放 WEEE/CE)。
  附一节"prompt 模板":每个位置一段可直接套用的 prompt 骨架(从旧任务包和 seedream_jobs.py 里提炼)。
- `references/文案规则.md`:标题/描述/属性/安全提示/类目/GPSR 短名/`overlays.json` 图上文字怎么写;长度限制和 `check` 的校验一致;
  标题按买家搜索词(词表在 `references/电商经验.md`);组合装标题 "Pack de N" 开头;不写没核实的材质尺寸。
  附一个完整的 `content.json` 单组例子 + 对应 B 组例子(可以取旧项目现成的一组)。
- 用户拍板过、必须写进规则的:
  - 文字由图像模型直接设计进画面(用户比较后选的),文字只用 `overlays.json` 里给的,一字不改,出完逐字校对,错了重做;
    **06 尺寸图的数字一律用脚本画**(模型两次写错过)。
  - 底图模式也要支持:无字底图 + 脚本叠字(`mlist.py overlay`),作为兜底。
  - 颜色不要过度美化,按友购原图颜色。
  - 价格按自己成本利润定,不跟竞品;经验文档写成参考,不写成禁止条款(规则写得太死会让生成变僵)。

## 2. 每组需要的出图资料进 `content.json`
旧 `seedream_jobs.py` 里写死的 `PRODUCTS`(商品外观中文描述)和 `SCENES07`(07 拼图四格场景)改成 `content.json` 每组字段
(字段名你定,写进 `references/数据格式.md`;B 组没写就继承主组)。`import-legacy` 顺带把旧值迁进来,
`tests/regress_legacy.py` 照样要全一致。

## 3. 命令
都在 `mlist.py` 下,`--json` 规则和 A1 一样。

| 子命令 | 作用 |
|---|---|
| `images-plan` | 按批次数据 + 已有图片 + 审阅记录,列出每张图要做什么:id(如 `G01/azurita-160x220-crema/02`)、输出路径、参考图路径、用哪种做法(模型出带字图 / 无字底图 + 叠字 / 脚本画 / 由别的图派生)、prompt(按规则模板填好商品描述和 overlays 文字)、状态(缺 / 已有 / 要重做 + 原因)。写批次根目录 `image_plan.json` 和给人/agent 看的 `image_plan.md`,打印汇总。Codex 拿着 `image_plan.md` 就能一张张出图,不用再读别的。 |
| `images-finish` | 把 agent 生成的原始图(放 `images/<组>/<变体>/internal/raw/<槽位>*.png|jpg`)整理成规格成品放进 `output/miravia-es/v01/`;从 01 派生 `variante.jpg`;06 走脚本画尺寸;B 组共用位置复制单件组成品。照旧逻辑(`overlay.py`、旧 `seedream_jobs.py install`),装新图前旧图备份到 `internal/old/`。 |
| `seedream` | Seedream 5.0 Pro 批量出图(照旧 `scripts/seedream.py` + `seedream_jobs.py`):读 `image_plan.json` 里选中的 id(`--only`,或 `--all-missing`)。**先打印张数和预计扣多少单位,不带 `--yes` 不出图**(退出码 2,`--json` 里 `"needs_confirm": true`)。Key 只从环境变量 `ARK_API_KEY` / Windows 用户环境变量读,不打印、不写文件;没有 Key 就说清怎么设。出图结果放 `internal/raw/`,然后提示跑 `images-finish`。 |
| `images-sheet` | 审阅拼图 `review/<名字>.jpg`(批次根目录下):按组排,每格下写 `组/变体/槽位` 和状态;可 `--group`、`--only`、`--pending`(只看没审过的)。 |
| `images-review` | 记录用户的审阅结果到批次根目录 `image_review.json`:`--ok <id>...`、`--redo <id> --note "颜色偏了"`。`images-plan` 把 redo 的列为要重做;`status` 显示审过/没审/要重做的数量。 |

旧项目里能复用的代码就搬过来改路径,别重写一遍。图片都在批次 `images/` 里;清单、审阅记录、拼图放批次根目录(旧批次的 `images/` 是只读联接,不能往里写清单);
`import-legacy` 联接进来的旧图目录是只读的,写命令遇到联接要报清楚(A1 已有这条规矩)。

## 4. 测试(离线)
Seedream 用假接口(返回一张纯色图)替掉;测 plan 的状态推断(缺/已有/重做/B 组共用/派生)、finish 的规格和备份、
sheet 能出图、review 的记录、seedream 不带 `--yes` 不出图且不读到 Key 时报错清楚。一条命令能跑。
`tests/smoke_test.py`、`tests/regress_legacy.py`、已有测试都要照样通过。

## 做完的标准
1. 所有测试通过(贴最后几行)。
2. 对旧批次只读跑一遍:`python scripts/mlist.py images-plan --batch 2026-10-冬季第一批`(工作区在 `E:\我的文件\文档\Miravia工作区`,
   已导入旧项目这批货;**只读**,写到 `.tmp/` 的副本里也行),贴汇总:每组缺几张、已有几张。
3. `references/出图规则.md`、`references/文案规则.md` 各自能单独看懂,不引用本机其他路径。

## 规矩
不要 git commit,不要动 `.git`;不要往旧项目、规则文件目录写;只在本仓库写文件(和 `.tmp/`)。
最后回复:改了哪些文件、测试原样输出(最后几行)、规则整理时你取舍了什么(两边规则冲突时怎么定的)、拿不准的地方。
