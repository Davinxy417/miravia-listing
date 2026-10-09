# 任务 A4:图床(GitHub 公开仓库)+ 发布图片 + 出最终表

## 背景
本仓库 `E:\我的文件\桌面\miravia-listing` 是米拉维亚上架 skill(先读 `AGENTS.md`、`references/数据格式.md`、
`references/店铺配置.md`、`python scripts/mlist.py --help`)。A1–A3 已完成:工作区/批次/定价/填表、友购抓取、出图步骤。

米拉维亚批量上传表里的图片必须是**公开可访问、以 `.jpg` 结尾的直链**。用户定了:每人一个 **GitHub 公开仓库**只放商品图
(本机已登录 `gh`,账号 Davinxy417)。本任务把"审过的成品图 → 推到图床 → 生成 `images.csv` → 重新填表"做成命令。

## 1. 店铺配置
`shop.json` 的 `image_host`(A1 留了 `null`)改成:
```json
"image_host": {"type": "github", "repo": "<账号>/<仓库名>", "branch": "main",
               "base_url": "https://raw.githubusercontent.com/<账号>/<仓库名>/main"}
```
`base_url` 可改(比如以后换 jsDelivr)。`references/店铺配置.md` 和示例一起更新;示例里仍是 `null`,写清怎么填。

## 2. 命令
| 子命令 | 作用 |
|---|---|
| `image-host-setup --repo <名字>` | 用 `gh` 建**公开**仓库(已存在就直接用)、克隆到 `<工作区>/.image-host/<名字>/`、写回 `shop.json`。**不带 `--yes` 只说明要做什么然后退出码 2**(建公开仓库是对外操作,agent 必须先问用户)。仓库里放一个 README:"本仓库只存放店铺商品图"。 |
| `publish-images` | 把本批次**审过(`image_review.json` 里 ok)**的成品图复制进本地克隆,提交、推送;然后写 `images.csv`(网址 = `base_url` + 发布路径)。**不带 `--yes` 只列出要推哪些(张数、总大小、目标仓库、没审过被跳过的)然后退出码 2**。`--include-unreviewed` 才推没审过的。推送后逐个抽查几条网址能访问(HEAD 200,`Content-Type` 是图片),访问不了要报出来。 |
| `finalize` | 一条龙收尾:`images-collect` → `images-urls`(或直接用 publish 写好的 `images.csv`)→ `fill` → `check`;最后说清楚表在哪、还差什么(没有占位链接、没有缺制造商才算"可以上传"),`--json` 里 `upload_ready`。 |

`finalize` 另外两件事:
- **上架台账**:`upload_ready` 为真时,往工作区根目录 `台账.csv` 追加本批次每个 SKU 一行
  (日期、批次、组、变体、EAN、卖家 SKU、批发商 id、友购货号、进价、实际成本、售价、每单利润);同一批次重跑不重复追加(按批次+EAN 覆盖)。
  出单后对账、以后回头查成本用。
- **分批**:`--max-groups N` 时把表拆成几份(`miravia_upload_1.xlsm`…),每份不超过 N 个链接,同一链接(含它的 B 组)不拆开。
  默认不拆。给"一次别全放出去、分几天匀速上新"用。

发布路径规则:**只用小写 ASCII**(字母数字 `-` `/`),`<批次 slug>/<组>/<变体>/<文件名>.jpg`;批次名可能是中文
(如 `2026-10-冬季第一批`),slug 要能稳定复现(同一批次每次一样)且不同批次不撞,规则写进 `references/数据格式.md`。
图片内容变了要能重新发布(同路径覆盖,或带版本号避免平台缓存旧图 —— 你选一个,写清理由)。

`.image-host/` 是工作区里的东西,不进本仓库。不要用 `git push --force`。推送失败(没登录、没权限、网络)要说人话。

## 3. 测试(离线)
用本地 bare 仓库假装 GitHub(不调真的 `gh`、不联网):测 setup 不带 `--yes` 不动手、publish 只推审过的、
重复 publish 只推变化的、`images.csv` 网址格式、slug 稳定、finalize 的 `upload_ready` 判断。
`gh` 和网址抽查那层薄薄包一层,测试里替掉。已有测试都要照样通过。

## 做完的标准
1. 所有测试通过(贴最后几行)。
2. `image-host-setup / publish-images / finalize --help` 看得懂。
3. **不要**真的建仓库或推送(Claude 验收时会先问用户再做)。

## 规矩
不要 git commit,不要动 `.git`(本仓库的);不要往旧项目写;只在本仓库写文件(和 `.tmp/`)。
最后回复:改了哪些文件、测试原样输出(最后几行)、拿不准的地方。
