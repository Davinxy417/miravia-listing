# 任务 A1:skill 骨架 + 核心搬家 + 店铺配置 + 按表头填表

## 背景
用户在米拉维亚(Miravia 西班牙站)开店,货从友购(Yollgo)批发商拿。现在的流程是一个项目里的一堆脚本:
`E:\我的文件\桌面\Miravia`(下称**旧项目**,只读,不要往里写任何东西)。
要把它做成可复用的 skill 仓库 `E:\我的文件\桌面\miravia-listing`(下称**本仓库**,你在这里干活),
给用户和他妹妹各用一份店铺配置。以后还会有本地网页调用同一个命令行入口,所以**接口要稳定、输出要能机读**。

先读:本仓库 `AGENTS.md`;旧项目 `AGENTS.md`、`docs/交接.md`(重点看"定价规则""已定"两节)、
`scripts/` 全部、`data/` 各文件表头、`docs/电商经验.md`。

本任务只做"数据 → 定价 → 填表 → 检查"这条线和骨架。**不做**:友购抓取、出图、文案生成、图床、SKILL.md(后面的任务做)。

## 要做的

### 1. 命令行入口 `scripts/mlist.py`
一个入口,子命令如下(内部模块怎么拆你定,别和 `mlist.py` 重名导致 import 冲突)。
所有子命令:`--ws <工作区>` 可选;`--batch <批次名>` 用于批次相关命令;`--json` 时 stdout 只输出一个 JSON 对象
(`{"ok": bool, "warnings": [...], "errors": [...], ...}`),给网页用;不带 `--json` 时用中文人话输出。
出错退出码非 0,错误信息说清"哪里不对、该怎么办"。

| 子命令 | 作用 |
|---|---|
| `init` | 建工作区目录结构;`shop.json` 不存在就从 `config/shop.example.json` 复制一份(绝不覆盖已有的) |
| `new-batch <名字>` | 建批次文件夹(结构见下) |
| `import-legacy --from <旧项目路径> --batch <名字>` | 把旧项目 `data/` 里的数据文件转成新格式放进批次;`images/` 用目录联接(Windows junction,不需要管理员)指过去,不复制 |
| `price` | 读 `candidates.csv` → 写 `priced.csv`(逻辑照旧 `pricing.py`,参数从 `shop.json` 读) |
| `fill` | 读批次数据 → 写 `output/miravia_upload.xlsm`(逻辑照旧 `fill_template.py`,改成按表头认列,见第 4 条) |
| `check` | 不写文件,只检查批次数据能不能填表(文案、条码、下拉值、图片、制造商),列出所有问题 |
| `status` | 每一步做到哪了(有没有条码清单/候选/定价/文案/图片/输出,输出是否比输入新),按文件推出来,不另存状态文件 |
| `categories --search <词>` | 在模板的类目下拉里搜,打印完整类目文字(给 agent 选类目用) |
| `gpsr` | GPSR 标签(照旧 `gpsr_labels.py`,公司资料从 `shop.json` 读,商品短名和安全提示从批次数据读) |
| `overlay` / `images-collect` / `images-urls --base-url <url>` | 照旧 `overlay.py` / `collect_images.py` / `make_images_csv.py`,路径改成批次内 |

旧项目的 `image_layout.py`、`line_icons.py` 等被引用的模块一起搬过来。`seedream*.py` 这次不搬。

### 2. 工作区(每人一份,不在本仓库)
位置:`--ws` > 环境变量 `MIRAVIA_WS` > `~/.miravia-listing.json` 里的 `{"workspace": ...}` >
默认 = 系统"文档"文件夹下的 `Miravia工作区`(用 Windows 已知文件夹取,本机是 `E:\我的文件\文档`,
**不要**拼 `%USERPROFILE%\Documents`)。
```
<工作区>/
  shop.json                 店铺配置
  template/                 自己后台下载的官方模板 .xlsm(shop.json 指定用哪个)
  batches/<批次>/
    barcodes.txt            选好的条码(下个任务用,先建空文件)
    candidates.csv  variantes.csv  content.json  overlays.json
    image_files.csv  images.csv  priced.csv
    images/                 图片
    output/miravia_upload.xlsm
```
文件格式沿用旧项目(表头不变),只有一处改动:**原来写死在代码里的每链接数据搬进 `content.json`**:
`fill_template.py` 的 `CATEGORIES`、`gpsr_labels.py` 的 `NAMES` / `GENERAL`,放进对应 group 的条目里
(字段名你定,写进 `references/数据格式.md`);B 组(组合装,如 `G01B`)没写就继承主组(`G01`)。
`import-legacy` 负责把这些从旧代码里的常量转进 `content.json`。

