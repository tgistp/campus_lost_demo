"""Idempotently add twenty extra classroom examples, preserving user data."""
import json
import hashlib
import shutil
import uuid
from datetime import timedelta
import core


def add_examples():
    core.init_db()
    with core.connect() as con:
        if not con.execute("SELECT 1 FROM items LIMIT 1").fetchone():
            empty=True
        else:empty=False
    if empty:
        import os
        os.environ["CAMPUS_ALLOW_DEMO"]="1"
        core.seed_demo()
    asset_folder=core.BASE/"assets/demo_photos"
    examples=json.loads((core.BASE/"assets/demo_items.json").read_text(encoding="utf-8"))
    p=core.places();count=0
    image_folder=core.DATA/"images";image_folder.mkdir(parents=True,exist_ok=True)
    if image_folder.resolve().parent!=core.DATA.resolve():raise ValueError("사진 경로를 확인해 주세요.")
    with core.connect() as con:
        demo=core.code_hash("PNU-DEMO")
        alias=con.execute("SELECT owner_hash FROM owner_aliases WHERE alias_hash=?",(demo,)).fetchone()
        owner_hash=alias[0] if alias else demo
        con.execute("INSERT OR IGNORE INTO owners VALUES (?,?)",(owner_hash,core.now().isoformat()))
        for i,item in enumerate(examples):
            if con.execute("SELECT 1 FROM items WHERE demo_key=?",(item["key"],)).fetchone():continue
            source=(asset_folder/item["photo"]).resolve()
            if source.parent!=asset_folder.resolve() or not source.is_file():raise ValueError("시연용 사진이 없습니다.")
            image=f"images/{uuid.uuid4().hex}.jpg";shutil.copyfile(source,core.DATA/image)
            place=item["place"]
            try:
                iid=con.execute("""INSERT INTO items(title,category,color,description,place,lat,lon,found_at,storage,image,
                    private_hint,verification_question,is_demo_image,demo_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                    (item["title"],item["category"],item["color"],item["description"],place,float(p.loc[place,"lat"]),float(p.loc[place,"lon"]),
                     (core.now()-timedelta(hours=i+1)).isoformat(),f"{place} 1층 시연용 보관함 (실제 운영 장소 아님)",image,
                     item["answer"],item["question"],item["key"])).lastrowid
                con.execute("INSERT INTO registrations VALUES (?,?)",(iid,owner_hash));count+=1
            except Exception:
                (core.DATA/image).unlink(missing_ok=True);raise
        core.sec.event(con,core.now(),"demo_examples_added")
    refresh_example_assets()
    return count


def refresh_example_assets():
    """Update only identified generated examples; never overwrite real uploads."""
    folder=core.BASE/"assets/demo_photos"
    examples=json.loads((core.BASE/"assets/demo_items.json").read_text(encoding="utf-8"))
    created=[]
    def digest(path):
        with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()
    changed=0
    try:
        with core.connect() as con:
            for item in examples:
                row=con.execute("SELECT id,image,title,color,description,is_demo_image FROM items WHERE demo_key=?",(item["key"],)).fetchone()
                if not row or not row[5]:continue
                source=(folder/item["photo"]).resolve()
                if source.parent!=folder.resolve() or not source.is_file():raise ValueError("시연용 사진이 없습니다.")
                current=core.sec.image_path(core.DATA,row[1])
                same=current is not None and digest(current)==digest(source)
                if same and tuple(row[2:5])==(item["title"],item["color"],item["description"]):continue
                image=row[1]
                if not same:
                    image=f"images/{uuid.uuid4().hex}.jpg"
                    target=core.DATA/image
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if target.parent.resolve().parent!=core.DATA.resolve():raise ValueError("사진 경로를 확인해 주세요.")
                    created.append(target)
                    shutil.copyfile(source,target)
                con.execute("UPDATE items SET image=?,title=?,color=?,description=? WHERE id=? AND is_demo_image=1",
                            (image,item["title"],item["color"],item["description"],row[0]))
                changed+=1
            if changed:core.sec.event(con,core.now(),"demo_photos_updated")
    except Exception:
        for path in created:path.unlink(missing_ok=True)
        raise
    return changed


if __name__=="__main__":print("Additional demo items:",add_examples())
