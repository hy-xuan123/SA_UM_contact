# -*- coding: utf-8 -*-
"""
生成前端「下载/更新标注」所需的元数据文件：
  1. dataset/update_meta.json —— 最后更新时间 + 最近更新高校列表（供 new 标注）
  2. dataset/全国重点院校/更新部分.csv —— 最近更新高校及其变更字段（供「下载更新部分」）

校验功能：
  对每条更新的「更新后」值做数据质量校验（邮箱格式 / 电话假号 / URL 协议 / 乱码），
  校验结果写入 CSV 的「校验结果」列，并汇总输出到控制台。
"""
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

BASE = "dataset"
CHANGE_LOG = os.path.join("change_log", "变更记录.json")
META_OUT = os.path.join(BASE, "update_meta.json")
UPDATE_CSV = os.path.join(BASE, "全国重点院校", "更新部分.csv")
VALIDATE_REPORT = os.path.join("change_log", "update_validate_report.json")

RECENT_DAYS = 7  # 最近 N 天内的变更视为「更新部分」

# ===== 校验规则 =====
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
URL_RE = re.compile(r"^https?://")
FAKE_PHONE_RE = re.compile(r"^040243\d+$")          # 假电话（040243 固定前缀系列）
GARBAGE_RE = re.compile(r"[\ue000-\uf8ff\ufffd]")   # 私用区乱码 + 替换符
EMAIL_NOISE = ("placeholder", "required", "invalid", "english", "transportation",
               "example", "address", "name@", "@example")

# 字段类型关键词 → 校验类型
FIELD_RULES = [
    ("email", "邮箱"),
    ("phone", "电话"),
    ("url", "网址"),
]


def classify_field(field):
    """根据字段名判断校验类型"""
    fl = field.lower()
    for kw, label in FIELD_RULES:
        if kw in fl:
            return label
    return "文本"


def check_string(val, vtype):
    """校验单个字符串，返回问题列表"""
    issues = []
    s = (val or "").strip()
    if GARBAGE_RE.search(s):
        issues.append("含乱码字符")
    if vtype == "邮箱":
        if not s:
            issues.append("邮箱为空")
        elif not EMAIL_RE.fullmatch(s):
            issues.append(f"邮箱格式错误")
        elif s.split("@")[0].lower() in EMAIL_NOISE:
            issues.append("邮箱为占位符噪音")
    elif vtype == "电话":
        if FAKE_PHONE_RE.fullmatch(s.replace("-", "").replace(" ", "")):
            issues.append("疑似假电话(040243系列)")
        if len(s) > 25:
            issues.append("电话超长")
    elif vtype == "网址":
        if not URL_RE.match(s):
            issues.append("缺少http(s)协议")
        if " " in s:
            issues.append("网址含空格")
    return issues


def validate_after(field, after_val):
    """
    校验「更新后」值。
    返回 (状态, 问题列表)
      状态: "通过" / "删除字段" / "⚠问题"
    """
    if after_val is None:
        return "删除字段", []

    vtype = classify_field(field)
    values = after_val if isinstance(after_val, list) else [after_val]

    issues = []
    for v in values:
        if isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        issues.extend(check_string(str(v), vtype))
    # 去重
    issues = list(dict.fromkeys(issues))
    return ("通过" if not issues else "⚠问题", issues)


def fmt_val(v):
    """格式化 before/after 值为可读字符串"""
    if v is None:
        return "（无）"
    if isinstance(v, list):
        if not v:
            return "（空）"
        return "；".join(str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    s = str(v)
    return s if s else "（空）"


def main():
    with open(CHANGE_LOG, encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("records", [])
    if not records:
        print("无变更记录")
        return

    last_time = records[-1]["time"]
    last_dt = datetime.strptime(last_time, "%Y-%m-%d %H:%M:%S")
    cutoff = last_dt - timedelta(days=RECENT_DAYS)

    # 最近 N 天内的变更（每条 change 展开为一行，保留具体内容 + 校验结果）
    rows = []
    problems = []
    for rec in records:
        t = datetime.strptime(rec["time"], "%Y-%m-%d %H:%M:%S")
        if t < cutoff:
            continue
        for ch in rec.get("changes", []):
            name = ch.get("university", "")
            field = ch.get("field", "")
            if not name:
                continue
            before = fmt_val(ch.get("before"))
            after = fmt_val(ch.get("after"))
            status, issues = validate_after(field, ch.get("after"))
            result = status if not issues else status + "：" + "；".join(issues)
            rows.append([name, field, before, after, rec["time"], result])
            if issues:
                problems.append({
                    "university": name, "field": field,
                    "after": after, "issues": issues, "time": rec["time"],
                })

    # 生成更新部分 CSV（含校验结果列）
    with open(UPDATE_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["高校名称", "更新字段", "更新前", "更新后", "最后更新时间", "校验结果"])
        for row in sorted(rows, key=lambda r: (r[0], r[4])):
            w.writerow(row)

    # 按高校聚合（用于元数据 JSON）
    school_map = {}
    for name, field, before, after, t, result in rows:
        if name not in school_map:
            school_map[name] = {"fields": set(), "time": t}
        school_map[name]["fields"].add(field)
        school_map[name]["time"] = t

    meta = {
        "last_update": last_time,
        "recent_days": RECENT_DAYS,
        "updated_count": len(school_map),
        "updated_schools": [{"name": n, "fields": sorted(v["fields"]), "time": v["time"]}
                            for n, v in sorted(school_map.items())],
        "files": {
            "summary_xlsx": "dataset/全国重点院校/全国高校汇总表.xlsx",
            "summary_csv": "dataset/全国重点院校/全国高校汇总.csv",
            "update_csv": "dataset/全国重点院校/更新部分.csv",
        },
    }
    with open(META_OUT, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 校验报告
    with open(VALIDATE_REPORT, "w", encoding="utf-8") as f:
        json.dump({"checked": len(rows), "problems": problems}, f,
                  ensure_ascii=False, indent=2)

    print(f"最后更新: {last_time}")
    print(f"最近 {RECENT_DAYS} 天内更新高校: {len(school_map)} 所")
    print(f"更新记录明细: {len(rows)} 条")
    print(f"校验发现问题: {len(problems)} 条")
    if problems:
        print("\n=== 问题明细 ===")
        for p in problems:
            print(f"  {p['university']} | {p['field']} | {p['after'][:40]} | {'; '.join(p['issues'])}")
    print(f"\n已生成 {META_OUT}")
    print(f"已生成 {UPDATE_CSV}")
    print(f"已生成 {VALIDATE_REPORT}")


if __name__ == "__main__":
    main()
