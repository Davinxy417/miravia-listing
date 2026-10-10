"""GitHub 图床：确认前纯预览；只提交本批次选中的成品。"""
import hashlib
import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .common import Problem, inside, require, write_csv, write_json, CSV_FIELDS
from .image_layout import SLOTS, output_dir, hero_variant, variant_folders
from .image_workflow import review_data


def file_digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def slug(value):
    """Readable prefix + hash of the exact original name (including case)."""
    prefix = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    prefix = re.sub('[^a-z0-9]+', '-', prefix).strip('-')[:40].rstrip('-') or 'batch'
    return prefix + '-' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]


def validate_host(host):
    require(isinstance(host, dict) and host.get('type') == 'github',
            'shop.json.image_host 应为 GitHub 图床对象；请先运行 image-host-setup。')
    repo = host.get('repo', '')
    require(isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', repo)
            and len(repo.split('/')[1]) <= 100 and not repo.endswith('/.git'),
            'image_host.repo 应为 账号/仓库名，不能是网址或本地路径。')
    branch = host.get('branch', '')
    require(isinstance(branch, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_/-]*', branch)
            and '..' not in branch and not branch.endswith('/') and '//' not in branch,
            'image_host.branch 应为有效分支名，例如 main。')
    base_url = host.get('base_url', '')
    require(isinstance(base_url, str), 'image_host.base_url 应为 HTTP(S) 网址前缀。')
    try:
        base = urlsplit(base_url)
        valid = base.scheme in ('http', 'https') and base.hostname and not base.username and not base.password
    except ValueError:
        valid = False
    require(valid and not base.query and not base.fragment and not re.search(r'\s', base_url),
            'image_host.base_url 应为 HTTP(S) 网址前缀，不能含认证信息、空格、查询参数或 #。')
    return host


def command(argv, cwd=None, allow_failure=False):
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=120,
                                env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GH_PROMPT_DISABLED='1'))
    except FileNotFoundError as exc:
        raise Problem(f'找不到 {argv[0]}；请安装 Git 和 GitHub CLI（gh），再运行 gh auth login 登录。') from exc
    except subprocess.TimeoutExpired as exc:
        raise Problem('图床命令超时；请检查网络后重试，未强制推送。') from exc
    if result.returncode and not allow_failure:
        # Never expose credential-bearing command lines or server diagnostics.
        raise Problem('图床操作失败；请确认 gh auth login 已登录、账号有仓库写权限、网络正常；然后重跑本步骤。若分支冲突，请先同步本地图床克隆。')
    return result


def gh(*args, allow_failure=False):
    return command(['gh', *args], allow_failure=allow_failure)


def git(directory, *args, allow_failure=False):
    return command(['git', '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
                    '-c', 'user.name=Miravia Listing', '-c', 'user.email=miravia-listing@users.noreply.github.com',
                    '-c', 'core.quotepath=false', *args], cwd=directory, allow_failure=allow_failure)


def remote_url(host):
    return f'https://github.com/{host["repo"]}.git'


def clone_path(ws, repo):
    return inside(ws, Path(ws) / '.image-host' / repo.split('/')[1])


def verify_clone(ws, host):
    directory = clone_path(ws, host['repo'])
    require(directory.is_dir(), '本地图床克隆不存在；请先运行 image-host-setup --repo 账号/仓库名 --yes。')
    # Reject nested repositories / symlinked metadata before invoking Git.
    inside(directory, directory / '.git')
    require((directory / '.git').is_dir(), '本地图床目录不是独立 Git 克隆；请换一个仓库名或检查 .image-host 目录。')
    top = git(directory, 'rev-parse', '--show-toplevel').stdout.strip()
    require(Path(top).resolve() == directory, '图床目录不是独立克隆；不能使用程序仓库作为图床。')
    branch = git(directory, 'branch', '--show-current').stdout.strip()
    require(branch == host['branch'], f'本地图床分支不是 {host["branch"]}；请切回配置的分支再发布。')
    remote = git(directory, 'remote', 'get-url', 'origin').stdout.strip()
    require(remote == remote_url(host),
            '本地图床 origin 与 shop.json.image_host.repo 不一致；请核对配置，避免推错仓库。')
    return directory


