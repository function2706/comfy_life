"""テスト用: 時刻を昼 (12:00) に固定する. 予定 (寝ている時間など) ・時間帯・時刻の条件が, テストを流す時刻に左右されないように.

    from testclock import fix_noon; fix_noon(engine)
"""


def fix_noon(engine):
    App = engine.App
    if getattr(App, "_noon_fixed", False):
        return
    sched, ctx = App.scheduled_scene, App.context
    App.phase_at = lambda self, dt: {"id": "noon", "label": "昼", "pos": "", "neg": ""}
    App.scheduled_scene = lambda self, char, dt: sched(self, char, dt.replace(hour=12, minute=0))

    def context(self, char, st, dt, scene=None):
        c = ctx(self, char, st, dt, scene)
        c.update(hour=12, time=720)
        return c
    App.context = context
    App._noon_fixed = True
