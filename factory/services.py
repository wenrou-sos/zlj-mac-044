"""纸张批次出入库业务逻辑

- 入库：按批次登记（批次号 + 到货日期 + 保质期）
- 出库：默认按“先到期先出”（FEFO）顺序从各批次扣减
"""
from datetime import datetime, timedelta

from django.db import transaction

from rest_framework.serializers import ValidationError

from .models import Paper, PaperBatch, PaperTransaction, today as _today


def parse_date(raw, field, default=None):
    """解析 YYYY-MM-DD 日期；为空时返回 default；非法抛 400"""
    if raw in (None, ''):
        return default
    if isinstance(raw, datetime):
        return raw.date()
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValidationError({field: '日期格式应为 YYYY-MM-DD'})


def compute_expiry(arrival_date, shelf_life_days, expiry_date_raw):
    """保质期：优先取直接指定的到期日，否则按保质期天数推算；都没有则为空"""
    expiry = parse_date(expiry_date_raw, 'expiry_date', default=None)
    if expiry:
        return expiry
    if shelf_life_days in (None, ''):
        return None
    try:
        days = int(shelf_life_days)
    except (TypeError, ValueError):
        raise ValidationError({'shelf_life_days': '保质期天数必须为整数'})
    if days <= 0:
        raise ValidationError({'shelf_life_days': '保质期天数必须大于 0'})
    return arrival_date + timedelta(days=days)


def fefo_batches(paper, include_empty=False):
    """先到期先出：到期日早的优先，无保质期的排最后；其次早到货优先"""
    qs = paper.batches.all()
    rows = []
    for b in qs:
        remaining = b.remaining
        if not include_empty and remaining <= 0:
            continue
        rows.append((b, remaining))
    rows.sort(key=lambda item: (
        item[0].expiry_date is None,
        item[0].expiry_date or _today() + timedelta(days=99999),
        item[0].arrival_date,
        item[0].id,
    ))
    return rows


def plan_fefo(paper, qty):
    """给定出库数量，按 FEFO 生成各批次分配方案 [(batch, remaining, take), ...]"""
    plan, left = [], qty
    for b, remaining in fefo_batches(paper):
        if left <= 0:
            break
        take = min(remaining, left)
        plan.append((b, remaining, take))
        left -= take
    return plan, left


@transaction.atomic
def stock_in(paper, qty, batch_no, arrival_date, expiry_date=None,
             shelf_life_days=None, note=''):
    """批次入库：同批次号再次到货则累加数量；新批次创建批次档案"""
    if qty <= 0:
        raise ValidationError({'quantity': '入库数量必须大于 0'})
    batch_no = (batch_no or '').strip()
    if not batch_no:
        raise ValidationError({'batch_no': '请填写批次号'})
    if not arrival_date:
        raise ValidationError({'arrival_date': '请填写到货日期'})
    if expiry_date and expiry_date < arrival_date:
        raise ValidationError({'expiry_date': '保质期到期日不能早于到货日期'})

    batch = paper.batches.filter(batch_no=batch_no).first()
    if batch:
        # 同批次补到货：仅累加数量，批次档案维持首次登记的日期/保质期
        created = False
    else:
        batch = PaperBatch.objects.create(
            paper=paper, batch_no=batch_no, arrival_date=arrival_date,
            expiry_date=expiry_date, note=note or '',
        )
        created = True

    PaperTransaction.objects.create(
        paper=paper, batch=batch, tx_type=PaperTransaction.TxType.IN,
        quantity=qty, tx_date=arrival_date, note=note or '采购入库',
    )
    paper.stock = (paper.stock or 0) + qty
    paper.save(update_fields=['stock'])
    return batch, created


@transaction.atomic
def stock_out(paper, qty, order=None, note='', allocations=None, tx_date=None):
    """批次出库

    allocations: 可选 [{batch: id/batch, quantity: n}]，手动指定各批次扣减量；
                 缺省时按 FEFO 自动分配。
    返回 (分配明细 [{batch, take}], 是否含过期批次)。
    """
    if qty <= 0:
        raise ValidationError({'quantity': '出库数量必须大于 0'})
    tx_date = tx_date or _today()

    used_expired = False
    lines = []  # [(batch, take)]

    if allocations:
        total = 0
        batch_map = {b.id: b for b in paper.batches.all()}
        for item in allocations:
            bid = item.get('batch')
            take = item.get('quantity')
            if isinstance(bid, PaperBatch):
                batch, bid = bid, bid.id
            else:
                batch = batch_map.get(bid)
            if not batch:
                raise ValidationError({'allocations': '存在不属于该纸张的批次'})
            try:
                take = int(take)
            except (TypeError, ValueError):
                raise ValidationError({'allocations': '批次数量必须为整数'})
            if take < 0:
                raise ValidationError({'allocations': '批次数量不能为负'})
            if take == 0:
                continue
            if take > batch.remaining:
                raise ValidationError(
                    {'allocations': f'批次 {batch.batch_no} 剩余 {batch.remaining} 张，不足 {take} 张'})
            if batch.expiry_state == 'expired':
                used_expired = True
            total += take
            lines.append((batch, take))
        if total != qty:
            raise ValidationError(
                {'allocations': f'各批次合计 {total} 张，与出库数量 {qty} 张不一致'})
    else:
        plan, shortage = plan_fefo(paper, qty)
        if shortage > 0:
            raise ValidationError({'detail': f'库存不足，当前库存 {paper.stock} 张'})
        for b, _remaining, take in plan:
            if b.expiry_state == 'expired':
                used_expired = True
            lines.append((b, take))

    for batch, take in lines:
        PaperTransaction.objects.create(
            paper=paper, batch=batch, tx_type=PaperTransaction.TxType.OUT,
            quantity=take, order=order, tx_date=tx_date,
            note=note or f'生产领料（批次 {batch.batch_no}）',
        )
    paper.stock = (paper.stock or 0) - qty
    paper.save(update_fields=['stock'])
    return [{'batch_id': b.id, 'batch_no': b.batch_no, 'quantity': t} for b, t in lines], used_expired
