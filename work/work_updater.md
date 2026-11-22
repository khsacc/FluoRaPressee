# ビルド版の配布と更新の通知 実装計画

作成日: 2026-11-21
改訂: 2026-11-21(レビュー第1回の反映 — 更新を適用するときの排他、移行の条件、キャッシュの更新消失、
パスの補正、Analysis Mode からの更新、mutex の名前空間)
改訂: 2026-11-21(方針変更 — アプリ内からのダウンロードとインストールをやめ、配布ページへの案内だけに
する。Step 7 を削除)
改訂: 2026-11-21(レビュー第2回の反映 — 旧APIキーの移行の条件、ログファイルの分け方、知らない版の
データ形式の拒否、インストーラー用 mutex の名前空間)

## 背景

仮版(ベータ版)をビルドして公開する。現状の配布形態は「`git clone` → `setup.bat` で `.venv` を作る →
`.bat` から `python main.py` を起動」であり、利用者のPCにPythonが必要で、更新も `git pull` と
`pip install` を手で行うしかない。

そこで、**Pythonを必要としないビルド版をGitHub Releasesで配布する。** 新しい版が出たらアプリが知らせて
配布ページへ案内し、利用者はインストーラーをダウンロードして実行するだけで更新できるようにする。

**更新の通知を持たない版を一度配ると、その利用者は新しい版が出たことに気づけない。** したがって
更新確認は最初の仮版(`v0.1.0b1`)に必ず入れる。また、その前に、前提となる準備(バージョン番号、
ユーザーデータの置き場所の分離)を済ませる必要がある。

### 現状(2026-11-21 時点の調査結果)

1. **バージョン番号がコードのどこにもない。** 新旧を比べる基準がない。
2. GitHubリポジトリ(`khsacc/FluoraPressee`)は公開で、Releaseは0件。Releases APIは認証なしで使える。
3. **実行時にカレントディレクトリ(=リポジトリ直下)へ書き込むファイルがある。**
   インストール版ではインストール先が更新のたびに差し替わるため、ここに置けない。
   - `spectrometerConfig.json`: `src/app_bootstrap.py:26`, `src/ui/ui_mixins/config_mixin.py:122`, `:212`,
     `src/ui/ui_mixins/api_mixin.py:403`, `src/hardware/spectrometer_andor.py:41`
     (`src/api/info_helpers.py:88` は表示用のラベル)
   - `local_cache.json`: `src/ui/local_cache.py` の `_CACHE_PATH`
   - `ShamrockCIF.dll`: `dll_path` が空のとき、カレントディレクトリ相対の `"ShamrockCIF.dll"` を読む
     (`src/hardware/spectrometer_andor.py:40`)。ウィザードの既定値は空(`src/ui/config_wizard.py:71`)。
4. 次はすでにユーザーデータ領域にある。ただし、OS別のベースパスを決める処理が2カ所に重複している。
   - `configurations/`(`src/core/configuration_catalog.py:60` `default_configuration_root()`)
   - `api_clients.json`(`src/core/api_clients.py:37` `default_api_clients_path()`)
   - `logs/instrument_state.log`(`src/core/instrument_state_log.py`、上の関数を流用)
5. 同梱データを `__file__` からの相対パスで探している箇所がある。
   - `calibrationStandards/`: `src/ui/calibration_ui.py:97`
   - `logo/`: `src/app_bootstrap.py:78`
6. `calibrationStandards/*.json` は glob で読み込まれる(`src/core/calibration_reference.py:82`)。
   利用者が独自のJSONを置けるが、インストール版ではこのフォルダが更新のたびに消える。
7. `main.py:4-5` と `analysis_main.py:4-5` が `sys.stdout.reconfigure()` を呼ぶ。PyInstallerの
   ウィンドウ版(コンソールなし)では `sys.stdout` が `None` なので、**起動直後に `AttributeError` で
   落ちる**。また、ログは `print()` でコンソールに出す前提になっている。
8. エントリーポイントは2つある(`main.py` と、ハードウェアに依存しない `analysis_main.py`)。
9. メニューバーは Hardware / API / Tools のみで、Help はない(`src/ui/main_window.py:873-891`)。
   Analysis Mode のウィンドウにはメニューバーがない。メインウィンドウにステータスバーもない。
10. ~~`.gitignore` に `/tests/` がある。~~ → 2026-11-21 に削除済み。
11. `.gitignore` に `/scripts/` がある(追跡されているのは `scripts/_dev_api_load.py` だけ)。そのため、
    ビルド用のファイルは `scripts/` ではなく `packaging/` に置く。
12. 開発用PCは macOS と Windows の両方。Python は 3.13.11(`.python-version`)。
13. 旧APIキーのファイル `fluora_pressee_api_key.json` は、`load_clients()` が既定でカレントディレクトリ
    から読み、移行して保存できたら削除する(`src/core/api_clients.py:92-94`、
    `src/ui/ui_mixins/config_mixin.py:191-202`)。**この経路は、保存先をどこに指定しても動く。**
14. データ形式の版の扱いがそろっていない。
    - 構成レコード(JSON)は、新しい `schema_version` を拒否する(`src/core/configuration_catalog.py:811-816`)。
    - SQLite のカタログは、新しい `schema_version` でも処理を続ける(`_migrate_catalog` は
      `version >= CATALOG_SCHEMA_VERSION` なら戻るだけ。`:280`)。しかも、版を見る前に
      `PRAGMA journal_mode = WAL`、`CREATE TABLE IF NOT EXISTS`、`INSERT OR IGNORE` を実行している。
    - `api_clients.json` は `version` を見ない。`clients` がなければ新規インストールとみなし、新しい鍵を
      作って上書き保存する(`src/core/api_clients.py:140-141`、`config_mixin.py:191-197`)。各クライアントの
      未知のキーは捨てる(`_normalize_client`)。
    - `src/ui/main_window.py:225` は `ConfigurationCatalog()` の例外を捕まえない。

### 決定事項

- 配布形態は **PyInstaller(onedir) + Inno Setup のインストーラー + GitHub Releases**。
- **インストーラー1本で、新規インストールと上書き更新を兼ねる。**
- **アプリは新しい版を知らせ、配布ページを開くだけにする**(2026-11-21 方針変更)。インストーラーの
  ダウンロードと実行は利用者が行う。アプリはファイルのダウンロードもインストーラーの起動もしない。
  詳細は方針7。
- **起動中の FluoRaPressée はインストーラーが検出し、終了するよう求める**(2026-11-21 決定)。
  いつ終了するか(測定中かどうかなど)は利用者が判断する。インストーラーは FluoRaPressée を強制終了
  しない。詳細は方針6。
