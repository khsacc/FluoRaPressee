---
sidebar_position: 3
title: ハードウェア設定
description: spectrometerConfig.jsonの仕様と、初回接続時にGUIのセットアップウィザードから自動生成される仕組み
---

# ハードウェア設定

FluoRaPressée がどの分光器・カメラをどう制御するか（メーカー、接続方法、grating構成、ROIの初期値、冷却設定など）は、リポジトリルート直下の `spectrometerConfig.json` に保存されています。このファイルはアプリ起動時にカメラ／分光器スレッドを構築する際に読み込まれ、以後は明示的に再起動するまで一部の項目（後述）は再読み込みされません。

:::note
似た名前のものに、較正ダイアログの「Save and apply」で作られる**Configuration**（grating・中心波長・ROI・横軸較正のバージョン管理付き記録）があります。こちらはアプリ本体ではなくOSのユーザー別application data領域に保存される別の仕組みで、詳細は[Configurationファイル](data-formats/configuration.md)を参照してください。本ページで扱う `spectrometerConfig.json` は、装置そのものの構成（どのメーカー・どう接続するか）を表す、より低レベルな設定です。
:::

## 初回起動時の自動生成

`main.py` を実行した際（`--debug` モードでも同様です）、`spectrometerConfig.json` が存在しなければセットアップウィザードが自動的に開きます。ウィザードは3ステップです。

1. **メーカー選択**: Andor / Princeton Instruments / Ocean Optics
2. **接続設定**: メーカーごとに異なる項目を入力します（[メーカー別の接続設定項目](data-formats/spectrometer-config.md#メーカー別の接続設定項目)を参照）。Andor・Princeton InstrumentsのDLL/Runtimeパス欄は、ウィザードが裏でよくあるインストール先を自動検索し、見つかった候補を一覧に出します（✓ = ファイルを発見、✗ = 未発見、– = 未チェック）。**Read parameters from connected hardware** ボタンを押すと、接続済みの実機から接続情報・grating構成・機種名/シリアル番号を読み取り、各欄に反映します。読み取りに失敗した項目があっても手入力にフォールバックするだけで、ウィザードが停止することはありません。
3. **Grating・検出器設定**: gratingのgrooves/mm（カンマ区切り）、`flip_x`（左右反転表示）、冷却器の目標温度初期値などを設定します。Princeton Instrumentsは指定したCOMポートに対して `?GRATINGS` 照会を試み、成功すればgrating欄を自動的に埋めます。Ocean Opticsは可動gratingも冷却器も持たない固定分光器のため、この画面ではgratingと冷却温度の項目が表示されません。

ウィザードを最後まで完了する（Finish）と、入力内容が `spectrometerConfig.json` としてリポジトリルートに書き込まれます。

:::caution
ウィザードを**キャンセル**すると、`spectrometerConfig.json` は作成されず、アプリケーションはそのまま終了します。デフォルト設定が自動生成されることはありません。ハードウェアなしでUIの動作確認だけを行いたい場合（`--debug` モード）でも、初回はウィザードの入力を完了させる必要があります。
:::

メーカー別の接続設定項目、ファイル内の各キーの意味、`grating`配列・`hardware_identity`の構造、メーカー別の設定例、設定の変更方法、読み込みに関する補足など、設定ファイル自体の詳しい仕様は
[spectrometerConfig.jsonの仕様](data-formats/spectrometer-config.md)を参照してください。