### 3. 店铺配置 `shop.json`(一人一份)
`config/shop.example.json` 放本店现在的值当示例,所有旧项目里的店铺级常量都进来,比如:
- 定价:`COST_FACTOR`、`PACKAGING`、费率、优惠券余量、`MIN_PROFIT`、`PROFIT_RATE`、`SPREAD_WARN`、`SHIP_TIERS`、划线价倍数
- `STOCK_DEFAULT`、品牌(现在填 "Sin marca")、用哪个模板文件
- 批发商:按友购商家 id(`7868`、`3321`、`027`、`6850`…)列公司名、地址、邮箱(GPSR 标签用),
  以及模板下拉里的制造商 / 欧盟负责人原文(现在的 `data/fabricantes.json`)。
  `6850` 现在用的是 ZHENGDA COMERCIO 的资料,照抄即可。
- 图床:先留 `"image_host": null`,后面任务填。

每个字段在 `references/店铺配置.md` 里用一两句中文说明是什么、怎么改。
读配置时缺字段要报清楚缺哪个,不要静默用默认值。

### 4. 填表按表头认列(重点)
旧 `fill_template.py` 用固定列号(`values[12]`、第 48/50/51/52 列样式、`dropdown(wb, 61)` 等)。
米拉维亚换模板时列可能挪位,改成:
- 用 `Pantilla` 表第 1 行表头找列(第 2–4 行是说明)。一张"字段 → 表头文字"对照表放一处。
- 表头可能带店名后缀,例如库存列是 `Stock<br/><b>HIPER YANG</b>`,按前缀认。图片列 `Imágenes de producto1..8`、
  变体图列(旧代码 `variation_image_column` 已按说明认,保留)。
- 必填字段找不到或找到多个 → 报错停下,说清是哪个表头;多出来的不认识的列不管。
- 下拉值校验(类目、制造商、欧盟负责人、危险品、警告 Sí/No)、单元格样式也按找到的列。
- 保留旧做法:openpyxl `keep_vba=True` 只用来读和校验;写文件时只替换 `Pantilla` 的 sheetData/dimension,
  其他 ZIP 成员逐字节复制;`verify_integrity` 照旧。

### 5. 测试
- `tests/smoke_test.py`:一条命令跑完,自带小样本(`tests/fixtures/`:2–3 个 group,含一个多变体、一个 B 组合装、
  一份店铺配置、模板复制一份进来),依次跑 `init`(临时工作区)→ `price` → `fill` → 独立检查输出
  (把旧 `smoke_test.py` 里跟图片目录无关的检查搬过来)→ 打印 `SMOKE OK`。不依赖旧项目、不依赖用户工作区、不联网。
- `tests/regress_legacy.py`:**跟旧项目对拍**。旧项目不存在就打印 SKIP 退出 0。
  在 `.tmp/` 建临时工作区 → `import-legacy --from E:\我的文件\桌面\Miravia` → `price` → `fill`,然后比:
  - 新 `priced.csv` 和旧项目 `data/priced.csv` 每行每列数值一致;
  - 新输出和旧项目 `output/miravia_upload.xlsm` 的 `Pantilla` 表每个单元格值一致。
  旧项目这两个文件是 2026-10-09 12:21 用旧代码刚生成的,当基准用;对不上就是新代码有问题,别去改旧项目。
  (旧项目的图片检查现在有一个已知失败"Bundle shared image differs",是图片还没做完,跟本任务无关。)

### 6. 其他
- `references/电商经验.md`:从旧项目 `docs/电商经验.md` 原样复制。
- `requirements.txt`:openpyxl、Pillow。
- 本仓库 `AGENTS.md` 里的命令如有变化就更新。

## 做完的标准
1. `python tests/smoke_test.py` → `SMOKE OK`
2. `python tests/regress_legacy.py` → 全部一致(或列出每处差异并说明原因)
3. 本仓库代码里搜不到写死的列号、店铺常量、批发商资料、旧项目路径(测试里的旧项目路径除外)
4. `python scripts/mlist.py --help` 和每个子命令 `--help` 能看懂

## 规矩
不要 git commit,不要动 `.git`;不要往旧项目写任何文件;不要改模板原文件;只在本仓库里写文件。
最后回复:改了哪些文件、两条测试的原样输出(最后几行)、你拿不准或偏离任务包的地方。
