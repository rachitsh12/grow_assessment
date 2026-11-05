"""Approval gate: the ONLY place an action can become 'applied' / 'posted', and only with the user's OK (--approve)."""
SPEC = {"reads": [], "optional_reads": ["actions"], "writes": ["approvals"]}

DONE = {"apply": "applied", "post": "posted"}


async def run(ctx):
    actions = ctx.get("actions") or {}
    for who, a in sorted(actions.items()):
        if a.get("status") != "pending_approval":
            ctx.put(f"approvals.{who}", {"status": a.get("status"), "note": "nothing pending"})
        elif ctx.config.approve:
            ctx.put(f"approvals.{who}", {"status": DONE.get(a["type"], "done"), "note": "approved by user (--approve); simulated"})
            ctx.remember("fact", f"approval_{who}", f"Approval: user approved the {a['type']} action ({who}); {DONE.get(a['type'], 'done')}", source="--approve")
        else:
            ctx.put(f"approvals.{who}", {"status": "pending_approval", "note": "waiting for the user's OK; nothing sent"})
            ctx.remember("fact", f"approval_{who}", f"Approval: {who} {a['type']} is waiting for the user's OK; nothing sent", source="approval gate")