- 開発用PCでは、これまで通りコマンドから起動する。**開発用PCにはインストールしない。**
  - Windowsの開発用PCでは、ローカルでビルドした `dist\` のexeを直接起動して確認できる。
  - インストーラーと上書き更新は Windows Sandbox か仮想マシンで試す。
- ユーザーデータは、ソースから起動してもビルド版でも**同じ場所**に置き、環境変数で差し替えられる
  ようにする。
- **実験用PCはインターネットにつながる前提とする**(2026-11-21 決定)。起動時の自動確認を更新の
  主な経路にする。つながらないときに何も表示しない動作は、念のため残す。
- **当面はコード署名なしで配布する**(2026-11-21 決定)。インストールと更新のたびに SmartScreen の
  警告が出るが、「詳細情報 → 実行」で続行してもらう。影響と対策は方針8に書く。
- **Ocean Optics のドライバーは、同じインストーラーに入れた専用のexeで導入する**(2026-11-21 決定)。
  インストーラーの任意項目、セットアップウィザード、スタートメニューの3カ所から起動できるようにする。
  Ocean Optics 用の別のインストーラーは作らない。詳細は方針12。
- **同じPCにソース版とインストールした版がある場合は、一度に1つだけ起動する運用とし、その範囲で
  衝突が起きないようにする**(2026-11-21 決定)。詳細は方針13。

## 採用する方針

### 方針1: 実行形態を2種類に分け、判定を1カ所にまとめる

| 実行形態 | 判定 | 更新の案内 |
|---|---|---|
| `source`(ソースから起動) | `getattr(sys, "frozen", False)` が偽 | 最新版の確認と表示まで。「git pull してください」と案内する |
| `frozen`(ビルド版) | 上記が真 | インストーラーのダウンロードリンクと、リリースページを開くボタン |

判定は新設する `src/core/runtime_env.py` の1関数(`runtime_kind()`)に集約し、他のコードは
`sys.frozen` を直接見ない。

当初は、ビルド版をさらに「インストール済み」と「ビルドしただけ(`dist\` から直接起動)」に分ける予定
だった。アプリがインストーラーを起動する設計だったので、開発用PCで `dist\` から起動した版が意図せず
インストールしてしまうのを防ぐためである。アプリがインストーラーを起動しなくなったので(方針7)、
この区別は不要になった。

### 方針2: バージョン番号は `src/version.py` だけに書く

- `__version__ = "0.1.0b1"` のように PEP 440 形式で書く。Gitのタグは `v0.1.0b1`。
  リリース用CIは、タグと `__version__` が一致しなければ失敗させる。
- 表示用のバージョン文字列は `runtime_env.py` で組み立てる。
  - ソースから起動したとき: `0.1.0b1+dev.g1a2b3c4` のように、`git rev-parse --short HEAD` の結果を
    付ける。gitが使えなければ付けないだけで、失敗はさせない。
  - ビルド版: CIがビルド時に `src/_build_info.py`(コミットとビルド日時)を生成する。このファイルは
    `.gitignore` に入れ、ソースには存在しない。
- 版の比較には `packaging.version.Version` を使う(`requirements.txt` に `packaging` を追加)。
  自前の比較処理は書かない。`0.1.0b1 < 0.1.0rc1 < 0.1.0` の順序や、`+dev...` が付いた版の扱いを
  正しく処理できるため。
- Inno Setup の `AppVersion` には `__version__` をそのまま渡す(表示用)。exe のファイル情報
  (`VersionInfoVersion`)は数字しか受け付けないので、数字部分だけ(`0.1.0.0`)を渡す。
- バージョンを表示する場所: 起動時のコンソール出力、Help → About、保存データとAPI(Step 8)。

### 方針3: ユーザーデータは、実行形態によらず同じ場所に置く

新設する `src/core/app_paths.py` で場所を決める。

- `user_data_dir()`: 環境変数 `FLUORAPRESSEE_DATA_DIR` が設定されていればそれを使う。なければ OS 別の
  ベースパスの下の `FluoraPressee/` を使う。

  | OS | 場所 |
  |---|---|
  | Windows | `%LOCALAPPDATA%\FluoraPressee\` |
  | macOS | `~/Library/Application Support/FluoraPressee/` |
  | Linux | `$XDG_DATA_HOME/FluoraPressee/`(既定は `~/.local/share/FluoraPressee/`) |

- この下に置くもの:

  | パス | 内容 | 現状 |
  |---|---|---|
  | `spectrometerConfig.json` | ハードウェア設定 | リポジトリ直下から移す |
  | `local_cache.json` | UIの状態 | リポジトリ直下から移す |
  | `calibrationStandards/` | 利用者が追加した校正標準のJSON | 新設(方針5) |
  | `configurations/` | 構成カタログ | 現状のまま |
  | `api_clients.json` | APIクライアント | 現状のまま |
  | `logs/` | ログ | 現状のまま + 起動ごとのログファイル(方針9) |

- 既存の `default_configuration_root()` と `default_api_clients_path()` は、関数名をそのまま残して、
  中身を `user_data_dir()` に任せる。重複しているOS判定はここで1つにまとまる。
- **インストール先(`{app}`)には一切書き込まない。** これは方針6の `[InstallDelete]`(更新時に
  `_internal` を丸ごと消す)を安全に行うための前提である。

**ソースから起動するときだけリポジトリ直下を使い続ける案は採らない。** コードの分岐が2通りになり、
マニュアルにも2つの場所を書く必要が出る。また、同じ場所にそろえると、git clone で使っている
実験PCでは Step 1 の版に更新した時点で設定がユーザーデータ領域へ移る。そのため、後からビルド版を
入れてもそのまま引き継がれ、インストーラーが clone の場所を知る必要がなくなる。

環境変数 `FLUORAPRESSEE_DATA_DIR` は次の用途に使う。

- テストが実際のユーザーデータに触れないようにする。
- 空のフォルダを指定して、初回起動ウィザードを何度でも試す。
- Windowsの開発用PCで、ローカルビルドを試すときに開発中のデータと分ける。

この環境変数を設定すると、構成カタログとAPIクライアントの場所も一緒に変わる。完全に切り離すための
ものなので、これは意図した動作である。

### 方針4: 旧い場所からの移行はソースから起動したときだけ行い、旧ファイルは改名して残す

起動時、何かが設定を読む前に、次を行う。**行うのは、ソースから起動していて、かつ環境変数
`FLUORAPRESSEE_DATA_DIR` が設定されていないときだけである。**

1. 新しい場所に `spectrometerConfig.json` がなく、`<repo>/spectrometerConfig.json` があれば、
   コピーする。
2. コピーしたら、旧ファイルを `spectrometerConfig.json.migrated` に改名し、コンソールに知らせる。
3. `local_cache.json` も同様に扱う。
4. 新旧の両方があるときは新しい場所を使い、旧ファイルには触れず、警告だけ出す。

**環境変数で保存先を指定したときは移行しない。** 環境変数は、実際のデータから切り離して試すための
ものである(方針3)。ここで移行すると、空のフォルダを指定して試しただけで実際の設定がコピーされ、
リポジトリ側の旧ファイルまで改名されてしまう。初回起動ウィザードを試すこともできなくなる。
移行しなかったことは、コンソールに1行出して知らせる。

**旧APIキー(`fluora_pressee_api_key.json`)の自動移行にも、同じ条件を適用する。** この移行は
`load_clients()` が別の経路で行っていて、現状ではカレントディレクトリのファイルを読み、保存できたら
削除する(「現状」13)。条件を新設の移行処理にだけ付けると、空のテスト用フォルダを指定して起動した
だけで、実際の旧キーが一時フォルダへ移され、元のファイルが削除されてしまう。

- 移行するかどうかの判定は `app_paths.legacy_migration_enabled()`(ソースから起動していて、環境変数が
  設定されていない)の1つにまとめ、両方の移行処理がこれを使う。
- `load_clients()` の `legacy_path` の既定値を、カレントディレクトリのファイルから「旧ファイルを
  見ない」に変える。呼び出し側(`config_mixin.load_api_clients()`)が、判定が真のときだけ
  `<repo>/fluora_pressee_api_key.json` を渡す。基準をカレントディレクトリからリポジトリ直下に変えるのは、
  設定ファイルの移行とそろえるためである。
- 旧キーのファイルは、これまでどおり移行後に削除する。鍵は秘密の情報なので、コピーを残さない。

設定ファイルのほうは、移行後に**削除しない**。古いブランチをチェックアウトしたときに、手で戻せる
ようにするためである。一方、**そのまま残すこともしない。** 2つのコピーが黙って食い違っていくのを
防ぐためである。

**パスの補正**: 従来、設定ファイル内の相対パスは、カレントディレクトリ(=設定ファイルのあるフォルダ)
を基準に解決されていた。設定ファイルを別の場所へ移すと、この基準が変わってしまう。インストール版では
カレントディレクトリがインストール先になるので、そのままではDLLが見つからなくなる。
そこで、移すときに `dll_path` と `PIcam_dll_path` を次の規則で補正する。

| 元の値 | 補正後 |
|---|---|
| 絶対パス | そのまま |
| 相対パス(例: `sdk/ShamrockCIF.dll`) | **元の設定ファイルのフォルダ**を基準に絶対パスにする。ファイルがあるかどうかは問わない(元の意味を保つため) |
| 空(`dll_path` のみ) | 元の設定ファイルのフォルダに `ShamrockCIF.dll` があれば、その絶対パスを入れる。なければ空のまま |

- 「元の設定ファイルのフォルダ」は、自動移行ではリポジトリ直下、手動の読み込み(下記)では選んだ
  ファイルのフォルダになる。**どちらも同じ関数で補正する。**
- 既存の指定をほかのDLLに差し替えることはしない。空のときに限って補う。
- 移行後は、ウィザードと Hardware Configuration で相対パスを受け付けない(保存時に絶対パスを求める)。
  フォルダ選択で入る値はもともと絶対パスなので、影響を受けるのは手入力だけである。以後、設定ファイルの
  中のパスは常に絶対パスになり、基準の曖昧さがなくなる。

ビルド版では、場所の分からない clone からの自動移行はしない。代わりに、セットアップウィザードに
「既存の spectrometerConfig.json を読み込む…」ボタンを付ける。clone が Step 1 の版に一度も
更新されていないPCへの対応である。

**Step 1 は最初のビルド版より先に master へ入れ、clone の利用者に配る。** 移行を先に済ませておけば、
ビルド版への切り替えでは何も起きない。

### 方針5: 同梱データと利用者のデータを分ける

- `app_paths.bundled_resource_path(rel)`: ビルド版では `Path(sys._MEIPASS) / rel`、ソースから起動した
  ときはリポジトリ直下 `/ rel` を返す。`calibration_ui.py:97` と `app_bootstrap.py:78` の
  `__file__` 相対の参照はこれに置き換える。
- 校正標準は、同梱分(`bundled_resource_path("calibrationStandards")`)を読んだあと、利用者分
  (`user_data_dir() / "calibrationStandards"`)を読む。キーが重複したら利用者側を優先し、その旨を
  コンソールに出す。
- 利用者がリポジトリの `calibrationStandards/` に独自ファイルを置いているかは分からない。そのため、
  移行(方針4)の対象にはしない。マニュアルに新しい置き場所を書くだけにする。

### 方針6: インストーラーがアップデーターを兼ねる(Inno Setup)

| 設定 | 値 | 理由 |
|---|---|---|
| `AppId` | 初版で生成したGUIDを**永久に固定** | 変えると別のアプリとして扱われ、2重にインストールされる |
| `PrivilegesRequired` | `lowest` | ユーザー単位でインストールし、管理者権限を不要にする。途中で変えると前の版を見つけられなくなるので固定する |
| `DefaultDirName` | `{autopf}\FluoRaPressee` | `lowest` のとき `%LOCALAPPDATA%\Programs\FluoRaPressee` になる |
| `DisableDirPage` | `auto` | 更新時はフォルダ選択の画面を飛ばす(前回の場所を使う) |
| `[InstallDelete]` | `{app}\_internal` を丸ごと削除 | 後述 |
| `AppMutex` | `Global\FluoRaPresseeRunning:<インストール先>`(後述) | 起動中の FluoRaPressée を、別のセッションのものも含めて検出し、終了するよう求める |
| `CloseApplications` | `no` | **測定中・冷却中のアプリを強制終了させない**(後述) |
| `[Languages]` | 日本語(`compiler:Languages\Japanese.isl`)と英語 | 検出のメッセージなどを日本語で出すため |
| `[Run]` | `postinstall nowait` | 完了画面に「FluoRaPressée を起動する」のチェックボックスを出す |
| アンインストール | ユーザーデータは消さない | 設定と校正カタログは装置に紐づく資産のため |

**`_internal` を丸ごと消す理由**: Inno Setup は、新しい版に含まれないファイルを消さない。一方、
PyInstaller の `_internal` の中身は、ライブラリを更新するたびに変わる。古い DLL や `*.dist-info` が
残ると、原因の分かりにくい読み込みエラーにつながる。これを安全に行えるのは、方針3で `{app}` に
ユーザーデータを置かないと決めているからである。

**起動中の FluoRaPressée の検出**: 更新は、利用者がインストーラーを手で実行して行う(方針7)。
FluoRaPressée を起動したまま実行された場合は、インストーラーが検出して終了を求める。

1. ビルド版の3つのexe(live GUI、Analysis Mode、Ocean Optics ドライバー導入用)は、どれも起動時に
   mutex を作る(Step 2)。ソースから起動した場合は作らない(方針10)。インストール先のファイルを
   使っていないためである。
2. **mutex の名前は、`Global\FluoRaPresseeRunning:` にインストール先のパスを続けたものにする。**
   `Global\` を付ける理由と、インストール先を名前に含める理由は方針13に書く。
   - 名前には `\` を使えないので、`/` に置き換える。mutex の名前は大文字と小文字を区別するので、英字
     (A〜Z)を小文字にそろえる。末尾の `\` は除く。
     例: `Global\FluoRaPresseeRunning:c:/users/lab/appdata/local/programs/fluorapressee`
   - アプリは exe のあるフォルダ(`Path(sys.executable).parent`)から、インストーラーは `{app}` から、
     同じ規則で名前を作る。規則を `runtime_env.py` と `.iss` の2カ所に書くことになるので、両者が一致する
     ことを Step 4 で確かめる。アプリは、作った名前を起動時にログに出す。
   - ハッシュにしない理由: Inno Setup の `GetSHA256OfString` は引数が AnsiString なので、日本語を含む
     パスを正しく扱えない。パスをそのまま使えば、ログで名前を見比べられる。名前の長さの上限(MAX_PATH)
     に届くほど深いインストール先は、現実には使わない。
3. mutex は `CreateMutexExW` で作る(すでにあれば開く)。要求するアクセスは `SYNCHRONIZE` だけにし、
   Authenticated Users に `SYNCHRONIZE` を許すセキュリティ記述子を付ける。ハンドルはプロセスの終了まで
   持つ。
   - ドライバー導入用exeは管理者として起動する(方針12)。既定のセキュリティ記述子のままでは、その
     mutex を管理者権限なしのインストーラーが開けず、検出できない。標準ユーザーが管理者の資格情報で
     昇格した場合は、別のユーザーとして動くので、なおさら開けない。
   - 管理者として動くプロセスが作った mutex には、高い整合性レベルが付く。ただし、既定で制限されるのは
     書き込みだけ(NO_WRITE_UP)なので、`SYNCHRONIZE` で開くことは妨げない見込みである。Step 4 で
     確かめる。
   - 3つのexeは、同じ名前の mutex を開いてハンドルを持つ。要求するアクセスが `SYNCHRONIZE` だけなら、
     ほかのユーザー(昇格したドライバー導入用exeなど)が先に作った mutex でも開ける。ハンドルが1つでも
     残っていれば mutex は消えないので、最初に起動したexeが先に終了しても、残りのexeは検出される。
   - 作ることも開くこともできなければ、ログに警告を残して起動を続ける。この mutex は更新時の確認の
     ためのもので、装置の排他には使わない(装置の排他は方針13)。
4. インストーラーは、起動直後にこの mutex を確かめる。あれば「FluoRaPressée が実行中です。
   すべて閉じてから OK を押してください。中止する場合はキャンセルを押してください」という意味の
   メッセージを出す(Inno Setup の `AppMutex` の標準の動作。日本語の文面は `Japanese.isl` のもの)。
   - OK を押すと、もう一度確かめる。まだ起動していれば、同じメッセージを繰り返す。
   - キャンセルを押すと、何も変えずに終わる。
   - 起動直後には、インストール先(`{app}`)はまだ決まっていない。そこで、`AppMutex` に scripted
     constant(`{code:...}`)で名前を渡し、その関数の中で、アンインストール情報に記録された前回の
     インストール先から名前を作る(`AppMutex` には定数を含められる)。新規インストールでは、確かめる
     相手がいない。具体的な書き方は Step 4 で確定する。この方法がうまくいかなければ、`InitializeSetup`
     で `CheckForMutexes` を使って同じことをする。
   - アンインストーラーも、起動時に `AppMutex` で同じ確認をする(Inno Setup の標準の動作)。
5. ウィザードの途中で FluoRaPressée が起動される場合に備え、ファイルをコピーする直前にもう一度確かめる。
   `[Code]` の `PrepareToInstall` で、確定した `{app}` から名前を作って `CheckForMutexes` を呼び、
   起動していればメッセージを返してインストールを止める。

**いつ終了するかは利用者が判断する。** インストーラーは FluoRaPressée を終了させない。利用者が自分で
FluoRaPressée を閉じれば、測定中なら FluoRaPressée 自身の終了確認(`closeEvent`)が出るので、そこで
判断できる。なお、起動したまま上書きすることはそもそもできない(Windows は実行中のexe/DLLを上書き
できない)ので、終了してもらう以外の選択肢はない。

**`CloseApplications=no` にする理由**: 既定の設定では、Inno Setup が Windows の Restart Manager を
使って、ファイルを使っているアプリを閉じようとする。その場合、FluoRaPressée の終了確認を通らずに
閉じられるおそれがあり、測定や冷却の途中で止まる危険がある。上の `AppMutex` で検出できるので、
Restart Manager は使わない。

**ダウングレードは防がない。** 新しい版で実験装置が動かなくなったとき、古いインストーラーを実行して
戻せることには実用上の価値がある。更新の通知は、新しい版しか提示しない。古い版に戻したときに、
新しい版が作ったデータを壊さないための対策は、方針14に書く。

### 方針7: アプリは更新を知らせて配布ページへ案内するだけにし、インストールは利用者が行う

- **起動時の自動確認**
  - ウィンドウを表示したあと、バックグラウンドのスレッドで行う。カメラの初期化は待たせない。
  - 24時間に1回まで(最終確認時刻は local cache に保存)。
  - 失敗しても何も表示しない(ネットにつながらない実験PCを想定)。
  - 新しい版があれば、Help メニューに「Update available: v0.1.0b2」の項目を出すだけにする。
    **モーダルのダイアログは出さない**(実験の開始直後に割り込まないため)。
- **手動の確認**: Help → Check for Updates…。こちらは失敗したら理由を表示する。
- **ベータ版を含めるか**: 既定は「現在の版がプレリリースなら含める」。ベータ版の利用者は次のベータ版
  を受け取りたいはずだからである。local cache の `update_include_prerelease` で上書きできる。
- **更新のダイアログ**(`src/ui/menu/update_dialog.py`。live GUI と Analysis Mode の両方から使う)
  - 表示する内容: 現在の版、最新版、リリースノート(`QTextBrowser.setMarkdown`)。
  - ビルド版では、次の2つのボタンを出す。どちらもブラウザでURLを開くだけ(`QDesktopServices.openUrl`)。
    - 「インストーラーをダウンロード」: インストーラーのファイル(`browser_download_url`)を開く。
    - 「リリースページを開く」: そのリリースのページ(`html_url`)を開く。
  - ダウンロード用のボタンを別に用意する理由: GitHub は、リリースページに「Source code (zip)」を
    自動で添付する。リリースページだけを案内すると、利用者が誤ってそちらを落とすおそれがある。
  - ダイアログには「FluoRaPressée を終了してから、ダウンロードしたインストーラーを実行してください。
    起動したまま実行すると、インストーラーが終了を求めます」と書いておく(方針6)。
  - ソースから起動しているときは、ボタンの代わりに「git pull してください」と案内する。
- **アプリがしないこと**: インストーラーのダウンロード、インストーラーの起動、自分の終了。いつ更新するか
  (測定中でないか、など)は利用者が判断する。そのため、装置の空きを確かめる処理、ゲートの確保、
  終了処理への組み込みは要らない。live GUI と Analysis Mode で処理を分ける必要もない。
- **GitHub API**: 認証なしでは同じIPから1時間60回までに制限される。研究室内のPCが同じグローバルIPを
  共有していても、24時間に1回なら問題にならない。User-Agent は汎用の名前(`FluoRaPressee-Updater`)
  にし、利用者の情報は送らない。

**当初の案(アプリ内からのダウンロードとインストール)をやめた理由**(2026-11-21 方針変更):
構成を簡単にするためである。当初の案では、次の処理が必要だった(レビュー第1回でも、この部分に指摘が
集中した)。

- ダウンロードの間に始まった測定やAPIの要求を締め出すための、ゲートの確保
- 終了処理への組み込みと、終了が取りやめになったときの後片付け
- Analysis Mode の終了処理
- 同じインストール先のほかのプロセスの検出

代わりに、更新のたびに SmartScreen の警告が出る(方針8)。当初の案の設計は、git の履歴の改訂版
(レビュー第1回の反映版)に残っている。

### 方針8: コード署名なしで配布する(影響と対策)

- インストーラーは、利用者がブラウザで GitHub から HTTPS でダウンロードする。アプリはダウンロードした
  ファイルを照合しないので、チェックサムのファイルは添付しない。
- 署名のないファイルは、SmartScreen の信頼度がファイルごとに判定される。そのため、**新しい版を
  ダウンロードして実行するたびに警告が出る。** 2026-11-21 に、これを許容すると決めた。
  - 実行するとき: 「Windows によって PC が保護されました」→「詳細情報」→「実行」。
  - ブラウザによっては、ダウンロードの時点でも「一般的にダウンロードされていません」などの警告が出て、
    保存を選び直す必要がある。
  - マニュアル(Step 9)に、この手順を画面写真付きで書く。
- 大学の管理下にあるPCでは、ポリシーにより「実行」ボタン自体が出ないことがある。そういうPCが
  出てきたら、署名を検討し直す(「オープンな課題」2)。
- 署名の代わりに、無料でできる対策として次を行う。
  - リポジトリの所有者アカウントで2段階認証を有効にする。
  - `v*` タグの保護ルールで、リリースを作れる人を限定する。

### 方針9: ビルド版の標準出力は、起動ごとに別のログファイルに送る

- ビルド版はウィンドウ版(コンソールなし)にする。
- `app_bootstrap.setup_stdio(kind)` を新設し、`main.py` と `analysis_main.py` の `reconfigure` の2行を
  置き換える。`kind` は `live` か `analysis`。
  - `sys.stdout` が `None` なら、**このプロセス専用の**ログファイルを開いて、`stdout` と `stderr` の
    両方に割り当てる。名前は `logs/app-<kind>-<YYYYMMDD-HHMMSS>-<PID>.log`(例:
    `app-live-20261121-093015-12345.log`)。UTF-8、`errors="replace"`、行単位のバッファで開く。異常終了
    しても、直前までの出力が残るようにするためである。
  - `None` でなければ、従来どおり `reconfigure(errors="replace")` だけを行う。
- **共通の `app.log` を起動時に順送り(改名)する案は採らない。** live GUI と Analysis Mode は同時に
  起動してよい(方針13)。live GUI がログを開いている間に Analysis Mode を起動すると、使用中の
  `app.log` を改名しようとする。Windows では、ほかのプロセスが開いているファイルを改名できないので、
  この改名は失敗する。起動ごとにファイルを分ければ、改名そのものが要らない。
- 古いログの整理: 起動時に、`app-*.log` のうち30日より古いものを消す。新しい順に数えて100個を超えた
  分も消す。自分のファイルは消さない。
- **ログの作成や整理に失敗しても、起動は続ける。**
  - 整理: ファイルごとに `OSError` を無視する。ほかのプロセスが開いているファイルは、Windows では
    消せないので、次回以降の起動に回る。
  - 作成: フォルダやファイルを作れなければ、`stdout` と `stderr` を、書き込んだ内容を捨てる出力先
    (`os.devnull`。それも開けなければ、書き込みを無視するだけのオブジェクト)にする。`print()` や、
    `sys.stdout.write()` を直接呼ぶライブラリが落ちないようにするためである。
- `sys.excepthook` を設定し、捕まえられなかった例外をログに残す。
- Help → Open Log Folder を追加する(`configuration_manager_dialog.py:374` と同じ
  `QDesktopServices.openUrl` を使う)。Help → About には、このプロセスのログファイル名を出す。
  問い合わせを受けたときに、どのファイルを送ってもらえばよいか分かるようにするためである。
- ソースから起動したときの動作は変えない(コンソールに出る)。
- 既存の `logs/instrument_state.log`(`RotatingFileHandler`)は live GUI だけが開く。今回は、場所を
  `app_paths.logs_dir()` から取るように変えるだけにする。作成に失敗しても起動を止めない作りは、
  すでにある(`src/core/instrument_state_log.py:23-25`)。開発時に `--debug` の live GUI を2つ起動すると、
  順送りの改名が失敗しうる。その失敗は `logging` の内部で処理され(`handleError`)、その間の記録が
  失われるだけで、起動にも測定にも影響しない。

### 方針10: 開発環境は変えない

- `python main.py [--debug]`、既存の `.bat`/`.sh`、`setup.bat` はそのまま使える。
  `requirements.txt` に増えるのは `packaging` だけ。
- PyInstaller は `requirements-build.txt` に分ける。`setup.bat` ではインストールしない。
- ビルド手順は `packaging/build_windows.ps1` の1本にまとめ、CIもこのスクリプトを呼ぶだけにする。
  手元とCIでビルド手順がずれないようにするため。`scripts/` は `.gitignore` の対象なので使わない。
- `.gitignore` に `/build/`、`/dist/`、`/packaging/Output/`、`src/_build_info.py` を追加する。
- macOS の開発用PCでは Windows 版をビルドできない(PyInstaller は別OS向けにビルドできない)。
- **自動テストの実行と、アプリを起動しての確認は Windows で行う。** macOS では、テストもアプリの起動
  (`--debug` を含む)も行わず、コードと差分のレビューで確かめる(AGENTS.md の規定)。
- 「起動中」の目印(mutex)は**ビルド版でだけ**作る。ソースから起動しているときにインストーラーを
  止めないため。

### 方針11: ビルドは1種類にし、すべてのバックエンドを含める

- Andor / Princeton Instruments / Ocean Optics をすべて含める(`seabreeze` も含める)。
  インストーラーは1本で、どの装置を使うかは従来どおり `spectrometerConfig.json` の `model` で決まる。
- 装置メーカーの SDK・ランタイム(Andor SDK、PICam Runtime、`ShamrockCIF.dll`)は同梱しない
  (各社のライセンスのため)。利用者が従来どおりインストールし、`dll_path` などで場所を指定する。

### 方針12: Ocean Optics のドライバーは、同じインストーラーに入れた専用のexeで導入する

- 3つ目のexe `FluoRaPressee-OceanOpticsDriver.exe` を、他の2つと同じ `_internal` を使う形でビルドする。
  - 中身は `setup_oceanoptics.bat` の後半と同じ。seabreeze のドライバー導入処理を実行したあと、
    `list_devices()` で装置が見えるかを確かめる。
  - 進行状況が見えるように、このexeだけはコンソール版にする。
- 起動できる場所は次の3つ。

  | 場所 | 想定する人 |
  |---|---|
  | インストーラーの任意項目(`[Tasks]`、既定はオフ) | 最初から Ocean Optics を使うと分かっている人 |
  | セットアップウィザードと Hardware Configuration で Ocean Optics を選んだときに出るボタン | 後から Ocean Optics をつないだ人 |
  | スタートメニュー | 装置を付け替えたときなどに、もう一度導入したい人 |

- ドライバーの導入には管理者権限が必要なので、**どこから起動する場合も、このexeだけを管理者として
  起動する**(UAC の確認が出る)。本体はユーザー単位・管理者権限なしでインストールする方針を変えない。
  - インストーラーからは、`[Run]` に `Verb: runas` と `Flags: shellexec waituntilterminated` を付けて
    起動する。
  - アプリからは `ShellExecuteW(None, "runas", ...)` で起動する。ソース版では、代わりに
    `setup_oceanoptics.bat` を案内する。
- **更新のときは、この任意項目を表示しない。** Inno Setup は前回選んだ任意項目を覚えていて、更新の
  ときも印が付いた状態で表示する。そのままだと、更新のたびにドライバーの導入と UAC の確認が繰り返される。
  前の版がインストールされているか(アンインストール情報があるか)を `[Code]` の関数で判定し、`[Tasks]`
  の `Check:` に使う。導入し直したい人は、スタートメニューから実行する。

**Ocean Optics 用の別インストーラーは作らない。** 作ると、本体と Ocean Optics 版の2系統の更新を
管理することになり、利用者がどちらを入れたかで更新の扱いも変わってしまう。ドライバーの導入は1度
きりの作業なので、本体と同じインストーラーに入れておき、必要な人だけが実行する形で足りる。

### 方針13: 同じPCでの複数起動 — 一度に1つだけ起動する運用で、衝突を起こさない

想定しているのは、Windows の開発用PCが実験用PCを兼ねていて、ソース版とインストールした版の両方が
ある場合である。ユーザーデータは両者で共有する(方針3)。

**装置を使う live GUI は、PC全体で1つしか起動できないようにする。**

- ソース版かインストールした版かを問わず、ハードウェアモード(`--debug` なし)の live GUI は、起動時に
  名前付き mutex `Global\FluoRaPresseeInstrument` を作る。
- **名前には `Global\` を付ける。** 付けない名前は、ログオンセッションごとの名前空間に作られる。すると、
  別のユーザーやリモートデスクトップの別セッションからは見えず、同じ装置を開けてしまう(Microsoft の
  Kernel Object Namespaces の仕様)。装置はPCに1台なので、PC全体で排他する必要がある。なお、
  ファイルマッピングと違い、mutex を `Global\` に作るのに特別な権限は要らない。
- `CreateMutexW(None, False, name)` の結果は、下の表のように扱う。`GetLastError()` を確実に取るため、
  `ctypes.WinDLL("kernel32", use_last_error=True)` と `ctypes.get_last_error()` を使う。

| 結果 | 意味 | 動作 |
|---|---|---|
| ハンドルが返り、エラーなし | 自分が最初 | ハンドルをプロセスの終了まで持ち続ける |
| ハンドルが返り、`ERROR_ALREADY_EXISTS`(183) | 同じユーザーの別のプロセス(別セッションを含む)が使用中 | ハンドルを閉じ、「別の FluoRaPressée が装置を使用中です」と表示して終了する |
| NULL、`ERROR_ACCESS_DENIED`(5) | 別のユーザーが作った mutex がある(既定のアクセス権では、作ったユーザーしか開けない) | 「別のユーザーが装置を使用中です」と表示して終了する |
| NULL、それ以外のエラー | 排他を確認できない | ログに警告を残し、起動を続ける |

- アクセス権は既定のままにする(独自のセキュリティ記述子は付けない)。別のユーザーが開けなくても、
  `ERROR_ACCESS_DENIED` で使用中だと分かるので、開けるようにする必要はない。
- 確認できないときに起動を止めない理由: この mutex は、分かりやすいメッセージを出すための補助である。
  装置そのものも、二重に開こうとすれば各社のSDKやシリアルポートが拒否する。原因の分からない失敗で
  装置を一切使えなくするほうが、実害が大きい。
- インストーラー用の mutex(方針6。ビルド版でだけ作る)は、これとは別のものである。こちらは
  **インストール先ごと**に区別する。
  - **こちらにも `Global\` を付ける。** 同じユーザーが別のセッション(リモートデスクトップなど)で起動
    した FluoRaPressée も、同じインストール先のファイルを使っている。セッションごとの名前空間に作ると、
    インストーラーからはそのプロセスが見えず、使用中の `_internal` の削除(方針6の `[InstallDelete]`)に
    進んでしまう。
  - **名前にインストール先を含める。** 別のユーザーは別のインストール先を使うので名前が異なり、互いの
    更新を止めない。ソースから起動したものや、`dist\` から直接起動したものも、インストール先が違うので
    止めない(方針10)。
- `--debug` と Analysis Mode は制限しない。装置を使わないためである。ただし、`--debug` で2つ起動し、
  両方でAPIを有効にした場合のポートの衝突は、開発者が自分で避ける。
- Windows 以外では装置を制御しないので、この mutex は作らない。

**`local_cache.json` の読み書きは、プロセス間のロックで守る。**

- live GUI と Analysis Mode は同時に起動してよく、`--debug` の live GUI も複数起動できる。そのどれもが、
  このファイルに書き込む。
- 現在の `save_local_cache()` は「読み込み → キーを変更 → 書き込み」の順に処理する。2つのプロセスが
  同じ古い内容を読むと、後から保存した側が、先に保存された変更を消してしまう。atomic に置き換える
  だけでは、この消失は防げない。
- そこで、ロック用のファイル `local_cache.json.lock` に排他ロックを取り、**読み込みから置き換えまでを
  1つのロックの中で行う。** ロックは、Windows では `msvcrt.locking`、それ以外では `fcntl.flock` で取る。
  書き込みは、一時ファイルに書いてから `os.replace` で置き換える(atomic)。
- **`load_local_cache()` でもロックを取る。** Windows では、ほかのプロセスが開いているファイルを
  `os.replace` で置き換えられず、`PermissionError` になるためである。
- ロックが取れなければ、数秒で諦める。キャッシュは失われても困らないデータなので、待ち続けてGUIを
  止めることはしない。読み込みは、諦めたらロックなしで読む。保存は、諦めたら警告を出して保存しない。
- 保存先をプロセスごとに分ける案は採らない。`--debug` の live GUI は複数起動できるので、分けても
  live GUI 同士の衝突が残る。
- 構成カタログ(SQLite)は、自前で排他を持っている。`api_clients.json` を書き換えるのは live GUI の
  管理ダイアログだけで、ハードウェアモードの live GUI は1つしか起動しないので、今回の対象にしない。
- **交互に使うときの注意**: 開発中のソース版は、インストールした版より新しいことがある。ソース版が
  データの形式を新しくしたあとで、インストールした版を起動すると、そのデータは方針14により拒否されて
  使えなくなる(壊れはしない)。データ形式に関わる変更を試すときは、`FLUORAPRESSEE_DATA_DIR` で場所を
  分ける。

### 方針14: 知らない版のデータ形式は、変更せずに拒否する(b1 から)

**`v0.1.0b1` に必ず入れる。** 公開した版の読み込み処理は、後から直せない。一方、ダウングレードを
許し(方針6)、開発用PCではソース版(新しい)とインストールした版(古い)を交互に使うこともある
(方針13)。そのため、将来の版が作ったデータを b1 が読む場面は必ず来る。そのとき b1 が新しい形式を
古い形式として編集・保存すると、新しい版に戻してもデータは壊れたままになる。

| データ | 版の記録 | 現状(「現状」14) | 変更 |
|---|---|---|---|
| 構成カタログ(`catalog.sqlite3`) | `catalog_meta` の `schema_version`(現在3) | 新しい版でも処理を続ける。版を見る前に、WAL への切り替え、`CREATE TABLE IF NOT EXISTS`、`INSERT OR IGNORE` も実行する | **何かを書き込む前に**版を確かめ、新しければ専用の例外を出す。PRAGMA の設定を含めて、ファイルに一切書き込まない。チェックポイントされていない WAL に残った版も読む。初期化は1つのトランザクションにする |
| 構成レコード(JSON) | `schema_version`(現在2) | 新しい版の読み込みを拒否する | 変えない。テストで固定する |
| `api_clients.json` | `version`(現在2) | 版を見ない。`clients` がなければ新規インストールとみなし、新しい鍵を作って上書き保存する。各クライアントの未知のキーを捨てる | ほかの判定より先に版を確かめ、新しければ専用の例外を出す。保存も鍵の生成もしない。書き戻すときは未知のキーを残す |
| `spectrometerConfig.json`、`local_cache.json` | なし | 読み込んだ辞書をそのまま書き戻すので、未知のキーは残る | 変えない。未知のキーが残ることをテストで固定する |

- 版の値が整数として読めないときも、知らない版として扱う。作り直しはしない。
- **拒否しても、起動は止めない。** そのデータを使う機能だけを止め、理由を表示する。文面は「このデータは
  新しい版の FluoRaPressée で作られています(形式の版: 4。この版が扱えるのは 3 まで)。新しい版を
  使ってください」という意味のものにする。
  - 構成カタログ: `main_window.py:225` で例外を捕まえ、カタログなしの状態で起動する。Load
    Configuration、校正の保存、APIの `/configurations` と `configuration_id` を指定した取得は、理由を
    付けてエラーにする。
  - `api_clients.json`: API サーバーを起動しない(保存されている `api_mode` は変えない)。クライアント
    管理のダイアログは開かない。ウィンドウを作るときの読み込み(API が off でも行う)でも例外を捕まえる。
- 読めないファイル(JSONとして壊れているなど)の扱いは、今回は変えない。現状では、読めない
  `api_clients.json` は新規インストールとみなされ、新しい鍵で上書きされる。

**将来、スキーマを変えるときの決まり**: 版を上げるのは、古い版が読むと壊れる変更のときだけにする。
版を上げると、それより古い版はそのデータを一切使えなくなるためである。古い版が無視しても困らない追加
(キーの追加や、既定値のある列の追加)では、版を上げない。

- その備えとして、b1 で `api_clients.json` の未知のキーを残すようにする(上の表)。
- 構成レコードは、一度書いたら変えないので、この備えは要らない。
- カタログの `INSERT` は列名を明示しているので(`configuration_catalog.py:439` など)、既定値のある列を
  追加しても、古い版の書き込みは壊れない。

## 対象ファイル

新規作成:

| ファイル | 内容 |
|---|---|
| `src/version.py` | `__version__` |
| `src/core/runtime_env.py` | 実行形態の判定、表示用バージョン文字列、mutex |
| `src/core/app_paths.py` | ユーザーデータ・同梱データの場所、旧い場所からの移行 |
| `src/core/update_check.py` | Releases の取得と更新対象の選択(Qtに依存しない) |
| `src/ui/menu/about_dialog.py` | Help → About |
| `src/ui/menu/update_dialog.py` | Help → Check for Updates…(live と Analysis の両方から使う) |
| `packaging/FluoRaPressee.spec` | PyInstaller の設定 |
| `packaging/FluoRaPressee.iss` | Inno Setup のスクリプト |
| `packaging/oceanoptics_driver.py` | Ocean Optics ドライバー導入用exeの入口(方針12) |
| `packaging/build_windows.ps1` | ビルド手順(CIと手元で共通) |
| `requirements-build.txt` | PyInstaller(バージョン固定) |
| `.github/workflows/release.yml` | タグをpushしたらビルドしてReleaseの下書きを作る |
| `tests/test_runtime_env.py`, `tests/test_app_paths.py`, `tests/test_update_check.py` | 単体テスト |

変更:

| ファイル | 変更内容 |
|---|---|
| `main.py`, `analysis_main.py` | `setup_stdio()`、移行、mutex、`--smoke-test` |
| `src/app_bootstrap.py` | 上記の実装、起動時表示へのバージョン追加、ロゴの場所、ウィザードの設定ファイルの場所 |
| `src/ui/local_cache.py` | 場所を `app_paths` から取る(呼び出しのたびに評価する)。プロセス間ロックと atomic な書き込み(方針13) |
| `src/ui/ui_mixins/config_mixin.py`, `src/ui/ui_mixins/api_mixin.py`, `src/hardware/spectrometer_andor.py` | `spectrometerConfig.json` の場所。`config_mixin.py` は旧APIキーの移行の条件(方針4)と、`api_clients.json` を拒否したときの扱い(方針14)も。`api_mixin.py` は、そのときに API サーバーを起動しない処理(方針14)も |
| `src/api/info_helpers.py` | 表示用ラベル |
| `src/core/configuration_catalog.py`, `src/core/api_clients.py` | ベースパスを `app_paths` に任せる。知らない版の拒否(方針14)。`api_clients.py` は、旧キーの読み込み先の既定値の変更(方針4)と、未知のキーの保持(方針14)も |
| `src/core/instrument_state_log.py` | ログの場所を `app_paths.logs_dir()` から取る(方針9) |
| `src/ui/calibration_ui.py` | 同梱分と利用者分の校正標準 |
| `src/ui/config_wizard.py` | 「既存の spectrometerConfig.json を読み込む…」、Ocean Optics ドライバー導入のボタン |
| `src/ui/menu/hardware_config_dialog.py` | Ocean Optics ドライバー導入のボタン |
| `src/ui/main_window.py` | Help メニュー。構成カタログを拒否したときに、カタログなしで起動する(方針14) |
| `src/ui/analysis_ui.py` | Help メニュー(メニューバーの新設) |
| `src/core/measurement_metadata.py`, `src/core/file_io.py`, `src/api/` | バージョンの記録(Step 8) |
| `tests/test_local_cache.py` | `os.chdir` ではなく環境変数で場所を差し替える |
| `tests/test_api_clients.py`, `tests/test_api_client_persistence.py`, `tests/test_configuration_catalog.py` | 旧APIキーの移行の条件(方針4)、知らない版の拒否と未知のキーの保持(方針14)のテスト |
| `.gitignore`, `requirements.txt` | 方針10、`packaging` |
| `docs-site/docs/`, `README.md`, `README_ja.md`, `CLAUDE.md` | Step 9 |

## ステップ間の依存関係

```
Step 0 版・実行形態 ─┬─ Step 1 パス・移行・版の検査 ── Step 2 起動処理 ── Step 3 PyInstaller ── Step 4 Inno Setup ── Step 5 CI
                    ├─ Step 6 更新の通知
                    └─ Step 8 保存データ・APIへの記録
