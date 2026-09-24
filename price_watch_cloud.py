#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逆水寒黄金畅玩服 铜钱价格盯价脚本（手机推送版）
=================================================
盯 dd373、7881 上 女儿国/花果山/水帘洞 的最低单价。
任一服「1万铜钱」跌破阈值，就通过 Bark 推送到你的 iPhone。

【原理】手机本身不运行脚本。脚本跑在「常开的电脑」或「云服务器/免费定时任务」上，
到价时用 Bark（iOS 免费 App）把提醒推送到你手机。

【手机端一次性准备】
1. App Store 安装免费 App「Bark」
2. 打开 Bark，复制里面的「推送地址」，形如  https://api.day.app/AbCdEf123456
   在 iPhone 上直接访问它，能收到通知即表示可用。

【运行方式】（选一种，详见 README_手机版部署说明.md）
  A. 常开的电脑：  python price_watch_cloud.py --loop    （推荐，5 分钟级实时）
  B. GitHub Actions 免费定时：按说明传到 GitHub，自动每 15 分钟跑一次
  C. 云服务器：    nohup python price_watch_cloud.py --loop &

【参数】
  --loop   常驻循环（默认），适合电脑 / 服务器
  --once   只检查一次后退出，适合定时任务（GitHub Actions / cron）
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

# ============ 配置区（改这里） ============
THRESHOLD   = 4.80      # 目标价：1万铜钱低于此价就提醒
CHECK_EVERY = 300       # --loop 模式下每隔几秒查一次（300=5分钟）
SERVERS     = ["女儿国", "花果山", "水帘洞"]

# 你的 Bark 推送地址：把「在这里填你的Bark推送地址」替换成从 Bark App 复制的那串。
# 支持多个地址（比如手机+备用手机），每行一个。
# 也可以不填这里，用环境变量 BARK_URL 传入（GitHub Actions 方式）。
BARK_URLS = [
    "https://api.day.app/在这里填你的Bark推送地址",
]
# ==========================================

URLS = {
    # dd373 已按比例最佳排序；7881 打开后会自动点「比例最好」
    "dd373": "https://www.dd373.com/s-xu9np3-0-0-0-wdxrj-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
    "7881":  "https://search.7881.com/G6065-100001-G6065P002-0-0.html?pageNum=1",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "price_watch_state.json")

from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import Stealth
    _HAS_STEALTH = True
except Exception:
    _HAS_STEALTH = False


def new_page(ctx):
    page = ctx.new_page()
    if _HAS_STEALTH:
        try:
            Stealth().apply_stealth_sync(page)
        except Exception:
            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
            except Exception:
                pass
    return page


def parse_dd373(html):
    result = {}
    for b in re.split(r"游戏区服", html)[1:]:
        rm = re.search(r"黄金畅玩服[/／]\s*([^\s(（<]{1,6})", b)
        pm = re.search(r"1万铜钱\s*=\s*([\d.]+)\s*元", b)
        if not rm or not pm:
            continue
        room = rm.group(1).strip()
        if room not in SERVERS:
            continue
        price = float(pm.group(1))
        if room not in result or price < result[room]:
            result[room] = price
    return result


def parse_7881(html):
    result = {}
    for b in re.split(r"游戏区服", html)[1:]:
        rm = re.search(r"黄金畅玩服[/／]\s*([^\s(（<]{1,6})", b)
        pm = re.search(r"([\d.]+)\s*元/万铜钱", b)
        if not rm or not pm:
            continue
        room = rm.group(1).strip()
        if room not in SERVERS:
            continue
        price = float(pm.group(1))
        if room not in result or price < result[room]:
            result[room] = price
    return result


PARSERS = {"dd373": parse_dd373, "7881": parse_7881}


