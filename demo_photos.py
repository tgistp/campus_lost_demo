"""Attach clearly labelled generated demo photos without replacing real uploads."""
import json
import shutil
import uuid
import core


def install_demo_photos():
    core.init_db()
    assets = core.BASE / "assets" / "demo_photos"
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    count = 0
    folder = core.DATA / "images"
    folder.mkdir(parents=True, exist_ok=True)
    if folder.resolve().parent != core.DATA.resolve():
        raise ValueError("사진 저장 경로를 확인해 주세요.")
    with core.connect() as con:
        for item in manifest["items"]:
            source = (assets / item["file"]).resolve()
            if source.parent != assets.resolve() or not source.is_file():
                continue
            ids = [r[0] for r in con.execute("SELECT id FROM items WHERE title=? AND image=''", (item["title"],))]
            for iid in ids:
                relative = f"images/{uuid.uuid4().hex}.jpg"
                shutil.copyfile(source, core.DATA / relative)
                try:
                    changed = con.execute("UPDATE items SET image=?,is_demo_image=1 WHERE id=? AND image=''", (relative, iid)).rowcount
                except Exception:
                    (core.DATA / relative).unlink(missing_ok=True)
                    raise
                if not changed:
                    (core.DATA / relative).unlink(missing_ok=True)
                count += changed
            if item.get("question"):
                con.execute("""UPDATE items SET verification_question=? WHERE title=?
                    AND is_demo_image=1 AND verification_question='' AND private_hint<>''""",
                    (item["question"], item["title"]))
    return count


if __name__ == "__main__":
    print("Demo photos attached:", install_demo_photos())
