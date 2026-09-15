"""建议交期测算与交期偏紧评估

依据三个因素：
1. 机台负荷：两周内已排计划量 vs 可用机台日产能；
2. 用纸库存：订单用纸的现有库存是否够用，缺纸按采购周期顺延；
3. 同客户在制订单量：该客户未排产覆盖的在制数量会优先占用产能。
"""
from datetime import timedelta

from django.db.models import Sum

from .models import (
    Machine,
    Order,
    Paper,
    PaperTransaction,
    Schedule,
    today,
)

HORIZON_DAYS = 14              # 排产评估窗口：两周
MACHINE_DAILY_CAPACITY = 10000  # 单台机每日产能（份）
PAPER_LEAD_DAYS = 3            # 缺纸时采购到货周期（天）


def _daily_capacity():
    """可用机台（非维保）数与合计日产能"""
    count = Machine.objects.exclude(status=Machine.Status.MAINTENANCE).count()
    return count, count * MACHINE_DAILY_CAPACITY


def _unscheduled_qty(order, cur):
    """订单在未来排产中尚未覆盖的数量"""
    scheduled = (order.schedules
                 .filter(planned_date__gte=cur, done=False)
                 .aggregate(s=Sum('planned_qty'))['s'] or 0)
    return max(0, order.quantity - scheduled)


