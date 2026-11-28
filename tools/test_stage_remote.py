"""離れている人の画像を舞台 (メインの画面) に出さない (F: デート中に別の人から届いた自撮りが舞台に出た).

画像のジョブが終わったとき (pollJobsOnce) も, 行動の結果 (handleActResult) と同じ判定 onStage を通す:
一人の記録・誰もそばにいないとき・そばにいない人の記録は出さない. 時刻が新しいだけで差し替えない.

    python tools/test_stage_remote.py
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def body_of(js, name):
    m = re.search(r"\n(?:async )?function %s\(" % name, js)
    assert m, name
    end = js.find("\n}\n", m.end())
    return js[m.start():end]


def main():
    js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
    st = body_of(js, "onStage")
    assert "e.mine" in st and "tid()" in st and "S.view.company" in st, "onStage の判定が崩れた"
    poll = body_of(js, "pollJobsOnce")
    assert "onStage(le)" in poll, "ジョブの完了で, そばにいない人の画像を舞台に出してしまう"
    assert "S.view.log.find((x) => x.id === j.entry) || {}).t) setImage" not in poll, "時刻だけで差し替える古い判定が残っている"
    assert "j.kind && j.kind !== 'entry'" in poll and "j.shown === false" in poll, "pollJobsOnce の見逃しが崩れた"
    assert "S.current.id === j.entry" in poll, "いま舞台に出している記録の絵は差し替える"
    act = body_of(js, "handleActResult")
    assert "!onStage(r.entry)" in act, "行動の結果の判定が onStage を通っていない"
    print("OK")


if __name__ == "__main__":
    main()
