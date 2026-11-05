"""Cohort generator for `run --users N`: same goal, small profile variations (deterministic, seeded)."""
import copy
import random

Q1 = ["SELECT MAX(salary) FROM employee WHERE salary < (SELECT MAX(salary) FROM employee);",
      "SELECT DISTINCT salary FROM employee ORDER BY salary DESC LIMIT 1 OFFSET 1;"]
Q2 = ["SELECT c.name FROM customers c INNER JOIN orders o ON c.id = o.customer_id WHERE o.id IS NULL;",   # wrong
      "SELECT c.name FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE o.id IS NULL;",    # right
      "SELECT name FROM customers WHERE id NOT IN (SELECT customer_id FROM orders);",                     # right
      "SELECT c.name FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE;"]                 # error


def make_users(base: dict, n: int, seed: int = 7) -> list:
    rnd = random.Random(seed)
    users = [base]
    for i in range(2, n + 1):
        u = copy.deepcopy(base)
        u["id"], u["name"] = f"u_{i:03d}", f"User {i}"
        u["education"][0]["score"] = f"{5.8 if i % 17 == 0 else round(rnd.uniform(6.2, 8.6), 1)} CGPA"
        u["education"][0]["year"] = rnd.choice([2025, 2026])
        if rnd.random() < 0.2:
            u["skills_claimed"].append("Power BI")            # claimed, no evidence: Mira must not list it
        if rnd.random() < 0.5:
            u["own_words"] = [w for w in u["own_words"] if "timer" not in w]
        u["coding_answers"] = [
            {"question_id": "q_second_highest_salary", "language": "sql", "code": rnd.choice(Q1)},
            {"question_id": "q_customers_without_orders", "language": "sql", "code": rnd.choice(Q2)}]
        users.append(u)
    return users
