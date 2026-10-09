# 任务 A5:全自动过夜模式(脚本部分)

## 背景
本仓库 `E:\我的文件\桌面\miravia-listing` 是米拉维亚上架 skill(先读 `AGENTS.md`、`SKILL.md`、`references/店铺配置.md`、
`references/数据格式.md`、`python scripts/mlist.py --help`)。A1–A4 已完成并合进 main;本任务在分支 `feat/auto` 上做。

用户要"睡前贴条码,早上拿到能上传的表":agent 全程不停下来问。原来靠 `--yes` 让用户逐次确认的付费出图,改成按店铺预算自动放行;
友购登录过期时自动点登录;最后出一份报告。SKILL.md 和文案/出图规则由 Claude 改,**你不要改 `SKILL.md`、`references/文案规则.md`、
`references/出图规则.md`、`references/电商经验.md`**。

## 1. 店铺配置 `auto`
`shop.json` 新增(示例 `config/shop.example.json`、`tests/fixtures/shop.json`、`references/店铺配置.md` 一起更新;缺这一段时按下面默认值):
```json
"auto": {"enabled": true, "budget_units_per_group": 15, "budget_units_per_batch": 150, "max_groups_per_file": 10}
```
单位就是 `seedream.py` 里估算用的"套餐单位"(每张 1.36 + 第二张起每张参考图 0.09)。配置校验沿用现有风格(数字须 > 0)。

## 2. `seedream --auto`
- 与 `--yes` 互斥。`--auto` 时不需要用户确认,但受预算限制:
  - 已花费 = 本批次 `seedream_log.json` 里所有尝试(含 failed、started——网络不确定也算钱)的单位之和。
    以后每条尝试记录写入 `units`(该次估算单位);旧记录没有 `units` 的按 1.36 计。
  - 按清单顺序逐张放行:放行前检查 本组已花费+本张 ≤ `budget_units_per_group`(组 = id 的第一段,如 `G01`;
    B 组 `G01B` 算自己一组)且 本批已花费+本张 ≤ `budget_units_per_batch`;不满足的跳过,记进结果 `over_budget`(id 列表)并接着看下一张。
  - 现有保护照旧:每 id 最多两次、清单过期拒绝、缺参考图拒绝、单张失败即停(break)。
- 结果 JSON 增加 `spent_units`(本批累计)、`budget`(两个上限)、`over_budget`。`--auto` 下超预算不是错误(退出码 0),有 `errors` 时照旧非 0。
- `auto.enabled` 为 false 时 `--auto` 报错:"店铺未开启全自动,请用 --yes 并先问用户"。

## 3. 友购自动登录(`scripts/listing_core/yollgo_browser.py`)
现状:`session()` 开可见 Edge(持久配置 `<工作区>/.yollgo-browser/`),没登录就提示用户并无限等待。用户已把密码存在这个 Edge 配置里。
登录页(`https://app.yollgo.com/#/account/login`,Angular/Ionic)结构:手机号 `input[ng-model="input.name"]`(type=number),
密码 `input[ng-model="input.password"]`(type=password),登录按钮 `button[ng-click="login()"]`(文字"登录")。

改成:没登录时先**自动尝试一次**:
1. 确保在登录页(不在就 `page.goto(URL + '/#/account/login')`)。
2. 最多等 15 秒,直到密码框被浏览器自动填充:只用 `el.matches(':autofill') || el.matches(':-webkit-autofill')` 判断。
   **绝不读取、打印、记录任何输入框的 value(包括长度)**,不往输入框里填任何东西,不碰 cookie/localStorage 里的凭据。
3. 被填充了:点一下密码框(Playwright 真实点击,让浏览器把自动填充的值交给页面),等 500ms,再点登录按钮;然后最多 30 秒轮询 `session_alive`。
4. 成功 → 照常继续。没填充、页面出现验证码/滑块、或 30 秒没登上 → 退回人工:
   - 交互模式(默认):照旧 `notify` 请用户在窗口里登录并 `wait_for_login`(无限等)。
   - 无人值守模式:最多等 10 分钟(`wait_for_login` 加超时参数),超时抛 `Problem('友购自动登录没成功(可能要验证码或密码失效);请醒来后运行 mlist yollgo-login 手动登录,再重跑 fetch。')`。
   - 不尝试绕过验证码。
- 无人值守模式的开关:`fetch`、`yollgo-search`、`yollgo-login` 加 `--auto` 参数传进 `session(..., unattended=True)`。
- `tests/test_yollgo.py` 的假对象补上:自动填充成功、没填充(退回人工/无人值守超时)两种路径;测试里超时用小数值,不能挂起。

## 4. `mlist report --batch <批次>`
在批次根目录写 `早上看这里.md`(`--json` 同时输出结构化结果),给不看代码的店主看,中文短句:
- 一句话结论:能不能上传(复用 finalize/status 的判断,`upload_ready`),表在哪(`output/` 下的 .xlsm,分了几份列全)。
- 链接与 SKU 数;每个 SKU 售价、每单利润(读 `priced.csv`,一张小表)。
- Seedream:本批花了多少单位、各组多少、`over_budget` 过的 id(读 `seedream_log.json`)。
- 图片审阅:通过/没审/要重做数(复用 status 的统计);要重做或失败的列出 id 和备注。
- 跳过和待办:原样附上批次 `notes.md` 全文(agent 把自动做的决定写在那里)。
- 没有的文件就写"没做到这一步",不报错。

## 5. 其他
- `mlist.py --help` 和各子命令说明同步。
- `references/数据格式.md` 补:`seedream_log.json` 的 `units` 字段、`早上看这里.md`。
- `CHANGELOG.md` 不用改(Claude 合并时写)。

## 做完的标准
- `python tests/smoke_test.py`、`regress_legacy.py`、`auxiliary_test.py`、`test_yollgo.py`、`test_images.py`、`test_publish.py` 全部 OK
  (Windows 下先设 `PYTHONIOENCODING=utf-8`)。新增测试覆盖:预算放行/跳过/累计(含旧日志无 units)、`--auto` 与 `--yes` 互斥、
  `auto.enabled=false` 报错、自动登录两条路径、report 在空批次和完整批次上都能出。
- 不联网、不调用真实 Seedream/友购/GitHub。
- **不要 git commit,不要动 `.git`。** 不要改上面列出的 Claude 负责的四个文件。
- 最后用中文列出改了哪些文件、新增了哪些命令参数。
