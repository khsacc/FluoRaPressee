---
sidebar_position: 3
title: 基本操作
description: 測定、較正、解析の基本的な流れ
---

# 基本操作

## アプリケーションの起動

Windowsでは`FluoRaPressee_run.bat`を実行します。

保存済みスペクトルの解析だけを行うAnalysis Modeは、装置を接続せずに単独で
起動できます。

```powershell
.venv\Scripts\python.exe analysis_main.py
```

## 基本的な測定の流れ

1. 使用する装置構成を選択します。
2. 露光時間、積算回数、ROIを設定します。
3. 必要に応じてバックグラウンドを取得します。
4. スペクトルを取得して保存します。
5. 波長較正、ピークフィッティング、圧力計算を行います。

## 主な機能

- 単発測定、連続測定、インターバル測定
- 1Dスペクトルと2Dイメージの表示
- バックグラウンドの取得と差し引き
- ネオン標準線などを用いた波長較正
- Pseudo-Voigt、Moffat、Gaussian、Lorentzianによるピークフィット
- 蛍光およびRamanスケールを用いた圧力計算

より詳細な説明は、今後このオンラインマニュアルへ順次追加します。