def setup(ws, shop, repo, yes=False, branch='main'):
    require(isinstance(repo, str) and re.fullmatch(r'(?:[A-Za-z0-9][A-Za-z0-9-]*/)?[A-Za-z0-9][A-Za-z0-9_.-]*', repo),
            '--repo 请填仓库名或 账号/仓库名，不能是网址。')
    validate_host(dict(type='github', repo=repo if '/' in repo else 'account/' + repo,
                       branch=branch, base_url='https://raw.githubusercontent.com/account/repo/main'))
    message = f'将建立或使用公开图床 {repo}，克隆到工作区 .image-host/{repo.split("/")[-1]}/，缺 README 时补写并推送，最后写回 shop.json。'
    if not yes:
        return dict(needs_confirm=True, exit_code=2, errors=['请先确认公开仓库操作，同意后加 --yes。'], message=message)
    if '/' not in repo:
        owner = gh('api', 'user', '--jq', '.login').stdout.strip()
        repo = owner + '/' + repo
    host = validate_host(dict(type='github', repo=repo, branch=branch,
                              base_url=f'https://raw.githubusercontent.com/{repo}/{branch}'))
    directory = clone_path(ws, repo)
    inside(ws, Path(ws) / 'shop.json')
    info = gh('repo', 'view', repo, '--json', 'isPrivate,nameWithOwner', allow_failure=True)
    if info.returncode:
        # Only an explicit not-found response permits creation; auth/network errors stop.
        require('Could not resolve to a Repository' in info.stderr or 'Not Found' in info.stderr,
                '无法确认图床仓库是否存在；请先运行 gh auth login，并检查网络与仓库名后重试。')
        gh('repo', 'create', repo, '--public', '--description', '本仓库只存放店铺商品图')
        info = gh('repo', 'view', repo, '--json', 'isPrivate,nameWithOwner')
    metadata = json.loads(info.stdout)
    require(metadata.get('isPrivate') is False and metadata.get('nameWithOwner', '').casefold() == repo.casefold(),
            '这个仓库不是指定的公开仓库；请使用公开商品图仓库，程序不会自动更改可见性。')
    remote = remote_url(host)
    if not directory.exists():
        directory.parent.mkdir(parents=True, exist_ok=True)
        git(directory.parent, 'clone', '--', remote, str(directory))
        heads = git(directory, 'ls-remote', '--heads', 'origin').stdout
        if heads.strip():
            require(f'refs/heads/{branch}' in heads.split(), f'仓库没有 {branch} 分支；请用 --branch 指定已有分支。')
            git(directory, 'checkout', branch)
        else:
            git(directory, 'symbolic-ref', 'HEAD', f'refs/heads/{branch}')
    verify_clone(ws, host)
    require(not git(directory, 'status', '--porcelain').stdout.strip(),
            '本地图床有未提交改动；请先处理 .image-host 里的改动，再重跑 setup。')
    heads = git(directory, 'ls-remote', '--heads', 'origin').stdout.split()
    ref = sync(directory, branch) if f'refs/heads/{branch}' in heads else None
    if ref:
        outgoing = git(directory, 'log', '--format=', '--name-only', f'{ref}..HEAD').stdout.splitlines()
        require(set(filter(None, outgoing)) <= {'README.md'},
                '本地图床有非 README 的待推送提交；请先处理后重新 setup。')
    else:
        head_exists = git(directory, 'rev-parse', '--verify', 'HEAD', allow_failure=True).returncode == 0
        history = git(directory, 'log', '--format=', '--name-only').stdout.splitlines() if head_exists else []
        require(set(filter(None, history)) <= {'README.md'},
                '远端分支不存在，而本地图床含已有商品提交；请核对仓库与分支后再 setup。')
    readme = inside(directory, directory / 'README.md')
    if not readme.exists():
        readme.write_text('本仓库只存放店铺商品图\n', encoding='utf-8')
        git(directory, 'add', '--', 'README.md')
        git(directory, 'commit', '-m', '说明商品图仓库用途', '--', 'README.md')
    # Also retries the README push if an earlier setup stopped after the commit.
    if ref is None or git(directory, 'rev-list', '--count', f'{ref}..HEAD').stdout.strip() != '0':
        git(directory, 'push', '-u', 'origin', f'HEAD:refs/heads/{branch}')
    old = shop.get('image_host')
    if isinstance(old, dict) and old.get('repo') == repo and old.get('branch') == branch:
        host['base_url'] = old.get('base_url', host['base_url'])
    shop = dict(shop, image_host=validate_host(host))
    write_json(Path(ws) / 'shop.json', shop)
    return dict(repo=repo, output=str(directory), message='公开图床已就绪，已有 README 和其他内容均保留；shop.json 已更新。')


