"""セーブの書き出し・読み込み: ワールド 1 つ (data/worlds/<id>) と, そこに現れているキャラの定義を 1 つの zip にする.

zip の中身:
  comfy_life.json        目印と中身の一覧 (format / version / ワールドの名前など / 画像を含めたか)
  world/...              ワールドのフォルダそのまま (状態・ログ・あなた・トーク・定義類)
  characters/<id>.json   顔ぶれの定義 (全体の定義から)
  personas/<id>.json     顔ぶれが使っている性格プリセットのうち, 編集・自作したもの
  images/...             画像を含めるときだけ. 記録・定義から参照されている画像と, その索引 (images_index.json)

読み込みは, いつも新しいワールドとして足す (いまのワールド・定義・画像は上書きしない):
  - 定義: 同じ id が無ければ足す. 同じ id で同じ中身 (両方にある項目が同じ) ならそれを使う. 中身が違えば別の人として新しい id を振り,
    読み込んだワールドの記録の中の id を付け替える (同じ人が別の PC で編集された場合も, こちらの定義は変えない).
  - 性格プリセット: こちらに無い id だけ足す.
  - 画像: こちらに無いファイルだけ足す. 画像を含めていなければ, 記録の画像は表示されない (ファイルを後から写せば出る).
ワールドの形式の移行は, そのワールドを開いたときにいつもどおり行う.
"""
import base64
import io
import json
import os
import re
import time
import uuid
import zipfile

from . import store

FORMAT = "comfy-life-world"
VERSION = 1
MANIFEST = "comfy_life.json"
IMG_RE = re.compile(r"^[^:\\]+\.(png|jpe?g|webp)$", re.I)
SKIP_SUFFIX = (".tmp", ".migrated")
MAX_IMPORT = 1024 * 1024 * 1024          # 展開後の合計 (1GB) を超える zip は読まない


def _json_bytes(o):
    return json.dumps(o, ensure_ascii=False, indent=1).encode("utf-8")


