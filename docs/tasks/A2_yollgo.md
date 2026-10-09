# 任务 A2:友购抓取 + 条码 → 批次数据

## 背景
本仓库 `E:\我的文件\桌面\miravia-listing` 是米拉维亚上架 skill(先读 `AGENTS.md`、`references/数据格式.md`、
`references/店铺配置.md`、`scripts/mlist.py --help`,了解 A1 已经搭好的工作区/批次/店铺配置)。
旧项目 `E:\我的文件\桌面\Miravia` 只读,条码规则的来历见它的 `docs/交接.md`"已定"一节和
`docs/codex_task_06_mantas_colores.md`。

用户在友购(Yollgo)App 里人工选好商品,把**条码**交给程序。本任务让程序:按条码去友购查商品 → 存原始数据和原图 →
agent 判断怎么分组(哪些条码是同一个链接的不同尺寸/颜色、重量尺寸估计)写 `groups.json` → 程序生成
`candidates.csv` / `variantes.csv`(含条码规则)。之后接 A1 已有的 `price` / `fill`。

## 友购网页版(Claude 已实测,2026-10-09)
- 地址 `https://app.yollgo.com`,Ionic/Angular 应用,**必须登录**(手机号 + 密码)。接口带混淆签名,
  **不要**逆向签名或直接调 HTTP 接口;一律在已登录的页面里调用 App 自己的函数:
  ```js
  const inj = angular.element(document.querySelector('[ng-app]')).injector();
  const af = inj.get('ajaxFactory');
  inj.get('storageFactory').userid()   // 未登录是 -1
  (await af.shops()).data.shop_lists   // 用户关注的批发商,24 家左右
  (await af.select({shopid, content: '<条码>', type: 0, from: 0, to: 20})).data.articulo_lists  // 按条码搜,每家一次
  (await af.category({shopid})).data.mulu_lists                       // 分类
  (await af.products({shopid, topid, subid})).data.articulo_lists     // 分类下的商品
  ```
  返回都是 `{code: 1000, ...}`,1000 = 成功。
- 批发商一条:`{"shopId":"3321","name":"乐家居(瓦伦西亚)","namees":"H&J TEXHOGAR S.L.U","des":"…","tel":"…","baseurl":"https://img-eu-2.freex.es","imgurl":"https://img-eu-2.freex.es/img/%@/%@/%dx%d/%@",…}`。
  `des` 里有的写"所有产品已含IVA,不含RECARGO"(如旺达 2822)。
- 商品一条:`{"artId":"1000015560","usercode":"9010186009002","bianhao":"9010186009002","namecn":"MANTA BORREGO 130X160CM AZURITA","namees":"","muluID":"001067","baozhuangshu":1,"precio":6.5,"imageHash":"f8e13d55325363057daa71f7c9317fee","is_attr":0,"attributes":[]}`。
  `bianhao` = 条码;`precio` = 单价;`baozhuangshu` = 起订包装数(12 就是要按 12 个拿货);只有一张图。
- 原图:`{baseurl}/img/{shopId}/{artId}/600x600/{imageHash}`,只有 600x600 能下。
- 同一条码可能多家都有;`artId` 只在一家店内唯一,不同店可能重号。

## 要做的

### 1. 浏览器(Playwright,已装 `playwright` 1.63)
- 用系统自带 Edge:`channel="msedge"`,**不要** `playwright install` 下浏览器。
- 持久化配置目录放工作区 `<工作区>/.yollgo-browser/`(加进 `.gitignore` 说明里;工作区本来就不进仓库)。
- `mlist.py yollgo-login`:有界面打开 Edge 到 `https://app.yollgo.com`,提示"请在弹出的窗口里登录友购",
  等到 `userid() !== -1` 就说"已登录"并关窗。**程序和 agent 都不经手密码**,只由用户在窗口里输入。
- 其他命令无界面运行;发现没登录就停下,提示先跑 `yollgo-login`。不要打印或保存 token。

### 2. `mlist.py fetch --batch <批次>`
- 读批次 `barcodes.txt`:一行一个条码;`#` 开头是注释;条码后面空格隔开的文字原样存为备注。
- 按条码搜:先搜 `shop.json` 里登记过的批发商(按配置顺序),再搜其他关注的批发商。精确匹配 `bianhao` 或 `usercode`。
- 多家都有:全记下来;默认选配置里排前面的那家,都没登记就选最便宜的,并提示。
- 写 `yollgo.json`:每个条码的所有报价(原始字段 + 批发商名/西语名)、选中的那家、抓取时间;
  另写/更新工作区级 `yollgo_shops.json`(批发商公开资料:名称、西语名、说明、电话,给用户去后台登记制造商时参考)。
