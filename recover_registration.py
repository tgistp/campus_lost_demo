"""Local operator recovery only. There is deliberately no browser recovery endpoint."""
import argparse
import sqlite3
import secrets
from pathlib import Path
import core


def recover(item_ids=None, all_unlinked=False):
    core.init_db()
    with core.connect() as con:
        unlinked = {r[0] for r in con.execute("SELECT i.id FROM items i LEFT JOIN registrations r ON r.item_id=i.id WHERE r.item_id IS NULL")}
    selected = unlinked if all_unlinked else set(item_ids or [])
    if not selected or not selected.issubset(unlinked):
        raise ValueError("연결되지 않은 등록 번호만 선택할 수 있습니다.")
    stamp = core.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    backup_path = core.DATA / f"before-registration-recovery-{stamp}.db"
    with core.connect() as con:
        backup = sqlite3.connect(backup_path)
        try:
            con.backup(backup)
        finally:
            backup.close()
    code, session = core.create_owner("local-operator")
    with core.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        for iid in sorted(selected):
            con.execute("INSERT INTO registrations(item_id,code_hash) VALUES (?,?)", (iid, core.code_hash(code)))
        core.sec.event(con, core.now(), "local_registration_recovery", outcome="ok")
    core.logout(session)
    destination = core.DATA / f"private-registration-code-{stamp}.txt"
    destination.write_text("등록 번호: " + ", ".join(map(str, sorted(selected))) + "\n확인 코드:\n" + code + "\n\n다른 사람에게 공유하지 마세요.\n", encoding="utf-8")
    try:
        destination.chmod(0o600)
    except OSError:
        pass
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="이 컴퓨터에서만 기존 미연결 등록물의 코드를 복구합니다.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-unlinked", action="store_true")
    group.add_argument("--item-id", type=int, action="append")
    args = parser.parse_args()
    try:
        path = recover(args.item_id, args.all_unlinked)
        print("Recovery complete. Open this LOCAL file for your private code:")
        print(path)
    except (ValueError, sqlite3.Error):
        print("Recovery failed. Check the selected IDs and local database.")
        raise SystemExit(1)
