# app/services/settlement_service.py
from typing import Dict, List
from sqlmodel import Session
from app.models.user import User

def suggest_settlements(nets: Dict[int, float], session: Session) -> List[dict]:
    creditors = [(uid, amt) for uid, amt in nets.items() if amt > 0.005]
    debtors = [(uid, -amt) for uid, amt in nets.items() if amt < -0.005]
    creditors.sort(key=lambda x: x[1], reverse=True)
    debtors.sort(key=lambda x: x[1], reverse=True)
    i = j = 0
    settlements = []
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt_amt = debtors[i]
        creditor_id, cred_amt = creditors[j]
        pay = round(min(debt_amt, cred_amt), 2)
        if pay > 0:
            settlements.append({"from": debtor_id, "to": creditor_id, "amount": pay})
        debt_amt -= pay
        cred_amt -= pay
        if debt_amt <= 0.005:
            i += 1
        else:
            debtors[i] = (debtor_id, debt_amt)
        if cred_amt <= 0.005:
            j += 1
        else:
            creditors[j] = (creditor_id, cred_amt)
    # add names
    for s in settlements:
        s["from_name"] = session.get(User, s["from"]).name
        s["to_name"] = session.get(User, s["to"]).name
    return settlements
