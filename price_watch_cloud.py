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
THRESHOLD   = 4.9
CHECK_EVERY = 300
SERVERS     = ["女儿国", "花果山", "水帘洞"]

BARK_URLS = [
    "https://api.day.app/在这里填你的Bark推送地址",
]
# ================================

URLS = {
    "dd373": "https://www.dd373.com/s-xu9np3-h3x9gf-0-0-0-0-wdxrjj-0-0-0-0-0-1-0-5-0.html",
    "7881":  "https://search.7881.com/G6065-100001-G6065P002-0-0.html?pageNum=1",
}

# Jina Reader 前缀：把目标 URL 拼在后面即可
JINA_PREFIX = "https://r.jina.ai/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "price_watch_state.json")


def parse_dd373(text):
    """只取第一个商品（按比例最佳排序后的最低价），返回 {区服: 价格}。"""
    result = {}
    chunks = re.split(r"游戏区服", text)[1:]
    for chunk in chunks:
        rm = re.search(r"黄金畅玩服[/／]\s*([^\s(（<\n]{1,10})", chunk)
        pm = re.search(r"1万铜钱\s*[=＝]\s*([\d.]+)\s*元", chunk)
        if not rm or not pm:
            continue
        room = rm.group(1).strip()
        price = float(pm.group(1))
        result[room] = price
        break  # 只取第一个商品
    return result


def parse_7881(text):
    """只取第一个商品，返回 {区服: 价格}。"""
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
        break
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
    hits = []
    for site, url in URLS.items():
        try:
            print(f"  [{site}] 通过 Jina Reader 抓取...")
            text = fetch_via_jina(url)
            # 调试：保存前 500 字看看抓到了什么
            preview = re.sub(r"\s+", " ", text)[:300]
            print(f"  [{site}] 返回 {len(text)} 字，预览: {preview}")
            low = PARSERS[site](text)
            if not low:
                print(f"  [{site}] 没解析到价格")
            else:
                line = "  ".join(f"{r} {v:.4f}" for r, v in sorted(low.items(), key=lambda x: x[1]))
                print(f"  [{site}] {line}")
                for room, price in low.items():
                    if price < THRESHOLD:
                        hits.append((site, room, price))
        except Exception as e:
            print(f"  [{site}] 抓取失败：{e}")
    return hits


def handle_hits(hits, state):
    if not hits:
        return
    new_hits = [(s, r, v) for s, r, v in hits if mark_push(s, r, v, state)]
    if not new_hits:
        print("  命中但价格未创新低，跳过推送")
        return
    lines = [f"【{s}】{r}  1万铜钱 = {v:.4f} 元" for s, r, v in sorted(new_hits, key=lambda x: x[2])]
    body = "\n".join(lines) + f"\n已跌破 {THRESHOLD} 元，快去买！"
    print("!" * 44)
    print(body)
    print("!" * 44)
    sent = bark_push("逆水寒铜钱到价啦", body)
    print(f"  [已推送到 {sent} 台设备]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    if not get_bark_urls():
        print("[警告] 尚未配置 Bark 推送地址！")

    state = load_state()
    if args.once:
        hits = run_once()
        handle_hits(hits, state)
        return

    while True:
        try:
            hits = run_once()
            handle_hits(hits, state)
        except Exception as e:
            print(f"  [巡检异常] {e}")
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