Step 7: 削除(方針7)
Step 9 ドキュメント: 各ステップと並行して進める
```

リリースとの関係:

- **Step 0 と Step 1 は、最初のビルド版より先に master へ入れ、clone の利用者に `git pull` してもらう**
  (方針4)。
- `v0.1.0b1` には **Step 0〜6 が必須**。知らない版のデータ形式の拒否(方針14)は Step 1 に含む。
- Step 8 は任意だが、保存データの再現性のために b1 に入れることを推奨する。

## 各ステップ共通の検証手順

**以下はすべて Windows の開発用PCで行う。** macOS では、テストの実行もアプリの起動(`--debug` を含む)
も行わず、コードと差分のレビューで確かめる(AGENTS.md の規定)。

1. `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v`
2. `python main.py --debug` で該当する操作を確かめる。
3. Step 2 以降でビルドに関わる変更をした場合は、`packaging/build_windows.ps1` でビルドする。
   `FLUORAPRESSEE_DATA_DIR` を一時フォルダに設定してから、`dist\FluoRaPressee\FluoRaPressee.exe --debug`
   を起動して確かめる。

## Step 0: バージョン番号と実行形態の判定

作業:

- `src/version.py` を作り、`__version__ = "0.1.0b1"` とする。
- `src/core/runtime_env.py`:
  - `is_frozen()`、`runtime_kind()`(`"source"` / `"frozen"`)、`app_dir()`
  - `display_version()`: ソースのとき `+dev.g<hash>`、ビルド版のときは `_build_info` の内容を付ける。
- `print_software_and_author_info()` に、バージョンと実行形態を表示する行を追加する。
- `requirements.txt` に `packaging` を追加する。

テスト(`tests/test_runtime_env.py`):

- `sys.frozen` を差し替え、2種類の判定がそれぞれ正しく返ること。
- git が使えない環境でも `display_version()` が例外を出さないこと。

完了条件: 起動時の表示にバージョンが出る。Qtに依存しない。

## Step 1: パスの一元化、ユーザーデータの移行、データ形式の版の検査

作業:

- `src/core/app_paths.py`: `user_data_dir()`、`spectrometer_config_path()`、`local_cache_path()`、
  `user_calibration_standards_dir()`、`logs_dir()`、`bundled_resource_path()`、
  `migrate_legacy_user_files(repo_root, data_dir)`。
  - **すべて呼び出しのたびに評価する。** import 時に固定すると、環境変数やテストでの差し替えが
    効かなくなる。
- 「現状」3〜5に挙げた参照を、すべて `app_paths` 経由に置き換える。
- `main.py` と `analysis_main.py` の両方で、何かが設定を読む前に移行を呼ぶ。移行は何度呼んでも
  同じ結果になるように作る。Analysis Mode も `local_cache.json` を読むため、両方で呼ぶ。
  環境変数 `FLUORAPRESSEE_DATA_DIR` が設定されていれば、移行しない(方針4)。
- 移行するかどうかの判定を `app_paths.legacy_migration_enabled()` にまとめ、旧APIキーの移行にも使う
  (方針4)。`load_clients()` の `legacy_path` の既定値を「旧ファイルを見ない」に変え、
  `config_mixin.load_api_clients()` は判定が真のときだけ `<repo>/fluora_pressee_api_key.json` を渡す。
- 校正標準を同梱分と利用者分の両方から読む(方針5)。
- セットアップウィザードに「既存の spectrometerConfig.json を読み込む…」を追加する。JSONとして
  読めることを確かめ、パスの補正(方針4)を自動移行と同じ関数で行う。基準は、選んだファイルのフォルダ。
- ウィザードと Hardware Configuration で、`dll_path` と `PIcam_dll_path` の相対パスを受け付けない
  ようにする(方針4)。
- `ShamrockCIF.dll` を相対パスで読もうとして失敗したときは、Hardware Configuration で `dll_path` を
  設定するよう案内するメッセージを出す。
- 知らない版のデータ形式を拒否する(方針14)。
  - `ConfigurationCatalog`: 初期化の最初、WAL への切り替えやテーブルの作成より前に `schema_version` を
    読み、新しければ専用の例外を出す。`main_window.py` はこの例外を捕まえ、カタログを使う機能を止めて
    起動を続ける。
  - `load_clients()`: ほかの判定より先に `version` を確かめ、新しければ専用の例外を出す。呼び出し側は
    保存も鍵の生成もせず、API サーバーを起動しない。
  - `save_clients()`: 未知のキー(ファイル全体と各クライアント)を残して書き戻す。

テスト(`tests/test_app_paths.py` と `tests/test_local_cache.py` の修正):

- 環境変数で場所が変わること。
- OS別のベースパスが正しいこと。
- 移行で、コピーと改名が行われること。
- 新しい場所にすでにファイルがあれば、上書きしないこと。
- **環境変数が設定されているときは、移行しないこと。** 旧ファイルがあっても新しい場所は空のままで、
  旧ファイルも改名されないこと。
- パスの補正が方針4の表のとおりに行われること。
  - 絶対パスはそのまま。
  - 相対パス(`sdk/ShamrockCIF.dll` など)は、元の設定ファイルのフォルダを基準に絶対パスになる。
    直下に `ShamrockCIF.dll` があっても、それに差し替えられない。
  - 空のときだけ、直下の `ShamrockCIF.dll` で補われる。直下になければ空のまま。
  - 手動の読み込みでも、選んだファイルのフォルダを基準に同じ結果になる。
- 移行を2回呼んでも結果が変わらないこと。
- 旧APIキー:
  - 環境変数を設定した状態で `load_api_clients()` を呼ぶと、リポジトリ直下に置いた旧キーのファイルが
    内容も含めてそのまま残り、一時フォルダの `api_clients.json` には旧キーと異なる新しい鍵が作られる
    こと。
  - `load_clients()` を `legacy_path` なしで呼ぶと、カレントディレクトリの旧キーのファイルを読まない
    こと。
  - 移行する側(旧キーが引き継がれ、旧ファイルが削除される)は、判定関数と `user_data_dir()` を
    差し替えて確かめる。環境変数を外すと、実際のユーザーデータの場所を使ってしまうためである。
- 知らない版:
  - `schema_version` を1つ上げたカタログを開くと専用の例外になり、データベースのファイルの内容が
    変わらず、`-wal` などのファイルも作られないこと。
  - 新しい `schema_version` の構成レコードの読み込みが拒否されること(現状の動作の固定)。
  - `version` を1つ上げた `api_clients.json` と、`version` が整数でない `api_clients.json` を読み込むと
    拒否され、ファイルが変わらず、`load_api_clients()` が保存しないこと。
  - `api_clients.json`、`spectrometerConfig.json`、`local_cache.json` で、知らないキーが書き戻したあとも
    残ること。

完了条件:

- リポジトリ直下に設定ファイルがある clone で起動すると、設定が移行され、ウィザードは出ず、すべての
  機能が従来どおり動く。
- `FLUORAPRESSEE_DATA_DIR` に空のフォルダを指定して起動すると、ウィザードが出る。リポジトリ直下の
  設定ファイルと旧APIキーのファイルは、そのまま残る。
- `schema_version` を上げたカタログがあっても起動でき、カタログを使う操作だけが理由付きのエラーになる。

## Step 2: ビルド版向けの起動処理

作業:

- `setup_stdio()` と `sys.excepthook` を設定する(方針9。起動ごとのログファイル、古いログの整理、
  失敗しても起動を続けること)。
- インストーラー用の mutex: ビルド版でだけ、3つのexe(live GUI、Analysis Mode、Ocean Optics
  ドライバー導入用)のすべてで作る(どれもインストール先のファイルを使っているため)。名前の規則と、
  `CreateMutexExW` での作り方は方針6のとおり。名前は `.iss` と同じ規則で作り、ログに出す。
- 装置用の mutex `Global\FluoRaPresseeInstrument`(ソース版・ビルド版の両方。ハードウェアモードの
  live GUI だけが作る)。`CreateMutexW` の結果の扱いは方針13の表のとおり。
- `local_cache.json` の読み書きを、プロセス間ロックと atomic な書き込みで守る(方針13)。
- `--smoke-test` フラグを追加する。
  - 各バックエンドのモジュール(andor / princeton / oceanoptics と `seabreeze` 本体)、
    `src.api.server.create_app`、Analysis Mode の import までを行い、ハードウェアには触れずに
    終了コード 0/1 で終わる。結果はログに書く。
  - ソースから起動したときも動くので、ビルド前の確認にも使える。
- Help → Open Log Folder を追加する。

テスト:

- `sys.stdout` を `None` にした状態で、`setup_stdio()` がこのプロセス専用のファイルに書き込むこと。
  PID を差し替えて2回呼ぶと、別々のファイルになること。
- ログのフォルダを作れない状態(同じ名前のファイルを置く)でも例外を出さず、そのあとの `print()` と
  `sys.stdout.write()` が落ちないこと。
- 整理で、30日より古いファイルと100個を超えた分が消え、自分のファイルは残ること。削除が
  `PermissionError` になっても、起動が続くこと。
- `--smoke-test` をソースから起動すると 0 を返すこと。
- 装置用の mutex について、`CreateMutexW` と `get_last_error` を差し替え、方針13の表の4通りの結果で
  それぞれ正しく動くこと。
  - 使用中と判定された場合(183 と 5)は、ハードウェアモードの起動が拒否されること。
  - `--debug` の起動は、どの場合も拒否されないこと。
- インストーラー用の mutex:
  - 大文字を含むパス、末尾に `\` があるパス、日本語を含むパスから、方針6の規則どおりの名前ができる
    こと。同じパスを Step 4 の確認にも使う。
  - `CreateMutexExW` が NULL を返しても、起動が続くこと。
- `local_cache.json` について:
  - **2つのプロセスがそれぞれ別のキーを50回ずつ保存しても、両方のキーがすべて残っていること**
    (`multiprocessing` で確かめる)。
  - 書き込みの途中で例外が起きても、元のファイルが壊れずに残ること。
  - ロックが取れないときに、読み込みと保存が数秒で諦めること。

## Step 3: PyInstaller でビルドする

作業:

- `requirements-build.txt`: `pyinstaller==<固定するバージョン>`
- `packaging/FluoRaPressee.spec`:
  - 3つのexe(`FluoRaPressee.exe`、`FluoRaPressee-Analysis.exe`、
    `FluoRaPressee-OceanOpticsDriver.exe`)を、同じ `_internal` に出力する。MERGE が必要かどうかなど、
    具体的な書き方はこのステップで確定する。
  - ウィンドウ版にする(ドライバー導入用のexeだけはコンソール版)。アイコンは `logo/app_icon.ico`。
  - 同梱データ: `calibrationStandards/`、`logo/`。
  - `hiddenimports`: uvicorn のサブモジュール、pylablib の各デバイス、seabreeze のバックエンド、
    pythonnet / `clr_loader`。過不足は `--smoke-test` で確認する。
  - `excludes`: PyQt5 / PySide2 / PySide6 / tkinter など。`pylablib_loader.py` の方針に合わせ、
    PyQt6 以外のQtを含めない。
- `packaging/build_windows.ps1`:
  1. `_build_info.py` を生成する。
  2. ソースで `--smoke-test` を実行する。
  3. PyInstaller でビルドする。
  4. ビルドしたexeで `--smoke-test` を実行する(`Start-Process -Wait -PassThru` で終了コードを確認)。

**実機での確認項目**(最大の不確定要素。結果は末尾の「実施ログ」に記録する):

| 項目 | 確認すること |
|---|---|
| numba / llvmlite | pylablib の import 時に読み込めるか。配布サイズへの影響 |
| Andor | pylablib が Andor SDK のDLLを見つけられるか。Shamrock を `dll_path` で読めるか |
| Princeton Instruments | PICam Runtime。pythonnet(`src/hardware/princeton_calibration.py:74`)と .NET ランタイム |
| Ocean Optics | seabreeze の cseabreeze バックエンドと libusb のDLL |
| Ocean Optics ドライバー導入用exe | seabreeze のドライバー導入処理が Windows で何をするか(ドライバーの入手元、ネット接続が必要か)。管理者として起動したあと、装置が見えるようになるか |
| API | GUIから uvicorn を起動し、別のPCから呼べるか |
| Analysis Mode | 単独のexeで起動し、解析・保存ができるか |
| ログ | live のexeを起動したまま Analysis のexeを起動して、両方が起動し、別々のログファイルに書き込まれるか。逆の順でも同じか |
| 表示 | `QT_OPENGL=software` と pyqtgraph |
| ウイルス対策ソフト | Windows Defender に誤検知されないか。署名なしなので起きやすい。誤検知されたら Microsoft の誤検知報告フォームに提出する。繰り返すようなら、PyInstaller のブートローダーを自分でビルドし直す(既製のブートローダーは誤検知されやすい) |

完了条件: Andor / PI / Ocean Optics の各実機で、`dist\` のexeから測定・校正・保存・APIが動く。

## Step 4: Inno Setup のインストーラー

作業:

- `packaging/FluoRaPressee.iss` を方針6のとおりに作る。バージョンはビルドスクリプトから
  `/DAppVersion=...` で渡す。
- `AppId` のGUIDを生成し、**この文書に記録する**: `AppId = {4ED49E72-6F8E-44EE-9A9D-E895C5F872E4}`(2026-11-21 生成。永久に変えない)
- スタートメニューに次を登録する。デスクトップのアイコンは任意(インストール時に選べるようにする)。
  - FluoRaPressée
  - FluoRaPressée Analysis
  - FluoRaPressée (Debug mode)(`--debug` 付き)
  - Ocean Optics ドライバーのインストール(方針12)
- 任意項目(`[Tasks]`)に「Ocean Optics のドライバーをインストールする(管理者権限が必要)」を、既定オフで
  追加する(方針12)。
- セットアップウィザードと Hardware Configuration で Ocean Optics を選んだときに、ドライバー導入の
  ボタンを出す(方針12)。
- `[Code]` に次を書く。
  - インストーラー用の mutex の名前を作る関数(方針6。アプリと同じ規則)。起動直後の確認では、前回の
    インストール先から名前を作り、`AppMutex` の scripted constant として使う。作った名前は
    インストーラーのログ(`/LOG`)に出す。
  - `PrepareToInstall`: ファイルをコピーする直前に、確定したインストール先で、FluoRaPressée が起動して
    いないかもう一度確かめる(方針6)。
  - 前の版がインストールされているかの判定(方針12。Ocean Optics の任意項目を更新時に隠すため)。
- 出力ファイル名は `FluoRaPressee-Setup-<version>.exe`。

Windows Sandbox での確認:

| 場面 | 確認すること |
|---|---|
| 新規インストール | 管理者権限なしで入り、起動できる |
| 上書き更新 | フォルダ選択が飛ばされる。`_internal` にわざと置いた不要なファイルが消える。ユーザーデータは残る |
| アプリの起動中 | 起動したまま実行すると、終了を求めるメッセージが出る。終了してから OK を押すと続行し、キャンセルを押すと何も変わらずに終わる。live GUI、Analysis Mode、ドライバー導入用exeのどれが起動していても検出される。管理者として起動したドライバー導入用exeも検出される |
| mutex の名前 | アプリのログとインストーラーのログに出た名前が一致する。インストール先のパスに大文字や日本語を含む場合も |
| ウィザードの途中で起動 | ファイルをコピーする直前で止まる |
| ソース版の起動中 | 検出されず、インストールが進む(方針10) |
| アンインストール | ユーザーデータが残る。FluoRaPressée の起動中は、終了を求めるメッセージが出る |
| Ocean Optics ドライバー | 新規インストールで任意項目を選ぶと、UAC の確認が出て導入される。更新のときは任意項目が表示されない |

同じユーザーの別のセッションで起動したものが検出されることは、Sandbox では試しにくい。仮想マシンで、
タスク スケジューラの「ユーザーがログオンしているかどうかにかかわらず実行する」を選んで exe を起動
すると、同じユーザーのまま別のセッション(セッション0)で動くので、これで試す。

## Step 5: リリース用のCI

作業:

- `.github/workflows/release.yml`: `v*` のタグをpushしたら、`windows-latest` で次を行う。
  1. checkout し、`.python-version` のPythonを用意する。
  2. `pip install -r requirements-oceanoptics.txt -r requirements-build.txt`
  3. タグと `__version__` が一致するか確認する。
  4. 単体テストを offscreen で実行する。
  5. `packaging/build_windows.ps1` を実行する。
  6. Inno Setup でインストーラーを作る(ランナーに入っていなければ choco でインストールする)。
  7. 公開済みの最新Releaseがあれば、それを入れてから新しい版で上書きし、インストールした版で
     `--smoke-test` を実行する。最初のリリースでは新規インストールだけを確かめる。
  8. **Releaseを下書き(draft)として作り**、インストーラーを添付する。
     `Version(__version__).is_prerelease` なら pre-release の印を付ける。
- 下書きは、実機で確認してから手動で公開する。更新機能は下書きを無視するので、公開するまで利用者には
  届かない。リリースノートは公開前に下書きへ書く(更新のダイアログに表示される)。
- リリースノートの先頭には、ダウンロードするファイル名(`FluoRaPressee-Setup-<version>.exe`)と、
  「FluoRaPressée を終了してから実行する」ことを書く。CIが下書きを作るときに、この定型文を入れておく。

## Step 6: 更新確認(通知まで)

作業:

- `src/core/update_check.py`(Qtに依存しない。通信部分は差し替えられるようにする):
  - `fetch_releases()`: `GET https://api.github.com/repos/khsacc/FluoraPressee/releases?per_page=20`
    を `urllib` で取得する。タイムアウトは10秒。
    **`/releases/latest` は pre-release を返さないので使わない。**
    `urllib` は Windows のプロキシ設定(レジストリ)と環境変数 `HTTPS_PROXY` を自動で使うので、
    プロキシのための追加対応は不要。
  - `select_update(releases, current_version, include_prerelease)` の選び方:
    1. 下書きを除く。
    2. `include_prerelease` が偽なら pre-release を除く。
    3. タグが PEP 440 として読めないものを除く。
    4. インストーラー(`FluoRaPressee-Setup-<version>.exe`)が添付されていないものを除く。
    5. 残りのうち `current_version` より新しい最大の版を選ぶ。
    - `0.1.0b1+dev...` は `0.1.0b1` より新しいと判定されるので、開発中の版に同じ版の更新が
      提示されることはない。
