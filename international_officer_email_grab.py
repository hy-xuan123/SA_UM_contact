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
    "机构人员", "人员设置", "处室简介", "部门概况", "部门介绍",
    "现任领导", "管理服务岗位", "机构人员设置", "内设机构",
    "成员信息", "成员介绍", "处室职责", "工作职责",
    "about", "contact", "staff", "leadership", "people", "directory",
    "team", "members", "administration", "organization", "profile", "overview",
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
    从「...姓名 职务...」中提取职务前的姓名（姓名在前的情况）。
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


def extract_name_after_title(text, title):
    """
    从「职务 姓名」中提取职务后的姓名（姓名在后的情况，如「处长 陈 洁」）。
    支持：处长 陈洁 / 处长：陈洁 / 处长（xx）陈 洁 / 部 长：邓鹤翔 / 副处长 盛静波
    姓名 2-3 字，以「工作分工/电话/联系/办公/分管/负责」等词为右边界。
    """
    idx = text.find(title)
    if idx < 0:
        return ""
    after = text[idx + len(title):]
    # 去除冒号、括号说明、空格
    after = re.sub(r"^[：:）)\]\s]+", "", after)
    # 去掉职务后的括号说明（如"处长（港澳台事务办公室主任）"）
    after = re.sub(r"^[（(][^（）()]*[）)]", "", after)
    after = after.lstrip("：: \t")
    # 取开头 2-3 个汉字（姓名中间可带空格，如"陈 洁"）
    m = re.match(r"([\u4e00-\u9fa5])\s?([\u4e00-\u9fa5])(?:\s?([\u4e00-\u9fa5]))?", after)
    if not m:
        return ""
    name = m.group(1) + m.group(2) + (m.group(3) or "")
    # 过滤非姓名
    if ORG_TERMS.fullmatch(name) or any(k in name for k in ("工作", "联系", "电话", "办公", "分管", "负责")):
        return ""
    return name


def _norm_text(s):
    """规范化文本：全角空格→半角，连续空格合并，职务词内空格去除"""
    s = re.sub(r"[\u3000\xa0]+", " ", s or "")
    s = re.sub(r"\s+", " ", s)
    # 去除单字职务内部空格：部 长 → 部长，处 长 → 处长，主 任 → 主任
    for a, b in [("部 长", "部长"), ("处 长", "处长"), ("主 任", "主任"),
                 ("科 长", "科长"), ("院 长", "院长"), ("书 记", "书记"),
                 ("副 部", "副部"), ("副 处", "副处"), ("副 主", "副主"),
                 ("副 科", "副科"), ("副 院", "副院")]:
        s = s.replace(a, b)
    return s


