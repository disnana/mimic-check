import sys
import argparse
import time

import toml
import requests
import subprocess
import os
import re
import json
import datetime
from pathlib import Path

# キャッシュと設定の管理
DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.toml"
CACHE_FILE = Path.home() / ".mimic_package_cache.json"
USER_CONFIG_FILE = Path.home() / ".mimic_config.toml"
REMOTE_CONFIG_URL = "https://raw.githubusercontent.com/disnana/mimic-check/main/config.toml"


def load_remote_config():
    try:
        res = requests.get(REMOTE_CONFIG_URL, timeout=5)
        if res.status_code == 200:
            return toml.loads(res.text)
    except Exception:
        pass
    return None


def load_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def get_stats(pkg_name, config):
    if pkg_name in config.get("trusted_packages", []):
        return {"downloads": 999999, "stars": 999999, "date": "trusted"}
    # キャッシュを読み込む（存在しない場合は空）
    cache = load_cache()
    today = str(datetime.date.today())

    # キャッシュの有効性チェック（当日分のみ有効）
    if pkg_name in cache:
        cached_data = cache[pkg_name]
        if cached_data.get("date") == today and cached_data.get("downloads", 0) > 0:
            return cached_data

    stats = {"downloads": 0, "stars": 0, "date": today}

    # 1. Downloads (pypistats)
    try:
        url = f"https://pypistats.org/api/packages/{pkg_name}/recent"
        for _ in range(3):
            res = requests.get(url, headers={'User-Agent': 'Mimi-Security-Scanner'}, timeout=5)
            if res.status_code == 200:
                # 公式APIのレスポンス構造(辞書型)に合わせる
                data = res.json().get("data", {})
                stats["downloads"] = data.get("last_month", 0)
                break
            elif res.status_code == 404:
                # 404の場合はPyPIに存在しないとみなし、チェックを即座に終了
                stats["not_found"] = True
                return stats
            else:
                time.sleep(1*_)
                continue
    except Exception as e:
        print(f"DEBUG: Pypistats failed for {pkg_name}: {e}")

    # 2. Stars (GitHub API)
    try:
        pypi_res = requests.get(f"https://pypi.org/pypi/{pkg_name}/json", timeout=5)
        if pypi_res.status_code == 200:
            pypi_res = pypi_res.json()
            urls = pypi_res["info"].get("project_urls", {})
            if urls:
                candidates = [url for url in urls.values() if "github.com" in url]
                repo_path = None

                for url in candidates:
                    # 除外キーワード
                    if any(k in url for k in ["/sponsors/", "/issues/", "/pulls/"]):
                        continue
                    # 正確なキャプチャ
                    match = re.search(r"github\.com/([^/]+)/([^/]+)", url)
                    if match:
                        repo_path = f"{match.group(1)}/{match.group(2)}"
                        break

                if repo_path:
                    api_url = f"https://api.github.com/repos/{repo_path}"
                    gh_res = requests.get(api_url, headers={'User-Agent': 'Mimi-Security-Scanner'}, timeout=5)
                    if gh_res.status_code == 200:
                        stats["stars"] = gh_res.json().get("stargazers_count", 0)
    except Exception as e:
        print(f"DEBUG: GitHub lookup failed for {pkg_name}: {e}")

    # 基準を満たした場合のみキャッシュする（＝未合格ならキャッシュされず、次回も再検証される）
    min_dl = config.get("min_downloads", 1000)
    min_st = config.get("min_stars", 10)

    if stats["downloads"] >= min_dl or stats["stars"] >= min_st:
        cache[pkg_name] = stats
        save_cache(cache)

    return stats


def levenshtein_distance(s1, s2):
    s1, s2 = s1.lower(), s2.lower()
    if len(s1) < len(s2): s1, s2 = s2, s1
    if len(s2) == 0: return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def analyze_package(pkg_name, config):
    # タイポチェック
    for famous in config.get("famous_packages", []):
        dist = levenshtein_distance(pkg_name, famous)
        if 0 < dist <= 2:
            return f"🚨 TYPO ALERT: '{pkg_name}' is close to '{famous}'"

    # 安全性評価 (configで閾値を可変に)
    stats = get_stats(pkg_name, config)

    if stats.get("not_found"):
        return f"🚨 NOT FOUND: '{pkg_name}' was not found on PyPI"

    downloads = stats["downloads"]
    stars = stats["stars"]

    min_dl = config.get("min_downloads", 1000)
    min_st = config.get("min_stars", 10)

    if downloads >= min_dl or stars >= min_st:
        return None

    return f"⚠️ UNVERIFIED: '{pkg_name}' (Downloads: {downloads}, Stars: {stars})"


def main():
    # WindowsのコンソールでUnicode出力をサポートするための設定
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="requirements.txt")
    parser.add_argument("--config")
    parser.add_argument("--ci", action="store_true")
    args = parser.parse_args()

    # 設定ファイルの読み込み優先順位:
    # 1. 引数 --config
    # 2. ユーザーホームディレクトリの .mimic_config.toml
    # 3. カレントディレクトリの config.toml
    # 4. パッケージ同梱のデフォルト config.toml

    # 設定ファイルの読み出し
    config = None
    config_path = None

    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            config = toml.load(config_path)
    elif USER_CONFIG_FILE.exists():
        config_path = USER_CONFIG_FILE
        config = toml.load(config_path)
    elif Path("config.toml").exists():
        config_path = Path("config.toml")
        config = toml.load(config_path)

    # ローカルに見つからない場合はリモート(GitHub)を試行
    if config is None:
        config = load_remote_config()
        if config:
            config_path = REMOTE_CONFIG_URL

    # リモートもダメなら同梱のデフォルト
    if config is None:
        config_path = DEFAULT_CONFIG_PATH
        if config_path.exists():
            config = toml.load(config_path)

    if config is None or "mimi" not in config:
        print(f"Config load error: Could not find valid config")
        sys.exit(1)

    config = config["mimi"]

    with open(args.file, "r") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    safe_lines = []
    for line in lines:
        match = re.match(r"^([a-zA-Z0-9\-_.]+)", line)
        if not match: continue
        pkg_name = match.group(1)

        issue = analyze_package(pkg_name, config)
        if issue:
            print(issue)
            if args.ci: sys.exit(1)
            if input(f"Proceed with '{line}'? [y/N]: ").lower() != 'y': continue

        safe_lines.append(line)

    tmp_file = "requirements.tmp.txt"
    with open(tmp_file, "w") as f:
        f.write("\n".join(safe_lines))

    subprocess.run([sys.executable, "-m", "pip", "install", "-r", tmp_file])
    os.remove(tmp_file)


if __name__ == "__main__":
    main()
