# data/

## 公开（git 跟踪）

- `Q&A.xlsx` — 官方金标评测集
- `表描述.sql` — 建表说明
- `extra/`、`extra2/`、`extra3/` — 可公开泛化 / 安全评测集

## 官方 CSV（本地自备，不入库）

将竞赛提供的 8 张表放到本目录后执行 `python scripts/import_data.py`：

| 表名 | 文件名模式 |
|------|------------|
| `dim_product` | `dim_product_*.csv` |
| `ads_cust_info_d` | `ads_cust_info_d_*.csv` |
| `dws_cust_fin_d` | `dws_cust_fin_d_*.csv` |
| `dwd_cust_hold_d` | `dwd_cust_hold_d_*.csv` |
| `dwd_cust_tran_d` | `dwd_cust_tran_d_*.csv` |
| `dws_cust_aset_d` | `dws_cust_aset_d_*.csv` |
| `dim_branch` | `dim_branch_*.csv` |
| `dim_public` | `dim_public_*.csv` |

`/data/*.csv` 已写入根目录 `.gitignore`，请勿提交。
