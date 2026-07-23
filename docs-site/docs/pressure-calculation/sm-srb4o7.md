---
sidebar_position: 3
title: Sm2+:SrB4O7
description: Sm2+:SrB4O7 蛍光線による圧力スケールと温度補正
---

# Sm²⁺:SrB₄O₇

- 種類: 蛍光 (fluorescence)
- 横軸単位: nm
- ゼロ圧ピーク位置の初期値: 685.410 nm（あくまで初期値です。実際の測定系・試料で測ったゼロ圧位置に
  置き換えてください）

## 圧力スケール（3種類、いずれも温度補正は任意）

- **Datchi et al. 1997** — <i>J. Appl. Phys.</i>、0-0線、MXB1986ルビースケールに対して較正
  [DOI: 10.1063/1.365025](https://doi.org/10.1063/1.365025)

  $$
  P = C\,\Delta\lambda\,\frac{1 + a\,\Delta\lambda}{1 + b\,\Delta\lambda}
  $$

  $C = 4.032$ GPa/nm、$a = 9.29\times10^{-3}$ nm⁻¹、$b = 2.32\times10^{-2}$ nm⁻¹

- **Datchi et al. 2007** — <i>High Press. Res.</i>、0-0線、DO2007ルビースケールに対して較正
  [DOI: 10.1080/08957950701659593](https://doi.org/10.1080/08957950701659593)

  $$
  P = C\,\Delta\lambda\,\frac{1 + a\,\Delta\lambda}{1 + b\,\Delta\lambda}
  $$

  $C = 3.989$ GPa/nm、$a = 0.006915$ nm⁻¹、$b = 0.0166$ nm⁻¹

- **Rashchenko et al. 2015**（0-0線, λ1） — <i>J. Appl. Phys.</i>
  [DOI: 10.1063/1.4918304](https://doi.org/10.1063/1.4918304)

  $$
  P = \frac{A}{B}\left[\left(\frac{\lambda}{\lambda_0}\right)^{B} - 1\right]
  $$

  Mao et al. (1986) 型の式。$A = 2836$ GPa、$B = 14.3$

:::note
Rashchenko et al. (2015) は0-0線(λ1)に加えて0-1線(λ2–λ4)の3系統も報告していますが、現在のアプリの
Pressure Scale選択肢には0-0線(λ1)のみが登録されています。
:::

## 温度シフト補正スケール（任意）

| スケール | 有効範囲 |
|---|---|
| Datchi et al. 2007 | 296 – 900 K |

[圧力計算の共通の考え方](index.md#圧力計算の共通の考え方表記)のオフセット補正式
$\lambda_0(T) = \lambda_{0,T_0} + [f(T)-f(T_0)]$ における $f(T)$ は次の通りです。

$$
f(T) = -8.7\times10^{-5}(T-296) + 4.62\times10^{-6}(T-296)^2 - 2.38\times10^{-9}(T-296)^3
$$

## 注意点

- 3種類の圧力スケールはすべて温度補正が任意です。
- Datchi et al. (1997)・(2007)の2スケールはいずれも別のルビースケール（それぞれMXB1986・DO2007）
  を基準に較正されています。ルビーで求めた圧力と比較する際は、どちらのルビースケールを基準にしたかに
  注意してください。