def evaluate_due_date(*, customer_id, paper_id, quantity, paper_consumption,
                      exclude_order_id=None):
    """计算建议交期。

    exclude_order_id：评估/编辑既有订单时排除其自身
    （自身排产视为已占产能，自身已领纸视为已备料）。
    """
    cur = today()
    horizon_end = cur + timedelta(days=HORIZON_DAYS - 1)

    # ---- 产能：两周内每日已排计划量（不含本单自身排产）----
    machine_count, capacity = _daily_capacity()
    loads = {cur + timedelta(days=i): 0 for i in range(HORIZON_DAYS)}
    sched_qs = Schedule.objects.filter(
        planned_date__range=(cur, horizon_end), done=False)
    if exclude_order_id:
        sched_qs = sched_qs.exclude(order_id=exclude_order_id)
    for row in sched_qs.values('planned_date').annotate(s=Sum('planned_qty')):
        loads[row['planned_date']] += row['s']
    scheduled_load = sum(loads.values())

    # ---- 本单自身排产：已完成产量 + 未来排产按日期累计，哪天够数哪天算完 ----
    done_qty = 0
    own_future = {}
    if exclude_order_id:
        done_qty = (Schedule.objects
                    .filter(order_id=exclude_order_id, done=True)
                    .aggregate(s=Sum('planned_qty'))['s'] or 0)
        for row in (Schedule.objects
                    .filter(order_id=exclude_order_id,
                            planned_date__gte=cur, done=False)
                    .values('planned_date').annotate(s=Sum('planned_qty'))):
            own_future[row['planned_date']] = row['s']

    own_needed = max(0, quantity - done_qty)
    own_future_total = sum(own_future.values())
    cum_own = 0
    own_cover_date = None
    for d in sorted(own_future):
        cum_own += own_future[d]
        if cum_own >= own_needed:
            own_cover_date = d
            break
    # 自身排产未覆盖的缺口，转由空闲产能池兜底
    shortfall = max(0, own_needed - own_future_total)

    # ---- 同客户在制订单：未排产部分与本单缺口争夺空闲产能 ----
    wip_orders = (Order.objects
                  .filter(customer_id=customer_id)
                  .exclude(status=Order.Status.COMPLETED)
                  .exclude(pk=exclude_order_id))
    wip_qty = sum(_unscheduled_qty(o, cur) for o in wip_orders)
    wip_count = wip_orders.count()

    # 逐日累计空闲产能，覆盖"同客户在制未排量 + 本单未排产缺口"的最早一天
    pool = wip_qty + shortfall
    free_cover_date = None
    if pool <= 0:
        free_cover_date = cur
    else:
        cum = 0
        for d in sorted(loads):
            cum += max(0, capacity - loads[d])
            if cum >= pool:
                free_cover_date = d
                break
        if free_cover_date is None:
            # 两周窗口内排不下：按剩余需求与日产能估算顺延
            remaining = pool - cum
            extra = (remaining + capacity - 1) // capacity if capacity else HORIZON_DAYS
            free_cover_date = horizon_end + timedelta(days=max(1, extra))

    # 本单完成日 = 自身排产覆盖日与空闲产能覆盖日两者取晚
    fit_date = max(own_cover_date or cur, free_cover_date)
    capacity_tight = fit_date > horizon_end
    capacity_date = fit_date

    # ---- 纸张：现有库存是否够用（扣除本单已领数量）----
    paper = Paper.objects.get(pk=paper_id)
    paper_secured = 0
    if exclude_order_id:
        paper_secured = (PaperTransaction.objects
                         .filter(order_id=exclude_order_id, paper_id=paper_id,
                                 tx_type=PaperTransaction.TxType.OUT)
                         .aggregate(s=Sum('quantity'))['s'] or 0)
    paper_unknown = paper_consumption <= 0  # 未填用纸量，无法核对库存
    paper_needed = max(0, paper_consumption - paper_secured)
    paper_shortage = max(0, paper_needed - int(paper.stock))
    paper_tight = not paper_unknown and paper_shortage > 0
    paper_date = cur + timedelta(days=PAPER_LEAD_DAYS) if paper_tight else cur

    suggested = max(capacity_date, paper_date)

    reasons = []
    if capacity_tight:
        if own_cover_date and own_cover_date > horizon_end and free_cover_date <= horizon_end:
            reasons.append(f'本单排产计划已排到 {own_cover_date}，超出两周排产窗口')
        else:
            reasons.append(f'两周内机台已排满，按日产能 {capacity:,} 份估算需顺延至 {capacity_date}')
    if paper_tight:
        reasons.append(f'用纸缺口 {paper_shortage:,} 张，采购到货约需 {PAPER_LEAD_DAYS} 天')
    if paper_unknown:
        reasons.append('未填写用纸量，纸库存未核对')
    if not reasons:
        reasons.append('两周内产能与纸张库存均可满足')

    return {
        'suggested_date': suggested.isoformat(),
        'reasons': reasons,
        'capacity': {
            'tight': capacity_tight,
            'fit_date': capacity_date.isoformat(),
            'horizon_days': HORIZON_DAYS,
            'machine_count': machine_count,
            'daily_capacity': capacity,
            'scheduled_load': scheduled_load,
        },
        'paper': {
            'tight': paper_tight,
            'unknown': paper_unknown,
            'name': f'{paper.name} {paper.spec}',
            'stock': int(paper.stock),
            'needed': paper_needed,
            'secured': paper_secured,
            'shortage': paper_shortage,
            'lead_days': PAPER_LEAD_DAYS,
        },
        'customer_wip': {
            'count': wip_count,
            'quantity': wip_qty,
        },
    }


def assess_order(order):
    """评估既有订单的当前交期：是否偏紧、紧在产能还是缺纸"""
    if order.status == Order.Status.COMPLETED:
        return None
    result = evaluate_due_date(
        customer_id=order.customer_id,
        paper_id=order.paper_id,
        quantity=order.quantity,
        paper_consumption=order.paper_consumption,
        exclude_order_id=order.id,
    )
    from datetime import date
    suggested = date.fromisoformat(result['suggested_date'])
    due = order.due_date
    capacity_fit = date.fromisoformat(result['capacity']['fit_date'])
    capacity_tight = capacity_fit > due
    paper_tight = result['paper']['tight']
    tight = suggested > due
    return {
        'level': 'tight' if tight else 'ok',
        'capacity_tight': capacity_tight,
        'paper_tight': paper_tight,
        'suggested_date': result['suggested_date'],
        'days_over': (suggested - due).days if tight else 0,
    }
