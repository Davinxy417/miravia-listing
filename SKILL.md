---
name: miravia-listing
description: 把友购(Yollgo)批发商品做成米拉维亚(Miravia 西班牙站)批量上架表:按条码抓友购商品和原图、分组成链接和变体、定价、调研同款写西语标题描述、Seedream 出 8 张带字设计图和 GPSR 标签、推图床、填官方 .xlsm 模板,可整夜全自动跑完。用户说"上架这些条码""米拉维亚上新""做上传表""给这批货出图/写文案/定价"时使用。
---

# 米拉维亚上架(友购 → Miravia)

使用者是店主,不看代码。你负责把流程走完。
所有命令:`python <本skill目录>/scripts/mlist.py <步骤> [--batch <批次>] [--json]`(下面简写 `mlist`)。
命令出错时会用中文说明怎么办;照做。`mlist status --batch <批次>` 随时看做到哪一步。
工作区配好后不用加 `--ws`(找工作区的顺序:`--ws` > 环境变量 `MIRAVIA_WS` > `~/.miravia-listing.json` > 系统"文档"下的 `Miravia工作区`)。
Windows 上先设 `PYTHONIOENCODING=utf-8`,否则自己用 Python 读中文文件/打印会报 cp1252 编码错。
**本 skill 的规则优先于你记忆里的旧偏好**(尤其旧的"不编造、保守写"):卖点按 `references/文案规则.md` 大胆写。

## 两种模式
- **全自动(默认)**:`shop.json` 的 `auto.enabled` 为 true(没写也算 true)。用户交代完条码就去睡觉了:**不要停下来问,也不要等回复**,
  一路做到出表和报告。下面每步的"全自动:"写了该怎么自己定;每个自己做的决定(跳过了什么、估了什么、换了什么)一句话写进批次 `notes.md`。
  遇到真做不下去的(友购登不上、Key 没设、预算用完),把能做的都做完,写进 notes.md,最后照样出报告。
- **看着做**:用户说"这批我要看着做/每步给我看",或 `auto.enabled` 为 false。在标 → 的地方停下来给用户看、等确认;花钱用 `--yes` 且先问。

## 规矩(两种模式都要遵守)
- **不碰密码**:友购由 Edge 自动填密码、程序点登录;登不上就请用户自己在窗口里登。不读、不打印、不保存任何 token/Key/密码。
- **花钱**:Seedream 全自动用 `seedream --auto`(按 `shop.json` 的 `auto` 预算自动放行,超了跳过,不算错);永远不要为了出图绕过预算。
- **建新的公开仓库**(第一次设图床)一定先问用户。往已设好的图床推图不用问。
- **不替用户在米拉维亚后台提交**:最终表交给用户自己上传。
- 认证和标志(CE、FDA、certificado、homologado、grado médico)、疗效、别人的品牌名不写;其余卖点按 `references/文案规则.md` 大胆写。
- GPSR 标签不能伪造成真实照片:标签是平面设计,用户打印贴到货上。
- 写标题/文案、定价、出图前读对应规则:`references/文案规则.md`、`references/出图规则.md`、`references/电商经验.md`(经验是参考,不是死规定)。
- 每步做完一句话告诉用户结果;别把命令输出整段贴给用户。

## 第一次用(工作区不存在或 `shop.json` 没填)——这一段要和用户一起做
1. `mlist init`,然后看 `references/店铺配置.md`,和用户一起把 `shop.json` 填好:店铺用的利润/运费参数(不知道就用示例值)、
   批发商资料(公司名、地址、邮箱、模板下拉里的制造商/欧盟负责人原文)、`auto` 预算(默认每个链接 15 单位、每批 150 单位)。
2. 让用户从米拉维亚后台下载批量上传模板(.xlsm)放进工作区 `template/`,`shop.json` 的 `template` 写文件名。
   批发商要先在后台 Setting → Manufacturer information management 登记成制造商和欧盟负责人,审核通过后重新下载模板,下拉里才有。
3. 友购登录:跑一次 `mlist yollgo-login`,弹出的 Edge 窗口里让用户登录并让 Edge 记住密码;以后程序会自己点登录。
   友购同一账号同一时间只认一个登录:抓货时手机 App 会被挤下线。
4. 出图 Key:请用户自己在终端运行 `setx ARK_API_KEY "Key"` 后重开(见 README.md);图床第一次用 `mlist image-host-setup`(问用户)。
5. 提醒用户:要整夜自动跑,Codex 权限设成"完全访问"("自动审批"会拒掉付费出图和推图床),电脑别睡眠。
   不想开完全访问,就每次第一句话写明授权:`全自动上架 <条码>。我授权按 shop.json 预算调用 Seedream 付费出图、把图推到图床、把文案发给 Claude 打磨,中途不用问我。`

## 上一批货
1. **建批次、收条码**:`mlist new-batch <名字>`(名字用日期+一句话,如 `2026-11-圣诞`),把用户给的条码一行一个写进批次的 `barcodes.txt`。
   用户给完条码后告诉他"开始了,早上看报告"即可。
2. **抓友购**:`mlist fetch --batch <批次> --auto`(会弹 Edge 窗口、自动登录)。
   - 找不到的条码、批发商还没登记进模板的:全自动跳过,记 notes.md。
   - **"已经上过"**(米拉维亚一个条码只能上一次,`build` 会拦):全自动从分组里去掉,记 notes.md;看着做时问用户。
   - **多家都有**:选 `shop.json` 里 `suppliers` 排在前面的那家(不一定最便宜),各家价格记 notes.md。
   - **起订量大于 1** 只是提醒:照样按单件卖,不要把整包当一个 SKU 定价;记 notes.md(会压货)。
   - 友购自动登录失败:停在这一步,notes.md 写清楚,出报告(`mlist report`),结束。
