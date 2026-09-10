# jp-medical-registry

日本の保険医療機関・保険薬局データを収集・正規化し、Wikidataとの対応と月次変更を追跡するためのプロジェクトです。Wikibaseへの投入は別リポジトリ [wikibase-registry-sync](https://github.com/hirokiu/wikibase-registry-sync) が担当します。

## 現在の実装（0.1）

- HTTPS原本のSHA-256保存と取得記録の追記
- 都道府県2桁＋点数表1桁＋地域コード7桁によるP13179の10桁ID生成
- 整形済みCSVから共通JSON bundleへ変換、確認済みQIDの保持
- snapshot間の観測差分（消失を廃止と推定しない）

全国帳票adapter、自動WD照合、行政Change Event生成、定期実行は未実装です。CSVは公式Excelそのものではなく、明示した共通列を持つ入力です。チェックデジットの検証は未実装です。

## ローカル実行

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
jp-medical-registry code 13 医科 '02,7075,1'
jp-medical-registry convert-csv examples/canonical.csv > /tmp/medical-bundle.json
python -m unittest discover -s tests -v
```

`fetch URL DIRECTORY --bureau 局名 --period 対象年月`で原本を取得できます。同一内容は再利用し、取得記録は追記します。`diff OLD.json NEW.json`は観測差分を返します。

サンプルの聖路加国際病院は2026年9月資料による検証例です。QIDは確認済み入力を渡す方式であり、自動照合の結果ではありません。

[設計と未実装範囲](docs/architecture.md)。MITライセンスはプログラムに適用し、取得データの利用条件は各出典に従います。
