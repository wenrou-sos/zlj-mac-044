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
| 📋 订单管理 | 订单新建/编辑/筛选（关键字、状态、客户、交期级别）；列表内嵌三工序流水线与进度条；详情抽屉维护工序进度、排产、返工 |
| 🗓️ 建议交期 | 新建/编辑订单时按 **两周内机台已排计划量 + 订单用纸现有库存 + 同客户在制订单量** 自动测算建议交期，可一键采用也可手动覆盖；订单详情实时标注当前交期是否偏紧、紧在产能还是缺纸 |
| 📦 纸张材料 | 纸张库存、安全库存预警、库存金额；入库/出库（可关联订单）自动写出入库流水；出库超量拦截 |
| 🏭 机台排产 | 按日期浏览各机台任务（日历式排产表）、班次、计划/实际产量与完成率；机台增删改与状态（生产中/空闲/维保）随排产自动联动 |
| 🔧 返工跟踪 | 返工单全生命周期：待处理 → 返工中 → 已闭环；记录工序、原因（色差/套印/划伤/装订/材料）、数量、责任人、问题描述与处理结果 |

### 工序与订单状态联动

印前 → 印刷 → 装订三道工序各自有状态（未开始/进行中/已完成/返工中）与 0–100% 进度：

- 更新工序进度后**订单主状态自动推导**（印前中 → 印刷中 → 装订中 → 已完成）；
- 登记返工单后，对应工序与订单自动进入 **返工中**；
- 返工闭环后工序自动恢复为进行中，订单回到实际工序；
- 全部工序完成自动记录完工日期。

### 建议交期测算口径

- **产能**：可用机台（非维保）× 单台日产能 10,000 份；逐日累计两周内空闲产能（日产能 − 当日已排计划量），同客户在制订单未排产部分优先占用，覆盖本单需求的最早一天为产能可完成日；两周排不下则按剩余量与日产能估算顺延；
- **纸张**：订单用纸现有库存 ≥ 用纸量（扣除本单已领）即可，缺纸按采购周期 3 天顺延；
- **建议交期** = 产能可完成日与纸张可到料日两者取晚；订单详情中建议日期晚于当前交期即判 **偏紧**，并标明紧在产能还是缺纸。

## 主要 API

| 接口 | 说明 |
|------|------|
| `GET /api/dashboard/` | 看板汇总（统计、预警订单、低库存、7日负荷） |
| `GET/POST /api/orders/`、`PATCH /api/orders/{id}/` | 订单 |
| `GET /api/orders/suggest-due-date/` | 建议交期测算（参数：customer、paper、quantity、paper_consumption、exclude） |
| `GET/PATCH /api/orders/{id}/progress/` | 三工序进度（服务端校验 0–100 与状态一致性） |
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
