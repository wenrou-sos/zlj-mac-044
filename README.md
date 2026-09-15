# 🖨️ 印刷厂生产管理系统

面向中小型印刷厂的生产管理系统，覆盖 **订单管理、纸张材料、机台排产、印前/印刷/装订工序进度、交期预警、返工跟踪** 全流程。

- **后端**：Django 5 + Django REST Framework + SQLite
- **前端**：Vue 3 + Element Plus（无构建，本地静态资源，离线可用）
- 内置 5 家客户、7 种纸张、5 台机台、8 个覆盖各状态的样例订单、排产计划与返工单

## 快速开始

```bash
cd printing_system
bash start.sh
# 或手动执行：
#   pip install -r requirements.txt
#   python manage.py migrate
#   python manage.py seed        # 写入/重置样例数据（可重复执行）
#   python manage.py runserver
```

浏览器打开 <http://127.0.0.1:8000>

> 样例日期按运行当天相对生成，保证"逾期 / 紧急 / 预警"数据在任何时候都有效。

## 功能模块

| 模块 | 功能 |
|------|------|
| 📊 生产看板 | 在制/逾期/返工/低库存统计卡；交期三级预警（逾期、≤2天紧急、≤5天预警）；近7日机台负荷图；订单状态分布、机台概况、低库存清单，全部可点击下钻 |
| 📋 订单管理 | 订单新建/编辑/筛选（关键字、状态、客户、交期级别）；列表内嵌三工序流水线与进度条、已领/未领差额；详情抽屉维护工序进度、排产、返工，并可**直接按用纸量领料**（一键领足/分批领，库存不足提示还差多少张，超未领量自动拦截防重复扣料，每次领料自动关联订单与纸张并写流水） |
| 📦 纸张材料 | 纸张库存、安全库存预警、库存金额；入库/出库（可关联订单）自动写出入库流水；出库超量拦截 |
| 🏭 机台排产 | 按日期浏览各机台任务（日历式排产表）、班次、计划/实际产量与完成率；机台增删改与状态（生产中/空闲/维保）随排产自动联动 |
| 🔧 返工跟踪 | 返工单全生命周期：待处理 → 返工中 → 已闭环；记录工序、原因（色差/套印/划伤/装订/材料）、数量、责任人、问题描述与处理结果 |

### 工序与订单状态联动

印前 → 印刷 → 装订三道工序各自有状态（未开始/进行中/已完成/返工中）与 0–100% 进度：

- 更新工序进度后**订单主状态自动推导**（印前中 → 印刷中 → 装订中 → 已完成）；
- 登记返工单后，对应工序与订单自动进入 **返工中**；
- 返工闭环后工序自动恢复为进行中，订单回到实际工序；
- 全部工序完成自动记录完工日期。

## 主要 API

| 接口 | 说明 |
|------|------|
| `GET /api/dashboard/` | 看板汇总（统计、预警订单、低库存、7日负荷） |
| `GET/POST /api/orders/`、`PATCH /api/orders/{id}/` | 订单 |
| `GET/PATCH /api/orders/{id}/progress/` | 三工序进度（服务端校验 0–100 与状态一致性） |
| `POST /api/orders/{id}/receive_paper/` | 订单领料：不传数量按未领量一次领完，传 `quantity` 分批领；库存不足返回还差多少张；超未领量拦截防重复扣料 |
| `GET/POST /api/schedules/`、`PATCH /api/schedules/{id}/` | 机台排产 |
| `POST /api/papers/{id}/stock_in/`、`stock_out/` | 纸张出入库 |
| `GET /api/paper-transactions/` | 出入库流水 |
| `GET/POST /api/reworks/`、`PATCH /api/reworks/{id}/` | 返工单 |
| `GET/POST /api/machines/`、`/api/customers/` | 机台、客户 |

另可访问 Django Admin：`python manage.py createsuperuser` 后登录 <http://127.0.0.1:8000/admin/>。

## 目录结构

```
printing_system/
├── config/                 # Django 项目配置、路由
├── factory/
│   ├── models.py           # 客户/纸张/机台/订单/工序进度/排产/返工/流水
│   ├── serializers.py      # 序列化 + 状态联动与校验
│   ├── views.py            # DRF 视图集 + 看板聚合
│   └── management/commands/seed.py   # 样例数据
├── templates/index.html    # SPA 入口
├── static/
│   ├── vendor/             # Vue / Element Plus 本地资源（离线可用）
│   ├── js/app.js           # 全部前端组件（看板/订单/纸张/排产/返工）
│   └── css/app.css
└── manage.py
```
