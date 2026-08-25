# -*- coding: utf-8 -*-
"""将汇总 CSV 数据生成 Excel（xlsx），含格式美化 + 嵌入二维码图片"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

import xlsxwriter

import gen_summary as gs

BASE = "dataset"
NATIONAL = os.path.join(BASE, "全国重点院校")
OUT = os.path.join(NATIONAL, "全国高校汇总表.xlsx")
QR_DIR = os.path.join(BASE, "qrcodes")
SOFTKE_RANK = gs.SOFTKE_RANK

HEADER = ["序号", "省份", "高校名称", "城市", "院校档次", "办学性质", "软科排名",
          "就业中心-官网", "就业中心-公众号", "就业中心-邮箱", "就业中心-电话",
          "研究生院-官网", "研究生院-公众号", "研究生院-邮箱", "研究生院-电话",
          "国际处-官网", "国际处-公众号", "国际处-邮箱", "国际处-领导及邮箱", "国际处-电话", "备注"]

# 公众号列的索引（用于插入图片）
WECHAT_COL_INDEX = {
    "career": 8,   # 就业中心-公众号
    "grad": 12,    # 研究生院-公众号
    "intl": 16,    # 国际处-公众号
}

COL_WIDTHS = [5, 8, 20, 8, 9, 12, 9,
              30, 22, 24, 20,
              30, 22, 24, 20,
              30, 22, 24, 30, 20, 28]
# 公众号列需要更宽以容纳图片
WECHAT_COL_WIDTH = 22  # 图片大约 100x100 像素，对应约22列宽

DEPT_KEYS = ["career", "grad", "intl"]
QR_NOISE = {"二维码", "官网二维码", "我们二维码", "跳转二维码"}


def build_rows(data):
    prov_order = {"广东省": 0, "吉林省": 1, "辽宁省": 2, "黑龙江省": 3}
    data.sort(key=lambda r: (prov_order.get(r.get("province"), 9),
                             gs.TIER_ORDER.get(r.get("tier"), 9),
                             r.get("city", ""),
                             r.get("name", "")))
    rows = []
    for i, r in enumerate(data, 1):
        depts = r.get("depts") or {}
        row = [i, r["province"], r["name"], r["city"], r["tier"], r["school_type"],
               gs.rank_str(r["name"])]
        for k in DEPT_KEYS:
            v = depts.get(k) or {}
            wechat_val = wechat_value(v)
            if k == "intl":
                row += [v.get("url", ""), wechat_val,
                        "; ".join(v.get("email", [])), gs.leaders_str(v),
                        "; ".join(v.get("phone", []))]
            else:
                row += [v.get("url", ""), wechat_val,
                        "; ".join(v.get("email", [])), "; ".join(v.get("phone", []))]
        row.append(r.get("web_fail_reason", ""))
        rows.append(row)
    return rows


def wechat_value(v):
    """公众号：返回名称或标记为二维码"""
    w = v.get("wechat", "")
    if not w:
        return ""
    if w in QR_NOISE:
        return "【公众号二维码】"
    return w


def has_qrcode_image(name, dept):
    """检查是否有对应的二维码图片"""
    for ext in (".jpg", ".png", ".jpeg", ".gif"):
        path = os.path.join(QR_DIR, f"{name}_{dept}{ext}")
        if os.path.exists(path):
            return path
    return None


def main():
    with open(os.path.join(BASE, "index.json"), encoding="utf-8") as f:
        data = json.load(f)

    by_prov = {}
    for r in data:
        by_prov.setdefault(r["province"], []).append(r)

    wb = xlsxwriter.Workbook(OUT)

    title_fmt = wb.add_format({"bold": True, "font_size": 14, "align": "center",
                               "bg_color": "#1e5aa8", "font_color": "#ffffff"})
    head_fmt = wb.add_format({"bold": True, "bg_color": "#dbe7f6", "border": 1,
                              "text_wrap": True, "valign": "vcenter", "align": "center"})
    cell_fmt = wb.add_format({"border": 1, "valign": "top", "text_wrap": True})
    qr_cell_fmt = wb.add_format({"border": 1, "valign": "top", "align": "center",
                                 "bg_color": "#fff8e1"})
    no_qr_fmt = wb.add_format({"border": 1, "valign": "top", "align": "center",
                              "italic": True, "font_color": "#9ca3af", "font_size": 10})

    # 按院校档次区分的行背景色
    tier_row_fmt = {
        "985":    wb.add_format({"border": 1, "valign": "top", "text_wrap": True, "bg_color": "#e3eefb"}),
        "211":    wb.add_format({"border": 1, "valign": "top", "text_wrap": True, "bg_color": "#eaf3fb"}),
        "双一流": wb.add_format({"border": 1, "valign": "top", "text_wrap": True, "bg_color": "#f3f7fc"}),
        "双非":   wb.add_format({"border": 1, "valign": "top", "text_wrap": True}),
    }
    tier_qr_fmt = {
        "985":    wb.add_format({"border": 1, "valign": "top", "align": "center", "bg_color": "#fff3d6"}),
        "211":    wb.add_format({"border": 1, "valign": "top", "align": "center", "bg_color": "#fff6e0"}),
        "双一流": wb.add_format({"border": 1, "valign": "top", "align": "center", "bg_color": "#fff9ea"}),
        "双非":   wb.add_format({"border": 1, "valign": "top", "align": "center", "bg_color": "#fff8e1"}),
    }

    def fill_sheet(ws, rows, data, with_province, title):
        cols = HEADER if with_province else [h for h in HEADER if h != "省份"]
        ws.merge_range(0, 0, 0, len(cols) - 1, title, title_fmt)
        for c, h in enumerate(cols):
            ws.write(1, c, h, head_fmt)
            # 列宽
            idx = c if with_province else c + 1
            ws.set_column(c, c, COL_WIDTHS[idx])
        # 公众号列宽加大
        for col in (WECHAT_COL_INDEX["career"], WECHAT_COL_INDEX["grad"], WECHAT_COL_INDEX["intl"]):
            ws.set_column(col, col, WECHAT_COL_WIDTH)
        # 数据行
        for ri, row in enumerate(rows, 2):
            name = row[2]  # 高校名称列
            tier = data[ri - 2]["tier"] if ri - 2 < len(data) else "双非"
            row_fmt = tier_row_fmt.get(tier, cell_fmt)
            row_qr_fmt = tier_qr_fmt.get(tier, qr_cell_fmt)
            for ci, val in enumerate(row):
                # 公众号列特殊处理
                is_wechat_col = ci in (WECHAT_COL_INDEX["career"],
                                       WECHAT_COL_INDEX["grad"],
                                       WECHAT_COL_INDEX["intl"])
                dept_key = None
                if ci == WECHAT_COL_INDEX["career"]:
                    dept_key = "career"
                elif ci == WECHAT_COL_INDEX["grad"]:
                    dept_key = "grad"
                elif ci == WECHAT_COL_INDEX["intl"]:
                    dept_key = "intl"

                if is_wechat_col and dept_key:
                    # 尝试插入二维码图片
                    qr_path = has_qrcode_image(name, dept_key)
                    if qr_path and val == "【公众号二维码】":
                        # 设置行高以容纳图片
                        ws.set_row(ri - 1, 90)
                        ws.write(ri, ci, "", row_qr_fmt)
                        # 依据图片原始尺寸等比缩放，使二维码边长约90px，适配单元格
                        try:
                            from PIL import Image
                            im = Image.open(qr_path)
                            w, h = im.size
                            target = 90
                            scale = target / max(w, h)
                            ws.insert_image(ri, ci, qr_path, {
                                "x_scale": scale, "y_scale": scale,
                                "object_position": 1,
                            })
                        except Exception as e:
                            ws.insert_image(ri, ci, qr_path, {
                                "x_scale": 0.25, "y_scale": 0.25,
                                "object_position": 1,
                            })
                    else:
                        # 文本（公众号名称或"无"）
                        if val:
                            ws.write(ri, ci, val, row_fmt)
                        else:
                            ws.write(ri, ci, "—", no_qr_fmt)
                else:
                    if val:
                        ws.write(ri, ci, val, row_fmt)
                    else:
                        ws.write(ri, ci, "—", row_fmt)
        ws.freeze_panes(2, 0)

    # 全国总表
    ws = wb.add_worksheet("全国总表")
    all_rows = build_rows(data)
    fill_sheet(ws, all_rows, data, with_province=True, title="全国高校汇总表（就业/研究生/国际处 渠道 + 软科排名 + 二维码，按985-211-双一流-双非排列）")

    # 分省 sheet
    for province, rows in by_prov.items():
        ws_name = province.replace("省", "")
        ws = wb.add_worksheet(ws_name)
        prov_rows = build_rows(rows)
        fill_sheet(ws, prov_rows, rows, with_province=False, title=f"{province}高校汇总表（按985-211-双一流-双非排列）")

    wb.close()
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
