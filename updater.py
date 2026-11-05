"""从固定 GitHub Release 检查和校验安装包。"""
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = 'noisy-fly/image-stego-workbench'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
ASSET_NAME = 'StegoWorkbench-Setup.exe'
MAX_INSTALLER = 250 * 1024 * 1024


def version_key(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?', value)
    if not match: raise ValueError('无法识别的版本号。')
    major, minor, patch = (int(v) for v in match.group(1, 2, 3))
    prerelease = match.group(4)
    identifiers = tuple((0, int(x)) if x.isdigit() else (1, x) for x in prerelease.split('.')) if prerelease else ()
    return major, minor, patch, 1 if prerelease is None else 0, identifiers


def allowed_url(url):
    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or '').lower()
        return (parts.scheme == 'https' and not parts.username and not parts.password and parts.port in (None, 443)
                and (host in ('github.com', 'api.github.com') or host.endswith('.githubusercontent.com')))
    except ValueError: return False


class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl): raise ValueError('下载地址跳转到非 GitHub 域名，已停止。')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_https(url):
    if not allowed_url(url): raise ValueError('不允许的更新地址。')
    request = urllib.request.Request(url, headers={'User-Agent': 'StegoWorkbench-Updater', 'Accept': 'application/vnd.github+json'})
    return urllib.request.build_opener(GitHubRedirect()).open(request, timeout=20)


def parse_release(data):
    tag = data.get('tag_name', ''); version_key(tag)
    if data.get('draft') or data.get('prerelease'): raise ValueError('没有可用的正式版。')
    assets = [a for a in data.get('assets', []) if a.get('name') == ASSET_NAME]
    if len(assets) != 1: raise ValueError('Release 中没有唯一的 Windows 安装包。')
    asset = assets[0]; url = asset.get('browser_download_url', ''); parsed = urllib.parse.urlsplit(url)
    expected_path = f'/{REPO}/releases/download/{tag}/{ASSET_NAME}'
    if not allowed_url(url) or parsed.hostname.lower() != 'github.com' or parsed.path != expected_path or parsed.query or parsed.fragment:
        raise ValueError('安装包地址与项目 Release 不匹配。')
    digest = asset.get('digest') or ''
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest): raise ValueError('Release 未提供有效的 SHA-256 校验值。')
    size = asset.get('size')
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_INSTALLER:
        raise ValueError('安装包大小无效或超过限制。')
    return {'tag': tag, 'url': url, 'sha256': digest[7:].lower(), 'size': size}


def fetch_latest():
    with open_https(API) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024: raise ValueError('Release 信息过大。')
    return parse_release(json.loads(payload.decode('utf-8')))


def should_prompt(info, current, ignored, manual=False):
    return version_key(info['tag']) > version_key(current) and (manual or info['tag'] != ignored)


def download_installer(info, directory, progress=None, cancel=None):
    directory = Path(directory)
    target = directory / ASSET_NAME
    if target.exists(): raise ValueError('更新文件已存在。')
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix='download_', suffix='.part', dir=directory, delete=False) as output:
            temp_name = Path(output.name); total = 0; digest = hashlib.sha256()
            with open_https(info['url']) as response:
                while True:
                    if cancel and cancel(): raise InterruptedError('已取消下载。')
                    chunk = response.read(256 * 1024)
                    if not chunk: break
                    total += len(chunk)
                    if total > info['size'] or total > MAX_INSTALLER: raise ValueError('下载大小超出 Release 声明。')
                    output.write(chunk); digest.update(chunk)
                    if progress: progress(total, info['size'])
        if total != info['size'] or digest.hexdigest() != info['sha256']:
            raise ValueError('安装包大小或 SHA-256 校验不匹配。')
        os.replace(temp_name, target); temp_name = None
        return str(target)
    finally:
        if temp_name is not None: temp_name.unlink(missing_ok=True)
