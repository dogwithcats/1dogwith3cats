# 在线资产管理系统（Python）

这是一个可直接部署的在线资产管理系统，满足以下需求：

1. 在用资产字段：所属员工、资产 SN、资产型号、电脑密码。
2. 员工离职后，名下资产自动归属到闲置池。
3. 支持手工录入和文件导入（CSV/XLSX）。
4. 纯 Python（Flask + SQLite）。

## 功能说明

- **资产台账**：展示资产状态（在用/闲置）、归属员工、SN、型号、密码。
- **员工管理**：新增员工，一键标记离职。
- **离职自动回收**：员工标记为离职后，其名下资产自动转为闲置。
- **导入能力**：支持导入以下列（中文/英文均兼容）：
  - 所属员工 / employee / owner
  - 资产SN / SN / sn / 资产编号 / 序列号
  - 资产型号 / model / 型号
  - 电脑密码 / password / 密码

## 快速启动

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

浏览器访问：`http://<服务器IP>:5000`

## 导入建议

- 如果你要直接导入现有 Excel（如仓库中的资产统计表），先确认首行是标题行。
- 建议把首行字段改成：`所属员工, 资产SN, 资产型号, 电脑密码`（或使用英文别名）。

## 数据库

- SQLite 文件默认在项目根目录：`assets.db`
- 首次启动会自动建表。
