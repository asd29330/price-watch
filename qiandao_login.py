#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
千岛登录脚本（本地运行一次）
- 打开浏览器，用千岛 App 扫码登录
- 登录成功后自动保存 storage_state 到 qiandao_storage_state.json
- 把这个文件提交到仓库，GitHub Actions 就能用登录态抓取
"""

import os
import time
from playwright.sync_api import sync_playwright

STORAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qiandao_storage_state.json")
SPU_URL = "https://www.qiandao.com/c2c/spu/1019270210852537580"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            locale="zh-CN",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        print("正在打开千岛登录页...")
        page.goto(SPU_URL, wait_until="networkidle")
        time.sleep(2)

        # 如果跳转到登录页，等待用户扫码
        if "login" in page.url:
            print("\n" + "=" * 50)
            print("请用千岛 App 扫描浏览器中的二维码登录")
            print("（打开千岛 App → 我的 → 扫一扫）")
            print("=" * 50 + "\n")

            # 等待登录成功（URL 离开 login 页）
            try:
                page.wait_for_url(lambda url: "login" not in url, timeout=120000)
                print("登录成功！")
            except Exception:
                print("等待登录超时（2分钟），请重试。")
                browser.close()
                return

        # 等页面完全加载
        time.sleep(3)
        print(f"当前页面: {page.url}")

        # 保存登录态
        context.storage_state(path=STORAGE_FILE)
        print(f"\n登录态已保存到: {STORAGE_FILE}")
        print("请把这个文件提交到 GitHub 仓库。")

        browser.close()


if __name__ == "__main__":
    main()
