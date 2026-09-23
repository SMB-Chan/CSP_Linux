# Clip Studio Paint 5.1.4 (Wine) 安定動作セットアップ記録

対象: `CSP_514w_setup.exe` (Clip Studio Paint 5.1.4 / CELSYS)
方針: **ソフトウェア本体（インストーラ・展開済みバイナリ）は一切改変しない。**
すべての調整は Wine 側の実行環境（プレフィックス・レジストリ・環境変数・補助 DLL の追加）のみで行う。

ホスト: Ubuntu 26.04 (Wayland/GNOME, Intel UHD 630)。アプリ環境は `$HOME` 配下に構築。
Wacom 筆圧転送用の入力読み取り権限のみ、管理者認証で udev ルールを追加。

---

## 1. 配置場所

| パス | 内容 |
|---|---|
| `~/ClipStudio/env.sh` | 共通環境変数（source してから wine 系コマンドを使う） |
| `~/ClipStudio/prefix/` | CSP 専用 Wine プレフィックス (win64) |
| `~/ClipStudio/bin/` | 起動・設定・検証スクリプト群 |
| `~/ClipStudio/logs/` | 各種ログ |
| `~/ClipStudio/share/icons/clipstudio.png` | デスクトップエントリ用アイコン |
| `~/opt/wine-11.4-amd64-wow64/` | ポータブル Wine 11.4 (wow64。32bit ライブラリ不要) |
| `~/opt/wine-11.18-amd64-wow64/` | 予備の Wine 11.18 (問題時の切替用) |
| `~/.local/share/applications/clipstudio-paint.desktop` | アプリメニューエントリ |
| `~/.local/share/applications/csp-pentab-settings.desktop` | ペンタブレット設定 GUI |
| `~/.local/share/applications/csp-tourbox-settings.desktop` | TourBox キー設定 GUI |
| `~/.local/share/applications/csp-pentab-settings.desktop` | ペンタブレット設定 GUI |
| `~/.local/share/applications/csp-tourbox-settings.desktop` | TourBox キー設定 GUI |

## 2. 起動方法

- アプリメニューの **Clip Studio Paint** アイコン、または
- `~/ClipStudio/bin/csp-launch.sh` （通常起動）
- `~/ClipStudio/bin/csp-launch.sh --debug` （`logs/paint.log` に warn/err を記録しながら起動）

起動対象はランチャー (`CLIPStudio.exe`) ではなく **`CLIPStudioPaint.exe` を直接** 起動する
（ランチャー経由は Wine 上で不安定になりやすい）。

## 3. 適用済みの環境設定（すべて Wine 側）

- Wine 11.4 (amd64-wow64) / プレフィックスは win64 専用
- `winetricks corefonts vcrun2022 dxvk` （VC++ 再頒布パッケージと DXVK）
- Windows バージョン偽装: 全体 `win10`、`CLIPStudioPaint.exe`/`CLIPStudio.exe` = `win81`、
  `msedgewebview2.exe` = `win7`
- DLL オーバーライド: `concrt140=native,builtin`、DXVK 系、**`dcomp=native,builtin`**
  （`system32/dcomp.dll` は DirectComposition シム。これがないと起動直後の画面が白紙になる）
- WebView2 Runtime 135.0.3179.85 をオフライン導入済み。自動更新はレジストリ
  (`Policies\Microsoft\EdgeUpdate`) で無効化
- Wine Gecko 2.47.4 / Wine Mono 11.0.0 導入済み（.NET アセンブリは CSP 側に無いことを確認済み）
- 日本語フォント代替: MS ゴシック系→Noto Sans CJK JP 等（ホストの fonts-noto-cjk を使用）
- クラッシュダイアログ抑止 (`WineDbg/ShowCrashDialog=0`)
- 不要サービス無効化: `PlugPlay`, `WineBus` (Start=4)
- `WINEESYNC=1 WINEFSYNC=1`、グラフィックは X11 (XWayland) 固定 (`winewayland=d`)
- `dxvk.conf`（`$WINEPREFIX/dxvk.conf`、`DXVK_CONFIG_FILE` で明示指定）:
  `dxgi.deferSurfaceCreation=True` / `dxvk.enableGraphicsPipelineLibrary=True` /
  `dxvk.numCompilerThreads=0` / `dxvk.maxChunkSize=16`
