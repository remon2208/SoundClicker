"""User-interface text in Traditional Chinese, Japanese and English.

To add a language: add its code to LANGS and a translation to every entry in STRINGS
(tests/test_core.py checks that nothing is missing and that the {placeholders} match).
"""

import locale
import sys

LANGS = {"zh": "繁體中文", "ja": "日本語", "en": "English"}
_lang = "en"


def set_lang(code):
    global _lang
    _lang = code if code in LANGS else "en"


def get_lang():
    return _lang


def detect_lang():
    """Language of the operating system: zh / ja / en."""
    try:
        if sys.platform == "win32":
            import ctypes
            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return {0x04: "zh", 0x11: "ja"}.get(primary, "en")
        code = (locale.getlocale()[0] or "").lower()
        return "zh" if code.startswith("zh") else "ja" if code.startswith("ja") else "en"
    except Exception:  # noqa: BLE001
        return "en"


def T(_key, /, **kw):
    entry = STRINGS[_key]
    s = entry.get(_lang) or entry["en"]
    return s.format(**kw) if kw else s


STRINGS = {
    # ---------------------------------------------------------------- app
    "app_title": {"zh": "音效自動點擊", "ja": "サウンドクリッカー", "en": "SoundClicker"},
    "language": {"zh": "語言", "ja": "言語", "en": "Language"},
    "ok": {"zh": "確定", "ja": "OK", "en": "OK"},
    "cancel": {"zh": "取消", "ja": "キャンセル", "en": "Cancel"},
    "refresh": {"zh": "重新整理", "ja": "更新", "en": "Refresh"},
    "unit_sec": {"zh": "秒", "ja": "秒", "en": "s"},
    "error_title": {"zh": "發生錯誤", "ja": "エラー", "en": "Error"},
    "missing_pkg_title": {"zh": "缺少套件", "ja": "パッケージが足りません", "en": "Missing packages"},
    "missing_pkg": {
        "zh": "請先在命令提示字元執行：\n\npip install -r requirements.txt",
        "ja": "コマンドプロンプトで次を実行してください：\n\npip install -r requirements.txt",
        "en": "Please run this in a command prompt first:\n\npip install -r requirements.txt"},

    # ---------------------------------------------------------------- 1. source
    "sec_source": {"zh": "1. 聽哪裡的聲音", "ja": "1. どの音を聞くか", "en": "1. Audio source"},
    "src_device": {"zh": "整個裝置", "ja": "デバイス全体", "en": "Whole device"},
    "src_window": {"zh": "只聽一個視窗", "ja": "1つのウィンドウだけ", "en": "One window only"},
    "src_device_hint": {
        "zh": "「電腦播放的聲音」= 整台電腦的聲音；也可以選麥克風。",
        "ja": "「PCの再生音」= PC全体の音です。マイクも選べます。",
        "en": "\"Speaker output\" = everything the PC plays. You can also pick a microphone."},
    "src_window_hint": {
        "zh": "只收這個視窗（和它的子程式）發出的聲音，音樂、Discord、影片都不會干擾。",
        "ja": "このウィンドウ（と子プロセス）の音だけを聞きます。音楽・Discord・動画の音は入りません。",
        "en": "Only this window's audio (and its child processes) is heard; music, Discord or videos won't interfere."},
    "src_window_unavailable": {"zh": "只聽一個視窗：{reason}。", "ja": "1つのウィンドウだけ：{reason}。",
                               "en": "One window only: {reason}."},
    "src_window_label": {"zh": "視窗「{title}」", "ja": "ウィンドウ「{title}」", "en": "window \"{title}\""},
    "win_only_windows": {"zh": "只有 Windows 能用", "ja": "Windows でのみ使えます", "en": "Windows only"},
    "win_unknown_version": {"zh": "無法判斷 Windows 版本", "ja": "Windows のバージョンを確認できません",
                            "en": "cannot tell the Windows version"},
    "win_too_old": {"zh": "需要 Windows 10 2004 以上（這台是 build {build}）",
                    "ja": "Windows 10 2004 以降が必要です（このPCは build {build}）",
                    "en": "needs Windows 10 2004 or newer (this PC is build {build})"},
    "win_list_title": {"zh": "視窗清單", "ja": "ウィンドウ一覧", "en": "Window list"},
    "win_list_error": {"zh": "讀不到視窗清單：{err}", "ja": "ウィンドウ一覧を取得できません：{err}",
                       "en": "Could not list windows: {err}"},
    "win_pick": {"zh": "（選一個視窗）", "ja": "（ウィンドウを選択）", "en": "(pick a window)"},
    "win_none": {"zh": "（找不到視窗）", "ja": "（ウィンドウがありません）", "en": "(no windows found)"},
    "win_pick_first": {
        "zh": "請先在「只聽一個視窗」選單裡選一個視窗（找不到就按旁邊的「重新整理」）。",
        "ja": "「1つのウィンドウだけ」の一覧からウィンドウを選んでください（見つからない場合は「更新」）。",
        "en": "Please pick a window in the \"One window only\" list first (press \"Refresh\" if it's missing)."},
    "win_closed_title": {"zh": "視窗已關閉", "ja": "ウィンドウが閉じられました", "en": "Window closed"},
    "win_closed": {"zh": "「{title}」已經關掉了，停止監聽。", "ja": "「{title}」が閉じられたので監視を止めました。",
                   "en": "\"{title}\" was closed, so listening stopped."},
    "no_device_title": {"zh": "沒有裝置", "ja": "デバイスがありません", "en": "No device"},
    "no_device": {"zh": "找不到音訊裝置，請按「重新整理」。", "ja": "オーディオデバイスが見つかりません。「更新」を押してください。",
                  "en": "No audio device found. Press \"Refresh\"."},
    "dev_loopback": {"zh": "電腦播放的聲音", "ja": "PCの再生音", "en": "Speaker output"},
    "dev_mic": {"zh": "麥克風", "ja": "マイク", "en": "Microphone"},
    "dev_none": {"zh": "（找不到音訊裝置）", "ja": "（デバイスがありません）", "en": "(no audio device)"},

    # ---------------------------------------------------------------- 2. templates
    "sec_templates": {"zh": "2. 要偵測的音效（範本）", "ja": "2. 検出する音（テンプレート）",
                      "en": "2. Sounds to detect (templates)"},
    "tpl_record": {"zh": "● 錄製新範本", "ja": "● 録音", "en": "● Record"},
    "tpl_record_cancel": {"zh": "■ 取消錄音", "ja": "■ 録音中止", "en": "■ Cancel"},
    "tpl_add": {"zh": "加入音檔…", "ja": "ファイル追加…", "en": "Add file…"},
    "tpl_play": {"zh": "▶ 試聽", "ja": "▶ 再生", "en": "▶ Play"},
    "tpl_remove": {"zh": "移除", "ja": "削除", "en": "Remove"},
    "tpl_folder": {"zh": "開啟資料夾", "ja": "フォルダ", "en": "Folder"},
    "tpl_play_title": {"zh": "試聽", "ja": "再生", "en": "Play"},
    "tpl_pick_first": {"zh": "請先在清單裡點選一個範本。", "ja": "一覧からテンプレートを選んでください。",
                       "en": "Select a template in the list first."},
    "tpl_item": {"zh": "{name}　（{sec:.2f} 秒）", "ja": "{name}　（{sec:.2f} 秒）", "en": "{name}   ({sec:.2f} s)"},
    "tpl_empty": {"zh": "（還沒有範本：先錄一個，或加入現成的音效檔）",
                  "ja": "（テンプレートがありません：録音するか、音声ファイルを追加してください）",
                  "en": "(no templates yet: record one or add an audio file)"},
    "rec_seconds": {"zh": "錄音秒數", "ja": "録音秒数", "en": "Record for"},
    "rec_hint": {"zh": "按「錄製新範本」，倒數結束後讓音效播放一次。",
                 "ja": "「録音」を押し、カウントダウン後に目的の音を1回鳴らしてください。",
                 "en": "Press \"Record\", then play the sound once after the countdown."},
    "rec_title": {"zh": "錄音", "ja": "録音", "en": "Recording"},
    "rec_countdown": {"zh": "{n}…  準備好讓音效播放", "ja": "{n}…  音を鳴らす準備をしてください",
                      "en": "{n}…  get ready to play the sound"},
    "rec_now": {"zh": "● 錄音中，請現在讓音效播放一次", "ja": "● 録音中：今、音を1回鳴らしてください",
                "en": "● Recording: play the sound once now"},
    "rec_cancelled": {"zh": "已取消錄音。", "ja": "録音を中止しました。", "en": "Recording cancelled."},
    "rec_too_quiet": {
        "zh": "幾乎沒錄到聲音（最大音量 {db:.0f} dB）。請確認音效有播出、沒有靜音，或換一個來源。",
        "ja": "ほとんど音が録れていません（最大 {db:.0f} dB）。音が出ているか、ミュートになっていないか確認するか、別の入力を選んでください。",
        "en": "Almost nothing was recorded (peak {db:.0f} dB). Make sure the sound plays and isn't muted, or pick another source."},
    "rec_ok": {"zh": "已錄好 {name}（{sec:.2f} 秒）。可以按「試聽」確認是不是對的聲音。",
               "ja": "{name} を録音しました（{sec:.2f} 秒）。「再生」で正しい音か確認できます。",
               "en": "Saved {name} ({sec:.2f} s). Press \"Play\" to check it's the right sound."},
    "rec_failed": {"zh": "錄音失敗：{err}", "ja": "録音に失敗しました：{err}", "en": "Recording failed: {err}"},
    "file_silent": {"zh": "檔案裡幾乎沒有聲音", "ja": "ファイルにほとんど音がありません", "en": "the file is almost silent"},
    "file_bad_title": {"zh": "無法使用這個音檔", "ja": "この音声ファイルは使えません", "en": "Can't use this file"},
    "file_bad_hint": {"zh": "（wav 一定可以讀；mp3/ogg 需要先 pip install soundfile）",
                      "ja": "（WAV は必ず読めます。mp3/ogg は pip install soundfile が必要です）",
                      "en": "(WAV always works; mp3/ogg need: pip install soundfile)"},
    "file_pick_title": {"zh": "選擇音效檔", "ja": "音声ファイルを選択", "en": "Choose audio files"},
    "file_type_audio": {"zh": "音效檔", "ja": "音声ファイル", "en": "Audio files"},
    "file_type_all": {"zh": "所有檔案", "ja": "すべてのファイル", "en": "All files"},
    "folder_info": {"zh": "範本放在：\n{path}\n\n（無法自動開啟：{err}）", "ja": "テンプレートの場所：\n{path}\n\n（開けませんでした：{err}）",
                    "en": "Templates are in:\n{path}\n\n(could not open it: {err})"},

    # ---------------------------------------------------------------- 3. actions
    "sec_actions": {"zh": "3. 聽到之後要做的動作", "ja": "3. 検出したときのアクション", "en": "3. Actions when detected"},
    "col_order": {"zh": "順序", "ja": "順番", "en": "#"},
    "col_action": {"zh": "動作（雙擊可以編輯）", "ja": "アクション（ダブルクリックで編集）", "en": "Action (double-click to edit)"},
    "step_add": {"zh": "＋ 新增", "ja": "＋ 追加", "en": "+ Add"},
    "step_edit": {"zh": "編輯", "ja": "編集", "en": "Edit"},
    "step_delete": {"zh": "刪除", "ja": "削除", "en": "Delete"},
    "step_up": {"zh": "▲ 上移", "ja": "▲ 上へ", "en": "▲ Up"},
    "step_down": {"zh": "▼ 下移", "ja": "▼ 下へ", "en": "▼ Down"},
    "try": {"zh": "▶ 試跑", "ja": "▶ テスト実行", "en": "▶ Test run"},
    "try_stop": {"zh": "■ 停止試跑", "ja": "■ テスト中止", "en": "■ Stop test"},
    "try_title": {"zh": "試跑", "ja": "テスト実行", "en": "Test run"},
    "try_hint": {"zh": "試跑：3 秒後開始，可以先切到遊戲視窗。", "ja": "テスト実行：3秒後に開始。先にゲーム画面へ切り替えられます。",
                 "en": "Test run starts after 3 s, so you can switch to the game first."},
    "try_no_steps": {"zh": "這個範本還沒有動作，先按「＋ 新增」。", "ja": "このテンプレートにはアクションがありません。「＋ 追加」で追加してください。",
                     "en": "This template has no actions yet. Press \"+ Add\" first."},
    "try_countdown": {"zh": "{n} 秒後開始…請切到遊戲視窗（F8 取消）", "ja": "{n} 秒後に開始…ゲーム画面へ（F8 で中止）",
                      "en": "Starting in {n} s… switch to the game (F8 cancels)"},
    "try_running": {"zh": "試跑中…（F8 取消）", "ja": "テスト実行中…（F8 で中止）", "en": "Running… (F8 cancels)"},
    "try_done": {"zh": "試跑完成（{sec:.1f} 秒）。", "ja": "テスト実行が完了しました（{sec:.1f} 秒）。", "en": "Test run finished ({sec:.1f} s)."},
    "try_cancelled": {"zh": "已取消試跑。", "ja": "テスト実行を中止しました。", "en": "Test run cancelled."},
    "apply_all": {"zh": "套用到所有範本", "ja": "全テンプレートに適用", "en": "Apply to all"},
    "apply_all_only_one": {"zh": "目前只有一個範本。", "ja": "テンプレートは1つしかありません。", "en": "There is only one template."},
    "apply_all_confirm": {
        "zh": "把「{name}」的動作複製給其他 {n} 個範本？\n（它們原本的動作會被取代）",
        "ja": "「{name}」のアクションを他の {n} 個のテンプレートにコピーしますか？\n（元のアクションは置き換えられます）",
        "en": "Copy the actions of \"{name}\" to the other {n} template(s)?\n(Their current actions will be replaced.)"},
    "act_pick_template": {"zh": "先在上面選一個範本，再設定聽到它之後要做什麼。",
                          "ja": "上でテンプレートを選び、検出したときの動作を設定してください。",
                          "en": "Select a template above, then set what happens when it's detected."},
    "act_summary": {"zh": "聽到「{name}」之後，依序做這 {n} 個動作（約 {sec:g} 秒）：",
                    "ja": "「{name}」を検出したら、次の {n} 個のアクションを順に実行（約 {sec:g} 秒）：",
                    "en": "When \"{name}\" is heard, run these {n} action(s) in order (~{sec:g} s):"},
    "act_empty": {"zh": "「{name}」還沒有動作，按「＋ 新增」加一個。", "ja": "「{name}」にはアクションがありません。「＋ 追加」で追加してください。",
                  "en": "\"{name}\" has no actions yet. Press \"+ Add\"."},

    # ---------------------------------------------------------------- 4. settings
    "sec_settings": {"zh": "4. 設定", "ja": "4. 設定", "en": "4. Settings"},
    "threshold": {"zh": "相似度門檻", "ja": "一致度のしきい値", "en": "Similarity threshold"},
    "threshold_hint": {"zh": "誤觸發就調高、漏掉就調低", "ja": "誤検出が多いなら上げ、取りこぼすなら下げる",
                       "en": "Raise it if it triggers by mistake, lower it if it misses"},
    "cooldown": {"zh": "冷卻時間", "ja": "クールダウン", "en": "Cooldown"},
    "max_len": {"zh": "比對長度", "ja": "照合の長さ", "en": "Match length"},
    "min_db": {"zh": "最小音量", "ja": "最小音量", "en": "Min. volume"},
    "cooldown_tip": {"zh": "觸發後這段時間內不再觸發（動作還在執行時也不會重複觸發）",
                     "ja": "検出後この時間は再検出しません（アクション実行中も再検出しません）",
                     "en": "No new trigger for this long after one (nor while actions are still running)"},
    "max_len_tip": {"zh": "越短反應越快，越長越不會誤判", "ja": "短いほど反応が速く、長いほど誤検出が減ります",
                    "en": "Shorter reacts faster, longer makes fewer mistakes"},
    "min_db_tip": {"zh": "比這個小聲的聲音不理會", "ja": "これより小さい音は無視します", "en": "Sounds quieter than this are ignored"},
    "test_mode": {"zh": "測試模式（只顯示，不執行動作）", "ja": "テストモード（表示のみ、実行しない）",
                  "en": "Test mode (log only, don't act)"},
    "topmost": {"zh": "視窗置頂", "ja": "常に手前に表示", "en": "Always on top"},

    # ---------------------------------------------------------------- 5. listen
    "sec_listen": {"zh": "5. 監聽", "ja": "5. 監視", "en": "5. Listen"},
    "btn_start": {"zh": "▶ 開始監聽（F8）", "ja": "▶ 監視開始（F8）", "en": "▶ Start (F8)"},
    "btn_stop": {"zh": "■ 停止監聽（F8）", "ja": "■ 監視停止（F8）", "en": "■ Stop (F8)"},
    "st_idle": {"zh": "待機中", "ja": "待機中", "en": "Idle"},
    "st_starting": {"zh": "啟動中…", "ja": "開始中…", "en": "Starting…"},
    "st_stopping": {"zh": "停止中…", "ja": "停止中…", "en": "Stopping…"},
    "st_recording": {"zh": "錄音中…", "ja": "録音中…", "en": "Recording…"},
    "st_playing": {"zh": "試聽中…", "ja": "再生中…", "en": "Playing…"},
    "st_trying": {"zh": "試跑動作中…", "ja": "テスト実行中…", "en": "Test run…"},
    "st_listening": {"zh": "監聽中：{name}", "ja": "監視中：{name}", "en": "Listening: {name}"},
    "hotkey_hint": {"zh": "F8：開始／停止（遊戲裡也能按）", "ja": "F8：開始／停止（ゲーム中でも使えます）",
                    "en": "F8: start / stop (works in games too)"},
    "hotkey_hint_local": {"zh": "F8：開始／停止（視窗在前景時）", "ja": "F8：開始／停止（このウィンドウが前面のとき）",
                          "en": "F8: start / stop (while this window is focused)"},
    "triggered": {"zh": "已觸發 {n} 次", "ja": "検出 {n} 回", "en": "Triggered {n}×"},
    "graph_hint": {"zh": "最近 5 秒的相似度。橘色虛線是門檻，在圖上點一下或拖曳可以調整。",
                   "ja": "直近5秒の一致度。オレンジの点線がしきい値で、クリックやドラッグで調整できます。",
                   "en": "Similarity over the last 5 s. The orange line is the threshold; click or drag to change it."},
    "graph_threshold": {"zh": "門檻 {v:.2f}", "ja": "しきい値 {v:.2f}", "en": "threshold {v:.2f}"},
    "graph_now": {"zh": "目前 {v:.2f}", "ja": "現在 {v:.2f}", "en": "now {v:.2f}"},
    "graph_peak": {"zh": "近 3 秒最高 {v:.2f}", "ja": "直近3秒の最大 {v:.2f}", "en": "3 s peak {v:.2f}"},
    "graph_idle": {"zh": "按「開始監聽」後，這裡會即時顯示相似度", "ja": "「監視開始」を押すと、ここに一致度が表示されます",
                   "en": "Press \"Start\" to see the live similarity here"},
    "no_templates_title": {"zh": "還沒有範本", "ja": "テンプレートがありません", "en": "No templates"},
    "no_templates": {"zh": "請先「錄製新範本」或「加入音檔」，再開始監聽。", "ja": "先に「録音」か「ファイル追加」でテンプレートを用意してください。",
                     "en": "Record a template or add an audio file before starting."},
    "log_test_mode": {"zh": "（測試模式）", "ja": "（テストモード）", "en": "(test mode)"},
    "log_started": {"zh": "開始監聽 {name}", "ja": "監視開始 {name}", "en": "Listening to {name}"},
    "log_fallback": {"zh": "找不到原本選的裝置，已改用預設的電腦聲音。", "ja": "選んだデバイスが見つからないため、既定の再生音を使います。",
                     "en": "The chosen device is gone; using the default speaker output."},
    "log_stopped": {"zh": "停止監聽", "ja": "監視停止", "en": "Stopped"},
    "log_hit": {"zh": "偵測到音效（相似度 {score:.2f}{more}）", "ja": "音を検出（一致度 {score:.2f}{more}）",
                "en": "Sound detected (similarity {score:.2f}{more})"},
    "log_hit_test": {"zh": "測試模式，不執行（{n} 個動作）", "ja": "テストモードのため実行しません（{n} 個のアクション）",
                     "en": "test mode, not running ({n} actions)"},
    "log_hit_no_actions": {"zh": "這個範本沒有設定動作", "ja": "このテンプレートにはアクションがありません",
                           "en": "this template has no actions"},
    "log_hit_run": {"zh": "執行 {n} 個動作", "ja": "{n} 個のアクションを実行", "en": "running {n} action(s)"},
    "log_aborted": {"zh": "動作已中止", "ja": "アクションを中止しました", "en": "actions aborted"},
    "log_done": {"zh": "動作完成（{sec:.1f} 秒）", "ja": "アクション完了（{sec:.1f} 秒）", "en": "actions done ({sec:.1f} s)"},
    "err_action": {"zh": "執行動作失敗：{err}", "ja": "アクションの実行に失敗しました：{err}", "en": "Action failed: {err}"},

    # ---------------------------------------------------------------- step dialog
    "dlg_add": {"zh": "新增動作", "ja": "アクションを追加", "en": "Add action"},
    "dlg_edit": {"zh": "編輯動作", "ja": "アクションを編集", "en": "Edit action"},
    "dlg_type": {"zh": "動作類型", "ja": "種類", "en": "Type"},
    "type_click": {"zh": "滑鼠點擊", "ja": "マウスクリック", "en": "Mouse click"},
    "type_key": {"zh": "鍵盤按鍵", "ja": "キー入力", "en": "Key press"},
    "type_hold": {"zh": "按住不放", "ja": "押し続ける", "en": "Hold down"},
    "type_wait": {"zh": "等待", "ja": "待機", "en": "Wait"},
    "type_move": {"zh": "移動滑鼠", "ja": "マウス移動", "en": "Move mouse"},
    "type_scroll": {"zh": "滾輪", "ja": "ホイール", "en": "Scroll"},
    "btn_left": {"zh": "左鍵", "ja": "左ボタン", "en": "Left"},
    "btn_right": {"zh": "右鍵", "ja": "右ボタン", "en": "Right"},
    "btn_middle": {"zh": "中鍵", "ja": "中ボタン", "en": "Middle"},
    "f_button": {"zh": "按鍵", "ja": "ボタン", "en": "Button"},
    "f_count": {"zh": "次數", "ja": "回数", "en": "Clicks"},
    "f_position": {"zh": "位置", "ja": "位置", "en": "Where"},
    "f_coords": {"zh": "座標", "ja": "座標", "en": "Position"},
    "f_key": {"zh": "按鍵", "ja": "キー", "en": "Key"},
    "f_hold": {"zh": "按住", "ja": "押すもの", "en": "Hold"},
    "f_hold_for": {"zh": "按住多久", "ja": "押す時間", "en": "Hold for"},
    "f_wait": {"zh": "等待", "ja": "待ち時間", "en": "Wait"},
    "f_jitter": {"zh": "隨機多加", "ja": "ランダム追加", "en": "Random extra"},
    "f_direction": {"zh": "方向", "ja": "方向", "en": "Direction"},
    "f_notches": {"zh": "格數", "ja": "量", "en": "Notches"},
    "single_click": {"zh": "單擊", "ja": "シングル", "en": "single"},
    "double_click": {"zh": "雙擊", "ja": "ダブル", "en": "double"},
    "pos_cursor": {"zh": "滑鼠目前的位置", "ja": "現在のカーソル位置", "en": "Where the cursor is"},
    "pos_fixed": {"zh": "指定座標", "ja": "座標を指定", "en": "Fixed position"},
    "keyboard": {"zh": "鍵盤按鍵", "ja": "キーボード", "en": "Keyboard key"},
    "key_examples": {"zh": "例如：e、space、enter、esc、f1、ctrl+c、shift+tab",
                     "ja": "例：e、space、enter、esc、f1、ctrl+c、shift+tab",
                     "en": "e.g. e, space, enter, esc, f1, ctrl+c, shift+tab"},
    "jitter_hint": {"zh": "（0～這個秒數隨機，讓間隔不要每次都一樣）", "ja": "（0〜この秒数をランダムに足して、間隔を毎回変えます）",
                    "en": "(adds 0 to this many seconds at random, so it isn't always the same)"},
    "dir_up": {"zh": "往上", "ja": "上", "en": "Up"},
    "dir_down": {"zh": "往下", "ja": "下", "en": "Down"},
    "unit_notch": {"zh": "格", "ja": "ノッチ", "en": "notches"},
    "pick_pos": {"zh": "取得座標（3 秒）", "ja": "座標を取得（3秒）", "en": "Pick (3 s)"},
    "pick_pos_hint": {"zh": "按「取得座標」後 3 秒內把滑鼠移到要點的位置。", "ja": "「座標を取得」を押して、3秒以内にマウスを目的の位置へ。",
                      "en": "Press \"Pick\", then move the mouse to the spot within 3 s."},
    "pick_pos_countdown": {"zh": "{sec:.1f} 秒後記錄…目前滑鼠在 {x}, {y}", "ja": "{sec:.1f} 秒後に記録…現在 {x}, {y}",
                           "en": "Recording in {sec:.1f} s… cursor at {x}, {y}"},
    "pick_pos_done": {"zh": "已記錄座標 {x}, {y}", "ja": "座標 {x}, {y} を記録しました", "en": "Position {x}, {y} saved"},
    "record_key": {"zh": "錄製按鍵", "ja": "キーを記録", "en": "Record key"},
    "record_key_wait": {"zh": "請按鍵…", "ja": "キーを押して…", "en": "Press a key…"},
    "err_not_number": {"zh": "「{name}」請填數字", "ja": "「{name}」には数字を入れてください", "en": "\"{name}\" must be a number"},
    "err_range": {"zh": "「{name}」要在 {lo:g} 到 {hi:g} 之間", "ja": "「{name}」は {lo:g}〜{hi:g} にしてください",
                  "en": "\"{name}\" must be between {lo:g} and {hi:g}"},
    "err_need_coords": {"zh": "請填座標，或按「取得座標」", "ja": "座標を入力するか「座標を取得」を押してください",
                        "en": "Enter a position or press \"Pick\""},
    "key_err_empty": {"zh": "請輸入按鍵，例如 e、space、ctrl+c", "ja": "キーを入力してください（例：e、space、ctrl+c）",
                      "en": "Enter a key, e.g. e, space, ctrl+c"},
    "key_err_format": {"zh": "格式不對：組合鍵請用 + 連接，例如 ctrl+c", "ja": "形式が違います。組み合わせは + でつなぎます（例：ctrl+c）",
                       "en": "Invalid format: join keys with +, e.g. ctrl+c"},
    "key_err_unknown": {"zh": "看不懂「{key}」這個按鍵", "ja": "「{key}」というキーはわかりません", "en": "Unknown key \"{key}\""},
    "key_err_combo": {"zh": "組合鍵是 Ctrl／Shift／Alt／Win 再加一個鍵，例如 ctrl+shift+a",
                      "ja": "組み合わせは Ctrl／Shift／Alt／Win ＋ 1つのキーです（例：ctrl+shift+a）",
                      "en": "A combination is Ctrl/Shift/Alt/Win plus one key, e.g. ctrl+shift+a"},
    "key_err_hotkey": {"zh": "F8 是開始／停止監聽的快捷鍵，請換一個按鍵", "ja": "F8 は監視の開始／停止に使うので、別のキーにしてください",
                       "en": "F8 starts/stops listening; please choose another key"},
    "at_cursor": {"zh": "目前位置", "ja": "現在位置", "en": "at cursor"},
    "at_pos": {"zh": "座標 {x}, {y}", "ja": "座標 {x}, {y}", "en": "at {x}, {y}"},
    "desc_click": {"zh": "滑鼠{button} {count}（{where}）", "ja": "マウス{button} {count}クリック（{where}）",
                   "en": "{button} {count} click ({where})"},
    "desc_key": {"zh": "按鍵盤 {keys}", "ja": "キー入力 {keys}", "en": "Press {keys}"},
    "mouse_button": {"zh": "滑鼠{button}", "ja": "マウス{button}", "en": "{button} mouse button"},
    "keyboard_key": {"zh": "鍵盤 {keys}", "ja": "キー {keys}", "en": "{keys}"},
    "desc_hold": {"zh": "按住 {what} {sec:g} 秒", "ja": "{what} を {sec:g} 秒押し続ける", "en": "Hold {what} for {sec:g} s"},
    "desc_wait": {"zh": "等待 {sec:g} 秒", "ja": "{sec:g} 秒待つ", "en": "Wait {sec:g} s"},
    "desc_wait_jitter": {"zh": "（再隨機多 0～{sec:g} 秒）", "ja": "（＋ランダム 0〜{sec:g} 秒）", "en": " (+ random 0–{sec:g} s)"},
    "desc_move": {"zh": "滑鼠移到 {x}, {y}", "ja": "マウスを {x}, {y} へ移動", "en": "Move mouse to {x}, {y}"},
    "desc_scroll_up": {"zh": "滾輪往上 {n} 格", "ja": "ホイールを上へ {n}", "en": "Scroll up {n}"},
    "desc_scroll_down": {"zh": "滾輪往下 {n} 格", "ja": "ホイールを下へ {n}", "en": "Scroll down {n}"},

    # ---------------------------------------------------------------- engine / errors
    "err_wav_format": {"zh": "不支援的 wav 格式", "ja": "対応していない WAV 形式です", "en": "unsupported WAV format"},
    "err_template_silent": {"zh": "範本「{name}」幾乎是無聲的，請重新錄製。", "ja": "テンプレート「{name}」はほぼ無音です。録り直してください。",
                            "en": "Template \"{name}\" is almost silent; please record it again."},
    "err_no_device": {"zh": "找不到任何可以錄音的裝置。", "ja": "録音できるデバイスが見つかりません。", "en": "No recording device found."},
    "err_soundcard": {"zh": "無法載入 soundcard 套件，請先執行：pip install -r requirements.txt",
                      "ja": "soundcard パッケージを読み込めません。pip install -r requirements.txt を実行してください。",
                      "en": "Cannot load the soundcard package. Run: pip install -r requirements.txt"},
    "err_window_capture": {
        "zh": "無法只錄「{title}」的聲音：{msg}\n\n可能的原因：\n・Windows 版本太舊（需要 Windows 10 2004 以上）\n"
              "・這個遊戲是用系統管理員身分執行的（那這個程式也要用系統管理員身分開）\n\n可以先改回「整個裝置」使用。",
        "ja": "「{title}」の音だけを録音できません：{msg}\n\n考えられる原因：\n・Windows が古い（Windows 10 2004 以降が必要）\n"
              "・ゲームが管理者として実行されている（このアプリも管理者として起動してください）\n\nひとまず「デバイス全体」に戻して使えます。",
        "en": "Can't capture only \"{title}\": {msg}\n\nPossible reasons:\n• Windows is too old (needs Windows 10 2004 or newer)\n"
              "• The game runs as administrator (then run this app as administrator too)\n\nYou can switch back to \"Whole device\" meanwhile."},
}
