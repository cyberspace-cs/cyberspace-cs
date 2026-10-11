#!/usr/bin/env python3
"""
rank-gate.py — GitHub 等级展示门控
==================================
规则：**只有等级达到 A 及以上（S / A+ / A）才展示等级圆环**，否则隐藏。

原理
----
1. 通过 GitHub API 采集六项指标
2. 用与 github-readme-stats 完全一致的算法复算等级
3. 等级 >= A → 卡片 URL 不加 hide_rank（显示圆环）
   等级 < A  → 卡片 URL 加 hide_rank=true（隐藏圆环）
4. 改写 README 中<!-- rank-gate:start --> 到 <!-- rank-gate:end --> 之间的内容

安全性
------
- 幂等：同样的输入产生同样的输出，可重复运行
- 只改动标记块内的内容，块外内容原样保留
- 采集失败时直接退出，不做任何修改（fail-safe，绝不误删内容）
- 不需要 token 也能工作（仅用公开 API），有 token 时限流更宽松

用法
----
    python rank-gate.py --user cyberspace-cs
    python rank-gate.py --user cyberspace-cs --readme README.md --dry-run
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------- 等级算法
# 与 anuraghazra/github-readme-stats 及 stats-organization/github-stats-extended
# 的 calculateRank 完全一致（源码级复刻）
THRESHOLDS = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
LEVELS = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]

# 只有这三个等级允许展示
SHOW_RANKS = {"S", "A+", "A"}

# 卡片服务：官方推荐的后继项目（github-readme-stats 已停止维护）
CARD_HOST = "https://github-stats-extended.vercel.app"

MARK_START = "<!-- rank-gate:start -->"
MARK_END = "<!-- rank-gate:end -->"


def exp_cdf(x):
    return 1 - 2 ** (-x)


def log_cdf(x):
    return x / (1 + x)


def calculate_level(commits, prs, issues, reviews, stars, followers):
    """复刻官方 calculateRank，返回 (level, percentile)"""
    weighted = (
        2 * exp_cdf(commits / 250)      # COMMITS_MEDIAN 250, weight 2
        + 3 * exp_cdf(prs / 50)         # PRS_MEDIAN 50, weight 3
        + 1 * exp_cdf(issues / 25)     # ISSUES_MEDIAN 25, weight 1
        + 1 * exp_cdf(reviews / 2)     # REVIEWS_MEDIAN 2, weight 1
        + 4 * log_cdf(stars / 50)      # STARS_MEDIAN 50, weight 4
        + 1 * log_cdf(followers / 10)  # FOLLOWERS_MEDIAN 10, weight 1
    ) / 12.0
    rank = 1 - weighted
    level = LEVELS[next(i for i, t in enumerate(THRESHOLDS) if rank * 100 <= t)]
    return level, rank * 100


# ---------------------------------------------------------------- GitHub API
class GitHub:
    def __init__(self, token=None, retries=3):
        self.token = token
        self.retries = retries
        self.opener = urllib.request.build_opener()

    def get(self, path):
        url = "https://api.github.com" + path
        last = None
        for attempt in range(self.retries):
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "rank-gate",
            })
            if self.token:
                req.add_header("Authorization", "Bearer " + self.token)
            try:
                with self.opener.open(req, timeout=45) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                # 4xx 是确定性错误，重试无意义
                if e.code < 500:
                    raise
                last = e
            except Exception as e:
                # 网络中断 /IncompleteRead / 超时等
                last = e
            time.sleep(1.5 * (attempt + 1))
        raise last if last else RuntimeError("unknown error")

    def paginate(self, path, max_pages=3):
        out = []
        for p in range(1, max_pages + 1):
            sep = "&" if "?" in path else "?"
            batch = self.get("%s%sper_page=100&page=%d" % (path, sep, p))
            if not batch:
                break
            out += batch
            if len(batch) < 100:
                break
        return out


def collect(gh, user):
    """采集六项指标"""
    profile = gh.get("/users/" + user)
    repos = gh.paginate("/users/%s/repos?type=owner&sort=full_name" % user)

    # 完整性校验：分页静默失败会导致 star 总数偏小，宁可整体放弃
    if len(repos) < 10:
        raise RuntimeError("repo list looks truncated: %d repos" % len(repos))

    stars = sum(r.get("stargazers_count", 0) or 0 for r in repos)
    followers = profile.get("followers", 0) or 0

    # 近一年提交数
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    commits = gh.get("/search/commits?q=author:%s+committer-date:>=%s&per_page=1"
                     % (user, since)).get("total_count", 0)
    prs = gh.get("/search/issues?q=author:%s+type:pr&per_page=1"
                 % user).get("total_count", 0)
    issues = gh.get("/search/issues?q=author:%s+type:issue&per_page=1"
                    % user).get("total_count", 0)

    return {
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "reviews": 0,       # 公开 API 拿不到准确值，按 0 计（官方卡片缺省亦为 0）
        "stars": stars,
        "followers": followers,
    }


# ---------------------------------------------------------------- README
def build_block(user, theme, stats, level, percentile):
    """生成标记块内容"""
    show = level in SHOW_RANKS
    rank_param = "" if show else "&hide_rank=true"
    url_stats = ("%s/api?username=%s&show_icons=true&theme=%s%s"
                 % (CARD_HOST, user, theme, rank_param))
    url_langs = ("%s/api/top-langs/?username=%s&layout=compact&theme=%s"
                 % (CARD_HOST, user, theme))

    state = "展示等级圆环" if show else "隐藏等级圆环"
    badge = ("✅ 等级 **%s**（全球前 %.1f%%）已达标，圆环已展示"
             % (level, percentile)) if show else \
            ("🔒 当前等级 **%s**（全球前 %.1f%%），未达 A 门槛，圆环已隐藏"
             % (level, percentile))

    return (
        "{s}\n"
        "\n"
        "<!-- 本区块由 rank-gate.py 自动生成，请勿手动编辑 -->\n"
        "<!-- 规则：等级 >= A(S/A+/A) 才展示圆环；数据每日自动刷新 -->\n"
        "\n"
        "<!-- 状态：{state} -->\n"
        "<!-- 指标：commits={c} prs={p} issues={i} reviews={r} stars={st} followers={f} -->\n"
        "\n"
        "<div align=\"center\">\n"
        "\n"
        "![{user}'s GitHub stats]({u1})\n"
        "![Top Langs]({u2})\n"
        "\n"
        "</div>\n"
        "\n"
        "<sub>{badge} · 更新于 {ts}</sub>\n"
        "{e}"
    ).format(
        s=MARK_START, e=MARK_END, state=state, badge=badge,
        c=stats["commits"], p=stats["prs"], i=stats["issues"],
        r=stats["reviews"], st=stats["stars"], f=stats["followers"],
        user=user, u1=url_stats, u2=url_langs,
        ts=datetime.datetime.now().strftime("%Y-%m-%d"),
    )


def replace_block(text, new_block):
    """替换标记块内容；标记不存在则追加到末尾"""
    pattern = re.compile(
        re.escape(MARK_START) + r".*?" + re.escape(MARK_END),
        re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _: new_block, text)
    return text.rstrip() + "\n\n" + new_block + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--theme", default="vue")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gh = GitHub(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))

    print("[rank-gate] 采集 GitHub 数据: %s" % args.user, file=sys.stderr)
    try:
        stats = collect(gh, args.user)
    except Exception as e:
        # fail-safe：任何采集异常都不改动 README，绝不误删内容
        print("[rank-gate] 数据采集失败（%s: %s），已跳过，README 未改动"
              % (type(e).__name__, str(e)[:120]), file=sys.stderr)
        return 0

    level, pct = calculate_level(**stats)
    show = level in SHOW_RANKS

    print("[rank-gate] 指标: %s" % stats, file=sys.stderr)
    print("[rank-gate] 等级: %s (%.2f%%) -> %s"
          % (level, pct, "展示" if show else "隐藏"), file=sys.stderr)

    with open(args.readme, encoding="utf-8") as f:
        original = f.read()

    updated = replace_block(original, build_block(
        args.user, args.theme, stats, level, pct))

    if updated == original:
        print("[rank-gate] README 无需变更", file=sys.stderr)
        return 0

    if args.dry_run:
        print("[rank-gate] --dry-run，未写入", file=sys.stderr)
        print(updated)
        return 0

    with open(args.readme, "w", encoding="utf-8", newline="\n") as f:
        f.write(updated)
    print("[rank-gate] 已更新 %s" % args.readme, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())