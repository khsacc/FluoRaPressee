---
sidebar_position: 2
title: インストール
description: FluoRaPresséeの動作環境、インストール・更新・アンインストールの手順
---

# インストール

FluoRaPressée は、Pythonを必要としない**インストール版**（Windows用）を[GitHub Releases](https://github.com/khsacc/FluoraPressee/releases)で配布しています。
実験用PCでは、通常はインストール版を使ってください。
開発者向けに、ソースコードから起動する方法も[後述](#ソースから起動する開発者向け)します。

## 必須環境

- Windows 10またはWindows 11（64ビット）
- 使用する装置に対応したSDKまたはドライバー（次の節を参照）

## インストール版

### 装置メーカーのランタイム

装置メーカーのSDK・ランタイムは、ライセンスの都合でインストーラーに含まれていません。
使用する装置に応じて、先にインストールしてください。

- Andor：Andor SDK（装置に付属のCD-ROMにインストーラーが入っている）
- Princeton Instruments：PICam Runtime（オンラインでダウンロード可能）
- Ocean Optics：USBドライバー。FluoRaPresséeのインストーラーから導入できます（[後述](#ocean-optics-のドライバー)）。

### インストールの手順

1. [Releases](https://github.com/khsacc/FluoraPressee/releases)で最新版を開き、*Assets* にある `FluoRaPressee-Setup-<バージョン>.exe` をダウンロードします。
   「Source code (zip)」ではありません。
2. ダウンロードしたファイルを実行します。**管理者権限は不要**です（ユーザーごとに `%LOCALAPPDATA%\Programs\FluoRaPressee` へインストールされます）。
3. 「FluoRaPressée の新規インストール」と表示されるので、案内に従ってインストール先とオプションを確認し、インストールします。

:::caution[SmartScreen の警告]
インストーラーにはコード署名がないため、実行時に「Windows によって PC が保護されました」と表示されます。
「**詳細情報**」を押し、表示された「**実行**」を押すと続行できます。
ブラウザによっては、ダウンロードの時点でも「一般的にダウンロードされていません」などの警告が出ます。その場合は、保存を選び直してください。
この警告は、新しい版をダウンロードして実行するたびに表示されます。
:::

スタートメニューには次の項目が登録されます。

| 項目 | 内容 |
|---|---|
| FluoRaPressée | 装置を制御するメイン画面 |
| FluoRaPressée Analysis | 装置を接続せずに保存済みスペクトルを解析するAnalysis Mode |
| FluoRaPressée（デバッグモード） | 装置なしで動作を確認する `--debug` モード |
| Ocean Optics ドライバーのインストール | Ocean Optics のUSBドライバーを導入する（管理者権限が必要） |

### Ocean Optics のドライバー

Ocean Optics の装置には、SeaBreezeからアクセスできるUSBドライバーが必要です。
**すでにFluoRaPresséeで装置を認識して測定できている場合は、追加導入や再インストールは不要です。**
Python側のSeaBreezeはインストール版に同梱されているため、別途Pythonやpipを導入する必要もありません。

装置が認識されないPCでは、装置を接続し、装置を使用する他のソフトを終了してから、次のどれかで確認・導入ツールを実行します。
どれも管理者権限が必要で、Windowsの確認（UAC）が表示されます。

- インストーラーの「Ocean Optics (SeaBreeze) の USB ドライバーをインストールする」を選ぶ（新規インストール時のみ表示されます）
- セットアップウィザードまたはHardware Configurationで Ocean Optics を選んだときに表示される **Install Ocean Optics driver…** ボタン
- スタートメニューの「Ocean Optics ドライバーのインストール」

ツールは最初に装置を検出し、すでに認識できる場合はドライバーの導入を省略します。
検出できない場合だけSeaBreezeのWindowsドライバーパッケージを導入し、最後にもう一度装置を検出します。
装置の検出は測定成功までを保証するものではないため、終了後にFluoRaPresséeでスペクトルを取得してください。
複数台を使う場合は、使用する各装置が認識・測定できることを確認してください。

#### 署名関連のエラーが多数表示される場合

SeaBreezeの導入処理は、接続した機種だけでなく、複数機種用のINFファイルをまとめてWindowsに登録します。
このパッケージには署名がないものやカタログ内のハッシュが一致しないものもあり、Windowsが一部を拒否することがあります。
これはダウンロード時のHTTPS証明書エラーとは別の問題です。
詳細は[SeaBreezeのセットアップ実装](https://github.com/ap--/python-seabreeze/blob/main/src/seabreeze/os_setup.py)を参照してください。

- **使用する装置が認識・測定できる場合**：他機種用のINFの失敗を解消する必要はありません。全件成功するまで導入し直す必要もありません。
- **使用する装置が認識されない場合**：未接続、他ソフトによる使用、再接続・再起動待ち、機種に対応するドライバーの不足や不適合を切り分けます。
  デバイスマネージャーで実機の型番と割り当てられたドライバーを確認し、該当機種のINFが拒否されている場合は、有効に署名された互換ドライバーパッケージを確認してください。

ドライバー署名の強制を無効にしたり、カタログやINFを書き換えたりして拒否されたファイルを強制導入する必要はありません。
また、INFの「登録成功」は、そのドライバーが接続中の装置に割り当てられたことまでを意味しません（[MicrosoftのPnPUtil仕様](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/pnputil-command-syntax#add-driver)）。
最終的には、使用する装置の認識と測定で判断してください。

### 初回起動

初回起動時に設定ウィザードが表示されるので、装置メーカー、接続情報、回折格子などを設定してください。
以前にソースから起動していたPCでは、ウィザードの **Load existing spectrometerConfig.json…** から以前の設定ファイルを読み込めます。
ウィザードの各項目と設定ファイルの仕様については[ハードウェア設定](hardware-config.md)を参照してください。

## 更新

新しい版が公開されると、FluoRaPressée の **Help** メニューに「Update available」が表示されます（起動時に1日1回まで確認します。確認できなくても何も表示されません）。
**Help → Check for Updates…** で、いつでも手動で確認できます。

1. 更新のダイアログの **Download FluoRaPressee-Setup-…exe** を押し、インストーラーをダウンロードします。
2. **FluoRaPressée をすべて終了**してから、ダウンロードしたインストーラーを実行します。
   起動したまま実行すると、インストーラーが「FluoRaPressée が実行中です」と表示して終了を求めます。測定中でないことを確かめてから終了し、OKを押してください。
3. 既存のインストールが検出されると「FluoRaPressée の更新」と表示されます。現在のバージョンと更新後のバージョンを確認し、確認画面の **更新** を押してください。
   インストール先の選択は省略され、前回と同じ場所が上書きされます。設定と較正データはそのまま引き継がれます。

新規インストールと更新には、同じ exe を使います。完了画面には「FluoRaPressée の更新完了」と表示されます。

更新でも[SmartScreen の警告](#インストールの手順)が表示されます。
インターネットにつながらないPCでは、別のPCでダウンロードしたインストーラーをUSBメモリなどで持ち込み、同じ手順で実行してください。
詳しくは[Helpメニュー](usage/menu/help.md)を参照してください。

### 古い版に戻す

新しい版で問題が起きた場合は、古い版のインストーラーを[Releases](https://github.com/khsacc/FluoraPressee/releases)から入手して実行すると、その版に戻せます。
ただし、新しい版が新しい形式で保存したデータ（構成カタログなど）は、古い版では使えなくなることがあります。
その場合、古い版はデータを書き換えずに理由を表示し、そのデータを使う機能だけを止めます。新しい版に戻せば、そのまま使えます。

## アンインストール

Windowsの「設定 → アプリ」から FluoRaPressée をアンインストールします。
設定と較正データ（[保存場所](data-formats/index.md#アプリが自動で保存するファイル)）は、装置に結びついた資産のため**削除されません**。不要であれば手動で削除してください。

## 同じPCでソース版とインストール版を使う場合

開発用PCなどでソースから起動する版とインストール版の両方がある場合、設定と較正データは両者で共有されます。
**装置を使うメイン画面は、PC全体で同時に1つしか起動できません**（2つ目は「別の FluoRaPressée が装置を使用中です」と表示して終了します）。
デバッグモードとAnalysis Modeには、この制限はありません。

## ソースから起動する（開発者向け）

### 必須環境

- Python 3.9以上、3.13以下

### リポジトリの取得

```powershell
git clone https://github.com/khsacc/FluoRaPressee.git
cd FluoRaPressee
```

### Andor / Princeton Instruments

`setup.bat`を実行します。
プロジェクト内に`.venv`が作成され、必要なPythonパッケージがインストールされます。
装置メーカーのランタイムは[インストール版](#装置メーカーのランタイム)と同様に必要です。

### Ocean Optics

Windowsでは`setup_oceanoptics.bat`を管理者として実行します。

macOSまたはLinuxでOcean Opticsを使用する場合は、次を実行します。

```bash
./setup_oceanoptics.sh
```

### 起動と更新

Windowsでは`FluoraPressee_run.bat`を実行します。
更新は `git pull` のあと `setup.bat` を実行し直します（Help → Check for Updates… は、新しい版があるかどうかの表示だけを行います）。

以前の版では `spectrometerConfig.json` などをリポジトリ直下に保存していました。
現在の版を初めて起動すると、これらは自動的に[ユーザーデータの保存場所](data-formats/index.md#アプリが自動で保存するファイル)へ移され、リポジトリ直下の元のファイルは `.migrated` を付けた名前に変わります。