- WebView2 用ブラウザ引数 (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`):
  `--no-sandbox --in-process-gpu --disable-gpu-compositing` ほか

## 4. 再設定・検証コマンド

```bash
source ~/ClipStudio/env.sh
~/ClipStudio/bin/csp-configure.sh     # レジストリ・dxvk.conf・gecko/mono の冪等な再適用
~/ClipStudio/bin/csp-postinstall.sh   # アプリ別 Windows バージョン等の再適用
~/ClipStudio/bin/csp-verify.sh        # 導入状況の一覧表示
~/ClipStudio/bin/xdo.py list|shot|click|key|type   # X11 窓の操作・撮影（Wayland 下は SendEvent 方式）
```

インストール自体は `CSP_514w_setup.exe /s /v"/qn"`（サイレント）で成功済み。
再インストールが必要な場合: `~/ClipStudio/bin/csp-install.sh silent`（または `gui`）。

## 4b. `.clip` ファイルの関連づけ

- ユーザーレベルの MIME タイプ `application/x-clipstudio-paint` を登録
  （`~/.local/share/mime/packages/x-clipstudio-paint.xml`、マジック `CSFCHUNK` + glob `*.clip`）
- `clipstudio-paint.desktop` を既定ハンドラに設定（`Exec=... %f`、`MimeType=` 追加）
- `csp-launch.sh` は渡された実在ファイルを `winepath -w` で Windows パスに変換して起動する
- 検証済み: `xdg-open ウナみく.clip` → 起動中の CSP インスタンスが文書を開く

再登録が必要な場合:
```bash
update-mime-database ~/.local/share/mime
xdg-mime default clipstudio-paint.desktop application/x-clipstudio-paint
update-desktop-database ~/.local/share/applications
```

## 5. 確認済みの動作（2026-09-23）

- 初回起動→プライバシー設定→ようこそ画面→ログイン→**メインエディタ表示・描画まで動作**
- 日本語 UI・ツールパレット・レイヤーパレット・カラーサークル表示
- 約 18 分の連続稼働でクラッシュなし（`logs/launch2.log` に致命的エラーなし）
- ログに残る既知の無害メッセージ: WinRT 一部クラスの未取得（ペンデバイス検出のフォールバック）、
  EDID/ディスプレイメタデータ解析失敗、winebth（Bluetooth）ドライバ読込失敗

## 6. トラブルシューティング早見表

| 症状 | 対処 |
|---|---|
| 起動画面が白紙/灰色のまま | `dcomp` オーバーライドと `system32/dcomp.dll` の存在を確認 |
| メニューが別窓になる | GNOME(XWayland) の既知挙動。窓リストで前面へ |
| 描画が重い/化ける | `WINEDLLOVERRIDES="d3d11=builtin,dxgi=builtin"` で DXVK を一時無効化して比較 |
| Wine 11.4 で不具合 | `env.sh` の `WINE_DIR` を `~/opt/wine-11.18-amd64-wow64` に変更 |
| 起動しない | `csp-launch.sh --debug` の `logs/paint.log` を確認 |
| ペンタブでカーソルが動かない | `map.grab` を `off` にする（既定）。`grab=on` はデスクトップ側カーソルを止める。`pentab.sh --set map.grab off && pentab.sh --reload` |
| ペンで線の太さが変わらない | `csp-tablet-mode.sh wintab`（CSP 終了後）→ 再起動。環境設定 → タブレット = Wintab |

## 7. 改変していないもの（規約順守）

- `CSP_514w_setup.exe` および `C:\Program Files\CELSYS\` 配下の全ファイル（読取・実行のみ）
- 追加 DLL (`dcomp.dll` 等) は Wine プレフィックスの `system32` にのみ配置し、
  アプリ側ディレクトリには何も置いていない

## 8. Wacom One のクリック・筆圧（2026-09-23）

Wacom One Medium (`0531:0102`) の実ペンで、CSP の筆圧動作をユーザー確認済み。
Linux の入力イベントを `wacom-pressure.py` で読み、Pain Studio Mask v0.1.0 の
Wintab DLL に転送する。クリック座標は XTest で同期する。

- 通常の CSP 起動スクリプトから転送を自動起動し、CSP 終了時に停止。
- CSP をマウスで前面に出してから使用する。タブレットサービスは Wintab。
- Wacom に限定した読み取り ACL を設定済み。毎回の sudo 実行は不要。
- 現在の座標設定は 1920×1080 のミラー表示用。
- 導入内容・ログ・復元方法: [wacom-pressure/README.md](wacom-pressure/README.md)。
- マウスまで反応しない場合は、背面の「動作保証対象外の OS」ダイアログを確認し、
  「閉じる」を押す。このダイアログを閉じてマウス操作が回復した実績あり。

## 8b. タブレットサービス（Wintab）構築（2026-09-24）

ペンの筆圧・接地は Pain Studio Mask の Wintab DLL 経由で CSP に渡す。
Windows Ink / WM_POINTER は Wine がスタブのみなので使わない。

| 項目 | 設定 |
|---|---|
| 使用するタブレットサービス | **Wintab**（`csp-tablet-mode.sh wintab`） |
| UseAccurateWMPointer | **0**（`csp-tablet-mode.sh accurate off`） |
| UseMouseMode | 1 のまま（座標はデスクトップのカーソル、筆圧は Wintab） |
| wintab32.dll | prefix `system32` / `syswow64` に PSM、`DllOverrides=wintab32=native,builtin` |
| 転送 | `wacom-pressure.py`（カーソルは libinput、`map.grab=off`） |

```bash
~/ClipStudio/bin/csp-tablet-mode.sh show     # 現在値
~/ClipStudio/bin/csp-tablet-mode.sh verify   # DLL・psm.json・転送・接続の確認
~/ClipStudio/bin/csp-tablet-mode.sh wintab   # Wintab に切替（CSP 終了後）
~/ClipStudio/bin/csp-tablet-mode.sh accurate off
```

確認: G ペンで軽い線と濃い線を描き分け、
`~/ClipStudio/logs/wacom-pressure-status.json` の `max_pressure` が動くこと。
CSP 側は 環境設定 → タブレット → 使用するタブレットサービス = Wintab。

注意: `csp-tablet-mode.sh` の起動中判定は `pgrep -f '[C]LIPStudioPaint\.exe'`
（自プロセスへの誤マッチ防止）。設定変更は CSP 終了後のみ（終了時に上書きされる）。
`csp-launch.sh` は起動前の CSP 未起動時に `wintab` を自動で書き直し、
転送ブリッジ終了時（= CSP 終了）にも書き直す。CSP 起動中は
`SetContextKindNextBoot` が 0 のまま見えることがあり、その場合は
`verify` が NOTE 表示になる（NG ではない。本セッションは起動時適用済み）。

## 9. TourBox Lite の導入とキー設定（2026-09-23）

公式 TourBox Console は Wine 上でローダーデッドロックして起動しない（`SWT_Window_SWT`
などの補助窓だけ出て本体窓が出ず、`+comm` トレースも皆無）。そこで Wine 側には何も
入れず、Linux ネイティブのドライバで駆動する。CSP 本体・プレフィックス内のアプリ
ファイルは改変していない。

- デバイス: USB `cafe:4001` → CDC-ACM `/dev/ttyACM0`。`dialout` グループ所属なので root 不要。
- ドライバ: `~/ClipStudio/bin/tourbox-daemon.py`。アンロック列 `55 00 07 88 94 00 1a fe`
  を送った後、1 バイト＝1 イベント（最上位ビット=解放）を解釈する。
- 起動ラッパ: `~/ClipStudio/bin/tourbox-daemon.sh`
  （引数なし=起動、`--status` `--stop` `--reload` `--scan` `--probe` `--test <アクション>`）。
- 設定: `~/ClipStudio/etc/tourbox.conf`。書式とボタン名の一覧はファイル内のコメント参照。
  保存後の反映は `tourbox-daemon.sh --reload`（= SIGHUP）で即時、再起動不要。
- キー設定 GUI: `~/デスクトップ/clip/tourbox/tourbox-settings.py`（GTK4）。
  保存時に `~/ClipStudio/backups/tourbox/` へバックアップを取り、`--reload` まで行う。
- 自動起動: `~/.config/autostart/tourbox-daemon.desktop`（ログイン時に起動、5 秒遅延）。
- ログ: `~/ClipStudio/logs/tourbox-daemon.log`、PID: `~/ClipStudio/run/tourbox-daemon.pid`。
- 注入方式: XTEST のキー注入。**CSP（WM_CLASS `clipstudiopaint.exe`）が前面のときだけ**
  送出し、他のアプリには送らない。CSP 非フォーカス時は何も起きない（誤操作防止）。
  XWayland/mutter は XTest のポインタ移動を捨てるが、キー注入は届く（Wine 窓で実証）。
- 公式 Console が自分で登録した自動起動（`HKCU\...\Run` の `TourBox Console`）は削除済み。
  `C:\Program Files\TourBox Console\`（約 491 MB）は未使用のまま残してある。

検証済み: アンロック応答 26 バイト／実ボタンの押下・解放の解釈／Wine 窓への ctrl+z 注入
（`keyecho.exe` のログに `DOWN vk=0x11 ctrl=True` → `DOWN vk=0x5A ctrl=True`）／
設定変更の即時反映／GUI からの保存→再読込／クリーン環境からの起動（自動起動と同じ経路）。

## 10. ペンタブの感度・対応マップ設定（2026-09-23）

§8 の転送経路はそのままで、筆圧カーブとタブレット↔画面の対応マップ、
サイドスイッチの割り当てを設定可能にした。CSP 本体・Wintab DLL・psm.json は
変更していない（psm.json は純粋な Wintab 形状設定のみで、カーブやマップの
項目を持たない）。設定は転送スクリプト側で適用する。

- 設定ファイル: `~/ClipStudio/etc/pentab.conf`（日本語注釈入り）。
  `[map]` mode(full/aspect/area)・rotate(0/90/180/270)・area_*、
  `[pressure]` gain・gamma・input_floor・input_ceiling・output_floor、
  `[pen]` side_button(right/middle/none)。
- 反映: 転送プログラムが 1 秒ごとに mtime を見て自動再読込、または
  `~/ClipStudio/bin/pentab.sh --reload`（SIGHUP）。CSP の再起動は不要。
  範囲外の値は日本語エラー 1 行を出して直前の設定を維持する。
- CLI: `pentab.sh` は引数なし/`--gui`（設定画面）、`--show`、`--check`
  （検証と 0〜100% 応答表）、`--set section.key 値`、`--reload`、`--restart`。
  `--set` と GUI は注釈を保ったまま値の行だけ書き換える。
- 設定画面: `~/デスクトップ/clip/pentab/pentab-settings.py`（GTK4）。
  対応マップのプレビュー、筆圧カーブ図（実ペンの点が動く）、実機筆圧メーター、
  領域クイックボタン（右半分/左半分/中央 2/3/上半分）付き。保存時に
  `~/ClipStudio/backups/pentab/` へバックアップし `--reload` まで行う。
- 既定値は設定導入前の転送と完全に同一（等倍・線形・画面全体・右クリック）。
- ログ: `~/ClipStudio/logs/wacom-pressure.log`（再読込の成否）、
  状態: `~/ClipStudio/logs/wacom-pressure-status.json` の `settings`。
- 詳細: [pentab/README.md](pentab/README.md)、[wacom-pressure/README.md](wacom-pressure/README.md)。

検証済み: 既定値と導入前コードの全数一致（座標 158×12 通り・筆圧 0〜4095）、
アスペクト/領域/回転/カーブの計算単体試験 36 件、GUI からの保存→conf（注釈維持）
→実ブリッジ反映→既定へ復元、`--restart` 後の PSM 再接続と CSP（PID 不変）への無影響。
