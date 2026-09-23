# CSP_Linux — Clip Studio Paint を Linux (Wine) で使う

Ubuntu / GNOME Wayland 上で **CLIP STUDIO PAINT 5.1.4** を Wine 11.4 (wow64) で動かす
ための、root 不要の設定一式です。CSP 本体・インストーラは改変しません。

詳細な構築記録は [SETUP-NOTES.md](SETUP-NOTES.md) を参照。

## 含まれるもの

| パス | 内容 |
|---|---|
| `SETUP-NOTES.md` | 導入・設定・トラブルシューティング |
| `bin/` | 起動・タブレット・TourBox 用スクリプト |
| `etc/` | 設定サンプル（`pentab.conf` / `tourbox.conf`） |
| `pentab/` | ペンタブ設定 GUI（GTK4） |
| `tourbox/` | TourBox キー設定 GUI（GTK4） |
| `wacom-pressure/` | ペン入力 → PSM (Wintab) 転送と関連文書 |

**コミットしていないもの:** CSP / Wacom / TourBox のインストーラ、Wine プレフィックス、
PSM の `wintab32.dll` 本体。入手元は `wacom-pressure/PSM-SOURCE.txt`。

## 主要機能

- CSP 5.1.4 のサイレント導入・安定起動（`dcomp` シム、DXVK、WebView2）
- `.clip` ファイルの関連づけ
- Wacom One のカーソル・接地・筆圧（Pain Studio Mask の Wintab + 転送スクリプト）
- タブレットサービス自動切替（Wintab / `csp-tablet-mode.sh`）
- 筆圧・対応マップ設定 GUI（アプリメニュー「ペンタブレット設定」）
- TourBox Lite の Linux ネイティブドライバとキー設定 GUI

## 使い方（導入済みマシン）

```bash
~/ClipStudio/bin/csp-launch.sh          # CSP 起動（タブレット転送つき）
~/ClipStudio/bin/csp-tablet-mode.sh verify
~/ClipStudio/bin/pentab.sh --gui        # 筆圧・マップ
~/ClipStudio/bin/tourbox-gui.sh         # TourBox キー
```

初回構築の手順は `SETUP-NOTES.md` の §1〜§10 を上から実行してください。

## 環境

- Ubuntu 26.04 / GNOME Wayland / 1920×1080
- Wine 11.4 amd64-wow64（`~/opt/wine-11.4-amd64-wow64`）
- Wacom One Medium (`0531:0102`)、TourBox Lite (`cafe:4001`)
- CSP 5.1.4（CELSYS）※インストーラは同梱しません

## ライセンス

このリポジトリ内のスクリプト・文書は、併せて置く `wacom-pressure/PSM-LICENSE`
（MIT / Pain Studio Mask）を除き、利用・改変・再配布自由です。
CELSYS / Wacom / TourBox のソフトウェアは各社のライセンスに従ってください。
