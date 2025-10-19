# app/services/balance_service.py
from typing import Dict
from sqlmodel import Session, select
from app.models.user import User
from app.models.expense import Expense, ExpenseShare

def compute_group_balances(session: Session, group_id: int) -> Dict[int, float]:
    stmt_users = select(User).join_from(User, ExpenseShare)  # we will fetch users differently below
    # fetch group members:
    from app.models.group import GroupMember
    members = session.exec(select(User).join(GroupMember, User.id == GroupMember.user_id).where(GroupMember.group_id == group_id)).all()
    nets = {u.id: 0.0 for u in members}

    expenses = session.exec(select(Expense).where(Expense.group_id == group_id).order_by(Expense.created_at)).all()
    for e in expenses:
        shares = session.exec(select(ExpenseShare).where(ExpenseShare.expense_id == e.id)).all()
        if not shares:
            continue

        if any(s.share is not None for s in shares):
            weights = [float(s.share) if s.share is not None and float(s.share) > 0 else 0.0 for s in shares]
            total_weight = sum(weights)
            if total_weight <= 0:
                per_amounts = {s.user_id: round(e.amount / len(shares),2) for s in shares}
            else:
                per_amounts = {}
                for s,w in zip(shares, weights):
                    per_amounts[s.user_id] = round(e.amount * (w / total_weight), 2)
                allocated = round(sum(per_amounts.values()),2)
                remainder = round(e.amount - allocated, 2)
                if remainder != 0:
                    per_amounts[e.payer_id] = per_amounts.get(e.payer_id,0.0) + remainder
        else:
            per_share = round(e.amount / len(shares), 2)
            per_amounts = {s.user_id: per_share for s in shares}
            allocated = round(per_share * len(shares), 2)
            remainder = round(e.amount - allocated, 2)
            if remainder != 0:
                per_amounts[e.payer_id] = per_amounts.get(e.payer_id,0.0) + remainder

        for uid, amt in per_amounts.items():
            nets.setdefault(uid, 0.0)
            nets[uid] -= amt
        nets.setdefault(e.payer_id, 0.0)
        nets[e.payer_id] += e.amount

    for k in nets:
        nets[k] = round(nets[k], 2)
    return nets
