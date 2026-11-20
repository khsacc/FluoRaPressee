---
sidebar_position: 1
title: 圧力マーカーによる圧力計算
description: 圧力計算ウィンドウで使える圧力マーカー・圧力スケール・温度補正の一覧と注意点
---

# 圧力マーカーによる圧力計算

<img src={require('@site/static/img/usage_pressure_calculator.jpg').default} style={{maxWidth: '480px'}} />

## 実装されている圧力マーカー

| 圧力マーカー | 種類 | 単位 | 圧力スケール数 | 温度補正 |
|---|---|---|---|---|
| [Ruby](ruby.md) | 蛍光 | nm | 8 | 任意（6スケールから選択） |
| [Sm<sup>2+</sup>:SrB<sub>4</sub>O<sub>7</sub>](sm-srb4o7.md) | 蛍光 | nm | 4 | 任意（2スケールから選択） |
| [Sm<sup>2+</sup>:SrFCl](sm-srfcl.md) | 蛍光 | nm | 3 | 任意（1スケール） |
| [Sm<sup>3+</sup>:YAG](sm-yag.md) | 蛍光 | nm | 1 | 任意（1スケール） |
| [<sup>13</sup>C diamond 1st order](diamond-13c.md) | Raman | cm<sup>-1</sup> | 2 | スケールにより異なる（必須・埋め込み／補正手段なし） |
| [Diamond Raman Edge](diamond-raman-edge.md) | Raman（専用フィット） | cm<sup>-1</sup> | 4 | 補正手段なし |
| [Cubic BN TO](cubic-bn.md) | Raman | cm<sup>-1</sup> | 2 | スケールにより異なる（必須／任意） |
| [Zircon B1g](zircon.md) | Raman | cm<sup>-1</sup> | 2 | 任意（2スケール、それぞれ対応する論文とペア） |
| [Quartz 464 cm<sup>-1</sup>](quartz-464.md) | Raman | cm<sup>-1</sup> | 2 | 任意（1スケール） |
| [Quartz 128 cm<sup>-1</sup>](quartz-128.md) | Raman | cm<sup>-1</sup> | 1 | 必須（埋め込み、T0固定） |


## 圧力マーカーの種類と対応する横軸

圧力計算ウィンドウで選べる圧力マーカーは、横軸のモード（波長 nm / Raman shift cm<sup>-1</sup>）によって以下のように分かれます。

- **波長 (nm) モード・蛍光圧力マーカー**: [Ruby](ruby.md)、[Sm<sup>2+</sup>:SrB<sub>4</sub>O<sub>7</sub>](sm-srb4o7.md)、[Sm<sup>2+</sup>:SrFCl](sm-srfcl.md)、[Sm<sup>3+</sup>:YAG](sm-yag.md)
- **Raman shift (cm<sup>-1</sup>) モード・Raman圧力マーカー**: [<sup>13</sup>C diamond 1st order](diamond-13c.md)、[Cubic BN TO](cubic-bn.md)、[Zircon B1g](zircon.md)、[Quartz 464 cm<sup>-1</sup>](quartz-464.md)、[Quartz 128 cm<sup>-1</sup>](quartz-128.md)
- **Raman shift (cm<sup>-1</sup>) モード・専用フィットが必要な圧力マーカー**: [Diamond Raman Edge](diamond-raman-edge.md)

メインウィンドウ／Analysis Modeの横軸モードに応じて、選択できる圧力マーカーが自動的に絞り込まれます。

## 圧力計算の共通の考え方（表記）

各圧力マーカーのページに載せている計算式は、すべてアプリ内部の実装をそのまま数式に書き下したものです。
ページ間で共通して使う記法は次の通りです。

- 波長モードの蛍光圧力マーカー: $\lambda$ = 現在のピーク位置 (nm)、$\lambda_0$ = ゼロ圧ピーク位置 (nm)、$\Delta\lambda = \lambda - \lambda_0$
- Raman shiftモードの圧力マーカー: $\nu$ = 現在のピーク位置 (cm<sup>-1</sup>)、$\nu_0$ = ゼロ圧ピーク位置 (cm<sup>-1</sup>)、$\Delta\nu = \nu - \nu_0$
- $T$ = Current T（現在温度、K）、$T_0$ = Reference T0（基準温度、K）
- 添字T0付きの $\lambda_{0,T_0}$ / $\nu_{0,T_0}$ は「基準温度 $T_0$ で実測したゼロ圧ピーク位置」、すなわちUIの Zero-pressure peak at T0 欄の値を指します

