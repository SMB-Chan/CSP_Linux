# ペンタブレット設定（感度・対応マップ・サイドスイッチ）

対象: Wacom One M (`0531:0102`) → `wacom-pressure.py` → Pain Studio Mask
(Wintab) → CLIP STUDIO PAINT 5.1.4 (Wine)。

CSP 本体と Wintab DLL は変更していない。設定は転送スクリプト
`~/ClipStudio/bin/wacom-pressure.py` が読む `~/ClipStudio/etc/pentab.conf`
に集約し、保存後およそ 1 秒で動作中の転送へ反映される（CSP の再起動は
不要）。

## ファイル

- `pentab-settings.py`: 設定画面（GTK 4）。下記 `pentab.sh --gui` で起動する。
  アプリメニューの **ペンタブレット設定** からも開ける。
  アプリメニューの **ペンタブレット設定** からも開ける。
- `~/ClipStudio/bin/pentab.sh`: CLI ラッパー。
- `~/ClipStudio/etc/pentab.conf`: 設定本体（日本語の注釈入り）。
- `~/ClipStudio/backups/pentab/`: 保存ごとの変更前バックアップ。

## 設定画面

```bash
~/ClipStudio/bin/pentab.sh --gui
```

4 つの欄がある。

1. **対応マップ**: 画面全体／アスペクト比を維持／指定領域、および
   タブレットの回転（0/90/180/270）。領域は「右半分」「左半分」
   「中央 2/3」「上半分」のボタンでも設定できる。下の青い図が画面と
   読み取り範囲の対応を示す。
2. **筆圧の感度とカーブ**: プリセット（標準／やわらかめ／硬め）と
   5 本のスライダー（感度・カーブ・反応開始・最大入力・最小出力）。
   右の図が筆圧カーブで、ペンを実際に押すと点 が動く。
3. **ペンのボタン**: サイドスイッチが送るボタン（右クリック／
   中クリック／送らない）。ペン先は常に左クリック。CSP 側への機能
   割り当ては「環境設定 → ショートカット」で行う。
4. **実機テスト**: ペンに触れるとバーと数値が動き、CSP に届く筆圧値
   （0〜32767）を保存前に確認できる。

ボタン:

- **保存して適用**: 検証 → バックアップ → 書き込み → 転送プログラムへ
   再読み込み指示（SIGHUP）まで行う。
- **保存前の値に戻す**: 画面の値を conf の内容へ戻す。
- **既定（導入時の描き味）**: 導入時と同一の値（等倍・線形・画面全体）
   を画面に置く。
- **転送プログラムに読み直させる**: 書き込まず再読み込みだけ指示する。

## CLI

```bash
~/ClipStudio/bin/pentab.sh --show                 # 現在値と反映状態
~/ClipStudio/bin/pentab.sh --check                # 検証と 0〜100% の応答表
~/ClipStudio/bin/pentab.sh --set pressure.gain 1.3  # 1 項目だけ変更＋反映
~/ClipStudio/bin/pentab.sh --reload               # 手書き編集後の反映
~/ClipStudio/bin/pentab.sh --restart              # 転送プログラムの再起動
~/ClipStudio/bin/pentab.sh --gui                  # 設定画面
```

`--set` と設定画面は conf の日本語注釈を保ったまま値の行だけ書き換える。
手書きで編集した場合は `--reload` か、そのまま 1 秒待つだけで反映される。
値が範囲外のときは反映されず、直前の設定が維持される（ログ:
`~/ClipStudio/logs/wacom-pressure.log`）。

## 設定項目の一覧

| キー | 意味 | 範囲 | 既定 |
| --- | --- | --- | --- |
| `map.mode` | 対応マップ | full / aspect / area | full |
| `map.rotate` | タブレット回転 | 0 / 90 / 180 / 270 | 0 |
| `map.area_x` ほか 4 鍵 | area の画面領域 px | 0 以上（幅・高さは 0 で全画面） | 0 |
| `map.grab` | ペンの排他占有（on でデスクトップ側カーソル停止。このホストでは off 推奨） | on / off | off |
| `pressure.gain` | 感度（等倍=1） | 0.05〜8 | 1.0 |
| `pressure.gamma` | カーブ（1 未満=やわらかい） | 0.1〜8 | 1.0 |
| `pressure.input_floor` | 反応を開始する筆圧 | 0〜0.99 | 0.0 |
| `pressure.input_ceiling` | 最大筆圧に達する入力 | 0.01〜1 | 1.0 |
| `pressure.output_floor` | 触れた瞬間の最小出力 | 0〜0.9 | 0.0 |
| `pen.side_button` | サイドスイッチ | right / middle / none | right |

## 検証済み（2026-09-23）

- 既定値は設定導入前の転送と同一の結果になる（158×12 通りの座標と
  筆圧の全数比較、および実機ログの最大筆圧 32767 との一致）。
- 設定画面からの保存 → conf 書き換え（注釈維持）→ 転送プログラムの
  反映までを実機で確認。反映は状態ファイル
  `~/ClipStudio/logs/wacom-pressure-status.json` の `settings` で確認できる。
- 範囲外の値は日本語のエラー 1 行だけ出して直前の設定を維持する。

## 戻し方

`~/ClipStudio/backups/pentab/` の日時付きファイルを手順どおり conf に
戻して `--reload` する、または設定画面で「既定（導入時の描き味）」を
選んで保存する。conf を削除しても転送プログラムは既定値で動く。