- local cache に次を保存する: `update_check_on_startup`(既定 True)、`update_include_prerelease`
  (未設定なら方針7の既定)、`update_last_checked`。
- `src/ui/menu/update_dialog.py`: 方針7のとおり。ビルド版ではインストーラーのダウンロードリンクと、
  リリースページを開くボタンを出す。ソース版では git pull を案内する。
- Help メニュー(About / Check for Updates… / Open Log Folder)をメインウィンドウと Analysis Mode の
  両方に追加する。起動時の自動確認と、新しい版があるときの表示は方針7のとおり。
- 開発中の確認用に、環境変数 `FLUORAPRESSEE_UPDATE_FEED` で取得先をローカルのJSONファイルや別のURLに
  差し替えられるようにする。利用者向けのマニュアルには書かない。

テスト(`tests/test_update_check.py`。ネットワークには接続しない):

- 下書き、pre-release、読めないタグ、添付ファイルの欠け、古い版、同じ版、`+dev` 付きの版を含む
  JSONを用意し、正しい版が選ばれること。
- 選ばれた版から、インストーラーのダウンロードURLとリリースページのURLが正しく取り出されること。

## Step 7: (削除)ダウンロードと適用

2026-11-21 の方針変更で削除した(方針7)。ほかの箇所から番号で参照しているので、番号は詰めない。