温度補正が**任意**なスケールをOnにした場合、ゼロ圧ピーク位置はスケール固有のモデル関数 $f(T)$（多項式、またはDebyeモデルなどによる格子シフト量）を使って次のようにオフセット補正されます。

$$
\lambda_0(T) = \lambda_{0,T_0} + \big[f(T) - f(T_0)\big]
$$

（Raman圧力マーカーでは $\lambda_0$ を $\nu_0$ に読み替えます。）
$f(T)$ の絶対値そのものが正確でなくても、$T_0$ での実測値 $\lambda_{0,T_0}$ を基準に差分だけを適用するため、相対的なシフト量さえ文献の値と合っていれば正しく補正されます。
具体的な $f(T)$ の形は各圧力マーカーのページに記載しています。

温度補正が**必須**なスケールではこのオフセット補正は行われず、圧力の式 $P$ 自体が $T$ を直接の変数として含みます（式は各圧力マーカーのページを参照してください）。

## 温度補正の3パターン

圧力マーカー・圧力スケールの組み合わせによって、温度補正の扱いは次の3パターンのいずれかになります。

- **補正なし・補正手段もない**: ゼロ圧ピーク位置の温度シフトを表す補正式が用意されていません。
  「Temperature Correction」のOn/Offは切り替えられますが、Onにしても実質的に値は変化しません（あるいは温度補正欄自体が非表示になります）。
- **補正は任意**: 温度シフト補正スケールが用意されており、必要な場合のみOnにできます。
  On/Offのラジオボタンで切り替え可能です。
- **補正が必須**: 圧力スケールの数式自体が現在温度を直接使います。
  On/Offの切り替えUIは非表示になり常にOnとなり、「Temperature input is mandatory for this scale!」と赤字で警告表示されます。
  この種のスケールの一部は、基準温度T0も文献の基準値に固定され、変更できません（各圧力マーカーのページを参照）。

:::caution
現在温度が、選択した温度スケール（または温度補正必須スケールの有効範囲）の外にある場合、Current Tの入力欄が赤くなり "Warning: T out of range" と表示されます。
ただし計算そのものは止まらず、範囲外でも外挿してそのまま圧力が計算されるため、警告が出た場合は文献の適用範囲を確認したうえで結果を解釈してください。
:::

## ゼロ圧ピーク位置の誤差

ゼロ圧ピーク位置の入力欄（Zero-pressure peak / Zero-pressure peak at T0）のすぐ下にある **Uncertainty** 欄に、その標準不確かさを入力できます（単位はゼロ圧ピーク位置と同じ）。
入力した誤差は圧力の誤差に伝播されます。

- 「Use the current value as zero-pressure peak position」/「Use the Current Value as the zero-pressure peak position at T0」ボタンを押すと、現在のピーク位置と一緒に、そのフィットで得たピーク位置の誤差がUncertainty欄に入ります。
- 圧力マーカーを切り替えると、ゼロ圧ピーク位置は初期値に、Uncertaintyは0に戻ります。
- ゼロ圧ピーク位置とその誤差は、小数点以下4桁まで扱います。
- [Diamond Raman Edge](diamond-raman-edge.md)はスケール固有の $\nu_0$ を使うため、Uncertainty欄は表示されません。

### 圧力の誤差の内訳

表示・保存される圧力の誤差 $\sigma_P$ は、次の3つの成分の二乗和の平方根です（$\lambda$ と $\lambda_0$ の誤差は互いに独立として扱います）。

$$
\sigma_P = \sqrt{\left(\frac{\partial P}{\partial \lambda}\,\sigma_\lambda\right)^2 + \left(\frac{\partial P}{\partial \lambda_0}\,\sigma_{\lambda_0}\right)^2 + \sigma_{P,\mathrm{scale}}^2}
$$

