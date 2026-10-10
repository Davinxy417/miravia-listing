# 任务 A7:修夜跑发现的 skill 问题

仓库 `E:\我的文件\桌面\miravia-listing`,分支 `feat/auto`。先读 `AGENTS.md`、`SKILL.md`、`references/`。
夜跑批次(只读参考,不要改):`E:\文档\Miravia工作区\batches\2026-10-10-夜跑-cubertero`,问题原文在其 `notes.md`"给 Claude 的问题"一节,
审图拼图 `review/final.jpg`(04 多出一个短格、08 少一格,被自审拦下)。

店主已定方向不变:卖点爆款写法(只禁认证、医疗、别家品牌)、不准 emoji、标题 55～128、全自动少问。

## 要修(对应 notes 编号)
1. `yollgo-search` 结果带上 namees、货号(usercode)、原图下载(存到批次或工作区 `search/<shop>/<artId>.jpg`,并生成一张候选总览拼图),
   方便 agent 看图选品。保持不读写凭据的现有约束。
2. build 生成 candidates 时保留中文名和西语名两份原文(如 `src_name_cn`/`src_name_es`),尺寸/规格解析(06 脚本、GPSR、verified_specs)两边都读;
   不覆盖原始字段。旧批次/回归基准保持兼容。
3. 02 构图:按商品宽高比给出互相兼容的版面参数(宽扁商品不能同时要求"右侧 55% 版面"和"最长边 75%"),保证四角完整、留安全边距。
4. 结构锁定:content 新增可选 `structure_lock`(中文,如"长方形托盘,1 个纵向长格在左 + 4 个横向格在右,共 5 格,隔板固定"),
   进入所有槽位提示词的商品锁定;04/05/07/08 附件里除主图外再附一张能看清结构的正视/俯视原图(有就附),角色写"图N锁定结构和隔板数量"。
   出图规则 AI 自审:结构数量(格数、按钮数、件数)逐项数,对不上即不通过。
5. gpsr 诊断准确列出缺的具体字段(只缺尺寸就只说尺寸)。
6. 文档矛盾统一:数据格式.md 里"友购命令无界面"的旧说法;电商经验里"直接改 candidates.csv"与 build 哈希规则冲突(改成改 groups.json 后重新 build);
   gpsr_safety 文档与 SKILL 要求统一(缺资料时按商品用途写 3～5 条通用西语安全提示)。
7. 失败组被拦时 publish-images 不要再建议 `--include-unreviewed`,改为列出失败的 id 和原因;finalize 全是草稿时不提示上传表/完整备份;
   report 区分"没执行 finalize"和"执行了但全是草稿",并写清"要上传还差哪几张图重做、预计多少单位"。
8. 01/variante 导出时做规范白底:只把接近白色的背景像素(如 RGB 都 ≥ 245 且与边缘连通)置为 #FFFFFF,保留商品和柔和阴影;有测试。

## 做完的标准
- 全部测试 OK(`PYTHONIOENCODING=utf-8`):smoke_test、regress_legacy、auxiliary_test、test_yollgo、test_images、test_publish、test_auto、test_keywords、test_a6;
  为 1～8 补离线测试。不联网、不调真实服务,不碰 `E:\文档\Miravia工作区`(批次只读)。
- **不要 git commit,不要动 .git。** 最后中文列出改了哪些文件。
