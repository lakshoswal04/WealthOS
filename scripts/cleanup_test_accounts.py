"""Remove test accounts and simulated broker links from a WealthOS database.

Test runs (pytest uses its own database; the Playwright and smoke runs use
the development one) register accounts under reserved domains. This deletes
those accounts -- everything they own cascades -- and any simulated
(sandbox) broker link left on a real account.

Dry run by default: it prints what it would delete. Pass --yes to delete.

    PYTHONPATH=.:packages:backend .venv/bin/python scripts/cleanup_test_accounts.py [--yes]
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import or_, select

TEST_DOMAINS = ("@example.com", "@wealthos-test.com")


def plan(db) -> tuple[list, list]:
    from app.models import LinkedAccount, User

    users = list(db.scalars(select(User).where(or_(*[User.email.ilike(f"%{d}") for d in TEST_DOMAINS]))
                            .order_by(User.id)))
    test_ids = {u.id for u in users}
    links = [a for a in db.scalars(select(LinkedAccount).where(LinkedAccount.is_simulated.is_(True)))
             if a.user_id not in test_ids]
    return users, links


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="actually delete")
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        users, links = plan(db)
        print(f"{len(users)} test account(s) under {', '.join(TEST_DOMAINS)}:")
        for u in users[:15]:
            print(f"  #{u.id} {u.email}")
        if len(users) > 15:
            print(f"  … and {len(users) - 15} more")
        print(f"{len(links)} simulated broker link(s) on other accounts:")
        for a in links:
            print(f"  link #{a.id} ({a.provider}, {a.account_reference}) on user #{a.user_id}")
        if not args.yes:
            print("\nDry run: nothing deleted. Re-run with --yes to delete.")
            return 0
        for a in links:
            db.delete(a)
        for u in users:
            db.delete(u)
        db.commit()
        print(f"\nDeleted {len(users)} account(s) and {len(links)} simulated link(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
