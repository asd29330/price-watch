#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逆水寒黄金畅玩服 铜钱价格盯价脚本（GitHub Actions + Bark 推送版）
通过 Jina Reader (r.jina.ai) 免费渲染代理抓取 dd373 / 7881 列表页。
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

# ============ 配置区 ============
THRESHOLD   = 5.03
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

# 7881 暂时关闭（容易反爬）
# URLS_7881 = {
#     "7881":  "https://search.7881.com/G6065-100001-G6065P002-0-0.html?pageNum=1",
# }

# Jina Reader 前缀：把目标 URL 拼在后面即可
JINA_PREFIX = "https://r.jina.ai/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "price_watch_state.json")


def parse_dd373(text):
    """解析列表页所有商品，返回 {区服: 价格}。兼容两种价格格式：1万铜钱=X元 / X元/万铜钱"""
    result = {}
    chunks = re.split(r"游戏区服", text)[1:]
    for chunk in chunks:
        rm = re.search(r"黄金畅玩服[/／]\s*([^\s(（<\n]{1,10})", chunk)
        # 兼容两种价格格式
        pm = re.search(r"1万铜钱\s*[=＝]\s*([\d.]+)\s*元", chunk)
        if not pm:
            pm = re.search(r"([\d.]+)\s*元/万铜钱", chunk)
        if not rm or not pm:
            continue
        room = rm.group(1).strip()
        price = float(pm.group(1))
        result[room] = price
    return result


def parse_7881(text):
    """解析列表页所有商品，返回 {区服: 价格}。"""
    result = {}
    chunks = re.split(r"游戏区服", text)[1:]
    for chunk in chunks:
        rm = re.search(r"黄金畅玩服[/／]\s*([^\s(（<\n]{1,10})", chunk)
        pm = re.search(r"([\d.]+)\s*元/万铜钱", chunk)
        if not rm or not pm:
            continue
        room = rm.group(1).strip()
        price = float(pm.group(1))
        result[room] = price
    return result


PARSERS = {"dd373": parse_dd373, "7881": parse_7881}


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


def fetch_via_jina(url, timeout=60):
    """通过 Jina Reader 抓取页面，返回文本内容。"""
    jina_url = JINA_PREFIX + url
    headers = {
        "User-Agent": UA,
        "X-Return-Format": "text",
        "X-No-Cache": "true",
    }
    api_key = os.environ.get("JINA_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(jina_url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


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
            text = fetch_via_jina(url)
            
            # 调试：预览前 200 字
            preview = re.sub(r"\s+", " ", text)[:200]
            print(f"  [{room}] 返回 {len(text)} 字，预览: {preview}")
            
            # 直接找第一个商品的价格（按比例最佳排序后第一个就是最低价）
            price = None
            chunks = re.split(r"游戏区服", text)[1:]
            for chunk in chunks:
                # 兼容两种价格格式
                pm = re.search(r"1万铜钱\s*[=＝]\s*([\d.]+)\s*元", chunk)
                if not pm:
                    pm = re.search(r"([\d.]+)\s*元/万铜钱", chunk)
                if pm:
                    price = float(pm.group(1))
                    break  # 找到第一个就停，后面的都是更贵的
            
            if not price:
                print(f"  [{room}] 没解析到价格")
                continue
            
            print(f"  [{room}] 最低价: {price:.4f} 元/万铜钱")
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
