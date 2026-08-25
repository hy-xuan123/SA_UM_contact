#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
international_officer_email_grab.py —— 精准抓取国际处/部门领导的联系邮箱

用途：
  针对 985/211/双一流 高校，抓取国际交流处（含港澳台办）的部门领导信息，
  包括：姓名、职务、分管/工作职责、邮箱。

抓取路径（多条，逐步降级）：
  1. 国际处主站首页 + 「关于我们/联系我们/机构设置/领导分工」等子页面（中英文）
  2. 国际处子域名探测（复用 crawler.probe_intl_subdomains）
  3. 学校官网首页发现国际交流处/港澳台办链接，作为补充抓取路径
  4. 静态抓不到（JS 渲染）→ Playwright 动态抓取
  5. 页面可达但无法提取 → Playwright 截图存档

数据写入：
  各高校 JSON 的 depts.intl.leaders 字段，结构：
    [{"name": 姓名, "title": 职务, "duty": 分管/职责, "email": 邮箱}, ...]

汇总表输出：
  由 gen_summary.py / gen_excel.py 将 leaders 格式化为「姓名｜职务｜分管｜邮箱」，
  新增「国际处-领导及邮箱」列，排列整齐有序。

用法：
  python international_officer_email_grab.py                # 抓全部 985/211/双一流
  python international_officer_email_grab.py --limit 5      # 只处理前 5 所
  python international_officer_email_grab.py --start 10     # 从第 10 所开始
  python international_officer_email_grab.py --workers 8    # 并发数（默认 6）
  python international_officer_email_grab.py --show         # 仅列出目标
  python international_officer_email_grab.py --no-screenshot # 关闭截图
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup

import crawler
from crawler import (fetch_requests, fetch_playwright, clean_email, EMAIL_RE,
                     find_dept_links, probe_intl_subdomains, CHROME_PATH)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NATIONAL = os.path.join(BASE_DIR, "dataset", "全国重点院校")
INDEX_PATH = os.path.join(BASE_DIR, "dataset", "index.json")
LOG_PATH = os.path.join(BASE_DIR, "change_log", "international_officer_email_grab_log.json")
SHOT_DIR = os.path.join(BASE_DIR, "dataset", "国际处页面截图")

TIERS = ("985", "211", "双一流")

# 「关于我们 / 联系我们 / 领导」子页面关键词（中英文）
ABOUT_KEYWORDS = [
    "关于我们", "联系我们", "机构设置", "部门领导", "领导分工", "领导成员",
    "领导介绍", "人员构成", "工作人员", "机构简介", "部门简介", "科室设置",
    "岗位职责", "组织机构", "负责人", "职能",
    "about", "contact", "staff", "leadership", "people", "directory",
    "team", "members", "administration", "organization",
]

# 领导职务关键词（长词优先，避免"副处长"被"处长"抢先匹配）
TITLE_KEYWORDS = [
    "副处长", "副主任", "副科长", "副部长", "副院长", "副书记", "秘书长",
    "处长", "主任", "科长", "部长", "院长", "书记", "助理", "干事",
    "科员", "顾问", "调研员", "副秘书长",
    "deputy director", "deputy", "director", "chief", "dean", "secretary",
    "head", "manager", "officer", "coordinator", "assistant",
]

# 分管 / 职责关键词
DUTY_KEYWORDS = ["分管", "负责", "主持", "主管", "职责", "分工", "联系", "联系分管"]


def find_school_file(name):
    """在所有省份目录中查找高校 JSON 文件（兼容直辖市）"""
    for prov in os.listdir(NATIONAL):
        pdir = os.path.join(NATIONAL, prov)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if fn.endswith(".json") and fn.startswith(name + "_"):
                return os.path.join(pdir, fn)
    return None


def load_targets():
    """筛选：985/211/双一流 且 有国际处 url 的高校"""
    with open(INDEX_PATH, encoding="utf-8") as f:
        data = json.load(f)
    targets = []
    for u in data:
        tier = u.get("tier", "")
        if tier not in TIERS:
            continue
        intl = (u.get("depts") or {}).get("intl") or {}
        if intl.get("url"):
            targets.append(u)
    return targets


def find_about_links(html, base_url):
    """从页面找出「关于我们/联系我们/领导」等子页面链接"""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        text = (a.get_text(" ", strip=True) or "").lower()
        href = (a["href"] or "").lower()
        combined = f"{text} {href}"
        if not any(k in combined for k in ABOUT_KEYWORDS):
            continue
        full = urljoin(base_url, a["href"])
        if any(ext in full for ext in (".jpg", ".png", ".gif", ".pdf", ".zip")):
            continue
        if full in seen:
            continue
        seen.add(full)
        links.append(full)
    return links


# 机构名词（姓名提取前需剥离，避免"国际交流处副处长"误提取"流处/交流处"）
ORG_TERMS = re.compile(
    r"(国际交流与合作处|国际交流处|国际合作处|国际合作与交流处|港澳台办公室|港澳台事务办公室|"
    r"对外交流处|外事处|国际处|国际部|国际事务|外事办公室|国际教育|交流处|合作处|"
    r"办公室|处|部|院|室|科|中心)"
)