- 下原图到批次 `src/{shopId}-{artId}.jpg`(已存在就不重下),再拼一张总览 `src/_sheet.jpg`
  (每格:图 + 条码 + 名称 + 价格),给 agent / 用户一眼看全。
- 找不到的条码、选中的批发商不在 `shop.json` 里(制造商会空)、价格为 0 —— 都在结尾列清楚,`--json` 里也有。

### 3. `mlist.py yollgo-search --shop <id> <关键词>`
在某家批发商里按关键词/条码搜,打印条码、名称、价格。给 agent 找同系列其他尺寸用。

### 4. `groups.json`(agent 写,程序校验)+ `mlist.py build --batch <批次>`
`groups.json` 由 agent 按判断写(哪些条码是同一链接、变体名、颜色、重量尺寸估计、要不要组合装)。格式你定,
要求:人和 agent 都好写好读;写进 `references/数据格式.md`,附一个完整例子;`build` 遇到不合法的内容报清楚是哪一组哪一项。
至少要能表达:
- 一个链接(group,编号 `G01`…,批次内唯一)有哪些条码;变体名 1/2(如 `Tamaño` / `Color`)和每个条码的取值;
- 一个条码拆成多个颜色(友购一个货号混色发货,颜色是看图定的)→ 每个颜色一个 SKU;
- 重量(kg)、包装长宽高(cm)—— 必填,agent 估计,标 `"estimado": true`;
- 组合装:如 `"packs": [2]` → 生成 `G01B`,每个 SKU 一个 2 件装,`pack_qty=2`,重量尺寸按件数估或单独写;
- 备注。

`build` 生成 `candidates.csv` / `variantes.csv`(表头和 A1 一致,跟旧项目一样),规则:
- `unit_cost_ex_iva`:批发商在 `shop.json` 里标了含 IVA(新加字段,如 `"price_includes_iva": true`,默认 false)就除以 1.21;
  组合装 = 单件 × 件数。`shop.json` 示例和 `references/店铺配置.md` 一起更新;旺达 2822 在示例里标 true。
- 颜色条码:同一个条码拆出的第一个颜色保留原条码;其余 = 原条码前 11 位 + 颜色号(1–9)+ 重算 GS1 校验位;
  `unit_ean` 保留原条码。
- 组合装条码:`2` + 件数(1 位)+ 对应单件 SKU 条码的后 10 位 + 校验位(共 13 位)。
  (旧项目非毛毯组用的是 artId 后 10 位;artId 不同店会重号,新批次统一用单件条码。)
- 查重:本批次内、工作区所有其他批次的 `candidates.csv`、模板里已有的条码都不能撞;颜色号撞了换下一个号,
  9 个号用完或组合装撞了就报错停下,说清楚是哪个。
- `variante` 文件夹名:自动生成(小写、去重音、只留字母数字和 `-`),可在 `groups.json` 里手动指定。
- `src_name` = 友购名称,`img_hash` = `imageHash`,`shop` = 选中的批发商 id,`art_id` = `artId`;`market_low/high` 留空
  (用户定:不跟竞品定价);`notes` 带上起订包装数和 barcodes.txt 里的备注。
- 已有 `candidates.csv` 时,不加 `--force` 不覆盖。

### 5. 定价小改
`price` 允许 `market_low/high` 为空(空就不比市场价)。旧批次的结果不能变(`tests/regress_legacy.py` 照样全一致)。

### 6. 测试(离线,不登录不联网)
- 浏览器那层薄薄包一层,测试里用假的返回(就用上面的 JSON 样子)替掉:测 fetch 的选店、找不到、多家报价;
  测 build 的颜色条码、组合装条码、查重撞号、含税换算、groups.json 报错信息。
- 加进 `tests/smoke_test.py` 或单独 `tests/test_yollgo.py`,都要一条命令能跑。
- 真登录真抓取由 Claude 验收时跑,你不用跑。

## 做完的标准
1. `python tests/smoke_test.py` → `SMOKE OK`;`python tests/regress_legacy.py` 仍全一致;新测试通过。
2. `mlist.py yollgo-login / fetch / yollgo-search / build --help` 看得懂。
3. `references/数据格式.md` 里有 `barcodes.txt`、`yollgo.json`、`groups.json` 的说明和例子。

## 规矩
不要 git commit,不要动 `.git`;不要往旧项目写;只在本仓库写文件;不要逆向友购签名、不要直接调它的 HTTP 接口。
最后回复:改了哪些文件、测试原样输出(最后几行)、拿不准或偏离任务包的地方。
