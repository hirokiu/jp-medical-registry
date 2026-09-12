# jp-medical-registry

地方厚生局が公開する保険医療機関・保険薬局の月次一覧を取得し、Wikibase投入のためのCSV・JSONへ変換します。Wikibaseへの書込みは別リポジトリ [wikibase-registry-sync](https://github.com/hirokiu/wikibase-registry-sync) が担当します。

## 実装済み（0.2）

- 全国8局・支局の公開ページから、その月の主一覧Excel／ZIPを発見・取得
- SHA-256による原本の非上書き保存、取得ページ・URL・日時・HTTP情報の記録
- 複数行の帳票を1機関にまとめ、医療機関コードを10桁化（Wikidata P13179）
- 名称、郵便番号、住所、電話、開設者、管理者、病床・診療科・状態等の原文をCSVへ出力
- 原表のシート・行・セル・書庫メンバーとハッシュをJSONLに保存
- 県・種別・対象月・重複競合を検証し、不完全な結果は要確認ファイルとして分離
- 保存原本からネットワーク接続なしで再変換、前月との属性差分
- 変更一覧の候補資料を別取得し、Excelのセルを中間CSVへ出力

2026年9月の実資料30ファイルで、47都道府県×3種別、**224,517件**の主一覧を変換しました。これは保険指定一覧のレコード数であり、国内すべての物理施設数ではありません。[検証結果](docs/validation-2026-09.md)

## インストール

Python 3.10以上。

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
```

## 月次取得・変換

```sh
jp-medical-registry monthly --month 2026-09 --output data/processed/monthly
```

地域を限定する場合：

```sh
jp-medical-registry monthly --month 2026-09 --regions hokkaido tohoku --output data/processed/monthly
```

地域名：`hokkaido tohoku kanto tokai kinki chugoku shikoku kyushu`。

`--month`は主一覧の対象年月です。ファイル名の数字だけで判断せず、Excel内の「現在」日付と照合します。過去月が公開ページから消えている場合、別月のファイルで代用せず不完全と報告します。初回は公開中の対象月から原本の継続保存を始めてください。

終了コード0は、選択地域の主一覧について全県・3種別を確認し、取得・解析エラーと同一ID競合がない状態です。2は要確認です。0は全属性の意味解釈や変更イベント検証まで完了したという意味ではありません。

## 出力

実行ごとに`runs/対象月-時刻-ID/`を新規作成します。

| ファイル | 用途 |
|---|---|
| `institutions.csv` | UTF-8 BOM付きの1機関1行CSV。コード・郵便番号は文字列として読み込む |
| `institutions.jsonl` | CSV項目＋原表セル＋複数の出典位置 |
| `bundle.json` | 完全な主一覧に限って生成する、投入プログラム向けbundle 0.1 |
| `bundle.review.json` | 不完全な場合の確認用。投入用ファイルの代わりにはしない |
| `sources.json` / `pages.json` | 原本・掲載ページの取得記録 |
| `discovery.json` | 発見した実ファイルURLとページ上の文脈 |
| `report.json` | 件数、県・種別の充足、取得/解析失敗、警告 |
| `conflicts.jsonl` | 同じ10桁コードで内容が異なるレコード |
| `observed-diff.json` | `--previous`指定時の前月差分 |

原本は出力ルートの`raw/objects/SHA256`へ保存します。同じURLが差し替わっても過去版を残します。生成物・原本・実行状態はGit管理しません。

bundleにはP13179、P1448、P281、P6375、形式を確認できた電話のP1329、およびP854の出典を出力します。ローカルのP番号を決め打ちしません。開設者・管理者、病床と診療科が混在する欄は意味を推定せずCSV/JSONLの原文欄へ保存します。取得日時・SHA・行位置は出典sidecarに保存します。

## 再変換と前月比較

```sh
jp-medical-registry replay data/processed/monthly/runs/取得実行ID/sources.json \
  --month 2026-09 --output data/processed/replayed-2026-09

jp-medical-registry monthly --month 2026-10 --output data/processed/monthly \
  --previous data/processed/monthly/runs/前月実行ID/institutions.jsonl
```

再変換先は未作成のディレクトリを指定します。原本ハッシュを再確認します。前月比較は同じ地域範囲・前月/当月とも完全な結果に限ります。取得日時や資料ハッシュだけの変化は機関の属性変更に数えません。消失は廃止ではなく`missing`として報告し、発効日を推測しません。

## 変更一覧の取得

```sh
jp-medical-registry changes --month 2026-08 --output data/processed/monthly
```

主一覧とは別に、指定月に関係する新規・廃止・辞退・取消・診療科変更の候補資料を保存します。地域によって処理月、指定月、掲載月の表示が異なるため、`--month`は探索対象であり発効日ではありません。ページ上の文脈を保存し、リンクが見つからない場合も「変更なし」とは扱いません。

`change-runs/`に原本manifest、`change-cells.csv`、確認用reportを出力します。**このCSVは原表セルを保持する中間データで、Change Event Itemの完成形ではありません。** PDF/XLSは原本保存までです。変更処理は確認が必要なので終了コード2を返します。

## 残る範囲

- 併設機関の補助一覧：主一覧とは別扱い。ZIP内は原本保持、個別リンクは主一覧探索の対象外。括弧内コードは`secondary_codes_raw`に保持し、種別を推測して新IDを作らない。
- 変更一覧の地域別意味解釈、PDF/XLS parser、発効日と処理月の分離、Event Item生成、月次イベント再整合は未完了。
- 緊急避妊の別系列、Wikidata自動照合は未実装。通常の月次出力のQIDは未割当。既存`convert-csv`は確認済みQID列を保持できる。
- チェックデジット検証は未実装。10桁を正本とし、県・点数表との構成検証を行う。原資料の7桁は県・種別を明示して10桁化する。[識別子の確定仕様](docs/IDENTIFIER_DECISION.md)を参照。
- 公開ページや帳票が変わった際は検証エラーを修正する。全国・全月の将来互換性を保証するものではない。
- サーバーへの配備、月次スケジューラ登録、Wikibaseへの投入はまだ行わない。

## ライセンス

MITはオリジナルのプログラムに適用します。取得資料には各公開元の利用条件が適用されます。旧WikibaseSyncのコードはコピーしていません。

### 確認済みWikidata候補との接続

`python -m jp_medical_registry.match_cli sample.csv candidates.json --dataset jp-medical-registry --output bundle.json`

候補ファイルは10桁コードをキー、Wikidata Entity JSONの配列を値とする辞書です。事前にレビューした候補を渡します。コードと正規化名称が一致し、郵便番号・電話番号に矛盾がない単一候補のみQIDを付けます。名称のみの一致やコード重複は要確認とし、候補未取得は未照合として保存します。判定根拠とWikidata revisionをbundleに残します。網羅的なWikidata検索や曖昧名寄せはまだ行いません。
