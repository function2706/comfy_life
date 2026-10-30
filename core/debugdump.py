"""不具合を報告するときの書き出し: 別の PC で起きたことを, 貼ったテキストだけで開発側が再現・切り分けできるように.

中身 (要点 → 詳細の順. brief なら要点だけ):
- 要点: バージョン (git のコミット)・ワールド・いまの時刻・範囲 / あなた (お金・体力・在席・予定・行動パターン) /
  相手ごとの状態 (params・返信待ち msg_pending・働きかけ approach・謝罪 apology_last・連絡の多さと許容・機嫌の理由・約束・頼まれごと) /
  閉じていた間のまとめ (いちばん新しいもの)
- エラー: API・生成ワーカー・裏のスレッドの例外 (トレースバックつき)・画面側 (ブラウザ) のエラー・server.log のエラー.
  上限 (MAX_CHARS・server.log の行数) とは別枠で, 要点のすぐ後に必ず入れる (件数と最新の 1 行は要点にも)
- 詳細: 判断の記録とあなたの操作 (core/trace.py. 同じ時系列)・トーク・ログ (画像のプロンプトは省く)・一人の時間・日記・server.log (範囲の分)
遊ぶ人がうっかり見てしまわないように (チートにならないように), 画面には中身を出さず, 符号化した 1 つのブロックだけを渡す
(先頭の目印・長さ・チェックサムつき. 途中で切れていれば分かる). 開くのは開発側 (tools/debug_decode.py).
"""
import base64
import json
import os
import re
import subprocess
import time
import zlib
from datetime import datetime

from . import store
from .trace import ERROR_CATS, _xor

