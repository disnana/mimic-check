# mimic-check

`mimic-check` は、`requirements.txt` に記載された Python パッケージの安全性を検証するためのツールです。
タイポスクワッティング（有名なパッケージに似た名前の悪意あるパッケージ）の検出や、ダウンロード数・GitHub スター数に基づいた信頼性の評価を行います。

## 特徴

- **タイポ検出**: `requests` を `reqeusts` と書き間違えているようなケースを検出し警告します。
- **信頼性評価**: PyPI のダウンロード数（直近1ヶ月）と GitHub のスター数を確認し、閾値未満のパッケージを警告します。
- **効率的なキャッシュ**: 検証結果を当日中のみ有効なキャッシュとして保存し、不要な API リクエストを削減します。
- **PyPI 存在確認**: パッケージが PyPI に存在しない場合、即座に警告し後続のチェックをスキップします。
- **CI 対応**: `--ci` フラグを使用することで、問題検出時に非ゼロの終了コードで終了し、パイプラインを停止させることができます。

## セットアップ

### 必要条件

- Python 3.x
- `requests`, `toml` パッケージ

### インストール

PyPIからインストールする場合（公開後）：

```bash
pip install mimic-check
```

ローカルで開発用にインストールする場合：

```bash
pip install -e .
```

これにより、`mimi` コマンドが使用可能になります。

## 使い方

### 基本的な実行

```bash
mimi --file requirements.txt
```

実行すると、パッケージごとに以下のチェックが行われます：
1. 有名パッケージとの名前の類似性（タイポ）チェック
2. PyPI での存在確認
3. ダウンロード数とスター数の確認

問題が見つかった場合、警告が表示され、続行するかどうかを確認されます。`y` を入力すると、そのパッケージを含めた一時的な requirements ファイルで `pip install` が実行されます。

### CI モードでの実行

CI/CD パイプラインなどで、問題検出時に自動的にエラーとしたい場合は `--ci` フラグを使用します。

```bash
mimi --file requirements.txt --ci
```

## PyPIへの配布方法

1. ビルドツールのインストール:
```bash
pip install build twine
```

2. パッケージのビルド:
```bash
python -m build
```

3. PyPIへのアップロード (テスト環境):
```bash
python -m twine upload --repository testpypi dist/*
```

4. PyPIへのアップロード (本番環境):
```bash
python -m twine upload dist/*
```

## 設定 (`config.toml`)

プロジェクトのルートにある `config.toml` で動作をカスタマイズできます。

```toml
[mimi]
min_downloads = 1000  # 信頼できるとみなす最小ダウンロード数
min_stars = 10        # 信頼できるとみなす最小 GitHub スター数
famous_packages = ["requests", "numpy", "pandas", ...] # タイポチェック対象の有名パッケージ
trusted_packages = [] # チェックをスキップする信頼済みパッケージ
```

## キャッシュ

`package_cache.json` に検証結果がキャッシュされます。
- キャッシュは日付ごとに管理され、翌日には自動的に再検証されます。
- 信頼性の基準を満たしたパッケージのみがキャッシュされ、警告対象のパッケージは毎回チェックされます。
