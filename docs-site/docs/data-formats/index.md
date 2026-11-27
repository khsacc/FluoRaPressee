---
sidebar_position: 1
title: 保存データの形式
description: FluoraPresséeが保存する各種ファイルの形式一覧
---

# 保存データの形式

FluoRaPressée は、測定・解析の過程でいくつかの種類のファイルをディスクへ保存します。
ここでは、それぞれのファイルの拡張子・内部構造・記録される項目についてまとめます。

測定データ（スペクトル、バックグラウンド、フィッティング結果、連続測定ログ）の保存場所は、ユーザーがファイル保存ダイアログで指定したフォルダです。
Configurationファイルと`spectrometerConfig.json`などの設定は、次の[ユーザーデータの保存場所](#アプリが自動で保存するファイル)に自動で保存されます。

## アプリが自動で保存するファイル

設定・較正・ログは、OSのユーザーごとの領域にある1つのフォルダにまとめて保存されます。
インストール版でもソースから起動した場合でも、同じフォルダを使います。

| OS | 場所 |
|---|---|
| Windows | `%LOCALAPPDATA%\FluoraPressee\` |
| macOS | `~/Library/Application Support/FluoraPressee/` |
| Linux | `$XDG_DATA_HOME/FluoraPressee/`（既定 `~/.local/share/FluoraPressee/`） |

| パス | 内容 |
|---|---|
| `spectrometerConfig.json` | [ハードウェア設定](spectrometer-config.md) |
| `local_cache.json` | 前回の保存先フォルダ・APIの動作モードなど、画面の状態 |
| `configurations/` | [Configurationファイル](configuration.md)（JSONレコードとSQLiteカタログ） |
| `api_clients.json` | [APIクライアントのキー](../api/clients.md) |
| `calibrationStandards/` | 利用者が追加した較正標準のJSON（同梱の標準と同じ形式。同じ`standard_id`があればこちらが優先されます） |
| `logs/` | インストール版のログ（[Helpメニュー](../usage/menu/help.md#ログファイル)）と、APIの状態トークンの記録（`instrument_state.log`） |

インストール先のフォルダには何も保存しないため、更新やアンインストールでこれらが消えることはありません。

環境変数 `FLUORAPRESSEE_DATA_DIR` にフォルダを指定すると、上の場所の代わりにそのフォルダを使います。
既存の設定に触れずに初回起動ウィザードを試す場合などに使います。

:::note
以前の版は `spectrometerConfig.json` と `local_cache.json` をリポジトリ直下に保存していました。
ソースから起動したとき、上の場所にまだファイルがなければ自動的に移され、元のファイルは `.migrated` を付けた名前に変わります（`FLUORAPRESSEE_DATA_DIR` を指定しているときは移しません）。
設定ファイル内の相対パス（`dll_path`など）は、このとき元のフォルダを基準にした絶対パスに直されます。
:::

新しい版が新しい形式で保存したデータ（構成カタログ・`api_clients.json`）を古い版で開くと、古い版はデータを書き換えずに理由を表示し、そのデータを使う機能だけを止めます。

## ファイル一覧

| ファイル | 生成タイミング | 形式 | 説明 |
|---|---|---|---|
| [スペクトルデータファイル](spectrum-data.md) | 「Save Data」、連続測定の各フレーム | テキスト（`#`コメントヘッダー + CSVデータ） | 1Dスペクトルまたは2Dイメージ本体 |
| [バックグラウンドファイル](background.md) | バックグラウンド取得直後の保存ダイアログ | JSON | 差し引き用のバックグラウンドスペクトル |
| [フィッティング結果ファイル](fitting-results.md) | 「Save Data」時（フィット有効時）、連続測定 | テキスト（単発）／CSV（連続測定サマリ） | ピークフィッティングと圧力計算の結果 |
| [連続測定ログファイル](sequential-log.md) | 連続測定の終了時 | テキスト | 実行条件と、保存された各フレームのファイル名・タイムスタンプ一覧 |
| [Configurationファイル](configuration.md) | 較正ダイアログの「Save and apply」 | JSON + SQLiteカタログ | grating・中心波長・ROI・横軸較正のバージョン管理付き記録 |
| [spectrometerConfig.json](spectrometer-config.md) | 初回起動時のセットアップウィザード完了時、Hardware Configuration適用時 | JSON | メーカー・接続方法・grating構成・ROI初期値・冷却設定などハードウェアそのものの構成 |

これらのデータをHTTP経由で取得・適用する場合は[API](../api/index.md)を参照してください。
