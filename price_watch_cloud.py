#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逆水寒黄金畅玩服 铜钱价格盯价脚本（GitHub Actions + Bark 推送版）
直接 requests 抓取 dd373 列表页（不再依赖 Jina Reader，已修复反爬问题）。
"""

import argparse
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

# ============ 配置区 ============
THRESHOLD   = 4.85
CHECK_EVERY = 300
SERVERS     = ["女儿国", "花果山", "水帘洞", "三清山", "云樱岛", "白帝城", "桃花坞"]

BARK_URLS = [
    "https://api.day.app/在这里填你的Bark推送地址",
]
# ================================

# dd373 各区服专属搜索链接（比例最佳排序，最低价优先）
DD373_SERVER_URLS = {
    "女儿国": "https://www.dd373.com/s-xu9np3-h3x9gf-vxuhpf-0-0-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
    "花果山": "https://www.dd373.com/s-xu9np3-h3x9gf-nxc2tt-0-0-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
    "水帘洞": "https://www.dd373.com/s-xu9np3-h3x9gf-g0ra5g-0-0-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
    "三清山": "https://www.dd373.com/s-xu9np3-h3x9gf-0fqqtp-0-0-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
    "云樱岛": "https://www.dd373.com/s-xu9np3-h3x9gf-506c7t-0-0-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
    "白帝城": "https://www.dd373.com/s-xu9np3-h3x9gf-67nuq0-0-0-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
    "桃花坞": "https://www.dd373.com/s-xu9np3-h3x9gf-5uuvn9-0-0-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "price_watch_state.json")


def parse_dd373(html):
    """
    从 dd373 HTML 列表页解析最低单价（元/万铜钱）。
    商品标题格式: "60万铜钱=300.00元" → 300/60 = 5.00 元/万铜钱
    页面已按价格排序，取第一个匹配的即可。
    返回: (最低价, 总商品数) 或 (None, 0)
    """
    # 按商品 item 分割
    items = re.split(r'<div class="goods-list-item">', html)[1:]
    if not items:
        return None, 0

    prices = []
    for item in items:
        # 提取标题
        title_m = re.search(r'goods-list-title[^>]*>.*?<div[^>]*>(.*?)</div>', item, re.DOTALL)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()

        # 匹配 "X万铜钱=Y元" 或 "X万铜钱＝Y元"
        pm = re.search(r'([\d.]+)万铜钱\s*[=＝]\s*([\d,.]+)\s*元', title)
        if not pm:
            continue
        amount_wan = float(pm.group(1))
        total_price = float(pm.group(2).replace(',', ''))
        if amount_wan <= 0:
            continue
        prices.append(total_price / amount_wan)

    if not prices:
        return None, 0
    return min(prices), len(prices)


def get_bark_urls():
    urls = []
    env = os.environ.get("BARK_URL", "").strip()
    if env:
        urls.append(env)
    for u in BARK_URLS:
        u = u.strip().rstrip("/")
        if u and "在这里填你的" not in u:
            urls.append(u)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def bark_push(title, body):
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
    key = f"{site}|{room}"
    prev = state.get(key)
    if prev is not None and float(prev) <= price:
        return False
    state[key] = price
    save_state(state)
    return True


def fetch_direct(url, timeout=15):
    """直接请求 dd373 原站，带浏览器 UA 和 gzip 解压。替代 Jina Reader。"""
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip",
        "Referer": "https://www.dd373.com/",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode("utf-8", errors="ignore")


def run_once():
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 巡检中...")
    watched_prices = {}  # {区服: (站点, 价格)}

    for idx, room in enumerate(SERVERS):
        try:
            if idx > 0:
                time.sleep(3)  # 每个区服之间间隔3秒，避免被反爬

            url = DD373_SERVER_URLS.get(room)
            if not url:
                print(f"  [{room}] 未配置搜索链接，跳过")
                continue

            print(f"  [dd373] 抓取 {room}...")
            html = fetch_direct(url)

            price, count = parse_dd373(html)

            if not price:
                print(f"  [{room}] 没解析到价格（页面 {len(html)} 字, 商品 {count} 个）")
                continue

            print(f"  [{room}] 最低价: {price:.4f} 元/万铜钱（共 {count} 个商品）")
            watched_prices[room] = ("dd373", price)

        except Exception as e:
            print(f"  [{room}] 抓取失败：{e}")

    return watched_prices


def handle_watched(watched_prices):
    if not watched_prices:
        print("  未抓到任何监控区服的价格")
        return

    # 按价格从低到高排序
    sorted_rooms = sorted(watched_prices.items(), key=lambda x: x[1][1])
    cheapest_room, (cheapest_site, cheapest_price) = sorted_rooms[0]

    # 构建通知内容
    lines = [f"当前监控区服行情（共 {len(sorted_rooms)} 个有货）："]
    below_count = 0
    for room, (site, price) in sorted_rooms:
        below = " ⚠️跌破阈值" if price < THRESHOLD else ""
        if price < THRESHOLD:
            below_count += 1
        lines.append(f"【{site}】{room}  {price:.4f} 元{below}")

    lines.append(f"\n阈值：{THRESHOLD} 元")
    body = "\n".join(lines)

    print("=" * 44)
    print(body)
    print("=" * 44)

    # 如果有跌破阈值的，标题用告警样式，否则用普通行情样式
    if below_count > 0:
        title = "⚠️ 逆水寒铜钱到价啦"
    else:
        title = "逆水寒铜钱行情"

    sent = bark_push(title, body)
    print(f"  [已推送到 {sent} 台设备]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    if not get_bark_urls():
        print("[警告] 尚未配置 Bark 推送地址！")

    if args.once:
        watched = run_once()
        handle_watched(watched)
        return

    while True:
        try:
            watched = run_once()
            handle_watched(watched)
        except Exception as e:
            print(f"  [巡检异常] {e}")
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
