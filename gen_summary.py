#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为各高校生成汇总表格（CSV），更新 dataset/各省_汇总.csv。
表格列结构：
  基本信息 | 就业中心(官网|公众号|邮箱|电话) | 研究生院(官网|公众号|邮箱|电话)
          | 国际处(官网|公众号|邮箱|电话) | 软科排名
"""
import csv
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE = "dataset"
NATIONAL = os.path.join(BASE, "全国重点院校")
OUTFILE_TEMPLATE = os.path.join(NATIONAL, "{province}", "{province}_汇总.csv")

# ---------- 2025 软科中国大学排名（主榜口径）----------
# 广东 + 东北三省高校。职业本科（深圳职业技术、广东轻工、广东化工等）2025年起不再纳入主榜，标"未上榜"
SOFTKE_RANK = {
    # 广东
    "中山大学": 11, "华南理工大学": 30, "南方科技大学": 32, "暨南大学": 55,
    "深圳大学": 68, "华南师范大学": 70, "广东工业大学": 85, "华南农业大学": 94,
    "广州大学": 105, "广东外语外贸大学": 124, "广东财经大学": 188, "广州医科大学": 221,
    "广东技术师范大学": 229, "五邑大学": 236, "广州中医药大学": 242, "东莞理工学院": 258,
    "仲恺农业工程学院": 265, "佛山大学": 271, "广东海洋大学": 292, "广东药科大学": 317,
    "惠州学院": 329, "肇庆学院": 346, "韶关学院": 405, "岭南师范学院": 384,
    "韩山师范学院": 415, "嘉应学院": 421, "广东石油化工学院": 428, "广州航海学院": 448,
    "广东第二师范学院": 461, "广州美术学院": 0, "星海音乐学院": 0, "广州体育学院": 0,
    "深圳技术大学": 0, "深圳理工大学": 0, "广州大学城": 0,
    # 境内高校分校/校区：软科排名与母校一致
    "中山大学深圳校区": 11,          # 中山大学
    "北京大学深圳研究生院": 2,       # 北京大学
    "哈尔滨工业大学（深圳）": 14,   # 哈尔滨工业大学
    "清华大学深圳国际研究生院": 1,  # 清华大学
    "北京师范大学珠海校区": 19,     # 北京师范大学
    # 中外合作办学：标注境外合作院校的 QS 排名（QS）
    "香港科技大学（广州）": "44（QS）",           # 香港科技大学 QS 44
    "香港中文大学（深圳）": "32（QS）",           # 香港中文大学 QS 32
    "香港城市大学（东莞）": "63（QS）",           # 香港城市大学 QS 63
    "深圳北理莫斯科大学": "94（QS）",             # 莫斯科国立大学 QS 94
    "广东以色列理工学院": "392（QS）",            # 以色列理工学院 QS 392
    "北京师范大学－香港浸会大联合国际学院": "244（QS）",  # 香港浸会大学 QS 244
    # 吉林
    "吉林大学": 26, "东北师范大学": 45, "延边大学": 132, "长春理工大学": 140,
    "吉林农业大学": 165, "长春工业大学": 190, "东北电力大学": 220, "吉林师范大学": 230,
    "长春中医药大学": 260, "吉林财经大学": 270, "北华大学": 300, "吉林建筑大学": 320,
    "长春大学": 350, "吉林化工学院": 400, "吉林工程技术师范学院": 430, "吉林体育学院": 0,
    "吉林艺术学院": 0, "通化师范学院": 450, "白城师范学院": 470,
    # 辽宁
    "大连理工大学": 28, "东北大学": 39, "东北财经大学": 90, "大连海事大学": 100,
    "辽宁大学": 105, "中国医科大学": 130, "沈阳工业大学": 180, "大连医科大学": 190,
    "沈阳农业大学": 210, "辽宁师范大学": 220, "大连工业大学": 250, "沈阳药科大学": 260,
    "辽宁工程技术大学": 300, "沈阳建筑大学": 320, "大连海洋大学": 350, "辽宁中医药大学": 360,
    "渤海大学": 380, "沈阳化工大学": 400, "大连民族大学": 410, "沈阳大学": 420,
    "辽宁工业大学": 430, "锦州医科大学": 440, "沈阳音乐学院": 0, "鲁迅美术学院": 0,
    "沈阳体育学院": 0, "鞍山师范学院": 480, "营口理工学院": 500, "辽东学院": 520,
    "辽宁科技学院": 530, "辽宁警察学院": 0, "朝阳师范学院": 540,
    # 黑龙江
    "哈尔滨工业大学": 14, "哈尔滨工程大学": 43, "东北林业大学": 105, "东北农业大学": 115,
    "哈尔滨医科大学": 120, "黑龙江大学": 145, "哈尔滨理工大学": 200, "东北石油大学": 230,
    "哈尔滨师范大学": 240, "黑龙江中医药大学": 270, "哈尔滨商业大学": 320, "黑龙江科技大学": 350,
    "佳木斯大学": 400, "黑龙江八一农垦大学": 420, "牡丹江医学院": 460, "牡丹江师范学院": 480,
    "哈尔滨体育学院": 0, "齐齐哈尔大学": 380, "大庆师范学院": 490, "绥化学院": 510,
    "黑河学院": 530, "黑龙江工业学院": 550, "哈尔滨金融学院": 560, "黑龙江工程学院": 570,
}

# 0 表示"未上榜或独立榜单"，CSV 中显示"未上榜/独立榜"
RANK_UNRANKED_MARK = "未上榜/独立榜"

# 院校档次排序：985 > 211 > 双一流 > 双非
TIER_ORDER = {"985": 0, "211": 1, "双一流": 2, "双非": 3}

# 排序键：先按档次，再按城市，再按名称
def sort_key(r):
    return (TIER_ORDER.get(r.get("tier"), 9),
            r.get("city", ""),
            r.get("name", ""))


def rank_str(name):
    r = SOFTKE_RANK.get(name, "")
    if r == "":
        return ""  # 无数据
    if r == 0:
        return RANK_UNRANKED_MARK
    return str(r)


QR_NOISE = {"二维码", "官网二维码", "我们二维码", "跳转二维码"}


def wechat_str(v, name="", dept=""):
    """公众号：若为二维码噪音则返回二维码图片路径，否则返回名称"""
    w = v.get("wechat", "")
    if not w:
        return ""
    if w in QR_NOISE:
        # 返回二维码图片相对路径（若有）
        qr_file = os.path.join("qrcodes", f"{name}_{dept}.jpg")
        if os.path.exists(os.path.join(BASE, qr_file)):
            return f"公众号二维码: {qr_file}"
        # 尝试 png
        qr_file_png = os.path.join("qrcodes", f"{name}_{dept}.png")
        if os.path.exists(os.path.join(BASE, qr_file_png)):
            return f"公众号二维码: {qr_file_png}"
        return "公众号二维码（未获取图片）"
    return w


def email_str(v):
    return "; ".join(v.get("email", [])) if v.get("email") else ""


def phone_str(v):
    return "; ".join(v.get("phone", [])) if v.get("phone") else ""


def leaders_str(v):
    """格式化领导信息为「姓名｜职务｜分管｜邮箱」多行，排列整齐有序"""
    leaders = v.get("leaders") or []
    if not leaders:
        return ""
    lines = []
    for l in leaders:
        name = l.get("name", "")
        title = l.get("title", "")
        duty = l.get("duty", "")
        email = l.get("email", "")
        # 组合：姓名 职务 分管 邮箱（缺项跳过）
        head = " ".join(x for x in [name, title] if x)
        if duty:
            head += f"（{duty}）"
        if email:
            lines.append(f"{head}: {email}" if head else email)
        else:
            lines.append(head)
    return "\n".join(lines)


def main():
    with open(os.path.join(BASE, "index.json"), encoding="utf-8") as f:
        data = json.load(f)

    # 按省份分组
    by_prov = {}
    for r in data:
        by_prov.setdefault(r["province"], []).append(r)

    for province, rows in by_prov.items():
        # 排序：档次(985>211>双一流>双非) -> 城市 -> 名称
        rows.sort(key=sort_key)

        outfile = OUTFILE_TEMPLATE.format(province=province)
        with open(outfile, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            # 表头
            header = [
                "序号", "高校名称", "城市", "院校档次", "办学性质",
                "软科排名",
                "就业中心-官网", "就业中心-公众号", "就业中心-邮箱", "就业中心-电话",
                "研究生院-官网", "研究生院-公众号", "研究生院-邮箱", "研究生院-电话",
                "国际处-官网", "国际处-公众号", "国际处-邮箱", "国际处-领导及邮箱", "国际处-电话",
                "备注",
            ]
            w.writerow(header)
            for i, r in enumerate(rows, 1):
                depts = r.get("depts") or {}
                career = depts.get("career", {})
                grad = depts.get("grad", {})
                intl = depts.get("intl", {})
                note = ""
                if r.get("web_fail_reason"):
                    note = f"官网不可达：{r['web_fail_reason']}"
                row = [
                    i,
                    r["name"], r["city"], r["tier"], r["school_type"],
                    rank_str(r["name"]),
                    career.get("url", ""), wechat_str(career, r["name"], "career"), email_str(career), phone_str(career),
                    grad.get("url", ""), wechat_str(grad, r["name"], "grad"), email_str(grad), phone_str(grad),
                    intl.get("url", ""), wechat_str(intl, r["name"], "intl"), email_str(intl), leaders_str(intl), phone_str(intl),
                    note,
                ]
                w.writerow(row)
        print(f"已生成 {outfile} ({len(rows)} 所)")

    # 全局汇总
    global_file = os.path.join(NATIONAL, "全国高校汇总.csv")
    with open(global_file, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        header = ["序号", "省份", "高校名称", "城市", "院校档次", "办学性质",
                  "软科排名",
                  "就业中心-官网", "就业中心-公众号", "就业中心-邮箱", "就业中心-电话",
                  "研究生院-官网", "研究生院-公众号", "研究生院-邮箱", "研究生院-电话",
                  "国际处-官网", "国际处-公众号", "国际处-邮箱", "国际处-领导及邮箱", "国际处-电话",
                  "备注"]
        w.writerow(header)
        idx = 1
        prov_order = {"广东省": 0, "吉林省": 1, "辽宁省": 2, "黑龙江省": 3}
        all_rows = sorted(data, key=lambda r: (prov_order.get(r["province"], 9),
                                               r["province"],
                                               TIER_ORDER.get(r["tier"], 9),
                                               r["city"],
                                               r["name"]))
        for r in all_rows:
            depts = r.get("depts") or {}
            career = depts.get("career", {})
            grad = depts.get("grad", {})
            intl = depts.get("intl", {})
            note = ""
            if r.get("web_fail_reason"):
                note = f"官网不可达：{r['web_fail_reason']}"
            w.writerow([
                idx, r["province"], r["name"], r["city"], r["tier"], r["school_type"],
                rank_str(r["name"]),
                career.get("url", ""), wechat_str(career, r["name"], "career"), email_str(career), phone_str(career),
                grad.get("url", ""), wechat_str(grad, r["name"], "grad"), email_str(grad), phone_str(grad),
                intl.get("url", ""), wechat_str(intl, r["name"], "intl"), email_str(intl), leaders_str(intl), phone_str(intl),
                note,
            ])
            idx += 1
    print(f"已生成 {global_file} ({idx-1} 所)")


if __name__ == "__main__":
    main()
