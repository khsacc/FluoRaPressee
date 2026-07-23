---
sidebar_position: 6
title: Diamond Raman edge
description: ダイヤモンドアンビル自身の1次ラマンエッジ位置による圧力ゲージ
---

# Diamond Raman edge

- 種類: Raman（ダイヤモンドアンビル自身の高波数側ラマンエッジ位置を使う、専用の測定種別）
- 横軸単位: cm⁻¹
- ゼロ圧ピーク位置の初期値: 1334.0 cm⁻¹

:::caution
このセンサーを使うには、フィッティング設定の「Fit Function」で **Diamond Raman Edge** を選ぶ必要が
あります。これは通常のピーク関数フィットではなく、`-dI/dν` をPseudo-Voigtでフィットしてエッジ位置を
求める専用アルゴリズムで、ピーク数は常に1です。逆にFit Functionを Diamond Raman Edge にした場合は、
Pressure Scaleも本ページのDiamond Raman Edge系スケールのいずれかを選ぶ必要があります。組み合わせが
一致しないと圧力欄に "Configuration Error" と表示され、圧力は計算されません。
:::

## 圧力スケール（4種類）

- **Hilberer et al. 2026** — Hilberer, A., Loubeyre, P., Pépin, C. et al., "Spectroscopic limits of
  diamond anvils to 520 GPa and projected bandgap closure," <i>Nat. Commun.</i> 17, 2644 (2026).
  [DOI: 10.1038/s41467-026-69533-7](https://doi.org/10.1038/s41467-026-69533-7)

  $$
  P = k_0\,x\left[1 + \tfrac{1}{2}(k_0' - 1)\,x\right],\quad x = \frac{\nu}{\nu_0} - 1
  $$

  $\nu_0 = 1334.0$ cm⁻¹、$k_0 = 575.0(7.0)$、$k_0' = 3.3(0.1)$

- **Eremets et al. 2023** — Eremets, M.I., Minkov, V.S., Kong, P.P. et al., "Universal diamond edge
  Raman scale to 0.5 terapascal and implications for the metallization of hydrogen,"
  <i>Nat. Commun.</i> 14, 907 (2023).
  [DOI: 10.1038/s41467-023-36429-9](https://doi.org/10.1038/s41467-023-36429-9)

  $$
  P = a\,x + b\,x^{2},\quad x = \frac{\nu}{\nu_0} - 1
  $$

  $\nu_0 = 1332.5$ cm⁻¹、$a = 517.0$、$b = 764.0$

- **Akahama and Kawamura 2006** — Yuichi Akahama and Haruki Kawamura, "Pressure calibration of
  diamond anvil Raman gauge to 410 GPa," <i>J. Appl. Phys.</i> 100, 043516 (2006).
  [DOI: 10.1063/1.2335683](https://doi.org/10.1063/1.2335683)

  $$
  P = k_0\,x\left[1 + \tfrac{1}{2}(k_0' - 1)\,x\right],\quad x = \frac{\nu}{\nu_0} - 1
  $$

  $\nu_0 = 1334.0$ cm⁻¹、$k_0 = 547.0(11.0)$、$k_0' = 3.75(0.20)$

- **Akahama and Kawamura 2010** — Yuichi Akahama and Haruki Kawamura, "Pressure calibration of
  diamond anvil Raman gauge to 410 GPa," <i>J. Phys.: Conf. Ser.</i> 215, 012195 (2010), quadratic
  fit valid for P > 200 GPa (multimegabar range, up to 410 GPa).
  [DOI: 10.1088/1742-6596/215/1/012195](https://doi.org/10.1088/1742-6596/215/1/012195)

  他の3スケールと異なり、規格化シフト $x$ ではなくフィットで求めたエッジ位置 $\nu$ そのものの2次式です。

  $$
  P = c_0 + c_1\,\nu + c_2\,\nu^{2}
  $$

  $c_0 = 3141(3)$、$c_1 = -4.157(20)$、$c_2 = 1.429(12)\times10^{-3}$。$\nu_0 = 1334.0$ cm⁻¹は他
  スケールとの表示上の整合のために示しているだけで、この式自体には使われません。

| スケール | 基準エッジ位置 ν0 (cm⁻¹) | 式の形 |
|---|---|---|
| Hilberer et al. 2026 | 1334.0 | k0 = 575.0(7.0), k0' = 3.3(0.1) |
| Eremets et al. 2023 | 1332.5 | 2次式（a = 517.0, b = 764.0） |
| Akahama and Kawamura 2006 | 1334.0 | k0 = 547.0(11.0), k0' = 3.75(0.20) |
| Akahama and Kawamura 2010 | 1334.0（表示のみ、式には不使用） | 絶対波数ωの2次式：P = c0 + c1・ω + c2・ω²、c0 = 3141(3)、c1 = -4.157(20)、c2 = 1.429(12)×10⁻³ |

## 温度補正

このセンサーには温度補正の仕組み自体がありません。スケールを選ぶと「Temperature Correction」欄自体が
非表示になります。

## 注意点

- ゼロ圧位置(ν0)はスケールごとに固定されており、通常のセンサーとは異なりユーザーが入力・編集する欄
  （Zero-pressure peak）は無効化され、「Scale reference ν0」として表示のみになります。
- 上記の通り、Fit Function（Diamond Raman Edge）とPressure Scale（Diamond Raman Edge系）は必ず
  ペアで選択してください。
- **Akahama and Kawamura 2010** はP > 200 GPa（多メガバール領域、〜410 GPaまで）でのみ検証された式です。
  それより低圧側での適用は文献の対象範囲外であり、コード側にもこの圧力範囲を強制するチェックはないため、
  低圧のデータに使わないよう注意してください。