def extract_name_before_title(text, title):
    """
    从「...姓名 职务...」中提取职务前的姓名。
    先剥离机构名，再取紧邻职务的 2-3 个汉字作为姓名。
    """
    idx = text.find(title)
    if idx <= 0:
        return ""
    before = text[:idx]
    # 剥离机构名
    before = ORG_TERMS.sub("", before)
    # 取剩余末尾的 2-3 个汉字
    m = re.search(r"([\u4e00-\u9fa5]{2,3})\s*$", before)
    if not m:
        return ""
    name = m.group(1)
    # 姓名不应以"副"或机构词尾结尾
    if name in ("副",) or ORG_TERMS.fullmatch(name):
        return ""
    return name


def extract_leaders(html):
    """
    从 HTML 提取领导信息列表 [{name, title, duty, email}]。
    优先解析表格行，其次列表项。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    leaders = []
    seen = set()

    # 1. 表格行解析
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if not cells:
            continue
        text = " | ".join(cells)
        emails = [e for e in (clean_email(x) for x in EMAIL_RE.findall(text)) if e]
        if not emails:
            continue
        title = next((t for t in TITLE_KEYWORDS if t in text), "")
        if not title:
            continue
        name = extract_name_before_title(text, title)
        duty = ""
        m = re.search(r"(?:分管|负责|主持|主管|职责|分工)[^|，。]{0,30}", text)
        if m:
            duty = re.sub(r"(电话|传真|Tel|TEL|手机|邮箱|Email)[：: ]*[0-9+\-()（）@A-Za-z.\s]*", "", m.group(0)).strip()[:40]
        for email in emails:
            key = (name, email)
            if key not in seen:
                seen.add(key)
                leaders.append({"name": name, "title": title, "duty": duty, "email": email})

    # 2. 列表项 / 段落解析（非表格布局）
    if not leaders:
        for li in soup.find_all(["li", "p", "div"]):
            text = li.get_text(" ", strip=True)
            if len(text) > 200:  # 跳过整段正文
                continue
            emails = [e for e in (clean_email(x) for x in EMAIL_RE.findall(text)) if e]
            if not emails:
                continue
            title = next((t for t in TITLE_KEYWORDS if t in text), "")
            if not title:
                continue
            name = extract_name_before_title(text, title)
            duty = ""
            m = re.search(r"(?:分管|负责|主持|主管|职责|分工)[^，。]{0,30}", text)
            if m:
                duty = re.sub(r"(电话|传真|Tel|TEL|手机|邮箱|Email)[：: ]*[0-9+\-()（）@A-Za-z.\s]*", "", m.group(0)).strip()[:40]
            for email in emails:
                key = (name, email)
                if key not in seen:
                    seen.add(key)
                    leaders.append({"name": name, "title": title, "duty": duty, "email": email})

    return leaders[:30]


def screenshot_page(url, save_dir, name, label="page"):
    """
    Playwright 截图。返回 (ok, reason)。
    截图文件名：{name}_{label}_{时间戳}.png
    """
    p = crawler._get_playwright()
    if p is None or not os.path.exists(CHROME_PATH):
        return False, "playwright未安装或Chrome不存在"
    os.makedirs(save_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[\\/:*?"<>|]', "", name)
    path = os.path.join(save_dir, f"{safe_name}_{label}_{ts}.png")
    try:
        browser = p.chromium.launch(headless=True, executable_path=CHROME_PATH,
                                    args=["--no-sandbox", "--disable-gpu"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, timeout=25000, wait_until="load")
        time.sleep(2)
        page.screenshot(path=path, full_page=True)
        browser.close()
        return True, path
    except Exception as e:
        return False, f"截图失败:{str(e)[:40]}"


def grab_school(school, do_screenshot=True):
    """
    对单所高校抓取国际处领导邮箱。
    返回 dict: {name, tier, leaders(list), screenshot(list), status, source}
    """
    name = school.get("name", "?")
    tier = school.get("tier", "")
    website = school.get("website", "")
    intl = (school.get("depts") or {}).get("intl") or {}
    intl_url = intl.get("url", "")

    leaders = []
    shots = []
    sources = []

    # ---- 路径1：国际处主站 + 关于我们子页面 ----
    html, reason = fetch_requests(intl_url)
    if html:
        l = extract_leaders(html)
        if l:
            leaders.extend(l)
            sources.append(f"intl首页({reason})")
        # 关于我们/联系我们子页面
        for sub in find_about_links(html, intl_url)[:6]:
            shtml, _ = fetch_requests(sub, timeout=8)
            if shtml:
                sl = extract_leaders(shtml)
                if sl:
                    leaders.extend(sl)
                    sources.append(f"子页{sub.split('/')[-1][:20]}")
                    if len(leaders) >= 20:
                        break

    # ---- 路径2：学校官网首页发现国际处/港澳台办链接 ----
    if not leaders and website:
        whtml, _ = fetch_requests(website)
        if whtml:
            dept_links = find_dept_links(whtml, website)
            # 港澳台相关也纳入
            soup = BeautifulSoup(whtml, "html.parser")
            for a in soup.find_all("a", href=True):
                t = (a.get_text(" ", strip=True) or "").lower()
                h = (a["href"] or "").lower()
                if any(k in (t + h) for k in ("港澳台", "国际交流", "国际合作", "外事", "hmt", "ga", "gac")):
                    full = urljoin(website, a["href"])
                    if "intl" not in dept_links:
                        dept_links["intl"] = (a.get_text(strip=True) or "国际处", full)
            for dept, (title, durl) in dept_links.items():
                if dept != "intl":
                    continue
                dhtml, _ = fetch_requests(durl)
                if dhtml:
                    l = extract_leaders(dhtml)
                    if l:
                        leaders.extend(l)
                        sources.append(f"官网入口{title[:12]}")

    # ---- 路径3：Playwright 动态兜底 ----
    if not leaders:
        dyn_text, dyn_reason = fetch_playwright(intl_url)
        if dyn_text:
            # playwright 返回纯文本，包成 HTML 让 extract_leaders 解析
            l = extract_leaders(dyn_text)
            if l:
                leaders.extend(l)
                sources.append(f"playwright({dyn_reason})")

    # ---- 路径4：截图存档（页面可达但无法提取）----
    if not leaders and do_screenshot:
        ok, res = screenshot_page(intl_url, SHOT_DIR, name, "intl")
        if ok:
            shots.append(res)
            sources.append("已截图")
        else:
            sources.append(res)

    # 去重：同邮箱优先保留「有姓名」的记录，剔除空姓名重复项
    by_email = {}
    for l in leaders:
        email = l.get("email", "")
        if not email:
            continue
        if email not in by_email:
            by_email[email] = l
        else:
            # 已有记录无姓名，但当前有姓名 → 用当前替换
            if not by_email[email].get("name") and l.get("name"):
                by_email[email] = l
    leaders = list(by_email.values())
    # 过滤掉仍然无姓名的孤立记录（保留有姓名的）
    named = [l for l in leaders if l.get("name")]
    leaders = named if named else leaders

    # 写回 JSON
    if leaders:
        path = find_school_file(name)
        if path:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("depts", {}).setdefault("intl", {})["leaders"] = leaders
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    status = "ok" if leaders else ("shot" if shots else "none")
    return {"name": name, "tier": tier, "leaders": leaders,
            "screenshot": shots, "status": status, "source": "; ".join(sources)}


def main():
    parser = argparse.ArgumentParser(description="精准抓取国际处领导邮箱")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 所")
    parser.add_argument("--start", type=int, default=0, help="从第 N 所开始")
    parser.add_argument("--workers", type=int, default=6, help="并发线程数（默认6）")
    parser.add_argument("--show", action="store_true", help="仅列出目标")
    parser.add_argument("--no-screenshot", action="store_true", help="关闭截图")
    args = parser.parse_args()

    targets = load_targets()
    total = len(targets)
    print(f"目标：985/211/双一流 且有国际处网址的高校，共 {total} 所\n")

    if args.show:
        for i, u in enumerate(targets, 1):
            intl = (u.get("depts") or {}).get("intl") or {}
            print(f"  {i:3d}. {u['name']} | {u.get('tier','')} | {intl.get('url','')[:55]}")
        return

    if args.start or args.limit:
        end = args.start + args.limit if args.limit else len(targets)
        targets = targets[args.start:end]

    print(f"本次抓取 {len(targets)} 所（start={args.start}）\n")

    do_shot = not args.no_screenshot
    results = []
    ok = shot = none = 0

    # playwright 截图不支持多线程，故截图部分串行；静态抓取可并发。
    # 简化：全部串行，保证截图与动态抓取稳定。
    for i, school in enumerate(targets, 1):
        try:
            r = grab_school(school, do_screenshot=do_shot)
        except Exception as e:
            r = {"name": school.get("name", "?"), "tier": school.get("tier", ""),
                 "leaders": [], "screenshot": [], "status": f"ERR:{str(e)[:40]}",
                 "source": ""}
        results.append(r)
        if r["status"] == "ok":
            ok += 1
            print(f"[{i}/{len(targets)}] ✓ {r['name']} ({r['tier']}): "
                  f"{len(r['leaders'])} 位领导  ({r['source']})")
            for l in r["leaders"][:5]:
                print(f"       · {l['name']} {l['title']} {l['duty']} -> {l['email']}")
        elif r["status"] == "shot":
            shot += 1
            print(f"[{i}/{len(targets)}] 📸 {r['name']}: 已截图 {r['screenshot']}")
        else:
            none += 1
            print(f"[{i}/{len(targets)}] ✗ {r['name']}: {r['status']} ({r['source']})")
        time.sleep(0.3)

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n完成：抓到领导 {ok} 所 | 截图存档 {shot} 所 | 未命中 {none} 所")
    print(f"截图目录：{SHOT_DIR}")
    print(f"日志：{LOG_PATH}")


if __name__ == "__main__":
    main()