def get_bark_urls():
    """环境变量 BARK_URL 优先，其次用配置文件里的 BARK_URLS。"""
    urls = []
    env = os.environ.get("BARK_URL", "").strip()
    if env:
        urls.append(env)
    for u in BARK_URLS:
        u = u.strip().rstrip("/")
        if u and "在这里填你的" not in u:
            urls.append(u)
    # 去重且保持顺序
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def bark_push(title, body):
    """通过 Bark 推送到 iPhone，返回成功推送的设备数。"""
    sent = 0
    for base in get_bark_urls():
        url = (f"{base}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
               f"?sound=alarm&group={urllib.parse.quote('逆水寒')}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                resp.read()
            sent += 1
        except Exception as e:
            print(f"  [推送失败] {base} -> {e}")
    return sent


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        print(f"  [状态保存失败] {e}")


def mark_push(site, room, price, state):
    """去重：只有价格创新低才推送，避免每轮重复轰炸。返回是否要推。"""
    key = f"{site}|{room}"
    prev = state.get(key)
    if prev is not None and float(prev) <= price:
        return False
    state[key] = price
    save_state(state)
    return True


def fetch_all(page):
    out = {}
    for site, url in URLS.items():
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(8000)
            # 随机鼠标移动，更像真人
            try:
                page.mouse.move(300 + (hash(site) % 300), 200 + (hash(site) % 200))
                page.wait_for_timeout(500)
                page.mouse.move(500, 400)
                page.wait_for_timeout(1000)
            except Exception:
                pass
            if site == "7881":
                # 点「比例最好」让单价从低到高
                try:
                    btn = page.get_by_text("比例最好", exact=True).first
                    if btn.is_visible(timeout=3000):
                        btn.click()
                        page.wait_for_timeout(5000)
                except Exception:
                    pass
            html = page.content()
            low = PARSERS[site](html)
            out[site] = low
        except Exception as e:
            print(f"  [{site}] 抓取失败：{e}")
            out[site] = {}
    return out


def run_once():
    """巡检一轮，返回命中列表 [(site, room, price), ...]。"""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 巡检中...")
    hits = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ])
            ctx = browser.new_context(
                user_agent=UA,
                locale="zh-CN",
                viewport={"width": 1366, "height": 768},
                timezone_id="Asia/Shanghai",
            )
            page = new_page(ctx)
            data = fetch_all(page)
            browser.close()
    except Exception as e:
        print(f"  [启动浏览器失败] {e}")
        print("  请确认已安装：pip install playwright && playwright install chromium")
        return hits

    for site, low in data.items():
        if not low:
            print(f"  [{site}] 没解析到价格（可能被滑块拦，先在电脑浏览器里打开一次该网站过验证）")
            continue
        line = "  ".join(f"{r} {v:.4f}" for r, v in sorted(low.items(), key=lambda x: x[1]))
        print(f"  [{site}] {line}")
        for room, price in low.items():
            if price < THRESHOLD:
                hits.append((site, room, price))
    return hits


def handle_hits(hits, state):
    """命中后按创新低去重并推送。"""
    if not hits:
        return
    new_hits = [(s, r, v) for s, r, v in hits if mark_push(s, r, v, state)]
    if not new_hits:
        print("  命中但价格未创新低，跳过推送（防刷屏）")
        return
    lines = [f"【{s}】{r}  1万铜钱 = {v:.4f} 元" for s, r, v in sorted(new_hits, key=lambda x: x[2])]
    body = "\n".join(lines) + f"\n已跌破 {THRESHOLD} 元，快去买！"
    print("!" * 44)
    print(body)
    print("!" * 44)
    if not get_bark_urls():
        print("[提示] 未配置 Bark 推送地址，只在终端打印。")
        return
    sent = bark_push("逆水寒铜钱到价啦", body)
    print(f"  [已推送到 {sent} 台设备]")


def main():
    parser = argparse.ArgumentParser(description="逆水寒铜钱盯价（手机推送版）")
    parser.add_argument("--once", action="store_true", help="只检查一次后退出（配合定时任务）")
    parser.add_argument("--loop", action="store_true", help="常驻循环（默认行为）")
    args = parser.parse_args()

    if not get_bark_urls():
        print("=" * 56)
        print("[警告] 尚未配置 Bark 推送地址！")
        print("  iPhone 上装 Bark App 后，把推送地址填到脚本 BARK_URLS 里，")
        print("  或设置环境变量 BARK_URL，否则不会收到通知。")
        print("=" * 56)

    state = load_state()

    if args.once:
        hits = run_once()
        handle_hits(hits, state)
        return

    print("=" * 56)
    print(" 逆水寒铜钱盯价（手机推送版）已启动")
    print(f" 阈值: 1万铜钱 < {THRESHOLD} 元   每 {CHECK_EVERY} 秒查一次")
    print(" 按 Ctrl+C 或关窗口停止")
    print("=" * 56)
    while True:
        try:
            hits = run_once()
            handle_hits(hits, state)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"  [巡检异常] {e}")
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
#（注：内容由AI生成）