- 第1項: フィットで得たピーク位置の誤差 $\sigma_\lambda$ に由来する成分
- 第2項: ゼロ圧ピーク位置の誤差 $\sigma_{\lambda_0}$ に由来する成分
- 第3項: 圧力スケールの係数の誤差（文献で与えられている場合のみ）に由来する成分。温度補正スケールの係数の誤差を含めるスケールでは、その分もここに入ります（下記）

$\partial P/\partial \lambda_0$ の大きさは $\partial P/\partial \lambda$ とほぼ同じなので、$\sigma_{\lambda_0}$ が $\sigma_\lambda$ と同程度なら圧力の誤差への寄与も同程度になります。
HTTP APIでは3つの成分を別々に返します（[POST /acquire/pressure](../../api/acquire-pressure.md)）。

### 温度補正をOnにした場合

$\lambda_{0,T_0}$ の誤差は、温度補正の式を通して現在温度でのゼロ圧ピーク位置 $\lambda_0(T)$ の誤差に伝播させてから圧力の誤差に加えます。

$$
\sigma_{\lambda_0(T)} = \left|\frac{\partial \lambda_0(T)}{\partial \lambda_{0,T_0}}\right|\,\sigma_{\lambda_{0,T_0}}
$$

- nm（Raman圧力マーカーではcm<sup>-1</sup>）のまま $f(T) - f(T_0)$ を加える補正式では、係数は1で、誤差はそのまま引き継がれます。
- 波数 $\tilde\nu = 10^7/\lambda$ の領域で補正してnmに戻す補正式（Rubyの Kobayashi et al.・Yen and Nicol 1992、Sm<sup>2+</sup>:SrFClの Lorenz et al. 1994）では、係数は $\left(\lambda_0(T)/\lambda_{0,T_0}\right)^2$ です（1との差は1%程度以下）。

伝播させた誤差は、「Zero-pressure peak at current T」欄に「値 ± 誤差」の形で表示されます。
温度補正が**必須**なスケールでは、Zero-pressure peak at T0 の誤差がそのまま圧力の式に入ります。

#### 温度補正スケールの係数の誤差

Rubyの **Kobayashi et al.** スケールでは、Debyeモデルのパラメータ $(\alpha, \Theta)$ の誤差も、両者の共分散行列 $C$ を使って $\lambda_0(T)$ の誤差に加えます。

$$
\sigma_{\tilde\nu,\mathrm{coef}}^2 = \mathbf{g}^{\mathsf T} C\,\mathbf{g},\quad
\mathbf{g} = \nabla_{(\alpha,\Theta)}\big[f(T) - f(T_0)\big],\quad
\sigma_{\lambda_0(T),\mathrm{coef}} = \frac{\lambda_0(T)^2}{10^7}\,\sigma_{\tilde\nu,\mathrm{coef}}
$$

$C$ の値は[Rubyのページ](ruby.md)の温度シフト補正スケールの節に載せています。
$\alpha$ と $\Theta$ は強く反相関しているため（相関係数 −0.996）、この誤差は 0 – 300 K で $10^{-4}$ nm程度（圧力で約0.0003 GPa）と小さくなります。

- 「Zero-pressure peak at current T」欄の誤差は、$\lambda_{0,T_0}$ の誤差を伝播させた値と、この係数の誤差の二乗和の平方根です。
- 圧力の誤差の内訳では、係数の誤差は同じ温度補正スケールを使うすべての測定に共通なので、第3項（圧力スケールの係数の誤差）に含めます。第2項は $\lambda_{0,T_0}$ の誤差による分だけです。

ほかの温度補正スケールは、係数の誤差が文献に載っていないか、載っていても係数間の共分散がありません。
共分散なしに係数を独立とみなして伝播させると誤差を大きく過大評価してしまうため（例えばWei et al. 2024のRubyで773 Kのとき約0.7 nm）、これらのスケールでは係数の誤差を含めていません。

:::note
現在温度 $T$・基準温度 $T_0$ そのものの誤差は、圧力の誤差に含まれません。
:::
