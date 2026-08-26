#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
international_officer_retry.py —— 校验并修复已抓取的国际处领导信息

校验规则（针对每条 leader 的 name/title/duty/email）：
  1. 姓名合理性：2-4 字中文，不以「主持/负责/分管/协助/统筹」等动词开头，
     不以机构词尾（处/部/院/办/室/科/中心）结尾
  2. 职务合理性：必须含职务关键词（处长/主任/科长/书记/部长/院长 等）
  3. 邮箱合理性：合法邮箱格式（含 @ 和域名）
  4. 职责合理性：不含「电话/传真/Tel」等噪音，长度 < 60 字
  5. 不合格记录：自动剔除，重新写回 JSON

用法：
  python international_officer_retry.py              # 校验全部，输出报告
  python international_officer_retry.py --fix        # 校验并自动剔除不合格记录
  python international_officer_retry.py --show       # 仅展示不合格记录，不修改
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NATIONAL = os.path.join(BASE_DIR, "dataset", "全国重点院校")

# 姓名非法前缀（动词，不应出现在姓名开头）
BAD_NAME_PREFIX = ("主持", "负责", "分管", "协助", "统筹", "协调", "联系", "对接",
                   "承担", "从事", "开展", "推进", "落实", "抓好")
# 姓名非法后缀（机构词尾）
BAD_NAME_SUFFIX = ("处", "部", "院", "办", "室", "科", "中心", "组", "委")
# 职务关键词
TITLE_KW = ("处长", "副处长", "主任", "副主任", "科长", "副科长", "书记", "副书记",
            "部长", "副部长", "院长", "副院长", "秘书", "秘书长", "助理", "干事",
            "科员", "主任科员", "调研员", "director", "chief", "dean", "secretary")
# 邮箱正则
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
# duty 噪音
DUTY_NOISE = ("电话", "传真", "Tel", "TEL", "手机", "Email", "邮箱", "地址", "邮编")


def find_school_file(name):
    for prov in os.listdir(NATIONAL):
        pdir = os.path.join(NATIONAL, prov)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if fn.endswith(".json") and fn.startswith(name + "_"):
                return os.path.join(pdir, fn)
    return None


def check_leader(l):
    """校验单条领导记录，返回问题列表（空列表=合格）"""
    issues = []
    name = l.get("name", "").strip()
    title = l.get("title", "").strip()
    duty = l.get("duty", "").strip()
    email = l.get("email", "").strip()

    # 1. 姓名校验
    if not name:
        issues.append("姓名缺失")
    elif not re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", name):
        issues.append(f"姓名非纯中文2-4字: {name}")
    else:
        if name.startswith(BAD_NAME_PREFIX):
            issues.append(f"姓名以动词开头: {name}")
        if name.endswith(BAD_NAME_SUFFIX):
            issues.append(f"姓名以机构词结尾: {name}")

    # 2. 职务校验
    if not title:
        issues.append("职务缺失")
    elif not any(t in title for t in TITLE_KW):
        issues.append(f"职务不含关键词: {title}")

    # 3. 邮箱校验（若有）
    if email and not EMAIL_RE.fullmatch(email):
        issues.append(f"邮箱格式错误: {email}")

    # 4. 职责校验
    if duty:
        if any(n in duty for n in DUTY_NOISE):
            issues.append(f"职责含噪音: {duty[:30]}")
        if len(duty) > 60:
            issues.append(f"职责过长({len(duty)}字)")

    return issues


def main():
    parser = argparse.ArgumentParser(description="校验国际处领导信息合理性")
    parser.add_argument("--fix", action="store_true", help="自动剔除不合格记录")
    parser.add_argument("--show", action="store_true", help="仅展示不合格记录")
    args = parser.parse_args()

    total_leaders = 0
    valid_leaders = 0
    invalid_records = []
    schools_with_leaders = 0
    schools_fixed = 0

    for prov in os.listdir(NATIONAL):
        pdir = os.path.join(NATIONAL, prov)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            path = os.path.join(pdir, fn)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            intl = (data.get("depts") or {}).get("intl") or {}
            leaders = intl.get("leaders") or []
            if not leaders:
                continue
            schools_with_leaders += 1

            valid = []
            for l in leaders:
                total_leaders += 1
                issues = check_leader(l)
                if not issues:
                    valid.append(l)
                    valid_leaders += 1
                else:
                    invalid_records.append((data["name"], l, issues))

            if len(valid) != len(leaders):
                if args.fix:
                    if valid:
                        intl["leaders"] = valid
                    else:
                        intl.pop("leaders", None)
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    schools_fixed += 1

    print(f"=== 校验报告 ===")
    print(f"有领导信息的高校: {schools_with_leaders} 所")
    print(f"领导总记录数: {total_leaders} 条")
    print(f"合格记录: {valid_leaders} 条")
    print(f"不合格记录: {len(invalid_records)} 条")

    if invalid_records:
        print(f"\n=== 不合格记录明细 ===")
        for name, l, issues in invalid_records:
            print(f"  {name} | {l.get('name')} {l.get('title')} | {', '.join(issues)}")

    if args.fix:
        print(f"\n已修复 {schools_fixed} 所高校（剔除不合格记录）")
    elif not args.show:
        print(f"\n提示：加 --fix 自动剔除不合格记录，--show 仅展示")


if __name__ == "__main__":
    main()
