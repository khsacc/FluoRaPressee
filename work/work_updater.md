# ビルド版の配布とGUIからのアップデート 実装計画

作成日: 2026-11-21

## 背景

仮版(ベータ版)をビルドして公開する。現状の配布形態は「`git clone` → `setup.bat` で `.venv` を作る →
`.bat` から `python main.py` を起動」であり、利用者のPCにPythonが必要で、更新も `git pull` と
`pip install` を手で行うしかない。

そこで、**Pythonを必要としないビルド版をGitHub Releasesで配布し、GUIから最新版へ更新できるように
する**。

**更新機能を持たない版を一度配ると、その利用者は自動では更新できない。** したがって更新確認は
最初の仮版(`v0.1.0b1`)に必ず入れる。また、更新機能より先に、その前提となる準備(バージョン番号、
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

### 決定事項

- 配布形態は **PyInstaller(onedir) + Inno Setup のインストーラー + GitHub Releases**。
- **インストーラー1本で、新規インストールと上書き更新を兼ねる。**
- アプリ内の更新は、同じインストーラーをダウンロードして `/SILENT` で起動し、アプリ自身は通常の
  終了処理を通って終わる、という形にする。アプリが自分のファイルを差し替えることはしない
  (Windowsでは実行中のexe/DLLを上書きできないため)。
- **更新を自動で適用することはしない。** 知らせるだけにし、適用は操作者が明示的に行う。
- 開発用PCでは、これまで通りコマンドから起動する。**開発用PCにはインストールしない。**
  - Windowsの開発用PCでは、ローカルでビルドした `dist\` のexeを直接起動して確認できる。
  - インストーラーと上書き更新は Windows Sandbox か仮想マシンで試す。
- ユーザーデータは、ソースから起動してもビルド版でも**同じ場所**に置き、環境変数で差し替えられる
  ようにする。
- **実験用PCはインターネットにつながる前提とする**(2026-11-21 決定)。起動時の自動確認を更新の
  主な経路にする。つながらないときに何も表示しない動作は、念のため残す。
- **当面はコード署名なしで配布する**(2026-11-21 決定)。初回の手動インストールでは SmartScreen の
  警告が出るが、「詳細情報 → 実行」で続行してもらう。影響と対策は方針8に書く。
- **Ocean Optics のドライバーは、同じインストーラーに入れた専用のexeで導入する**(2026-11-21 決定)。
  インストーラーの任意項目、セットアップウィザード、スタートメニューの3カ所から起動できるようにする。
  Ocean Optics 用の別のインストーラーは作らない。詳細は方針12。
- **同じPCにソース版とインストールした版がある場合は、一度に1つだけ起動する運用とし、その範囲で
  衝突が起きないようにする**(2026-11-21 決定)。詳細は方針13。

## 採用する方針

### 方針1: 実行形態を3種類に分け、判定を1カ所にまとめる

| 実行形態 | 判定 | 更新機能 |
|---|---|---|
| `source`(ソースから起動) | `getattr(sys, "frozen", False)` が偽 | 最新版の確認と表示まで。「git pull してください」と案内する |
| `portable`(ビルドしただけ) | frozen だが、exe と同じフォルダに `unins000.exe` がない | Releasesページへのリンクだけ |
| `installed`(インストール済み) | frozen で、exe と同じフォルダに `unins000.exe` がある | ダウンロードしてインストーラーを起動 |

判定は新設する `src/core/runtime_env.py` の1関数(`runtime_kind()`)に集約し、他のコードは
`sys.frozen` を直接見ない。

**frozen かどうかだけで判定してはいけない。** そうすると、Windowsの開発用PCで `dist\` から直接起動した
ビルド版でも「インストール」ボタンが有効になる。押すとインストーラーが走り、開発用PCに意図せず
インストールされてしまう。`unins000.exe` は Inno Setup がインストール先に必ず置くファイルなので、
「インストーラーで入れたかどうか」の目印として使える。

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
  | `logs/` | ログ | 現状のまま + `app.log`(方針9) |
  | `updates/` | ダウンロードしたインストーラー | 新設(Step 7) |

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

起動時、何かが設定を読む前に、次を行う(ソースから起動したときのみ)。

1. 新しい場所に `spectrometerConfig.json` がなく、`<repo>/spectrometerConfig.json` があれば、
   コピーする。
2. コピーしたら、旧ファイルを `spectrometerConfig.json.migrated` に改名し、コンソールに知らせる。
3. `local_cache.json` も同様に扱う。
4. 新旧の両方があるときは新しい場所を使い、旧ファイルには触れず、警告だけ出す。

`api_clients` の旧鍵ファイルは移行後に削除しているが、ここでは**削除しない**。古いブランチを
チェックアウトしたときに、手で戻せるようにするためである。一方、**そのまま残すこともしない。**
2つのコピーが黙って食い違っていくのを防ぐためである。

**`dll_path` の補正**: 移行時に `dll_path` が空か相対パスで、かつ `<repo>/ShamrockCIF.dll` があれば、
その絶対パスを移行後の設定に書き込む。これをしないと、インストール版ではカレントディレクトリが
インストール先になるため、DLLが見つからなくなる。

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
| `AppMutex` | `FluoRaPresseeRunning` | 起動中のアプリを検出する |
| `CloseApplications` | `no` | **測定中・冷却中のアプリを強制終了させない** |
| `[Run]` | `postinstall nowait` | 手動のときは完了画面に「起動する」のチェックボックスを出し、`/SILENT` のときは自動で起動する |
| アンインストール | ユーザーデータは消さない | 設定と校正カタログは装置に紐づく資産のため |

**`_internal` を丸ごと消す理由**: Inno Setup は、新しい版に含まれないファイルを消さない。一方、
PyInstaller の `_internal` の中身は、ライブラリを更新するたびに変わる。古い DLL や `*.dist-info` が
残ると、原因の分かりにくい読み込みエラーにつながる。これを安全に行えるのは、方針3で `{app}` に
ユーザーデータを置かないと決めているからである。

**起動中のアプリを待つ処理**: アプリ内から更新する場合、インストーラーはアプリの終了処理
(`closeEvent`、カメラ停止・冷却終了を含む)の途中に起動する。そこで `[Code]` の `InitializeSetup` で
`CheckForMutexes('FluoRaPresseeRunning')` を繰り返し確認し、最大120秒待つ。`AppMutex` の判定が
`InitializeSetup` の前後どちらで行われるか、サイレント実行時にどう振る舞うかは Step 4 で確かめる。
待機処理と干渉する場合は、`AppMutex` をやめて `[Code]` の待機処理と独自のメッセージだけにする。

**再起動するアプリ**: 更新を始めた側のexeを再起動する。インストーラーに `/RELAUNCH=live|analysis`
を渡し、`[Run]` の `Check:` 関数で分岐させる。手動で実行したときの既定は live。

**ダウングレードは防がない。** 新しい版で実験装置が動かなくなったとき、古いインストーラーを実行して
戻せることには実用上の価値がある。アプリ内の更新機能は、新しい版しか提示しない。データ互換性の
問題は「オープンな課題」4に挙げる。

### 方針7: 更新は「通知」と「適用」を分け、適用は操作者の明示操作で、かつ装置が空いているときだけ

- **起動時の自動確認**
  - ウィンドウを表示したあと、バックグラウンドのスレッドで行う。カメラの初期化は待たせない。
  - 24時間に1回まで(最終確認時刻は local cache に保存)。
  - 失敗しても何も表示しない(ネットにつながらない実験PCを想定)。
  - 新しい版があれば、Help メニューに「Update available: v0.1.0b2」の項目を出すだけにする。
    **モーダルのダイアログは出さない**(実験の開始直後に割り込まないため)。
- **手動の確認**: Help → Check for Updates…。こちらは失敗したら理由を表示する。
- **ベータ版を含めるか**: 既定は「現在の版がプレリリースなら含める」。ベータ版の利用者は次のベータ版
  を受け取りたいはずだからである。local cache の `update_include_prerelease` で上書きできる。
- **適用の条件**(実行形態が `installed` のとき)
  - `self._ui_lock_reasons` が空で、かつ `self._gate_owner is None` のときだけ、インストールボタンを
    有効にする。これで連続測定中・APIサーバーのロック中・測定中を除外できる。
  - ボタンを押した時点でもう一度判定し、条件を満たさなければ理由を表示する。
- **適用の流れ**
  1. ダウンロードし、SHA-256 を照合する(方針8)。
  2. `self._pending_update_installer` にインストーラーのパスを入れ、`self.close()` を呼ぶ。
  3. 通常の `closeEvent` が走る(終了確認、APIサーバー停止、カメラ停止など)。
  4. `closeEvent` の受け入れ側の最後(`event.accept()` の直前)でインストーラーを起動する。
  - **操作者が終了確認でキャンセルすれば、更新も取り消される。** インストーラーを先に起動してから
    `close()` を呼ぶと、キャンセルされたときにインストーラーだけが残ってしまうため、この順番にする。
- **GitHub API**: 認証なしでは同じIPから1時間60回までに制限される。研究室内のPCが同じグローバルIPを
  共有していても、24時間に1回なら問題にならない。User-Agent は汎用の名前(`FluoRaPressee-Updater`)
  にし、利用者の情報は送らない。
- Analysis Mode にも同じ機能を付ける。更新のダイアログは両方のウィンドウから使える独立した部品として
  作る。

### 方針8: ダウンロードしたファイルは HTTPS と SHA-256 で確認する(コード署名は別途)

- Release には、インストーラーとチェックサムファイル(`FluoRaPressee-Setup-<ver>.exe.sha256`、
  形式は `<hex>  <ファイル名>`)を添付する。
- アプリは照合してから起動する。一致しなければ削除してエラーを表示する。
- チェックサムは同じ場所から取得するので、防げるのは通信途中の破損や途切れだけである。GitHubアカウント
  が乗っ取られた場合は防げない。根本的な対策はコード署名(「オープンな課題」2)。
- `urllib` でダウンロードしたファイルには「インターネットから取得した」印(Mark of the Web)が付かない
  ので、アプリ内の更新では SmartScreen の警告は出ない。最初に手動でインストールするときは出る。

**署名なしで配布することの影響**(決定事項):

- 署名のないファイルは、SmartScreen の信頼度がファイルごとに判定される。そのため、**新しい版を
  ブラウザでダウンロードして手動で入れるたびに警告が出る。** 警告なしで更新できるのはアプリ内からの
  更新だけになる。このため Step 7 を `v0.1.0b1` の必須とする。
- 大学の管理下にあるPCでは、ポリシーにより「実行」ボタン自体が出ないことがある。そういうPCが
  出てきたら、署名を検討し直す(「オープンな課題」2)。
- 署名の代わりに、無料でできる対策として次を行う。
  - リポジトリの所有者アカウントで2段階認証を有効にする。
  - `v*` タグの保護ルールで、リリースを作れる人を限定する。

### 方針9: ビルド版の標準出力はログファイルに送る

- ビルド版はウィンドウ版(コンソールなし)にする。
- `app_bootstrap.setup_stdio()` を新設し、`main.py` と `analysis_main.py` の `reconfigure` の2行を
  置き換える。
  - `sys.stdout` が `None` なら、`logs/app.log` を開いて `stdout` と `stderr` の両方に割り当てる。
    起動のたびに `app.log.1`〜`.3` へ順送りする。
  - `None` でなければ、従来どおり `reconfigure(errors="replace")` だけを行う。
- `sys.excepthook` を設定し、捕まえられなかった例外をログに残す。
- Help → Open Log Folder を追加する(`configuration_manager_dialog.py:374` と同じ
  `QDesktopServices.openUrl` を使う)。
- ソースから起動したときの動作は変えない(コンソールに出る)。

### 方針10: 開発環境は変えない

- `python main.py [--debug]`、既存の `.bat`/`.sh`、`setup.bat` はそのまま使える。
  `requirements.txt` に増えるのは `packaging` だけ。
- PyInstaller は `requirements-build.txt` に分ける。`setup.bat` ではインストールしない。
- ビルド手順は `packaging/build_windows.ps1` の1本にまとめ、CIもこのスクリプトを呼ぶだけにする。
  手元とCIでビルド手順がずれないようにするため。`scripts/` は `.gitignore` の対象なので使わない。
- `.gitignore` に `/build/`、`/dist/`、`/packaging/Output/`、`src/_build_info.py` を追加する。
- macOS の開発用PCでは Windows 版をビルドできない(PyInstaller は別OS向けにビルドできない)。
  macOS ではソースからの起動だけを行う。Qtに依存しない部分の単体テストは macOS でも実行できる。
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
  - インストーラーからは、`[Run]` に `Verb: runas` と `Flags: shellexec waituntilterminated skipifsilent`
    を付けて起動する。
  - アプリからは `ShellExecuteW(None, "runas", ...)` で起動する。ソース版では、代わりに
    `setup_oceanoptics.bat` を案内する。
- **`skipifsilent` は必須。** Inno Setup は前回選んだ任意項目を覚えていて、更新時にも同じ項目を実行する。
  付けないと、アプリ内から更新するたびに UAC の確認が出て、ドライバーの導入が繰り返される。

**Ocean Optics 用の別インストーラーは作らない。** 作ると、本体と Ocean Optics 版の2系統の更新を
管理することになり、利用者がどちらを入れたかで更新の扱いも変わってしまう。ドライバーの導入は1度
きりの作業なので、本体と同じインストーラーに入れておき、必要な人だけが実行する形で足りる。

### 方針13: 同じPCでの複数起動 — 一度に1つだけ起動する運用で、衝突を起こさない

想定しているのは、Windows の開発用PCが実験用PCを兼ねていて、ソース版とインストールした版の両方が
ある場合である。ユーザーデータは両者で共有する(方針3)。

- **装置を使う live GUI は、PC全体で1つしか起動できないようにする。**
  - ソース版かインストールした版かを問わず、ハードウェアモード(`--debug` なし)の live GUI は、起動時に
    名前付き mutex `FluoRaPresseeInstrument` を作る。
  - すでにあれば「別の FluoRaPressée が装置を使用中です」と表示して終了する。
  - これは、インストーラーのための `FluoRaPresseeRunning`(方針6。ビルド版でだけ作る)とは別のもの
    である。「ソース版の起動はインストーラーを止めない」という方針10は変えない。
  - `--debug` と Analysis Mode は制限しない。装置を使わないためである。ただし、`--debug` で2つ起動し、
    両方でAPIを有効にした場合のポートの衝突は、開発者が自分で避ける。
  - Windows 以外では装置を制御しないので、この mutex は作らない。
- **`local_cache.json` は atomic に書き込む**(一時ファイルに書いてから `os.replace` で置き換える)。
  live GUI と Analysis Mode は同時に起動してよく、両方がこのファイルに書き込むためである。構成カタログ
  (SQLite)と `api_clients.json`(すでに atomic に書き込んでいる)は対応済み。
- **交互に使うときの注意**: 開発中のソース版は、インストールした版より新しいことがある。ソース版が
  データの形式を新しくしたあとで、インストールした版を起動すると、「オープンな課題」4の問題が起きる。
  データ形式に関わる変更を試すときは、`FLUORAPRESSEE_DATA_DIR` で場所を分ける。

## 対象ファイル

新規作成:

| ファイル | 内容 |
|---|---|
| `src/version.py` | `__version__` |
| `src/core/runtime_env.py` | 実行形態の判定、表示用バージョン文字列、mutex |
| `src/core/app_paths.py` | ユーザーデータ・同梱データの場所、旧い場所からの移行 |
| `src/core/update_check.py` | Releases の取得、更新対象の選択、ダウンロード、SHA-256照合(Qtに依存しない) |
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
| `src/ui/local_cache.py` | 場所を `app_paths` から取る(呼び出しのたびに評価する)。atomic に書き込む(方針13) |
| `src/ui/ui_mixins/config_mixin.py`, `src/ui/ui_mixins/api_mixin.py`, `src/hardware/spectrometer_andor.py` | `spectrometerConfig.json` の場所 |
| `src/api/info_helpers.py` | 表示用ラベル |
| `src/core/configuration_catalog.py`, `src/core/api_clients.py` | ベースパスを `app_paths` に任せる |
| `src/ui/calibration_ui.py` | 同梱分と利用者分の校正標準 |
| `src/ui/config_wizard.py` | 「既存の spectrometerConfig.json を読み込む…」、Ocean Optics ドライバー導入のボタン |
| `src/ui/menu/hardware_config_dialog.py` | Ocean Optics ドライバー導入のボタン |
| `src/ui/main_window.py` | Help メニュー、`closeEvent` の最後でインストーラーを起動 |
| `src/ui/analysis_ui.py` | Help メニュー |
| `src/core/measurement_metadata.py`, `src/core/file_io.py`, `src/api/` | バージョンの記録(Step 8) |
| `tests/test_local_cache.py` | `os.chdir` ではなく環境変数で場所を差し替える |
| `.gitignore`, `requirements.txt` | 方針10、`packaging` |
| `docs-site/docs/`, `README.md`, `README_ja.md`, `CLAUDE.md` | Step 9 |

## ステップ間の依存関係

```
Step 0 版・実行形態 ─┬─ Step 1 パス・移行 ── Step 2 起動処理 ── Step 3 PyInstaller ── Step 4 Inno Setup ── Step 5 CI
                    │                                                                     │
                    ├─ Step 6 更新確認(通知) ────────────────────────────────────────── Step 7 適用
                    └─ Step 8 保存データ・APIへの記録
Step 9 ドキュメント: 各ステップと並行して進める
```

リリースとの関係:

- **Step 0 と Step 1 は、最初のビルド版より先に master へ入れ、clone の利用者に `git pull` してもらう**
  (方針4)。
- `v0.1.0b1` には **Step 0〜7 が必須**。
  - Step 7 がなくても、利用者は通知を見て新しいインストーラーを手動で実行すれば更新できる
    (インストーラーがアップデーターを兼ねるため)。
  - ただし署名なしで配布するので、手動で入れると版ごとに SmartScreen の警告が出る(方針8)。
    警告なしの更新経路を最初から用意するため、Step 7 も必須とした。
- Step 8 は任意だが、保存データの再現性のために b1 に入れることを推奨する。

## 各ステップ共通の検証手順

1. `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v`
2. `python main.py --debug` で該当する操作を確かめる。
3. Step 2 以降でビルドに関わる変更をした場合は、Windows の開発用PCでも確かめる。
   `packaging/build_windows.ps1` でビルドし、`FLUORAPRESSEE_DATA_DIR` を一時フォルダに設定してから
   `dist\FluoRaPressee\FluoRaPressee.exe --debug` を起動する。

## Step 0: バージョン番号と実行形態の判定

作業:

- `src/version.py` を作り、`__version__ = "0.1.0b1"` とする。
- `src/core/runtime_env.py`:
  - `is_frozen()`、`runtime_kind()`(`"source"` / `"portable"` / `"installed"`)、`app_dir()`
  - `display_version()`: ソースのとき `+dev.g<hash>`、ビルド版のときは `_build_info` の内容を付ける。
- `print_software_and_author_info()` に、バージョンと実行形態を表示する行を追加する。
- `requirements.txt` に `packaging` を追加する。

テスト(`tests/test_runtime_env.py`):

- `sys.frozen` / `sys.executable` を差し替え、一時フォルダに `unins000.exe` を置いた場合と置かない場合で、
  3種類の判定がそれぞれ正しく返ること。
- git が使えない環境でも `display_version()` が例外を出さないこと。

完了条件: 起動時の表示にバージョンが出る。Qtに依存しない。

## Step 1: パスの一元化とユーザーデータの移行

作業:

- `src/core/app_paths.py`: `user_data_dir()`、`spectrometer_config_path()`、`local_cache_path()`、
  `user_calibration_standards_dir()`、`logs_dir()`、`updates_dir()`、`bundled_resource_path()`、
  `migrate_legacy_user_files(repo_root, data_dir)`。
  - **すべて呼び出しのたびに評価する。** import 時に固定すると、環境変数やテストでの差し替えが
    効かなくなる。
- 「現状」3〜5に挙げた参照を、すべて `app_paths` 経由に置き換える。
- `main.py` と `analysis_main.py` の両方で、何かが設定を読む前に移行を呼ぶ。移行は何度呼んでも
  同じ結果になるように作る。Analysis Mode も `local_cache.json` を読むため、両方で呼ぶ。
- 校正標準を同梱分と利用者分の両方から読む(方針5)。
- セットアップウィザードに「既存の spectrometerConfig.json を読み込む…」を追加する。JSONとして
  読めることを確かめ、`dll_path` の補正(方針4)を同じ関数で行う。
- `ShamrockCIF.dll` を相対パスで読もうとして失敗したときは、Hardware Configuration で `dll_path` を
  設定するよう案内するメッセージを出す。

テスト(`tests/test_app_paths.py` と `tests/test_local_cache.py` の修正):

- 環境変数で場所が変わること。
- OS別のベースパスが正しいこと。
- 移行で、コピーと改名が行われること。
- 新しい場所にすでにファイルがあれば、上書きしないこと。
- `dll_path` の補正が行われること。
- 移行を2回呼んでも結果が変わらないこと。

完了条件:

- リポジトリ直下に設定ファイルがある clone で起動すると、設定が移行され、ウィザードは出ず、すべての
  機能が従来どおり動く。
- `FLUORAPRESSEE_DATA_DIR` に空のフォルダを指定して起動すると、ウィザードが出る。

## Step 2: ビルド版向けの起動処理

作業:

- `setup_stdio()` と `sys.excepthook` を設定する(方針9)。
- mutex: ビルド版でだけ、`ctypes` の `CreateMutexW` で `FluoRaPresseeRunning` を作り、プロセスが
  終わるまでハンドルを保持する。live と Analysis の両方のexeで作る(どちらもインストール先のファイルを
  使っているため)。名前は `.iss` の `AppMutex` と一致させる。
- 装置用の mutex `FluoRaPresseeInstrument`(ソース版・ビルド版の両方、ハードウェアモードの live GUI
  のみ)と、`local_cache.json` の atomic な書き込み(方針13)。
- `--smoke-test` フラグを追加する。
  - 各バックエンドのモジュール(andor / princeton / oceanoptics と `seabreeze` 本体)、
    `src.api.server.create_app`、Analysis Mode の import までを行い、ハードウェアには触れずに
    終了コード 0/1 で終わる。結果はログに書く。
  - ソースから起動したときも動くので、ビルド前の確認にも使える。
- Help → Open Log Folder を追加する。

テスト: `sys.stdout` を `None` にした状態で `setup_stdio()` が落ちず、ログファイルに書き込むこと。
`--smoke-test` がソースから起動して 0 を返すこと。装置用の mutex がすでにあるとき、ハードウェアモードの
起動が拒否され、`--debug` の起動は拒否されないこと(mutex を作る関数を差し替えて確かめる)。
`local_cache.json` の書き込み途中で例外が起きても、元のファイルが壊れずに残ること。

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
| 表示 | `QT_OPENGL=software` と pyqtgraph |
| ウイルス対策ソフト | Windows Defender に誤検知されないか。署名なしなので起きやすい。誤検知されたら Microsoft の誤検知報告フォームに提出する。繰り返すようなら、PyInstaller のブートローダーを自分でビルドし直す(既製のブートローダーは誤検知されやすい) |

完了条件: Andor / PI / Ocean Optics の各実機で、`dist\` のexeから測定・校正・保存・APIが動く。

## Step 4: Inno Setup のインストーラー

作業:

- `packaging/FluoRaPressee.iss` を方針6のとおりに作る。バージョンはビルドスクリプトから
  `/DAppVersion=...` で渡す。
- `AppId` のGUIDを生成し、**この文書に記録する**: `AppId = (Step 4 で生成して記入)`
- スタートメニューに次を登録する。デスクトップのアイコンは任意(インストール時に選べるようにする)。
  - FluoRaPressée
  - FluoRaPressée Analysis
  - FluoRaPressée (Debug mode)(`--debug` 付き)
  - Ocean Optics ドライバーのインストール(方針12)
- 任意項目(`[Tasks]`)に「Ocean Optics のドライバーをインストールする(管理者権限が必要)」を、既定オフで
  追加する(方針12)。
- セットアップウィザードと Hardware Configuration で Ocean Optics を選んだときに、ドライバー導入の
  ボタンを出す(方針12)。
- `[Code]` に、起動中のアプリの終了を待つ処理と `/RELAUNCH=` の分岐を書く。
- 出力ファイル名は `FluoRaPressee-Setup-<version>.exe`。

Windows Sandbox での確認:

| 場面 | 確認すること |
|---|---|
| 新規インストール | 管理者権限なしで入り、起動できる |
| 上書き更新 | フォルダ選択が飛ばされる。`_internal` にわざと置いた不要なファイルが消える。ユーザーデータは残る |
| アプリの起動中 | 手動で実行すると終了を促される。サイレントで実行すると終了を待つ |
| サイレント更新 | 更新後に、`/RELAUNCH` で指定した側のexeが起動する |
| アンインストール | ユーザーデータが残る |
| Ocean Optics ドライバー | 任意項目を選ぶと UAC の確認が出て導入される。そのあとサイレント更新しても、再実行されない |

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
  8. SHA-256 のファイルを作る。
  9. **Releaseを下書き(draft)として作り**、インストーラーとチェックサムを添付する。
     `Version(__version__).is_prerelease` なら pre-release の印を付ける。
- 下書きは、実機で確認してから手動で公開する。更新機能は下書きを無視するので、公開するまで利用者には
  届かない。リリースノートは公開前に下書きへ書く(更新のダイアログに表示される)。

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
    4. インストーラーとチェックサムの両方が添付されていないものを除く。
    5. 残りのうち `current_version` より新しい最大の版を選ぶ。
    - `0.1.0b1+dev...` は `0.1.0b1` より新しいと判定されるので、開発中の版に同じ版の更新が
      提示されることはない。
- local cache に次を保存する: `update_check_on_startup`(既定 True)、`update_include_prerelease`
  (未設定なら方針7の既定)、`update_last_checked`。
- `src/ui/menu/update_dialog.py`:
  - 表示する内容: 現在の版、実行形態、最新版、リリースノート(`QTextBrowser.setMarkdown`)。
  - ボタンは実行形態によって変える。`source` は git pull の案内、`portable` は Releasesページを開く。
    `installed` はダウンロードしてインストール(Step 7 が入るまでは Releasesページを開く)。
- Help メニュー(About / Check for Updates… / Open Log Folder)をメインウィンドウと Analysis Mode の
  両方に追加する。起動時の自動確認と、新しい版があるときの表示は方針7のとおり。
- 開発中の確認用に、環境変数 `FLUORAPRESSEE_UPDATE_FEED` で取得先をローカルのJSONファイルや別のURLに
  差し替えられるようにする。利用者向けのマニュアルには書かない。

テスト(`tests/test_update_check.py`。ネットワークには接続しない):

- 下書き、pre-release、読めないタグ、添付ファイルの欠け、古い版、同じ版、`+dev` 付きの版を含む
  JSONを用意し、正しい版が選ばれること。

## Step 7: ダウンロードと適用

作業:

- `updates_dir()` にダウンロードする。
  - 途中は `.part` で保存し、完了したら改名する。
  - 進捗を表示し、キャンセルできるようにする。
  - SHA-256 を照合し、一致しなければ削除する。
- 適用の条件と流れは方針7のとおり。インストーラーは `closeEvent` の受け入れ側の最後(現在の
  `self.spec_ctrl.close()` のあと、`event.accept()` の前)で起動する。
  - 起動方法:
    `subprocess.Popen([installer, "/SILENT", "/NORESTART", "/RELAUNCH=live"], creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, close_fds=True)`
  - 更新のダイアログには、「アプリを終了して更新します。このあと終了確認が表示されます」と事前に
    書いておく。
- 起動時に、`updates/` 内の現在の版以下のインストーラーを削除する。

テスト:

- `closeEvent` が受け入れられたときだけインストーラーが起動すること(`Popen` を差し替えて確認)。
- UIロックの理由があるとき、インストールボタンが無効になること。

確認: Windows Sandbox で旧版をインストールし、`FLUORAPRESSEE_UPDATE_FEED` を新しい版に向けて、
GUIから更新するところまで通しで確かめる。

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
  - 更新: GUIから行うか、新しいインストーラーを実行する。
  - アンインストール: ユーザーデータは残る。その場所。
  - ソース版: 開発者向けとして、現在の内容を残す。
- `hardware-config.md`、`data-formats/index.md`、`data-formats/spectrometer-config.md`、
  `usage/acquisition.md:49` 周辺: `spectrometerConfig.json` の場所を、OS別の表と環境変数の説明に
  改める。
- Help メニューのページを新しく作る(About / Check for Updates / Open Log Folder)。`add-docs-page`
  スキルの手順に従う。
- `README.md` / `README_ja.md`: Releases へのリンクを追加する。
- `CLAUDE.md`: Running(ビルド)、Config/state files(場所)、新しいモジュールについて追記する。

## 実装しない / 見送る事項

| 事項 | 理由 |
|---|---|
| ダウングレードの防止 | 実験装置が新しい版で動かなくなったとき、戻せることに価値があるため(方針6) |
| 差分更新 | 毎回インストーラー全体をダウンロードする(数百MBを想定)。当面はこれで十分 |
| 自動適用・時刻を指定した適用 | 実験中に割り込む危険があるため(方針7) |
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
3. ~~ビルド版での Ocean Optics ドライバーの導入。~~ → **同じインストーラーに入れた専用のexeで導入する**
   (2026-11-21 決定。方針12)。
4. **古い版で新しいデータを読んだときの互換性。** ダウングレードを許すので、次を確かめる。
   - 古い版が、新しいスキーマの `ConfigurationCatalog` や `api_clients.json`(`CLIENTS_FILE_VERSION`)を
     読んだときに、壊さずに読み込みを拒否すること。
   - 少なくとも、b1 のあとで最初にスキーマを変えるまでに確認する。
   - 開発用PCで、ソース版(新しい)とインストールした版(古い)を交互に使う場合にも起きる(方針13)。
5. ~~GitHub API の利用回数制限。~~ → **24時間に1回の確認で始める。** 足りなければ、GitHub Pages
   (docs-site はすでに公開済み)に `latest.json` を置き、それを取得先にする(2026-11-21 了承)。
6. ~~同じ Windows PC にソース版とインストールした版がある場合。~~ → **一度に1つだけ起動する運用とし、
   その範囲で衝突しないようにする**(2026-11-21 決定。方針13)。マニュアルにも書く。
7. **PyInstaller でビルドした版が実機で動くか。** Step 3 でビルドができたら、開発者本人が実機で
   確かめる。結果は下の「実施ログ」に記録する。
8. ~~`.gitignore` の `/tests/`。~~ → 2026-11-21 に削除した。以前は試験用のファイルを置いていたための
   設定だった。

## 実施ログ

(まだなし)
