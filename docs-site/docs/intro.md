---
sidebar_position: 1
slug: /
title: はじめに
description: FluoRaPresséeオンラインマニュアル
---

# FluoRaPressée

![](../../logo/Large_logo.svg)

FluoRaPresséeは、スペクトルのリアルタイム取得からバックグラウンド補正、
波長較正、ピークフィッティング、高圧実験における圧力計算までを一貫して行う
PythonベースのGUIアプリケーションです。

現在、以下の装置構成に対応しています。

- Andor製カメラ + Andor製分光器（Kymera / Shamrock）
- Princeton Instruments製カメラ + Acton SPシリーズ分光器
- Ocean Optics製分光器（USB2000/USB4000）

開発段階では、以下の実機を用いて動作確認を行っております。

| 製造元 | 分光器 | 分光器との通信  | 検出器  | 検出器との通信 | 場所 |
| --- | --- | --- | --- |  --- |  --- | 
| Zolix (Andor) | Omni-λ5006i | USB | iVac316 | USB | 東京大学 |
| Andor | Kymera KY-2775 | USB | iDus DV401 | USB | 東京大学 |
| Princeton Instruments | Acton SpectraPro SP-2750 | RS-232C–USB | ProEM 1600<sup>2</sup> | GigE | BL-18C, PF, KEK |
| Ocean Optics | USB2000 | USB | USB2000 | USB | 東京大学 |

## このマニュアルについて

左側のメニューから、インストール方法、基本操作、API連携について確認できます。

:::caution

Andor SDKおよびPrinceton Instruments PICam Runtimeを利用した装置制御は、
原則としてWindows環境を対象としています。

:::

## 関連リンク

- [GitHubリポジトリ](https://github.com/khsacc/FluoRaPressee)
- [不具合・要望の報告](https://github.com/khsacc/FluoRaPressee/issues)