3. **分组**(你判断):看 `src/_sheet.jpg` 和 `yollgo.json`,决定哪些条码是同一个链接的不同尺寸/颜色、一个货号拆几个颜色(看图)、
   重量和包装尺寸估计、要不要做 2 件装(B 链接)。写 `groups.json`,照 `references/数据格式.md` 里"groups.json 完整例子"那一节。
   - 每个条码必填 `weight_kg`、`len_cm`、`wid_cm`、`hei_cm`,估计的写 `"estimado": true`。只有一种变体(只分颜色)时只写 `var1_name`/`var1_value`,不写 var2。
   - 变体名和取值用西语(`Tamaño`、`Color`;`Crema`、`Gris`、`Rosa`、`Azul marino`…)。
   - 重量/包装参考(上一批估的,拿货称重后再改):毛毯 130x160 约 1.2 kg / 35×30×10;热水袋 0.45 kg / 35×22×5;
     门底挡风条 95cm 0.4 kg / 100×8×5;保温杯 0.5L 0.45 kg / 28×10×10;宠物垫 0.5 kg / 40×30×6;宠物衣 0.15 kg / 25×20×3;
     香薰蜡烛杯 0.9 kg / 25×10×10;暖气片晾衣架 0.7 kg / 60×12×6。
   - 原图有品牌/卡通/IP 图案(如 "Tommy"、迪士尼):全自动跳过这个组,记 notes.md。
   需要同系列其他尺寸时用 `mlist yollgo-search --auto --shop <id> <词>`。
   → 看着做:给用户看一张短表(链接 / 包含哪些条码和颜色 / 估计重量)。然后 `mlist build --batch <批次>`。
4. **定价**:`mlist price --batch <批次>`。有价差提醒就记 notes.md。→ 看着做:给用户看每个 SKU 进价、售价、每单利润。
5. **调研同款**:按 `references/文案规则.md`"调研同款"一节上网找同款,写批次根 `research.json`(参考标题、卖点、规格、搜索词)。
6. **文案**:按 `references/文案规则.md` 写 `content.json`(标题、描述、属性、安全提示、类目、GPSR 短名、出图用的外观描述、
   `use_scene` 真实用法、`hero_feature` 主打卖点)和 `overlays.json`(图上的西语文字,卖点取自 research.json)。
   初稿写完按"文案打磨"一节交给 Claude(或自己)改一轮,让描述和图上的字更诱人。类目用 `mlist categories --search <词>` 查原文。
   写完 `mlist check --batch <批次>` 直到没有错误。→ 看着做:给用户看标题和图上的字。
7. **出图**(一律用 Seedream,不用 Codex/GPT 自带出图,不要自己改成无字模式):`mlist images-plan --batch <批次>`,规则见 `references/出图规则.md`。
   - 04/05/07/08 要真人素材:先从 Pexels/Unsplash 下载合适的照片放进批次 `internal/stock/`,记进 `stock_fotos.csv`。
   - 先只出每个变体的 01:`mlist seedream --batch <批次> --auto --only <组/变体/01>...`;审过 01 后重跑 `images-plan`,
     再 `mlist seedream --batch <批次> --auto --all-missing` 出其余位置。结果里 `over_budget` 的记 notes.md。
   - 报"缺 ARK_API_KEY":停止出图,notes.md 写"请设 Key",接着做不需要图的步骤,最后出报告。你不读也不写 Key。
   - 生成完 `mlist images-finish --batch <批次>`,再 `mlist images-sheet --batch <批次> --pending` 出审阅拼图。
   - **全自动:你自己审**,照 `references/出图规则.md`"AI 自审"一节 `images-review --ok/--redo`;重做的先 `images-plan`,再 `seedream --auto --only <重做的 id>`(`--all-missing` 不含重做)。
     → 看着做:给用户看拼图,按他说的审。
8. **GPSR 标签**:`mlist gpsr --batch <批次>`(`output/gpsr/print_A4.pdf`,用户打印贴货)。
9. **发布图片**:`mlist publish-images --batch <批次> --yes`(全自动直接推;看着做时先不带 `--yes`,告诉用户张数,同意再推)。
   还没设图床:跳过,notes.md 写"要先设图床",接着出报告。
10. **出表**:`mlist finalize --batch <批次> --max-groups <shop.json 的 auto.max_groups_per_file>`(会自动把卖点图和场景图插进描述)。不为真的话 notes.md 写清还差什么。
11. **报告**:`mlist report --batch <批次>`,生成批次根 `早上看这里.md`。最后对用户只说:能不能上传、表在哪、花了多少、要他看的几件事,
    并给出报告的路径。上传方法:后台 → 商品 → 批量上传,选 .xlsm;分了几份就分几天传。
12. **传完抽查**(用户回来后):请他给几个商品前台链接(或店铺页),抽查约 1/10:类目对不对、图有没有裂、价格是不是表里的。
    平台报的错原样记进批次 `notes.md`,能改规则的告诉用户。

## 中途接手
先 `mlist status --batch <批次>` 并读 `notes.md`,从第一个没完成的步骤接着做;已经审过的图、确认过的分组和价格不要推翻重来。