def extract_leaders(html):
    """
    从 HTML 提取领导信息列表 [{name, title, duty, email}]。
    优先解析表格行，其次列表项。
    注意：邮箱不是必须的——很多高校「部门领导」页只列姓名/职务/分工/电话，
    无个人邮箱。此时仍应抓取领导名单，邮箱留空。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    leaders = []
    seen = set()

    def add_leader(name, title, duty, email):
        key = (name, title, email)
        if key not in seen:
            seen.add(key)
            leaders.append({"name": name, "title": title, "duty": duty, "email": email})

    # 1. 表格行解析（含无邮箱的领导行，支持姓名列与职务列分离）
    for tr in soup.find_all("tr"):
        cells = [_norm_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        if not cells:
            continue
        text = " | ".join(cells)
        # 跳过表头行
        if all(any(h in c for c in cells) for h in ("姓名", "职务")) and not any("@" in c for c in cells):
            if "姓名" in text or "职务" in text or "邮箱" in text:
                continue
        title = next((t for t in TITLE_KEYWORDS if t in text), "")
        if not title:
            continue
        emails = [e for e in (clean_email(x) for x in EMAIL_RE.findall(text)) if e]

        # 优先：找「纯姓名」单元格（2-3字、无职务词、无邮箱、无数字）
        name = ""
        for c in cells:
            c = c.strip()
            if (2 <= len(c) <= 3 and re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", c)
                    and not any(t in c for t in TITLE_KEYWORDS)):
                name = c
                break
        # 回退：拼接文本里提取
        if not name:
            name = extract_name_after_title(text, title) or extract_name_before_title(text, title)
        if not name:
            continue

        duty = ""
        m = re.search(r"(?:分管|负责|主持|主管|职责|分工)[^|，。]{0,30}", text)
        if m:
            duty = re.sub(r"(电话|传真|Tel|TEL|手机|邮箱|Email)[：: ]*[0-9+\-()（）@A-Za-z.\s]*", "", m.group(0)).strip()[:40]
        if emails:
            for email in emails:
                add_leader(name, title, duty, email)
        else:
            add_leader(name, title, duty, "")

    # 导航噪音词（列表项中命中这些说明是导航菜单，非领导条目）
    NAV_NOISE = ["返回", "设为首页", "加入收藏", "当前位置", "首页", "English",
                 "上一级", "站内", "搜索", "登录"]
    # 领导条目特征词（姓名后应紧跟这些，才认定是真实领导）
    LEADER_MARK = ("工作分工", "分管", "负责", "主持", "主管", "职责", "电话", "联系", "办公")

    # 2. 列表项 / 段落解析（非表格布局，含无邮箱）
    if not leaders:
        for li in soup.find_all(["li", "p", "div"]):
            text = _norm_text(li.get_text(" ", strip=True))
            if len(text) > 200:  # 跳过整段正文
                continue
            if any(n in text for n in NAV_NOISE):
                continue
            title = next((t for t in TITLE_KEYWORDS if t in text), "")
            if not title:
                continue
            name = extract_name_after_title(text, title) or extract_name_before_title(text, title)
            if not name:
                continue
            emails = [e for e in (clean_email(x) for x in EMAIL_RE.findall(text)) if e]
            duty = ""
            m = re.search(r"(?:分管|负责|主持|主管|职责|分工)[^，。]{0,30}", text)
            if m:
                duty = re.sub(r"(电话|传真|Tel|TEL|手机|邮箱|Email)[：: ]*[0-9+\-()（）@A-Za-z.\s]*", "", m.group(0)).strip()[:40]
            # 无邮箱且无工作特征 → 视为导航噪音，跳过
            if not emails and not duty and not any(k in text for k in ("电话", "联系", "办公")):
                continue
            if emails:
                for email in emails:
                    add_leader(name, title, duty, email)
            else:
                add_leader(name, title, duty, "")

    # 3. 连续文本解析（华中科大/武大：整页大 div，职务+姓名+工作分工连续排列）
    # 总是执行（与前面结果合并），能更完整抓取「职务 姓名 工作分工」结构
    plain = _norm_text(soup.get_text(" ", strip=True))
    title_pat = "|".join(re.escape(t) for t in TITLE_KEYWORDS)
    for m in re.finditer(
        rf"({title_pat})\s*(?:[（(][^）()]*[）)])?\s*[：:]?\s*"
        rf"([\u4e00-\u9fa5])\s?([\u4e00-\u9fa5])(?:\s?([\u4e00-\u9fa5]))?"
        rf"(?=\s*(?:工作分工|分管|负责|主持|主管|职责|电话|联系|办公|邮箱|Email))",
        plain):
        title = m.group(1)
        name = m.group(2) + m.group(3) + (m.group(4) or "")
        # 取该职务后的一段，找工作分工
        seg = plain[m.end():m.end() + 80]
        duty = ""
        dm = re.search(r"(?:工作分工|分管|负责|主持|主管|职责)[：: ]*([^联系电话办公地址]{0,40})", seg)
        if dm:
            duty = dm.group(1).strip()[:40]
        # 找邮箱（该段附近）
        email = ""
        email_seg = plain[m.end():m.end() + 250]
        em = EMAIL_RE.search(email_seg)
        if em:
            email = clean_email(em.group(0)) or ""
        add_leader(name, title, duty, email)

    return leaders[:30]


def fetch_playwright_html(url, timeout=25000):
    """
    用 Playwright 获取 JS 渲染后的完整 HTML（含链接），用于 requests 失败时的兜底。
    返回 (html, reason)。
    """
    p = crawler._get_playwright()
    if p is None or not os.path.exists(CHROME_PATH):
        return None, "playwright未安装或Chrome不存在"
    try:
        browser = p.chromium.launch(headless=True, executable_path=CHROME_PATH,
                                    args=["--no-sandbox", "--disable-gpu"])
        page = browser.new_page()
        page.goto(url, timeout=timeout, wait_until="load")
        time.sleep(2)
        html = page.content()
        browser.close()
        return html, "playwright-html"
    except Exception as e:
        return None, f"playwright失败:{str(e)[:30]}"


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


def grab_school(school, do_screenshot=True, use_playwright=True):
    """
    对单所高校抓取国际处领导邮箱。
    返回 dict: {name, tier, leaders(list), screenshot(list), status, source}
    use_playwright=False 时只走 requests 静态抓取（可并发）。
    """
    name = school.get("name", "?")
    tier = school.get("tier", "")
    website = school.get("website", "")
    intl = (school.get("depts") or {}).get("intl") or {}
    intl_url = intl.get("url", "")

    leaders = []
    shots = []
    sources = []
    officer_url = ""   # 领导信息实际来源的 URL（与国际处主站不一致时记录）

    # ---- 路径1：国际处主站 + 关于我们/部门领导子页面（二级递归）----
    html, reason = fetch_requests(intl_url)
    if html:
        l = extract_leaders(html)
        if l:
            leaders.extend(l)
            officer_url = intl_url
            sources.append(f"intl首页({reason})")
        # 一级子页面（关于我们/部门领导/机构设置等）
        for sub in find_about_links(html, intl_url)[:8]:
            shtml, _ = fetch_requests(sub, timeout=8)
            if not shtml:
                continue
            sl = extract_leaders(shtml)
            if sl:
                leaders.extend(sl)
                if not officer_url:
                    officer_url = sub
                sources.append(f"子页{sub.split('/')[-1][:20]}")
                if len(leaders) >= 25:
                    break
            # 二级递归：从子页面（如"关于我们"）再找"部门领导"链接
            for sub2 in find_about_links(shtml, sub)[:8]:
                if sub2 == sub or sub2 == intl_url:
                    continue
                s2html, _ = fetch_requests(sub2, timeout=8)
                if s2html:
                    sl2 = extract_leaders(s2html)
                    if sl2:
                        leaders.extend(sl2)
                        if not officer_url:
                            officer_url = sub2
                        sources.append(f"二级子页{sub2.split('/')[-1][:20]}")
                        if len(leaders) >= 25:
                            break
            if len(leaders) >= 25:
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

    # ---- 路径3：Playwright 动态兜底（requests 失败或 JS 渲染）----
    if not leaders and use_playwright:
        dyn_html, dyn_reason = fetch_playwright_html(intl_url)
        if dyn_html:
            l = extract_leaders(dyn_html)
            if l:
                leaders.extend(l)
                sources.append(f"playwright({dyn_reason})")
            else:
                # 从渲染后的首页找「部门领导」子页再抓
                for sub in find_about_links(dyn_html, intl_url)[:6]:
                    shtml, _ = fetch_requests(sub, timeout=8)
                    if not shtml:
                        sh, _ = fetch_playwright_html(sub)
                        shtml = sh
                    if shtml:
                        sl = extract_leaders(shtml)
                        if sl:
                            leaders.extend(sl)
                            sources.append(f"pw子页{sub.split('/')[-1][:20]}")
                            if len(leaders) >= 25:
                                break

    # ---- 路径4：截图存档（页面可达但无法提取）----
    if not leaders and do_screenshot:
        ok, res = screenshot_page(intl_url, SHOT_DIR, name, "intl")
        if ok:
            shots.append(res)
            sources.append("已截图")
        else:
            sources.append(res)

    # 去重：按 (姓名, 职务, 邮箱) 三元组去重，保留无邮箱的领导（邮箱留空）
    seen = set()
    deduped = []
    for l in leaders:
        key = (l.get("name", ""), l.get("title", ""), l.get("email", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(l)
    # 过滤掉既无姓名又无邮箱的孤立噪音记录
    leaders = [l for l in deduped if l.get("name") or l.get("email")]

    # 写回 JSON
    if leaders:
        path = find_school_file(name)
        if path:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            intl_d = data.setdefault("depts", {}).setdefault("intl", {})
            intl_d["leaders"] = leaders
            # 领导信息网址与国际处主站不一致时，分别标注 international / international_officer
            if officer_url and officer_url.rstrip("/") != intl_url.rstrip("/"):
                intl_d["officer_url"] = officer_url
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
    parser.add_argument("--retry-shots", action="store_true",
                        help="只重跑上次失败（截图/未命中）的院校")
    args = parser.parse_args()

    targets = load_targets()
    total = len(targets)

    # 重跑模式：从上次日志筛出失败院校
    if args.retry_shots and os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8") as f:
            prev = json.load(f)
        failed_names = {r["name"] for r in prev if r.get("status") in ("shot", "none")}
        targets = [u for u in targets if u["name"] in failed_names]
        print(f"重跑模式：上次失败 {len(failed_names)} 所，本次重跑 {len(targets)} 所\n")
    else:
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
