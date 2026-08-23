# SA_UM_contact

广东 & 东北三省高校一览 · 澳门大学（UM）信息学院与工学院 硕士招生目标院校库

## 页面

- `index.html` — 高校地图总览（Leaflet 地图 + 按省份/档次筛选 + 点击查看部门渠道：就业中心/研究生院/国际处的官网、公众号、邮箱、电话）
- `contact_audit_report.html` — 部门联系方式归属核验报告
- `HK_university_proposal.html` — 港校（港科广、港城莞等）在广东高校硕士招生策略企划报告

## 数据

`dataset/` 目录包含：
- `index.json` — 全部高校汇总数据（157 所，含经纬度、档次、软科排名、部门渠道）
- `四省高校汇总表.xlsx` — Excel 汇总表（含二维码图片）
- `四省汇总.csv` — 全局汇总 CSV
- `广东省/吉林省/辽宁省/黑龙江省/` — 各省数据与汇总 CSV
- `qrcodes/` — 公众号二维码图片
- `contact_audit.json` — 联系方式归属核验数据

## 本地预览

```bash
python -m http.server 8000
# 打开 http://localhost:8000/index.html
```
