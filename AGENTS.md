# AGENTS.md — miravia-listing

这是一个 skill(Claude Code 和 Codex 通用):把友购(Yollgo)批发商品做成米拉维亚(Miravia 西班牙站)
批量上传 Excel。仓库根目录就是 skill 目录(`SKILL.md` 在根上)。使用者是不懂代码的店主,
所有给人看的提示用中文、说人话,出错时说清楚"哪里不对、该怎么办"。

- 入口:`python scripts/mlist.py <步骤> ...`(所有步骤都走它;以后的本地网页也调它)
- 工作区(每人一份,不在本仓库):店铺配置 `shop.json`、官方模板、批次数据、图片、输出。
- 冒烟测试:`python tests/smoke_test.py`(必须打印 `SMOKE OK`)
- 旧基准对拍:`python tests/regress_legacy.py`(只读旧项目,全部一致时打印 `REGRESS OK`;旧项目不存在时 SKIP)
- 辅助模块测试:`python tests/auxiliary_test.py`(GPSR、叠字、图片收集/网址与工作区选择)
- 图片离线测试:`python tests/test_images.py`(假出图接口、不读密钥、不联网，必须打印 `IMAGES OK`)。
- 图床离线测试:`python tests/test_publish.py`(本地 bare 图床、假 gh/HEAD，不碰真实仓库，必须打印 `PUBLISH OK`)。
- 友购离线测试:`python tests/test_yollgo.py`(假浏览器,不登录、不联网,必须打印 `YOLLGO OK`)
- 配置和批次格式:`references/店铺配置.md`、`references/数据格式.md`;核心模块在 `scripts/listing_core/`。
- Python 3.12;依赖只用 openpyxl、Pillow、playwright(仅友购命令使用系统 Edge),要加别的先问。
- 米拉维亚官方 .xlsm 模板必须原样保留宏和数据校验:只改 `Pantilla` 表的 sheetData/dimension,其他 ZIP 成员逐字节复制。
- 电商经验(写标题/文案、改定价、选品):`references/电商经验.md`,是参考不是死规定。

规矩:
- 不要 git commit,不要动 `.git`。
- 仓库里不放密钥、店铺私有数据、商品图片、模板以外的大文件。
- 临时文件放仓库内 `.tmp/`(已忽略)。