削除前の設計は、git の履歴の改訂版に残っている。将来、更新のたびの SmartScreen の警告が負担になった
場合は、そこから再開できる。アプリ内でダウンロードしたファイルには「インターネットから取得した」印が
付かないので、警告が出なくなるためである。

## Step 8: 保存データとAPIへのバージョン記録(任意・推奨)

- 測定メタデータに `software: {name, version, runtime}` を追加する。スキーマバージョンを上げるか
  どうかは既存の方針に従う。`docs-site/docs/data-formats/` も更新する。
- スペクトルファイルのヘッダーに `Software: FluoRaPressée <version>` の行を追加する。読み込み側が
  知らないヘッダー行を無視することを、テストで確かめる。
- API の `GET /status` の応答に `app_version` を追加し、`docs-site/docs/api/status.md` を更新する。

## Step 9: ドキュメント

- `docs-site/docs/installation.md`: 全面的に書き直す。
  - ビルド版: インストーラーのダウンロード、SmartScreen の「詳細情報 → 実行」、管理者権限は不要、
    装置メーカーのSDKは従来どおり必要。Ocean Optics のドライバーは、インストーラーの任意項目か
    スタートメニューから導入する(このときだけ管理者権限が必要)。
  - ソース版とインストールした版を同じPCで同時に起動しないこと(方針13)。
  - 更新: 通知か Help → Check for Updates からインストーラーをダウンロードし、FluoRaPressée を終了して
    から実行する。起動したまま実行するとインストーラーが終了を求めること、SmartScreen の警告が更新の
    たびに出ること(方針8)も書く。
  - アンインストール: ユーザーデータは残る。その場所。
  - 古い版に戻す方法(古いインストーラーを実行する)。新しい版が作ったデータは、古い版では使えなくなる
    ことがある(方針14)。
  - ソース版: 開発者向けとして、現在の内容を残す。
