# packaging/ — ビルドとインストーラーのテスト

設計は [work/work_updater.md](../work/work_updater.md) を参照。開発用PCにはインストールしない。

## ビルド(開発用PC、Windows)

```powershell
pip install -r requirements-oceanoptics.txt -r requirements-build.txt
winget install --id JRSoftware.InnoSetup -e
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Installer
```

出力: `packaging\Output\FluoRaPressee-Setup-<version>.exe`

## テスト(Windows サンドボックス)

次の内容で `FRP-test.wsb` を作り(`HostFolder` は自分の環境に合わせる)、ダブルクリックで起動する。

```xml
<Configuration><MappedFolders><MappedFolder>
  <HostFolder>C:\…\FluoraPressee\packaging\Output</HostFolder>
  <SandboxFolder>C:\Users\WDAGUtilityAccount\Desktop\Installer</SandboxFolder>
  <ReadOnly>true</ReadOnly>
</MappedFolder></MappedFolders></Configuration>
```

インストーラーはログを取って実行する:
`& "$HOME\Desktop\Installer\FluoRaPressee-Setup-<version>.exe" /LOG="$HOME\Desktop\setup.log"`

| 確認すること | 期待する結果 |
|---|---|
| 新規インストール | 管理者権限なしで `%LOCALAPPDATA%\Programs\FluoRaPressee` に入る |
| 起動中に再実行 | 終了を求められる。キャンセルで何も変わらない |
| 「準備完了」画面で起動してから続行 | コピー前に止まる |
| 上書き更新(`_internal\dummy.txt` を置いてから再実行) | フォルダ選択と Ocean Optics の項目が出ず、`dummy.txt` が消え、設定が残る |
| mutex の名前 | `setup.log` の `running-mutex` とアプリのログの `Installer mutex:` が一致(日本語のインストール先でも) |
| アンインストール | 起動中は終了を求められる。`%LOCALAPPDATA%\FluoraPressee` は残る |

更新の通知は、手元のJSONを読ませて確かめる(GitHub API の形式で、`FluoRaPressee-Setup-<新しい版>.exe` を添付したリリースを1件書いておく):

```powershell
$env:FLUORAPRESSEE_UPDATE_FEED = "$HOME\Desktop\Installer\feed.json"
& "$env:LOCALAPPDATA\Programs\FluoRaPressee\FluoRaPressee.exe" --debug
```

サンドボックスでは確かめられないもの: SmartScreen の警告(公開後にブラウザで落として確認)、
別セッションからの検出(仮想マシン)、管理者として起動したドライバー導入用exeの検出(UAC が無効なら仮想マシン)。
