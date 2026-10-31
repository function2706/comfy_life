"""テスト用: 時刻を日曜の昼 (12:00) に固定する. 予定 (寝ている時間・平日の外出など)・時間帯・曜日・時刻の条件・
行き先の営業時間が, テストを流す日時に左右されないように (本物の営業時間は places.open_state_real).
離れている相手からのメッセージの時刻の重み (presence.hour_factor) も昼のもの (本物は presence.hour_factor_real. 時刻の重みは tools/test_dawn.py で).
移動 (core/geo.py) には時間をかけない (すぐ着く. 移動そのものは tools/test_geo.py で).
株の市場は, いつでも開いていることにする (本物は market.is_open_real. 取引時間そのものは tools/test_market.py で).

    from testclock import fix_noon; fix_noon(engine)
"""
from datetime import datetime

NOON = datetime(2026, 10, 18, 12, 0)      # 日曜


def fix_noon(engine):
    App = engine.App
    if getattr(App, "_noon_fixed", False):
        return
    sched, ctx = App.scheduled_scene, App.context
    App.phase_at = lambda self, dt: {"id": "noon", "label": "昼", "pos": "", "neg": ""}
    App.scheduled_scene = lambda self, char, dt: sched(self, char, NOON)

    def context(self, char, st, dt, scene=None, **kw):
        c = ctx(self, char, st, dt, scene, **kw)
        c.update(hour=12, time=720, weekday=6, day="sun", weekend=True)
        return c
    App.context = context
    from core import geo, market, offline, places, presence
    geo.INSTANT = True
    presence.hour_factor_real = presence.hour_factor          # 離れている相手からのメッセージの時刻の重み (夜中はまず来ない)
    presence.hour_factor = lambda dt: presence.hour_factor_real(NOON)
    market.is_open_real = market.is_open
    market.is_open = lambda dt: True
    real = places.open_state
    places.open_state_real = real
    places.open_state = offline.open_state = lambda pid, dt: real(pid, NOON)
    App._noon_fixed = True
