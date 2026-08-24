# SA_UM_contact

**SA_UM_contact**（SA = 澳门大学信息学院）全国高校一览 · 硕士招生目标院校库

GitHub Pages 在线地址：**https://hy-xuan123.github.io/SA_UM_contact/**

本仓库为澳门大学信息学院与工学院硕士招生组提供目标高校的集中调研视图：以交互式地图呈现全国高校分布，并整合各校就业中心、研究生院、国际处的官方渠道（官网、公众号、邮箱、电话），辅助招生对接与线下/线上活动策划。

> 語言切換：本文件同時提供 [简体中文](#简体中文版) 與 [繁體中文](#繁體中文版) 兩種版本。

---

# 简体中文版

## 页面功能

- `index.html` — 高校地图总览（Leaflet 在线地图）
  - 按省份 / 院校档次（985 → 211 → 双一流 → 双非）筛选
  - 点击高校图标高亮显示该院校
  - 展示部门渠道：就业中心 / 研究生院 / 国际处的官网、公众号、邮箱、电话

## 数据说明

`dataset/` 目录为数据资产，已纳入版本库，随 GitHub Pages 自动部署。其结构如下：

| 路径 | 说明 |
| --- | --- |
| `index.json` | 全部高校汇总数据（285 所，含经纬度、院校档次、软科排名、部门渠道） |
| `index_depts.json` | 各部门渠道抓取中间数据 |
| `contact_audit.json` | 联系方式归属核验数据 |
| `全国重点院校/` | 各高校数据 JSON（按省份组织） |
| `全国重点院校/全国重点院校_汇总.csv` | 广东 + 东北三省（吉辽黑）157 所高校汇总表 |
| `全国重点院校/全国高校汇总.csv` | 全国 285 所高校汇总表 |
| `全国重点院校/全国高校汇总表.xlsx` | Excel 汇总表（含公众号二维码图片，按层次配色） |
| `qrcodes/` | 公众号二维码图片 |

## 本地预览

```bash
python -m http.server 8000
# 浏览器打开 http://localhost:8000/index.html
```

## 数据更新

重新抓取 / 更新高校数据后，通过以下脚本重建汇总表：

```bash
python build_index.py    # 汇总各校 JSON -> index.json
python gen_summary.py    # 生成各省及全国汇总 CSV
python gen_excel.py      # 生成带二维码与层次配色的 Excel
python record_changes.py # 记录数据变更日志（可选）
```

## GitHub Pages 部署

- 在线地址：**https://hy-xuan123.github.io/SA_UM_contact/**
- 发布源：`gh-pages` 分支（当前）/ 或 `main` 分支
- 数据文件统一为 UTF-8 编码，浏览器可直接解析

更新线上数据：

```bash
git add -A
git commit -m "更新数据"
git push origin <branch>
```

## 声明

- 数据来源于各高校官方网站 / 微信公众号等公开渠道，仅供招生对接参考。
- 部分院校官网因网络策略（WAF、超时等）未能抓取，对应字段标注为「未获取」。
- 澳门大学保留对数据口径的最终解释权。

---

# 繁體中文版

## 頁面功能

- `index.html` — 高校地圖總覽（Leaflet 線上地圖）
  - 按省份／院校檔次（985 → 211 → 雙一流 → 雙非）篩選
  - 點擊高校圖示高亮顯示該院校
  - 展示部門渠道：就業中心／研究生院／國際處的官網、公眾號、電郵、電話

## 資料說明

`dataset/` 目錄為資料資產，已納入版本庫，隨 GitHub Pages 自動部署。其結構如下：

| 路徑 | 說明 |
| --- | --- |
| `index.json` | 全部高校彙總資料（285 所，含經緯度、院校檔次、軟科排名、部門渠道） |
| `index_depts.json` | 各部門渠道抓取中間資料 |
| `contact_audit.json` | 聯絡方式歸屬核驗資料 |
| `全國重點院校/` | 各高校資料 JSON（按省份組織） |
| `全國重點院校/全國重點院校_彙總.csv` | 廣東 + 東北三省（吉遼黑）157 所高校彙總表 |
| `全國重點院校/全國高校彙總.csv` | 全國 285 所高校彙總表 |
| `全國重點院校/全國高校彙總表.xlsx` | Excel 彙總表（含公眾號二維碼圖片，按層次配色） |
| `qrcodes/` | 公眾號二維碼圖片 |

## 本地預覽

```bash
python -m http.server 8000
# 瀏覽器開啟 http://localhost:8000/index.html
```

## 資料更新

重新抓取／更新高校資料後，透過以下腳本重建彙總表：

```bash
python build_index.py    # 彙總各校 JSON -> index.json
python gen_summary.py    # 產生各省及全國彙總 CSV
python gen_excel.py      # 產生含二維碼與層次配色的 Excel
python record_changes.py # 記錄資料變更日誌（可選）
```

## GitHub Pages 部署

- 線上地址：**https://hy-xuan123.github.io/SA_UM_contact/**
- 發布源：`gh-pages` 分支（目前）／或 `main` 分支
- 資料檔案統一為 UTF-8 編碼，瀏覽器可直接解析

更新線上資料：

```bash
git add -A
git commit -m "更新資料"
git push origin <branch>
```

## 聲明

- 資料來源於各高校官方網站／微信公眾號等公開渠道，僅供招生對接參考。
- 部分院校官網因網路策略（WAF、逾時等）未能抓取，對應欄位標註為「未取得」。
- 澳門大學保留對資料口徑之最終解釋權。