- `hardware-config.md`、`data-formats/index.md`、`data-formats/spectrometer-config.md`、
  `usage/acquisition.md:49` 周辺: `spectrometerConfig.json` の場所を、OS別の表と環境変数の説明に
  改める。
- Help メニューのページを新しく作る(About / Check for Updates / Open Log Folder)。ログは起動ごとに
  別のファイルになり、About にそのプロセスのファイル名が出ることも書く。`add-docs-page` スキルの手順に
  従う。
- `README.md` / `README_ja.md`: Releases へのリンクを追加する。
- `CLAUDE.md`: Running(ビルド)、Config/state files(場所)、新しいモジュールについて追記する。

## 実装しない / 見送る事項

| 事項 | 理由 |
|---|---|
| ダウングレードの防止 | 実験装置が新しい版で動かなくなったとき、戻せることに価値があるため(方針6) |
| 差分更新 | 毎回インストーラー全体をダウンロードする(数百MBを想定)。当面はこれで十分 |
| アプリ内からのダウンロードとインストール | 2026-11-21 の方針変更で削除した(方針7、Step 7)。構成を簡単にするため。代償として、更新のたびに SmartScreen の警告が出る |
| 自動適用・時刻を指定した適用 | 実験中に割り込む危険があるため |
| macOS / Linux 向けのビルド | 実機を制御する対象は Windows のみ。ソースからの起動で足りる |
| 「この版をスキップ」 | 通知が煩わしいという声が出てから検討する |
| 独自のアップデーター、tufup など | Inno Setup で足りる。PyUpdater は開発終了 |
| onefile ビルド | 起動のたびに展開するので遅い。ウイルス対策ソフトの誤検知も増える |