BEGIN = "-----BEGIN KURASHI-DUMP v1"
END = "-----END KURASHI-DUMP-----"
WIDTH = 76
MAX_CHARS = 400000          # 詳細が多すぎるときは, 古い方から省く (要点は必ず残す)
MAX_ERRORS = 100            # エラーの欄 (別枠) に入れる件数
MAX_TB_LINES = 40           # 1 件のトレースバックの行数
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def version():
    try:
        r = subprocess.run(["git", "-C", BASE, "log", "-1", "--format=%h %ci"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=5)
        v = r.stdout.decode("utf-8", "replace").strip()
        if v:
            return v
    except (OSError, subprocess.SubprocessError):
        pass
    try:                                    # git が無い: .git の HEAD から
        head = open(os.path.join(BASE, ".git", "HEAD"), encoding="utf-8").read().strip()
        if head.startswith("ref: "):
            return open(os.path.join(BASE, ".git", head[5:]), encoding="utf-8").read().strip()[:7]
        return head[:7]
    except OSError:
        return "不明"


def encode_block(text):
    payload = base64.b64encode(_xor(zlib.compress(text.encode("utf-8"), 9))).decode("ascii")
    crc = zlib.crc32(payload.encode("ascii")) & 0xFFFFFFFF
    lines = [payload[i:i + WIDTH] for i in range(0, len(payload), WIDTH)]
    return "%s len=%d crc=%08x-----\n%s\n%s\n" % (BEGIN, len(payload), crc, "\n".join(lines), END)


def decode_block(s):
    """ブロックを読める形に. (本文, 問題の一覧). 切れていても, 読めたところまで返す."""
    probs = []
    i = s.find(BEGIN)
    if i < 0:
        return "", ["書き出しの目印 (%s) が見つからない" % BEGIN]
    head = s[i:s.find("\n", i)]
    m = re.search(r"len=(\d+) crc=([0-9a-f]{8})", head)
    body = s[s.find("\n", i) + 1:]
    j = body.find(END)
    if j < 0:
        probs.append("終わりの目印が無い (途中で切れている)")
    else:
        body = body[:j]
    payload = re.sub(r"[^A-Za-z0-9+/=]", "", body)
    if m:
        if len(payload) != int(m.group(1)):
            probs.append("長さが合わない (%d / %s 文字. 途中で切れたか, 余計なものが混ざった)" % (len(payload), m.group(1)))
        elif "%08x" % (zlib.crc32(payload.encode("ascii")) & 0xFFFFFFFF) != m.group(2):
            probs.append("チェックサムが合わない (文字が化けた・書き換わった)")
    else:
        probs.append("先頭の行に長さ・チェックサムが無い")
    raw = base64.b64decode(payload[:len(payload) // 4 * 4])
    d = zlib.decompressobj()
    try:
        out = d.decompress(_xor(raw))
    except zlib.error as e:
        return "", probs + ["ほどけない: %s" % e]
    if not d.eof:
        probs.append("終わりまでほどけなかった (読めたところまで)")
    return out.decode("utf-8", "replace"), probs


def _ts(t):
    return datetime.fromtimestamp(t).strftime("%m/%d %H:%M:%S") if t else "-"


def _j(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def _trim(s, n=200):
    s = str(s or "").replace("\n", " ⏎ ")
    return s if len(s) <= n else s[:n] + "…"


class DebugDump:
    def __init__(self, app):
        self.app = app

    def range_of(self, hours=None, day=None, now=None):
        now = now or time.time()
        if day:
            t0 = datetime.strptime(day, "%Y-%m-%d").timestamp()
            return t0, t0 + 86400
        return now - float(hours or 24) * 3600, now + 1      # 記録の時刻は 0.1 秒に丸めてあるので, 直前のものが外れないように

    def build(self, hours=24, day=None, cid=None, brief=False, now=None):
        """書き出しの本文 (読める形) を返す."""
        app = self.app
        now = now or time.time()
        t0, t1 = self.range_of(hours, day, now)
        cids = [cid] if cid else list(app.chars)
        if cid and cid not in app.chars:
            raise KeyError("キャラが見つかりません: %s" % cid)
        world = next((w for w in (store.load_worlds() or {}).get("worlds") or [] if w.get("id") == store.WORLD), {})
        top = ["=== KURASHI デバッグ書き出し ===",
               "version: %s" % version(),
               "world: %s (%s)" % (world.get("name", ""), store.WORLD),
               "now: %s (%d)" % (datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"), now),
               "range: %s 〜 %s" % (_ts(t0), _ts(t1)),
               "target: %s" % ("全員" if not cid else "%s (%s)" % (app.chars[cid].get("name", ""), cid)), ""]
        top += self._me(now) + [""]
        for c in cids:
            top += self._char(c, now) + [""]
        top += self._offline_report(t0, t1)
        errs = self._errors(t0, t1)
        top[top.index("") if "" in top else len(top):0] = ["errors: %d 件%s" % (len(errs), "（最新: %s）" % errs[-1][0] if errs else "")]
        if errs:
            top += ["", "== エラー (%d 件. 新しい %d 件) ==" % (len(errs), min(len(errs), MAX_ERRORS))]
            for head, body in errs[-MAX_ERRORS:]:
                top.append(head)
                top += ["    " + x for x in body[-MAX_TB_LINES:]]
        detail = []
        if not brief:
            detail += self._section("判断の記録とあなたの操作", self._trace(t0, t1, cid))
            for c in cids:
                detail += self._section("トーク: %s" % app.chars[c].get("name", c), self._chat(c, t0, t1))
                detail += self._section("ログ: %s" % app.chars[c].get("name", c), self._log(c, t0, t1))
            detail += self._section("一人の時間", self._mylog(t0, t1))
            detail += self._section("日記", self._diary(t0, t1))
            detail += self._section("server.log", self._server_log(t0, t1))
        text = "\n".join(top + ["", "=== 詳細 ==="] + detail if detail else top)
        if len(text) > MAX_CHARS:            # 長すぎる: 詳細の古い方を省く (要点は残す)
            head = "\n".join(top)
            rest = "\n".join(["", "=== 詳細 (長いので, 古い方を省いた) ==="] + detail)
            text = head + rest[:200] + "\n…（省略）…\n" + rest[-(MAX_CHARS - len(head) - 300):]
        return text

    def dump(self, hours=24, day=None, cid=None, brief=False, now=None):
        text = self.build(hours, day, cid, brief, now)
        return {"block": encode_block(text), "lines": text.count("\n") + 1, "chars": len(text),
                "name": "kurashi_debug_%s.txt" % datetime.fromtimestamp(now or time.time()).strftime("%Y%m%d_%H%M")}

    # ------------------------------------------------------------------ 要点
    def _me(self, now):
        app = self.app
        ps = app.life.player_state()
        P = app.planner.rec()
        pr = app.presence.rec()
        off = app.offline.cfg()
        return ["== あなた ==",
                "money=%s stamina=%s presence=%s place=%s solo=%s" % (ps.get("money"), ps.get("stamina"), pr.get("mode"), pr.get("place"),
                                                                   _j(pr.get("solo"))),
                "skills=%s" % _j({k: round(v, 1) for k, v in (ps.get("skills") or {}).items()}),
                "plan.items=%s" % _j(P.get("items")), "plan.fallback=%s" % _j(P.get("fallback")), "plan.auto=%s" % _j(P.get("auto")),
                "offline.enabled=%s routine(today)=%s" % (off.get("enabled"), _j(off["days"][["mon", "tue", "wed", "thu", "fri", "sat", "sun"][
                    datetime.fromtimestamp(now).weekday()]])),
                "work_log=%s retro_work_v1=%s diary_fix_v1=%s" % (_j(ps.get("work_log")), ps.get("retro_work_v1"), ps.get("diary_fix_v1"))]

    def _char(self, cid, now):
        app = self.app
        char = app.chars[cid]
        st = app.state(cid)
        B = app.bonds
        out = ["== %s (%s) ==" % (char.get("name", ""), cid)]
        try:
            tol = B.tolerance(char, cid, st, now)
        except Exception:  # noqa: BLE001 - 以前のセーブで計算できなくても書き出しは続ける
            tol = None
        out.append("stage=%s mode=%s persona=%s age=%s" % (B.stage(cid), B.mode(cid), char.get("persona_id"), char.get("age")))
        out.append("params=%s" % _j({k: round(v, 1) for k, v in (st.get("params") or {}).items()}))
        out.append("attach(献身・依存)=%s nori=%s" % (_j({k: v for k, v in (st.get("attach") or {}).items() if k != "day"} or None),
                                                     _j(st.get("nori"))))
        out.append("tastes(話題の好み)=%s topic_tags=%s" % (_j(st.get("tastes")), _j((st.get("topic_tags") or [])[-8:])))
        out.append("msg_pending=%s" % _j(dict(st["msg_pending"], due_in_min=round((st["msg_pending"].get("due", now) - now) / 60, 1))
                                          if st.get("msg_pending") else None))
        out.append("approach=%s ap_quiet_until=%s phone_until=%s" % (_j({k: v for k, v in (st.get("approach") or {}).items() if k != "entry"} or None),
                                                                     _ts(st.get("ap_quiet_until")), _ts(st.get("phone_until"))))
        out.append("apology_last=%s apologies=%s" % (_j(st.get("apology_last")), [_ts(t) for t in st.get("apologies") or []]))
        out.append("contacts_24h=%s tolerance=%s contacts=%s" % (round(B._contacts(st, now), 2), tol and round(tol, 2),
                                                                 _j((st.get("contacts") or [])[-12:])))
        out.append("favors(お礼の心当たり)=%s" % _j(st.get("favors")))
        out.append("reasons(機嫌の理由)=%s" % _j([{k: r.get(k) for k in ("t", "kind", "mood", "tell", "delta", "action", "resolved", "told")}
                                                for r in (st.get("reasons") or [])[-10:]]))
        aps = [x for x in app.appoint.all() if x.get("cid") == cid and (x.get("status") in ("asked", "offered", "set", "waiting")
                                                                     or now - x.get("t", 0) < 7 * 86400)]
        out.append("appoints=%s" % _j([{k: x.get(k) for k in ("id", "status", "t", "place", "do", "label", "by", "favor", "fixed", "ask",
                                                               "rounds", "until")} for x in aps]))
        out.append("earn.favors=%s" % _j([f for f in app.earn.favors() if f.get("cid") == cid]))
        return out

    def _offline_report(self, t0, t1):
        rep = self.app.life.player_state().get("offline_report")
        if not rep or rep.get("to", 0) < t0:
            return []
        out = ["== 閉じていた間 (いちばん新しいまとめ) %s 〜 %s pay=%s stamina=%s seen=%s ==" % (
            _ts(rep.get("from")), _ts(rep.get("to")), rep.get("pay"), rep.get("stamina"), rep.get("seen"))]
        for x in rep.get("timeline") or []:
            out.append("%s〜%s %s | %s%s | plan=%s" % (_ts(x["t"]), _ts(x.get("end")), x.get("label"), _trim(x.get("text"), 120),
                                                    " (しなかった)" if x.get("skipped") else "", _j(x.get("plan"))))
        for m in rep.get("messages") or []:
            out.append("message %s %s: %s mood=%s auto=%s" % (_ts(m.get("t")), m.get("name"), _trim(m.get("text"), 80), m.get("mood"),
                                                            _j(m.get("auto_reply"))))
        return out

    # ------------------------------------------------------------------ 詳細
    @staticmethod
    def _section(title, lines):
        return ["", "--- %s (%d) ---" % (title, len(lines))] + (lines or ["(なし)"])

    def _trace(self, t0, t1, cid):
        out = []
        for r in self.app.trace.read(t0, t1, cid):
            v = r.get("v") or {}
            if r["c"] == "op":                 # あなたの操作: 押したもの → 結果
                out.append("%s [操作] %s %s → %s" % (_ts(r["t"]), r["m"], _j(v.get("args") or {}), v.get("result")))
            elif r["c"] in ERROR_CATS:         # 中身はエラーの欄に. ここは時系列の目印だけ
                out.append("%s [%s] %s%s" % (_ts(r["t"]), "エラー" if r["c"] == "error" else "画面のエラー", r["m"],
                                             " ×%d" % v["count"] if v.get("count", 1) > 1 else ""))
            else:
                out.append("%s [%s]%s %s %s" % (_ts(r["t"]), r["c"], " (%s)" % r["id"] if r.get("id") else "", r["m"], _j(v) if v else ""))
        return out

    def _errors(self, t0, t1):
        """エラーの欄: [(見出し, トレースバックなどの行)] 時刻順. 判断の記録の error / client と, server.log のエラー
        (時刻の付いていない以前の [API ERROR] も, 前の行の時刻で範囲に入れる. 判断の記録にあるものは重ねない)."""
        out = []
        for r in self.app.trace.read(t0, t1):
            if r["c"] not in ERROR_CATS:
                continue
            v = r.get("v") or {}
            if r["c"] == "error":
                head = "%s [エラー] %s" % (_ts(r["t"]), r["m"])
                body = (v.get("tb") or "").splitlines() + (["args=%s" % _j(v["args"])] if v.get("args") else [])
            else:
                head = "%s [画面のエラー] %s%s (screen=%s %s:%s:%s)" % (_ts(r["t"]), r["m"], " ×%d" % v["count"] if v.get("count", 1) > 1 else "",
                                                                       v.get("screen"), v.get("src"), v.get("line"), v.get("col"))
                body = (v.get("stack") or "").splitlines()[:8]
            out.append((r["t"], head, body))
        traced = " ".join(h for _, h, _ in out)
        for t, block in self._server_log_errors(t0, t1):
            m = re.search(r"\] job (\w+)", block[0])
            if m and "job " + m.group(1) in traced:      # 生成ジョブの失敗: 判断の記録 (トレースバックつき) にあるものは重ねない
                continue
            out.append((t, "%s [server.log] %s" % (_ts(t), block[0][:300]), block[1:]))
        out.sort(key=lambda x: x[0])
        return [(h, b) for _, h, b in out]

    @staticmethod
    def _log_blocks(t0, t1):
        """server.log を [(時刻, [行...])] のかたまりに (時刻の無い行は前のかたまりに続ける). 範囲の分だけ."""
        try:
            with open(store.dpath("server.log"), encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-20000:]
        except OSError:
            return []
        blocks, cur, t = [], None, 0
        y = datetime.fromtimestamp(t1).year
        for ln in lines:
            ln = ln.rstrip("\n")
            m = re.match(r"(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)", ln)
            if m:
                try:
                    t = datetime(y, *(int(x) for x in m.groups())).timestamp()
                except ValueError:
                    t = 0
                if t > t1 + 86400:            # 年をまたいだ
                    t = datetime(y - 1, *(int(x) for x in m.groups())).timestamp()
            if m or ln.startswith("[API ERROR]") or cur is None:
                cur = (t, [ln])
                blocks.append(cur)
            else:
                cur[1].append(ln)
        return [b for b in blocks if t0 <= b[0] <= t1]

    @staticmethod
    def _is_error(block):
        return "[API ERROR]" in block[0] or "[ERROR]" in block[0] or "Traceback" in "\n".join(block[1:2])

    def _server_log_errors(self, t0, t1):
        # 判断の記録に残っている新しい形 (時刻つきの [API ERROR]) は重ねない. 以前の時刻なし・[ERROR] (ワーカーの再起動など) は入れる
        return [(t, b) for t, b in self._log_blocks(t0, t1) if self._is_error(b) and not re.match(r"\d\d-\d\d .*\[API ERROR\]", b[0])]

    def _chat(self, cid, t0, t1):
        d = self.app.chat.load(cid)
        out = ["seen_t=%s" % _ts(d.get("seen_t"))]
        for it in d.get("items") or []:
            if t0 <= it.get("t", 0) <= t1:
                out.append("%s %s [%s]%s %s" % (_ts(it["t"]), it.get("who"), it.get("kind"), " 既読%s" % _ts(it["read_t"]) if it.get("read_t") else "",
                                               _trim(it.get("text"))))
        return out

    def _log(self, cid, t0, t1):
        out = []
        for e in self.app.log(cid):            # 画像のプロンプトなど大きいものは省く
            if t0 <= e.get("t", 0) <= t1:
                out.append("%s %s (%s) %s deltas=%s%s" % (_ts(e["t"]), e.get("action_name"), e.get("action"), _trim(e.get("text"), 160),
                                                       _j(e.get("deltas") or {}), " money=%s" % _j(e["money"]) if e.get("money") else ""))
        return out

    def _mylog(self, t0, t1):
        return ["%s [%s]%s %s" % (_ts(e["t"]), e.get("kind"), " void" if e.get("void") else "", _trim(e.get("text"), 300))
                for e in self.app.solo.mylog() if t0 <= e.get("t", 0) <= t1]

    def _diary(self, t0, t1):
        d0, d1 = datetime.fromtimestamp(t0).strftime("%Y-%m-%d"), datetime.fromtimestamp(t1).strftime("%Y-%m-%d")
        return ["%s (%s) %s" % (d["day"], d.get("src"), _trim(d.get("text"), 600)) for d in self.app.solo.diary_list() if d0 <= d["day"] <= d1]

    def _server_log(self, t0, t1, limit=300):
        """server.log の範囲の分 (新しい limit 行). エラーはエラーの欄に入れたので, ここでは 1 行目だけ."""
        out = []
        for _, b in self._log_blocks(t0, t1):
            out += [_trim(b[0], 400)] if self._is_error(b) else [_trim(x, 400) for x in b]
        return out[-limit:]