def selection(batch, include_unreviewed=False):
    from .image_readiness import group_issues
    failures = group_issues(batch)
    reviews = review_data(batch)['reviews']
    groups = variant_folders(batch / 'variantes.csv')
    items, skipped = [], []
    for group, variants in sorted(groups.items()):
        hero = hero_variant(group, variants, batch / 'images')
        for variant in variants:
            names = {'variante': 'variante.jpg'}
            if variant == hero:
                names.update(SLOTS)
            for slot, filename in sorted(names.items()):
                path = output_dir(batch / 'images', group, variant) / filename
                jid = f'{group}/{variant}/{slot}'
                if group in failures:
                    skipped.append(dict(id=jid, reason='；'.join(failures[group])))
                    continue
                if not path.is_file():
                    skipped.append(dict(id=jid, reason='缺成品图'))
                    continue
                sha = file_digest(path)
                record = reviews.get(jid, {})
                reviewed = record.get('result') == 'ok' and record.get('sha256') == sha
                if not reviewed and not include_unreviewed:
                    reason = '要重做' if record.get('result') == 'redo' else '没审过或图片已变化'
                    skipped.append(dict(id=jid, reason=reason))
                    continue
                rel = f'{slug(batch.name)}/{slug(group)}/{slug(variant)}/{filename}'
                items.append(dict(id=jid, group=group, variante=variant, slot=slot, path=rel,
                                  sha256=sha, size=path.stat().st_size, source=path, reviewed=reviewed))
    require(len({i['path'] for i in items}) == len(items), '发布路径出现重名；请检查组和变体名称。')
    return items, skipped


def head_image(url):
    """Thin replaceable network boundary; no credentials are read or sent."""
    try:
        with urlopen(Request(url, method='HEAD'), timeout=10) as response:
            return dict(url=url, ok=response.status == 200 and response.headers.get_content_type().startswith('image/'),
                        status=response.status, content_type=response.headers.get_content_type())
    except Exception:
        return dict(url=url, ok=False, status=None, content_type=None)


def samples(urls, limit=5):
    if len(urls) <= limit:
        return urls
    return [urls[round(i * (len(urls) - 1) / (limit - 1))] for i in range(limit)]


def sync(directory, branch, allowed_dirty=()):
    dirty = git(directory, 'status', '--porcelain', '--untracked-files=all', '-z').stdout
    # Prior failed copy/add may be retried, but unrelated work must never enter a commit.
    entries = [x for x in dirty.split('\0') if x]
    require(all(len(x) > 3 and x[:2] in ('??', ' M', 'M ', 'A ', 'AM') and x[3:] in allowed_dirty for x in entries),
            '本地图床有与本次发布无关的改动；请先处理 .image-host 里的改动再重试。')
    git(directory, 'fetch', 'origin', f'refs/heads/{branch}:refs/remotes/origin/{branch}')
    ref = f'refs/remotes/origin/{branch}'
    if git(directory, 'merge-base', '--is-ancestor', ref, 'HEAD', allow_failure=True).returncode == 0:
        return ref
    require(not dirty and git(directory, 'merge-base', '--is-ancestor', 'HEAD', ref, allow_failure=True).returncode == 0,
            '本地图床与远端分支冲突；请先同步 .image-host 中的分支，再重新发布。程序不会强制推送。')
    git(directory, 'merge', '--ff-only', ref)
    return ref


