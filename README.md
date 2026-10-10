# miravia-listing

把友购(Yollgo)批发商品做成米拉维亚(Miravia 西班牙站)批量上架表的 skill,Claude Code 和 Codex 都能用。
用法见 `SKILL.md`;装好后对 AI 说"米拉维亚上新"或"上架这些条码"即可。

**第一次用？先看 [使用说明.md](使用说明.md)**(从下载到每天怎么用,不用懂代码)。

## 安装(给 AI 照做,Windows)

1. 需要:Git、Python 3.12、GitHub CLI(`gh`,推图床用)、Edge(系统自带)。缺的用 `winget install` 装。
2. 下载(放哪都行,下面以用户目录为例):
   ```
   git clone https://github.com/Davinxy417/miravia-listing.git "%USERPROFILE%\miravia-listing"
   ```
3. 装依赖:`python -m pip install -r "%USERPROFILE%\miravia-listing\requirements.txt"`(友购用系统 Edge,不用 `playwright install`)。
4. 链接到 skill 目录(用了哪个 AI 就链哪个,目录不存在先建):
   ```
   mklink /J "%USERPROFILE%\.claude\skills\miravia-listing" "%USERPROFILE%\miravia-listing"
   mklink /J "%USERPROFILE%\.codex\skills\miravia-listing" "%USERPROFILE%\miravia-listing"
   ```
5. 自检:`python "%USERPROFILE%\miravia-listing\tests\smoke_test.py"` 打印 OK。
6. 出图用 Seedream(BytePlus)API。**Key 由用户自己设**,AI 不经手:用户在自己的终端里运行
   `setx ARK_API_KEY "你的Key"`,然后重开终端和 AI。
7. 图床要 GitHub 账号:用户自己运行 `gh auth login` 登录。
8. 开新对话说"米拉维亚上新",skill 会带着建工作区、填店铺资料(`shop.json`)、放后台下载的模板。

更新:在下载的文件夹里 `git pull`。
