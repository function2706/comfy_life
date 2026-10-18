"""テスト用: 時刻を日曜の昼 (12:00) に固定する. 予定 (寝ている時間・平日の外出など)・時間帯・曜日・時刻の条件が,
テストを流す日時に左右されないように.

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

    def context(self, char, st, dt, scene=None):
        c = ctx(self, char, st, dt, scene)
        c.update(hour=12, time=720, weekday=6, day="sun", weekend=True)
        return c
    App.context = context
    App._noon_fixed = True