## オープンな課題

1. ~~実験用PCがインターネットにつながるか。~~ → **つながる前提とする**(2026-11-21 決定)。
   つながらないPCが例外的にあっても、USBで持ち込んだインストーラーを実行すれば更新できる
   (更新と同じ手順)。マニュアルにはこの手順を一言書いておく。
2. ~~コード署名。~~ → **当面は署名なしで配布する**(2026-11-21 決定。影響と対策は方針8)。
   次のどれかが起きたら、署名を検討し直す。
   - 大学の管理下にあるPCで、ポリシーにより実行できない。
   - Defender の誤検知が繰り返し起きる。
   - 利用者が研究室の外に広がる。
   - 更新のたびの警告が利用者の負担になる(その場合は、Step 7 を再開する選択肢もある)。
3. ~~ビルド版での Ocean Optics ドライバーの導入。~~ → **同じインストーラーに入れた専用のexeで導入する**
   (2026-11-21 決定。方針12)。
4. ~~古い版で新しいデータを読んだときの互換性。~~ → **知らない版のデータ形式を変更せずに拒否する
   処理を、b1 の必須項目にした**(2026-11-21 レビュー第2回。方針14、Step 1)。公開した版の読み込み
   処理は、後から直せないため。以後は、版を上げる変更を最小限にする(方針14の決まり)。
