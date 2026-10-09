"""沿用旧项目计算顺序，参数全部由 shop.json 提供。"""
import math
from collections import defaultdict

from .common import Problem, read_csv, require, write_csv


def ean_ok(code):
    code = str(code)
    if not code.isascii() or not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    check = digits.pop()
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10 == check


def calculate(rows, shop):
    require(bool(rows), 'candidates.csv 没有商品；请先导入或填写候选商品。')
    p = shop['pricing']
    fee_rate = sum(p['fees'].values())
    keep_rate = 1 - fee_rate - p['coupon_rate']
    out, errors = [], []
    for n, original in enumerate(rows, 2):
        r = dict(original)
        label = f'candidates.csv 第 {n} 行 {r.get("group", "")}/{r.get("art_id", "")}'
        try:
            nums = {k: float(r[k]) for k in ('pack_qty', 'unit_cost_ex_iva', 'weight_kg', 'len_cm', 'wid_cm', 'hei_cm', 'market_low', 'market_high')}
            for key, value in nums.items():
                require(math.isfinite(value) and value > 0, f'{label} 的 {key} 必须为正数；请核对商品数据。')
            qty = int(r['pack_qty'])
            cost = nums['unit_cost_ex_iva'] * p['cost_factor'] * qty
            billable = max(nums['weight_kg'], nums['len_cm'] * nums['wid_cm'] * nums['hei_cm'] / p['volumetric_divisor'])
            ship = next((fee for limit, fee in p['ship_tiers'] if billable <= limit), p['ship_tiers'][-1][1])
            profit = max(p['min_profit'], cost * p['profit_rate'])
            price = math.ceil((cost + p['packaging'] + profit + ship) / keep_rate) - 0.01
            net = price * (1 - fee_rate) - ship
            net_coupon = net - price * p['coupon_rate']
            floor = (cost + p['packaging'] + ship) / keep_rate
            r.update(real_cost=round(cost, 2), ship_est=ship, billable_kg=round(billable, 2),
                     price=round(price, 2), original_price=round(price * p['original_markup'], 2),
                     profit_no_coupon=round(net - cost - p['packaging'], 2),
                     profit_with_coupon=round(net_coupon - cost - p['packaging'], 2),
                     min_safe_price=round(floor, 2), max_discount_pct=max(0, math.floor((1 - floor / price) * 100)),
                     ean_valid=ean_ok(r['ean']), vs_market='OK' if price <= nums['market_high'] else 'ABOVE')
            out.append(r)
        except (ValueError, KeyError, OverflowError) as exc:
            errors.append(f'{label}：{exc}；请修正该行数值后重新定价。')
    if errors: raise Problem(errors)
    warnings, prices = [], defaultdict(list)
    for row in out:
        prices[row['group']].append(row['price'])
        if not row['ean_valid']:
            warnings.append(f"{row['group']}/{row['art_id']} 条码 {row['ean']} 校验失败；填表前请核对。")
    for group, values in prices.items():
        if max(values) / min(values) > p['spread_warn']:
            warnings.append(f"{group}：SKU 价差 {min(values)}～{max(values)} 超过 {p['spread_warn']} 倍，请考虑拆分链接。")
    return out, warnings


def run(batch, shop):
    rows, warnings = calculate(read_csv(batch / 'candidates.csv'), shop)
    write_csv(batch / 'priced.csv', rows)
    return {'count': len(rows), 'output': str(batch / 'priced.csv'), 'warnings': warnings}
