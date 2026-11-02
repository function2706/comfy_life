# -*- coding: utf-8 -*-
"""セーブエディタ (設定 → データ. 画面は static/app.js の saveEditor): セーブの中身を木で見て, 値を書き換える・消す.
場所 (path) は鍵の列: ["player", "money"] / ["state", <id>, "params", "affection"] / ["char", <id>, "name"] など.
いちばん上: player (あなた・お金・借金・スキル・持ち物) / state (相手の状態. 次に id) / char (相手の定義. 次に id) /
presence (在席・外出) / geo (位置・乗り物) / plan (予定) / settings (設定). 書き換えは判断の記録 (trace) に残す.
"""
import time

from . import store

ROOTS = [("player", "あなた"), ("presence", "在席・外出"), ("geo", "位置・乗り物"), ("plan", "予定"), ("settings", "設定")]


class SaveEdit:
    def __init__(self, app):
        self.app = app

    def roots(self):
        """選べる入れ物 [{path, label}] (相手は状態と定義を一人ずつ)."""
        out = [{"path": [k], "label": v} for k, v in ROOTS]
        for cid, c in self.app.chars.items():
            out.append({"path": ["state", cid], "label": "%sの状態" % c.get("name", cid)})
            out.append({"path": ["char", cid], "label": "%sの定義" % c.get("name", cid)})
        return out

    def _root(self, path):
        """場所 → (入れ物, その下の鍵の列, 保存する関数)."""
        app = self.app
        if not path:
            raise ValueError("場所がありません")
        head = path[0]
        if head in ("state", "char"):
            if len(path) < 2 or path[1] not in app.chars:
                raise ValueError("相手が見つかりません")
            cid = path[1]
            if head == "state":
                return app.state(cid), path[2:], (lambda: app.save_state(cid))
            c = app.chars[cid]
            return c, path[2:], (lambda: store.save_character(c))
        roots = {"player": (app.life.player_state, app.life.save_player),
                 "presence": (app.presence.rec, app.presence.save),
                 "geo": (app.geo.rec, app.geo.save),
                 "plan": (app.planner.rec, app.planner.save),
                 "settings": ((lambda: app.settings), (lambda: store.save_settings(app.settings)))}
        if head not in roots:
            raise ValueError("知らない場所です: %s" % head)
        get, save = roots[head]
        return get(), path[1:], save

    @staticmethod
    def _step(obj, k):
        if isinstance(obj, list):
            return int(k)
        if isinstance(obj, dict):
            return k
        raise ValueError("その下には項目がありません")

    def _parent(self, path):
        """場所の 1 つ手前の入れ物と最後の鍵, 保存する関数."""
        obj, keys, save = self._root(path)
        if not keys:
            raise ValueError("いちばん上の入れ物そのものは書き換えられません")
        for k in keys[:-1]:
            try:
                obj = obj[self._step(obj, k)]
            except (KeyError, IndexError):
                raise ValueError("その場所はありません")
        return obj, self._step(obj, keys[-1]), save

    def get(self, path):
        obj, keys, _ = self._root(path)
        for k in keys:
            try:
                obj = obj[self._step(obj, k)]
            except (KeyError, IndexError):
                raise ValueError("その場所はありません")
        return {"path": path, "value": obj}

    def set(self, path, value):
        parent, key, save = self._parent(path)
        if isinstance(parent, list) and not 0 <= key < len(parent):
            raise ValueError("その場所はありません")
        old = parent.get(key) if isinstance(parent, dict) else parent[key]
        parent[key] = value
        save()
        self.app.trace.add("saveedit", "書き換えた", None, time.time(), path=path, old=old, new=value)
        return {"ok": True, "old": old, "value": value}

    def delete(self, path):
        parent, key, save = self._parent(path)
        try:
            old = parent.pop(key)
        except (KeyError, IndexError):
            raise ValueError("その場所はありません")
        save()
        self.app.trace.add("saveedit", "消した", None, time.time(), path=path, old=old)
        return {"ok": True, "old": old}