5. ~~GitHub API の利用回数制限。~~ → **24時間に1回の確認で始める。** 足りなければ、GitHub Pages
   (docs-site はすでに公開済み)に `latest.json` を置き、それを取得先にする(2026-11-21 了承)。
6. ~~同じ Windows PC にソース版とインストールした版がある場合。~~ → **一度に1つだけ起動する運用とし、
   その範囲で衝突しないようにする**(2026-11-21 決定。方針13)。マニュアルにも書く。
7. **PyInstaller でビルドした版が実機で動くか。** Step 3 でビルドができたら、開発者本人が実機で
   確かめる。結果は下の「実施ログ」に記録する。
8. ~~`.gitignore` の `/tests/`。~~ → 2026-11-21 に削除した。以前は試験用のファイルを置いていたための
   設定だった。

## 実施ログ

### 2026-11-21 Step 0〜6・8・9 のコードと文書(macOS で実装。実行による確認は未実施)

AGENTS.md に従い、macOS ではテストもアプリの起動もしていない。行った確認は、コードと差分の
レビュー、変更した Python ファイルの `py_compile`(構文の確認のみ)、ドキュメントの
`npm run typecheck` と `npm run build`(リンク切れ・アンカーの警告なし)だけである。

実装したもの:

- Step 0: `src/version.py`、`src/core/runtime_env.py`(実行形態、表示用バージョン、2つの mutex)。
- Step 1: `src/core/app_paths.py`(場所、移行、パスの補正、`legacy_migration_enabled()`)、
  `src/core/data_versions.py`(知らない版の拒否)、旧APIキーの移行条件、カタログと `api_clients.json`
  の版の検査、未知のキーの保持、校正標準の同梱分+利用者分、ウィザードの
  「Load existing spectrometerConfig.json…」、相対パスの拒否。
- Step 2: `src/core/app_logging.py`(起動ごとのログ、整理、失敗しても起動を続ける)、`--smoke-test`、
  インストーラー用・装置用の mutex、`local_cache.json` のプロセス間ロック。
- Step 3〜5: `packaging/FluoRaPressee.spec`、`packaging/oceanoptics_driver.py`、
  `packaging/build_windows.ps1`、`packaging/FluoRaPressee.iss`、`packaging/install_test.ps1`(CI 専用)、
  `.github/workflows/release.yml`、`requirements-build.txt`。
- Step 6: `src/core/update_check.py`、`src/ui/menu/help_menu.py`、`update_dialog.py`、`about_dialog.py`。
- Step 8: 測定メタデータの `software`、スペクトルファイルの `Software:` 行、`GET /status` の
  `app_version`。カタログを拒否したときの API は 503 `unsupported_data_version`。
- Step 9: マニュアル(インストール、Help メニューの新しいページ、保存場所、API)、README、
  CLAUDE.md / AGENTS.md。
- テスト: `test_runtime_env.py`、`test_app_paths.py`、`test_app_logging.py`、`test_update_check.py`、
  `test_local_cache.py`(書き直し)、`test_api_clients.py`・`test_api_client_persistence.py`・
  `test_configuration_catalog.py` への追加。

計画から変えた点・計画で決めていなかった点:

- `setup_stdio()` は `app_bootstrap.py` ではなく `src/core/app_logging.py` に置いた。
  `app_bootstrap.py` は import 時に PyQt6 を読み込むので、それより前、Qt に依存しない段階で
  標準出力を用意するためである。
- Help メニューの組み立てを `src/ui/menu/help_menu.py`(`HelpMenu`)にまとめ、live と Analysis の
  両方から使う。新しい版があるときはメニュー名を「Help (update available)」に変える
  (モーダルではない)。起動時の確認のオン・オフをメニューに置き、最後の確認結果を local cache に
  残して、24時間以内に開いた別のウィンドウでも表示できるようにした。
- 空の `dll_path` を補うときは、DLL のファイルではなく**フォルダ**の絶対パスを入れる。ウィザードと
  Hardware Configuration の欄が「ShamrockCIF.dll を含むフォルダ」であるため。
- `src/api/info_helpers.py` の `source_file` は、ファイル名(`spectrometerConfig.json`)のままにした。
  フルパスにすると、ユーザー名を含む場所が LAN 越しに見えてしまうため。
- ドライバー導入用exeには `uac_admin`(管理者権限を求めるマニフェスト)を付けた。スタートメニューから
  起動しても UAC の確認が出るようにするため。
- スペクトルファイルの `Software:` 行は ASCII(`FluoRaPressee`)で書く。`np.savetxt` はヘッダーを
  latin-1 で書くため。
- `pyinstaller==6.11.1` は仮の固定である。Step 3 で実際にビルドするときに確かめ、必要なら更新する。
- `AppMutex={code:RunningMutexName}` と `PrepareToInstall` 内の `SuppressibleMsgBox` は、Step 4 で
  動作を確かめる(方針6 の未確認事項)。

Windows で残っている作業:

1. `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v`(新しいテストと既存のテスト)。
2. `python main.py --debug` と `python analysis_main.py` で、Help メニュー、ウィザードの読み込みボタン、
   相対パスの拒否、カタログを拒否したときの起動を確かめる。
3. Step 3: `packaging/build_windows.ps1` でビルドし、実機の確認項目の表を埋める。
4. Step 4: Windows Sandbox / 仮想マシンで、表の各場面と mutex の名前の一致を確かめる。
5. Step 5: テスト用のタグでワークフローを動かし、下書きができることを確かめる(公開はしない)。

### 2026-11-22 レビュー(3回目)の指摘3件の修正(macOS で実装。テストは未実行)

1. **新しい形式の `api_clients.json` があると、GUI 全体が起動しなかった。** ウィンドウを作るときの
   `load_api_client_list()` が例外を捕まえていなかったため。`ApiMixin.load_api_client_list_at_startup()`
   を足して `main_window.py` から呼ぶ。クライアントなしの状態で起動を続け、API の起動と Manage Clients
   は、これまでどおりファイルを読み直して理由を表示する。テスト:
   `test_api_client_persistence.py` の `test_newer_file_does_not_stop_the_window_from_starting`。
2. **カタログの新しい版が WAL にだけ残っていると、拒否する前に DB を変更していた。** 事前の確認が
   `immutable=1`(WAL を読まない)で、版の再確認は `CREATE TABLE/INDEX` の後だった。
   `executescript()` は自動コミットなので、後の rollback でも DDL は戻らなかった。直した点:
   - 事前の確認は、`-wal` ファイルがあれば読み取り専用接続(`mode=ro`)で WAL も読む。読み取り専用接続は
     チェックポイントも書き込みもしない(scratch での SQLite 3.37 の実験で、本体と `-wal` が1バイトも
     変わらないことを確認した。`-shm` は作られる)。`-wal` がなければ、これまでどおり `immutable=1`。
   - 表があるのに `catalog_meta` を読めないファイルも拒否する(このモジュールは最初の版から
     `catalog_meta` を最初に作っている)。
   - 初期化全体を `BEGIN IMMEDIATE` の1つのトランザクションにし、書き込みロックを取った直後、DDL より
     前に版をもう一度確かめる。DDL は `executescript()` をやめ、`_BASE_SCHEMA` の文を1つずつ実行する
     (スキーマが変わっていないことは、新旧の DDL を SQLite で比べて確認した)。
   - テスト: `test_configuration_catalog.py` の
     `test_newer_catalog_still_in_the_wal_is_refused_before_any_ddl`(書き込み中の `-wal` を写して、
     落ちた新しい版の状態を作る)と `test_file_without_catalog_meta_is_refused_unchanged`。
3. **ビルド後に、呼び出し元の `FLUORAPRESSEE_DATA_DIR` が消えていた。** `build_windows.ps1` は元の値を
   退避し、`finally` で戻す(元がなければ消す)。同じ書き方だった `install_test.ps1` も直した。
