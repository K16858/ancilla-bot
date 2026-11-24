---
name: timers
description: カウントダウンタイマーの作成・一覧確認・時間変更・停止・取消の手順。タイマーに関する依頼で使う。
requires:
  capabilities:
    - timer_set
    - timer_list
    - timer_update
    - timer_stop
    - timer_cancel
---

秒精度のカウントダウンタイマーには `manage_state`（`reminders`）ではなく `timer_*` ツールを使う。

- **新規作成 (`timer_set`)**:
  - 時間が指定されていない場合（「タイマーセットして」等）は勝手に秒数を決めず、ユーザーに長さを聞き返す。
  - 分・時間表記は秒へ変換する（例: 3分 -> `180`、1時間半 -> `5400`）。
- **一覧確認 (`timer_list`)**:
  - 現在動いている／鳴動中のタイマーと残り秒数を確認する。
- **時間変更・ラベル変更 (`timer_update`)**:
  - 「それを5分に変えて」「あと1分伸ばして」等のときは、直前文脈または `timer_list` で対象の `timer_id`（`TMR-0001` 等）を確認してから更新する。
  - 残り時間を指定秒へ変えるときは `duration_sec`、今の終了時刻へ増減するときは `add_sec` を使う。
- **停止 (`timer_stop`) と 取消 (`timer_cancel`)**:
  - 鳴動中のアラームを止めるときは `timer_stop`（ID 省略で鳴動中すべて停止）。
  - まだカウントダウン中のタイマーをやめるときは `timer_cancel` を使う。
