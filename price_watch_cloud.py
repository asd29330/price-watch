#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逆水寒黄金畅玩服 铜钱价格盯价脚本（GitHub Actions + Bark 推送版）
- dd373: 直接 requests 抓取
- 7881: Playwright 无头浏览器渲染后抓取（API 有签名校验，不能直接请求）
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
THRESHOLD   = 4.80
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

# 7881 各区服 serverId（从页面 JS 配置中提取）
SERVER_7881_IDS = {
    "三清山": "G6065P002001",
    "桃花坞": "G6065P002002",
    "白帝城": "G6065P002003",
    "云樱岛": "G6065P002004",
    "花果山": "G6065P002005",
    "水帘洞": "G6065P002006",
    "女儿国": "G6065P002007",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "price_watch_state.json")


# ============ dd373 抓取（直接 requests） ============

def parse_dd373(html):
    """从 dd373 HTML 解析最低单价（元/万铜钱），返回 (最低价, 商品数) 或 (None, 0)"""
    items = re.split(r'<div class="goods-list-item">', html)[1:]
    if not items:
        return None, 0
    prices = []
    for item in items:
        title_m = re.search(r'goods-list-title[^>]*>.*?<div[^>]*>(.*?)</div>', item, re.DOTALL)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
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


def fetch_direct(url, timeout=15):
    """直接请求，带浏览器 UA 和 gzip 解压。"""
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


# ============ 7881 抓取（Playwright） ============

def fetch_7881_all(rooms):
    """
    用 Playwright 无头浏览器抓取 7881 所有区服价格。
    返回 {区服: 最低价}。如果 Playwright 不可用，返回空字典。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [7881] playwright 未安装，跳过 7881 监测")
        return {}

    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = browser.new_context(
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1280, "height": 800},
        )

        for room in rooms:
            server_id = SERVER_7881_IDS.get(room)
            if not server_id:
                continue
            url = f"https://search.7881.com/G6065-100001-G6065P002-{server_id}-0.html?pageNum=1"
            page = context.new_page()
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                time.sleep(3)  # 多等3秒让价格加载出来

                prices = page.evaluate("""
                    () => {
                        const all = document.querySelectorAll('*');
                        const prices = [];
                        for (const el of all) {
                            const text = el.textContent || '';
                            const m = text.match(/([\\d.]+)元\\/万铜钱/);
                            if (m && el.children.length < 3) {
                                prices.push(parseFloat(m[1]));
                            }
                        }
                        return prices;
                    }
                """)

                if prices:
                    result[room] = min(prices)
                    print(f"  [7881] {room}: 最低价 {min(prices):.4f} 元/万铜钱（{len(prices)}条）")
                else:
                    print(f"  [7881] {room}: 未抓到价格")
            except Exception as e:
                print(f"  [7881] {room}: 抓取失败 - {e}")
            finally:
                page.close()
            time.sleep(1)

        browser.close()
    return result


# ============ 千岛抓取（Playwright） ============

QIandAO_URL = "https://qiandao.com/currency/currency-zone?catalogName=%E9%80%86%E6%B0%B4%E5%AF%92%E4%B8%93%E5%8C%BA&islandId=300692&tagIds=[1883484]&attributeId=904221228984762040&entryId=1883484&entryType=TAG"


def fetch_qiandao_all(rooms):
    """
    用 Playwright 无头浏览器抓取千岛所有区服价格。
    返回 {区服: 最低价}。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [千岛] playwright 未安装，跳过千岛监测")
        return {}

    result = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            context = browser.new_context(
                user_agent=UA,
                locale="zh-CN",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.goto(QIandAO_URL, timeout=30000, wait_until="networkidle")
            time.sleep(3)

            for room in rooms:
                try:
                    print(f"  [千岛] 切换到 {room}...")
                    # 点击区服选项
                    page.click(f"text={room}", timeout=5000)
                    time.sleep(2)  # 等待价格加载

                    # 提取所有价格
                    prices = page.evaluate("""
                        () => {
                            const all = document.querySelectorAll('*');
                            const prices = [];
                            for (const el of all) {
                                const text = el.textContent || '';
                                const m = text.match(/1万币\\s*=\\s*([\\d.]+)\\s*元/);
                                if (m && el.children.length < 3) {
                                    prices.push(parseFloat(m[1]));
                                }
                            }
                            return prices;
                        }
                    """)

                    if prices:
                        min_price = min(prices)
                        result[room] = min_price
                        print(f"  [千岛] {room}: 最低价 {min_price:.4f} 元/万币（{len(prices)}条）")
                    else:
                        print(f"  [千岛] {room}: 未抓到价格")
                except Exception as e:
                    print(f"  [千岛] {room}: 抓取失败 - {e}")
                time.sleep(1)

            browser.close()
    except Exception as e:
        print(f"  [千岛] 整体失败 - {e}")
    return result


# ============ 推送与状态 ============

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


# ============ 主流程 ============

def run_once():
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 巡检中...")
    watched_prices = {}

    # --- dd373 ---
    print("  --- dd373 ---")
    for idx, room in enumerate(SERVERS):
        try:
            if idx > 0:
                time.sleep(3)
            url = DD373_SERVER_URLS.get(room)
            if not url:
                continue
            print(f"  [dd373] 抓取 {room}...")
            html = fetch_direct(url)
            price, count = parse_dd373(html)
            if not price:
                print(f"  [dd373] {room}: 未抓到价格")
                continue
            print(f"  [dd373] {room}: {price:.4f} 元/万铜钱（{count}条）")
            watched_prices[f"{room}"] = ("dd373", price)
        except Exception as e:
            print(f"  [dd373] {room}: 抓取失败 - {e}")

    # --- 7881 暂时关闭（容易超时/反爬）---
    # print("  --- 7881 ---")
    # try:
    #     prices_7881 = fetch_7881_all(SERVERS)
    #     for room, price in prices_7881.items():
    #         watched_prices[f"{room}"] = ("7881", price)
    # except Exception as e:
    #     print(f"  [7881] 整体失败 - {e}")

    # --- 千岛 ---
    print("  --- 千岛 ---")
    try:
        prices_qiandao = fetch_qiandao_all(SERVERS)
        for room, price in prices_qiandao.items():
            # 如果千岛价格更便宜，或者 dd373 没抓到，就更新
            if room not in watched_prices or price < watched_prices[room][1]:
                watched_prices[room] = ("千岛", price)
    except Exception as e:
        print(f"  [千岛] 整体失败 - {e}")

    return watched_prices


def handle_watched(watched_prices):
    if not watched_prices:
        print("  未抓到任何价格")
        return

    sorted_items = sorted(watched_prices.items(), key=lambda x: x[1][1])

    lines = [f"当前行情（共 {len(sorted_items)} 条报价）："]
    below_count = 0
    for label, (site, price) in sorted_items:
        below = " ⚠️跌破阈值" if price < THRESHOLD else ""
        if price < THRESHOLD:
            below_count += 1
        lines.append(f"【{site}】{label}  {price:.4f} 元{below}")

    lines.append(f"\n阈值：{THRESHOLD} 元")
    body = "\n".join(lines)

    print("=" * 44)
    print(body)
    print("=" * 44)

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