def publish(ws, batch, shop, yes=False, include_unreviewed=False):
    host = validate_host(shop.get('image_host'))
    items, skipped = selection(batch, include_unreviewed)
    total = sum(i['size'] for i in items)
    summary = f'拟发布 {len(items)} 张，共 {total} 字节，目标公开仓库 {host["repo"]}（{host["branch"]}）；跳过 {len(skipped)} 张。'
    result = dict(repo=host['repo'], count=len(items), total_bytes=total, skipped=skipped,
                  files=[{k: v for k, v in i.items() if k != 'source'} for i in items], message=summary)
    if not yes:
        return dict(result, needs_confirm=True, exit_code=2, errors=['请确认发布名单，同意后加 --yes。'])
    require(items, '没有可发布图片；请补齐成品并用 images-review --ok 审阅，或明确加 --include-unreviewed。')
    for name in ('images.csv', 'image_publish.json'):
        inside(batch, batch / name)
    metadata = json.loads(gh('repo', 'view', host['repo'], '--json', 'isPrivate,nameWithOwner').stdout)
    require(metadata.get('isPrivate') is False and metadata.get('nameWithOwner', '').casefold() == host['repo'].casefold(),
            '配置的图床不是指定的公开仓库；请核对仓库名和可见性后重试。')
    directory = verify_clone(ws, host)
    destinations = {i['path']: inside(directory, directory / i['path']) for i in items}
    ref = sync(directory, host['branch'], destinations)
    # An interrupted push is safe to retry only when *all* outgoing commits belong
    # to this selection. This prevents accidentally publishing older unapproved work.
    outgoing = git(directory, 'log', '--format=', '--name-only', f'{ref}..HEAD').stdout.splitlines()
    require(set(filter(None, outgoing)) <= set(destinations),
            '本地图床有不属于本次已选图片的待推送提交；请先处理这些提交，再重新发布。')
    for item in items:
        target = destinations[item['path']]
        if not target.is_file() or file_digest(target) != item['sha256']:
            blob = item['source'].read_bytes()
            require(hashlib.sha256(blob).hexdigest() == item['sha256'],
                    f'{item["id"]} 在发布期间被修改；请重新审阅后再发布。')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
    # Stage only exact selected paths, in bounded batches for Windows command limits.
    paths = list(destinations)
    for start in range(0, len(paths), 40):
        git(directory, 'add', '--', *paths[start:start + 40])
    staged = git(directory, 'diff', '--cached', '--name-only').stdout.splitlines()
    require(set(staged) <= set(paths), '暂存区混入了其他文件；请处理本地图床后重试。')
    if staged:
        git(directory, 'commit', '-m', '发布商品图片 ' + slug(batch.name))
    # Do not push when nothing changed. Retry a previously failed push when ahead.
    ahead = git(directory, 'rev-list', '--count', f'{ref}..HEAD').stdout.strip() != '0'
    if ahead:
        git(directory, 'push', 'origin', f'HEAD:refs/heads/{host["branch"]}')
    rows = [{k: i[k] for k in ('group', 'variante', 'slot')} |
            {'url': host['base_url'].rstrip('/') + '/' + i['path']} for i in items]
    checks = [head_image(url) for url in samples([r['url'] for r in rows])]
    errors = [f'图片直链抽查失败：{c["url"]}（HTTP {c["status"]}，类型 {c["content_type"]}）；请检查网络和图床/CDN，稍后重跑 publish-images。'
              for c in checks if not c['ok']]
    write_csv(batch / 'images.csv', rows, CSV_FIELDS['images.csv'])
    write_json(batch / 'image_publish.json', dict(version=1, host={k: host[k] for k in ('type', 'repo', 'branch', 'base_url')},
               files=result['files'], checks=checks, commit=git(directory, 'rev-parse', 'HEAD').stdout.strip()))
    return dict(result, changed=len(staged), pushed=ahead, checks=checks, errors=errors,
                output=str(batch / 'images.csv'), message=f'发布完成，本次提交变化图片 {len(staged)} 张；images.csv 已生成。')
