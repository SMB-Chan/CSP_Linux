# Wacom One → CSP の筆圧転送

対象: Ubuntu 26.04 / GNOME Wayland / CSP 5.1.4 / Wine 11.4。
USB Wacom One Medium (`0531:0102`) と、1920×1080 のミラー表示用。

Linux が報告するペン座標・接地・筆圧を読み、筆圧を Pain Studio Mask
v0.1.0 の Wintab DLL へ localhost TCP で送る。カーソル移動は
`XWarpPointer`（XWayland/mutter は XTest のポインタ移動を捨てる）、
クリックは XTest ボタンで併用する。転送は CSP が前面にある間に限定する。

## 導入ファイル

- `~/ClipStudio/bin/wacom-pressure.py`: 入力転送。CSP 終了時に停止。
- `~/ClipStudio/bin/csp-launch.sh`: 通常の起動に入力転送を追加。
- `~/ClipStudio/prefix/drive_c/windows/system32/wintab32.dll`: 公開版 PSM。
- `~/ClipStudio/prefix/drive_c/users/intel/AppData/Local/psm.json`: Wintab 設定。
- `~/ClipStudio/pressure/psm.json`: 転送側の画面設定。
- `~/ClipStudio/pressure-backups/`: 導入前 DLL・起動スクリプト等のバックアップ。
- `/etc/udev/rules.d/99-csp-wacom-pressure.rules`: 管理者認証後に作成する、
  対象 Wacom に限定したユーザー `intel` の読み取り ACL ルール。

CSP 本体の実行ファイルは変更しない。Windows 版 Wacom ドライバーと
OpenTabletDriver はインストールしていない。

## 起動・確認

入力権限の設定後は、通常の CSP アイコンから起動する。
起動中の CSP に手動接続する場合:

```bash
python3 ~/ClipStudio/bin/wacom-pressure.py
```

タブレットサービスは Wintab（`csp-tablet-mode.sh wintab`、確認は `verify`）。
G ペンなど筆圧で太さが変わるブラシを使い、軽い線と強い線を比較する。
座標検出の「マウスモードを使用する」は現行の CSP 設定を維持している。

ログ:

- `~/ClipStudio/logs/wacom-pressure-status.json`: 接続、転送数、最大筆圧。
- `~/ClipStudio/logs/wacom-pressure.log`: 起動・接続・停止。
- `~/ClipStudio/logs/wacom-pressure-console.log`: 自動起動時のエラー。
- `~/ClipStudio/logs/psm.log`: CSP 側 Wintab のログ。

`WTInfo lp_output is null` は PSM のサイズ照会時のログで、実装は 8192 を
返して継続する。このログだけでは入力失敗を意味しない。

## 検証

`test/PressureProbe.cs` は専用の Wine ウィンドウと Wintab コンテキストを
作り、受信した筆圧を読む。既知の `0, 4096, 16384, 32767` の送信に対し、
4 種類の値を受信する統合テストが成功。
2026-09-23、ユーザーが実ペンによる CSP 描画で筆圧の動作を確認済み。
実機の転送ログでも 7,114 パケット、最大筆圧 32,767 を確認した。
入力 ACL の適用と自動起動設定は完了。次回起動時の sudo 実行は不要。

PSM の配布 ZIP は GitHub release API の SHA256 と照合済み。
出典とハッシュは `PSM-SOURCE.txt`、ライセンスは `PSM-LICENSE`。

## 復元

CSP と転送スクリプトを終了し、`~/ClipStudio/pressure/last-backup.txt` に
記録されたフォルダーの `manifest.json` を確認する。バックアップの
`0-wintab32.dll` を Wine の system32 に、`1-csp-launch.sh` を bin に戻す。
その後、CSP 専用の `DllOverrides` から `wintab32` 値を削除する。

```bash
source ~/ClipStudio/env.sh
wine reg delete 'HKCU\Software\Wine\AppDefaults\CLIPStudioPaint.exe\DllOverrides' /v wintab32 /f
```

入力権限も戻す場合は管理者権限で上記 udev ルールを削除してルールを
再読み込みし、Wacom を接続し直す。画面配置を拡張表示へ変えた場合は、
転送の座標設定を更新してから使用する。

## 感度・対応マップの設定（2026-09-23 追加）

筆圧カーブ（感度・カーブ・反応開始・最大入力・最小出力）、タブレットと
画面の対応マップ（全体／アスペクト比維持／指定領域／回転）、サイド
スイッチの割り当ては `~/ClipStudio/etc/pentab.conf` で設定する。転送
スクリプトは 1 秒ごとに同ファイルを確認し、動作中にそのまま反映する
（CSP の再起動は不要）。設定画面と CLI は `~/デスクトップ/clip/pentab/
README.md` を参照。
