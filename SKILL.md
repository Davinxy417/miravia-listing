---
name: miravia-listing
description: 把友购(Yollgo)批发商品做成米拉维亚(Miravia 西班牙站)批量上架表:按条码抓友购商品和原图、分组成链接和变体、定价、写西语标题描述、按店铺规则出 8 张展示图和 GPSR 标签、推图床、填官方 .xlsm 模板。用户说"上架这些条码""米拉维亚上新""做上传表""给这批货出图/写文案/定价"时使用。
---

# 米拉维亚上架(友购 → Miravia)

使用者是店主,不看代码。你负责把流程走完,只在下面写明的几个地方停下来问。
所有命令:`python <本skill目录>/scripts/mlist.py <步骤> [--batch <批次>] [--json]`(下面简写 `mlist`)。
命令出错时会用中文说明怎么办;照做,做不到再问用户。`mlist status --batch <批次>` 随时看做到哪一步。

## 规矩(必须遵守)
- **停下来问用户**:建公开仓库、推图片到图床、Seedream 付费出图、任何会被别人看到或花钱的操作。
  命令不带 `--yes` 时只告诉你要做什么并退出(退出码 2)——把它说的内容转述给用户,用户说可以再加 `--yes`。
- **不碰密码**:友购登录由用户在弹出的窗口里自己输入;不读、不打印、不保存任何 token/Key。
- **不替用户在米拉维亚后台提交**:最终表交给用户自己上传。
- 不编造:尺寸、材质、成分、认证只写友购资料或图上看得到的;重量尺寸可以估,但要标"估计"。
- GPSR 标签不能伪造成真实照片:标签是平面设计,用户打印贴到货上。
- 写标题/文案、定价、出图前读对应规则:`references/文案规则.md`、`references/出图规则.md`、`references/电商经验.md`(经验是参考,不是死规定)。
- 每步做完一句话告诉用户结果;别把命令输出整段贴给用户。

## 第一次用(工作区不存在或 `shop.json` 没填)
1. `mlist init`,然后看 `references/店铺配置.md`,和用户一起把 `shop.json` 填好:店铺用的利润/运费参数(不知道就用示例值)、
   批发商资料(公司名、地址、邮箱、模板下拉里的制造商/欧盟负责人原文)。
2. 让用户从米拉维亚后台下载批量上传模板(.xlsm)放进工作区 `template/`,`shop.json` 的 `template` 写文件名。
   批发商要先在后台 Setting → Manufacturer information management 登记成制造商和欧盟负责人,审核通过后重新下载模板,下拉里才有。
3. `mlist yollgo-login`:弹出 Edge 窗口,请用户自己登录友购,登录一次以后会记住。

## 上一批货
1. **建批次、收条码**:`mlist new-batch <名字>`(名字用日期+一句话,如 `2026-11-圣诞`),把用户给的条码一行一个写进批次的 `barcodes.txt`。
2. **抓友购**:`mlist fetch --batch <批次>`。找不到的条码、批发商还没登记的,告诉用户。
3. **分组**(你判断):看 `src/_sheet.jpg` 和 `yollgo.json`,决定哪些条码是同一个链接的不同尺寸/颜色、一个货号拆几个颜色(看图)、
   重量和包装尺寸估计、要不要做 2 件装(B 链接)。写 `groups.json`(格式见 `references/数据格式.md`)。
   需要同系列其他尺寸时用 `mlist yollgo-search --shop <id> <词>`。
   → **给用户看一张短表**(链接 / 包含哪些条码和颜色 / 估计重量),确认后 `mlist build --batch <批次>`。
4. **定价**:`mlist price --batch <批次>`。→ **给用户看**:每个 SKU 进价、售价、每单利润;有价差提醒也说。用户要改就改 `shop.json` 或单个价格再重跑。
5. **文案**:按 `references/文案规则.md` 写 `content.json`(标题、描述、属性、安全提示、类目、GPSR 短名、出图用的外观描述)
   和 `overlays.json`(图上的西语文字)。类目用 `mlist categories --search <词>` 查原文。写完 `mlist check --batch <批次>` 直到没有错误。
6. **出图**:`mlist images-plan --batch <批次>`,照 `image_plan.md` 一张张做,规则见 `references/出图规则.md`。
   - 你是 Codex:用自带图像生成,原图存到清单写的 `internal/raw/`。额度用完(429)就停,告诉用户恢复时间,问要不要用 Seedream 补。
   - 你是 Claude:自己不能出图。本机有 `~/.agent-bridge/codex.cmd` 就把 `image_plan.md` 里没做的部分转给 Codex
     (`codex exec`,任务里写清批次路径和"照 image_plan.md 做,只写 internal/raw/");没有就用 Seedream。
   - Seedream:`mlist seedream --batch <批次> --only <id>...`,先不带 `--yes` 看张数和费用,**问用户**再加 `--yes`。
   - 生成完 `mlist images-finish --batch <批次>`,再 `mlist images-sheet --batch <批次> --pending` 出审阅拼图。
   → **给用户看拼图**,按他说的 `mlist images-review --ok ... / --redo <id> --note "..."`;重做的回到 images-plan。
7. **GPSR 标签**:`mlist gpsr --batch <批次>`,告诉用户 `output/gpsr/print_A4.pdf` 在哪,打印贴货。
8. **发布图片**:第一次要图床时 `mlist image-host-setup --repo <名字>`(先不带 `--yes`,**问用户**同意建公开仓库)。
   `mlist publish-images --batch <批次>`(先不带 `--yes`,把张数和仓库告诉用户,**同意后**再推)。
9. **出表**:`mlist finalize --batch <批次>`。`upload_ready` 为真才告诉用户"可以上传",说清表的位置:
   后台 → 商品 → 批量上传,选这个 .xlsm。不为真就说还差什么。
   链接多(十几个以上)时建议 `--max-groups` 拆成几份,分几天传,匀速上新比一次全放稳。
10. **传完抽查**:用户传完后,请他给几个商品前台链接(或店铺页),抽查约 1/10:类目对不对、图有没有裂、价格是不是表里的。
    平台报的错原样记进批次 `notes.md`,能改规则的告诉用户。

## 中途接手
先 `mlist status --batch <批次>`,从第一个没完成的步骤接着做;已经审过的图、用户确认过的分组和价格不要推翻重来。