def _walk_strings(o, out):
    if isinstance(o, dict):
        for v in o.values():
            _walk_strings(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_strings(v, out)
    elif isinstance(o, str) and IMG_RE.match(o):
        out.add(o)


def _world_files(wdir):
    """ワールドのフォルダのファイル (移行済みの古いフォルダ・一時ファイルは除く) を, フォルダからの相対パス (/ 区切り) で."""
    out = []
    for root, dirs, files in os.walk(wdir):
        dirs[:] = [d for d in dirs if not d.endswith(SKIP_SUFFIX)]
        for f in files:
            if f.endswith(SKIP_SUFFIX) or f == store.MIGRATED_MARK:
                continue
            full = os.path.join(root, f)
            out.append((os.path.relpath(full, wdir).replace(os.sep, "/"), full))
    return sorted(out)


def export_world(wid, images=False):
    """ワールドを zip にする. (ファイル名, zip のバイト列, 中身の要約) を返す."""
    meta = store.load_worlds()
    w = next((x for x in meta.get("worlds") or [] if x["id"] == wid), None)
    if not w:
        raise KeyError("ワールドが見つかりません: %s" % wid)
    wdir = store.dpath("worlds", wid)
    files = _world_files(wdir)
    defs = store.all_characters()
    cast = [c for c in store.load_cast(wid) if c in defs]
    personas = {c: defs[c].get("persona_id") for c in cast if defs[c].get("persona_id")}
    custom = {p for p in personas.values() if os.path.exists(store.dpath("personas", p + ".json"))}
    used = set()
    if images:
        for rel, full in files:
            if rel.endswith(".json"):
                _walk_strings(store.load(full), used)
        for c in cast:
            _walk_strings(defs[c], used)
        used = {p for p in used if os.path.isfile(store.dpath("images", *p.split("/")))}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = {"format": FORMAT, "version": VERSION, "t": time.time(),
                "world": {k: v for k, v in w.items() if k != "id"}, "world_id": wid,
                "characters": cast, "personas": sorted(custom), "images": len(used), "with_images": bool(images)}
        z.writestr(MANIFEST, _json_bytes(info))
        for rel, full in files:
            z.write(full, "world/" + rel)
        for c in cast:
            z.writestr("characters/%s.json" % c, _json_bytes(defs[c]))
        for p in sorted(custom):
            z.write(store.dpath("personas", p + ".json"), "personas/%s.json" % p)
        if used:
            idx = store.load(store.dpath("images", "index.json"), {}) or {}
            sub = {k: [im for im in v if im.get("path") in used] for k, v in idx.items()}
            z.writestr("images_index.json", _json_bytes({k: v for k, v in sub.items() if v}))
            for p in sorted(used):
                # 画像はもう圧縮されているので, 縮めずに入れる (速さのため)
                z.write(store.dpath("images", *p.split("/")), "images/" + p, compress_type=zipfile.ZIP_STORED)
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", w.get("name") or wid).strip("_") or wid
    fname = "comfy_life_%s_%s%s.zip" % (name, time.strftime("%Y%m%d"), "_images" if images else "")
    return fname, buf.getvalue(), {"characters": len(cast), "images": len(used), "files": len(files)}


def _safe_rel(rel):
    """zip の中のパスを, 外へ出られない相対パスの部品にする (だめなら None)."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or ":" in p for p in parts) or rel.startswith(("/", "\\")):
        return None
    return parts


def _rename_deep(o, ren):
    """記録の中の, キャラ id と完全に一致する文字列・辞書のキーを付け替える."""
    if isinstance(o, dict):
        return {ren.get(k, k): _rename_deep(v, ren) for k, v in o.items()}
    if isinstance(o, list):
        return [_rename_deep(v, ren) for v in o]
    if isinstance(o, str):
        return ren.get(o, o)
    return o


IGNORE_KEYS = ("prompt_history", "met", "icon", "icon_seed", "imported", "origin")


def same_person(here, c):
    """同じ人の定義か: 両方にある項目がすべて同じ. 片方にしかない項目は, 版の違いで後から補われた既定値のことが多いので見ない."""
    keys = (set(here) & set(c)) - set(IGNORE_KEYS)
    return all(store.obj_hash(here[k]) == store.obj_hash(c[k]) for k in keys)


def import_world(data, name=None):
    """zip (バイト列か base64 の文字列) を新しいワールドとして足す. 要約を返す (切り替えはしない)."""
    if isinstance(data, str):
        data = base64.b64decode(data.split(",", 1)[1] if data.startswith("data:") else data)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Comfy LIFE のセーブ (zip) ではありません")
    with z:
        try:
            info = json.loads(z.read(MANIFEST).decode("utf-8"))
        except KeyError:
            raise ValueError("Comfy LIFE のセーブ (zip) ではありません（%s がありません）" % MANIFEST)
        if info.get("format") != FORMAT:
            raise ValueError("Comfy LIFE のセーブではありません")
        if int(info.get("version") or 0) > VERSION:
            raise ValueError("新しい版のアプリで書き出したセーブです（このアプリを新しくしてください）")
        if sum(i.file_size for i in z.infolist()) > MAX_IMPORT:
            raise ValueError("大きすぎます")
        entries = {}
        for i in z.infolist():
            if i.is_dir():
                continue
            parts = _safe_rel(i.filename)
            if parts is None:
                raise ValueError("セーブの中に読めないパスがあります: %s" % i.filename)
            entries["/".join(parts)] = i

        # 定義: 同じ id が無ければそのまま, 同じ中身ならこちらのもの, 違えば別の人として新しい id
        here = store.all_characters()
        ren, added, same = {}, [], []
        incoming = []
        for key in entries:
            if key.startswith("characters/") and key.endswith(".json") and key.count("/") == 1:
                c = json.loads(z.read(entries[key]).decode("utf-8-sig"))
                if c.get("id"):
                    incoming.append(c)
        for c in incoming:
            old = here.get(c["id"])
            if old is not None and same_person(old, c):
                same.append(c["id"])
                continue
            if old is not None:
                ren[c["id"]] = "c" + uuid.uuid4().hex[:8]
        for c in incoming:
            if c["id"] in same:
                continue
            c = dict(c, id=ren.get(c["id"], c["id"]))
            c["imported"] = {"t": time.time(), "from": (info.get("world") or {}).get("name", "")}
            store.save_character(c)
            added.append(c["id"])

        # 性格プリセット: こちらに無いものだけ
        have = store.load_personas()
        personas = []
        for key in entries:
            if key.startswith("personas/") and key.endswith(".json") and key.count("/") == 1:
                p = json.loads(z.read(entries[key]).decode("utf-8-sig"))
                if p.get("id") and p["id"] not in have:
                    store.save_persona(p)
                    personas.append(p["id"])

        # ワールド: 新しい id のフォルダへ. JSON はキャラ id を付け替え, ファイル名 (<id>.json) も
        wid = "w" + uuid.uuid4().hex[:8]
        wdir = store.dpath("worlds", wid)
        n = 0
        for key, i in entries.items():
            if not key.startswith("world/"):
                continue
            parts = key.split("/")[1:]
            if not parts:
                continue
            stem, ext = os.path.splitext(parts[-1])
            if ext == ".json" and stem in ren:
                parts[-1] = ren[stem] + ext
            full = os.path.join(wdir, *parts)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            raw = z.read(i)
            if ext == ".json":
                o = json.loads(raw.decode("utf-8-sig"))
                store.save(full, _rename_deep(o, ren) if ren else o)
            else:
                with open(full, "wb") as f:
                    f.write(raw)
            n += 1
        store.init_world(wid)        # 欠けている定義類は既定で補う

        # 画像: こちらに無いファイルだけ
        imgs = 0
        for key, i in entries.items():
            if key.startswith("images/"):
                full = store.dpath("images", *key.split("/")[1:])
                if not os.path.exists(full):
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    with open(full, "wb") as f:
                        f.write(z.read(i))
                    imgs += 1
        if "images_index.json" in entries:
            idx = store.load(store.dpath("images", "index.json"), {}) or {}
            for k, v in json.loads(z.read(entries["images_index.json"]).decode("utf-8")).items():
                cur = idx.setdefault(k, [])
                paths = {im.get("path") for im in cur}
                cur.extend(im for im in v if im.get("path") not in paths)
            store.save(store.dpath("images", "index.json"), idx)

    meta = store.load_worlds()
    src = dict(info.get("world") or {})
    w = {k: v for k, v in src.items() if k in ("alone", "start_bonds", "created")}
    if w.get("start_bonds") and ren:
        w["start_bonds"] = _rename_deep(w["start_bonds"], ren)
    nm = (name or "").strip() or (src.get("name") or "読み込んだワールド")
    if not (name or "").strip() and nm in [x.get("name") for x in meta["worlds"]]:
        nm += "（読み込み）"
    w.update(id=wid, name=nm,
             imported={"t": time.time(), "name": src.get("name", ""), "with_images": bool(info.get("with_images"))})
    w.setdefault("created", time.time())
    meta["worlds"].append(w)
    store.save_worlds(meta)
    return {"id": wid, "name": w["name"], "files": n, "characters": len(incoming), "added": added,
            "renamed": ren, "same": same, "personas": personas, "images": imgs,
            "with_images": bool(info.get("with_images"))}
