---
sidebar_position: 11
title: "POST /acquire/pressure"
description: 取得・フィッティングに圧力算出を追加するエンドポイント
---

# POST /acquire/pressure

[`POST /acquire/fit`](acquire-fit.md) と同じボディに、圧力算出パラメータを追加します。

**追加フィールド:**
```json
{
  "sensor": "ruby",
  "pressure_scale": "ruby_shen_2020",
  "zero_pressure_peak": 694.30,
  "zero_pressure_peak_err": 0.003,
  "temperature_correction": {
    "enabled": true,
    "scale": "ruby_kobayashi_2026",
    "current_t": 300.0,
    "t0": 298.15,
    "zero_pressure_peak_at_t0": 694.30,
    "zero_pressure_peak_at_t0_err": 0.003
  }
}
```
- `sensor`/`pressure_scale`: [圧力計算](../usage/pressure-calculation/index.md)に一覧されている圧力マーカー・圧力スケールに対応するkey。
- Diamond Raman Edge の場合は `sensor: "diamond_raman_edge"` と`diamond_edge_...` スケールを指定します。
  `fit_function: "Diamond Raman Edge"` と通常のピーク圧力スケール、または通常のピークフィットとDiamond Edgeスケールを組み合わせると測定開始前に422エラーになります。
  Edgeスケール固有の `nu0` を使うため、`zero_pressure_peak` の値は計算には使用されません（互換性のためフィールド自体は必須）。
- `zero_pressure_peak`: 温度補正を使わない場合のゼロ圧力ピーク位置。
- `zero_pressure_peak_err`（省略可、既定値 `0`）: `zero_pressure_peak` の標準不確かさ。
  0以上の有限値のみ受け付け、負の値・`NaN`・`Infinity` は422エラーになります。
  省略すると、このフィールドを追加する前と同じ結果になります。
- `temperature_correction` は省略可。
  `enabled: false`、または省略した場合は温度補正無しで`zero_pressure_peak` がそのまま使われます。
  `enabled: true` の場合のみ、`scale` に`TEMPERATURE_SCALES` の key を指定し、その温度スケールでゼロ圧力ピークを補正してから圧力を計算します。
  温度が有効範囲外でも計算自体は続行し、`temperature_warning` に警告メッセージが入ります。
- `temperature_correction.zero_pressure_peak_at_t0_err`（省略可、既定値 `0`）: `zero_pressure_peak_at_t0` の標準不確かさ。
  温度補正の式を通して現在温度でのゼロ圧ピーク位置の誤差に伝播させてから圧力の誤差に加えます（伝播の式は[圧力計算](../usage/pressure-calculation/index.md#温度補正をonにした場合)を参照）。
  温度補正が必須なスケールでは、そのまま圧力の式に入ります。
  `temperature_correction` 自体を省略した場合は、`zero_pressure_peak_err` が使われます。
- 圧力スケール側で `T0` が固定されている場合は、リクエスト中の `t0` よりそのスケールの固定値が優先されます。

**レスポンス**: [`POST /acquire/fit`](acquire-fit.md) のフィールドに `pressure_gpa`, `pressure_err_gpa`, `pressure_err_peak_gpa`, `pressure_err_scale_gpa`, `pressure_err_zero_peak_gpa`, `zero_pressure_peak_at_current_t`, `zero_pressure_peak_at_current_t_err`, `temperature_warning` を追加。
```json
"pressure_gpa": 10.264,
"pressure_err_gpa": 0.0574,
"pressure_err_peak_gpa": 0.0143,
"pressure_err_scale_gpa": 0.0549,
"pressure_err_zero_peak_gpa": 0.0086,
"zero_pressure_peak_at_current_t": 694.30,
"zero_pressure_peak_at_current_t_err": 0.003,
"temperature_warning": null
```
（例は ruby / `ruby_shen_2020`、温度補正なし、Peak1 = 698.000 ± 0.005 nm、`zero_pressure_peak` = 694.30 ± 0.003 nm の場合）

`pressure_err_gpa` は圧力の不確かさで、次の 3 つの成分の二乗和の平方根です。
- `pressure_err_peak_gpa`: フィットで得たピーク位置の誤差に由来する成分。スペクトルごとに独立です。
- `pressure_err_scale_gpa`: 圧力スケールの係数の誤差に由来する成分。同じスケールで計算したすべての測定に共通です。係数の誤差が文献で与えられていないスケールでは `0` になります。温度補正スケールの係数の誤差を含めるスケール（現在は `ruby_kobayashi_2026` のみ、[詳細](../usage/pressure-calculation/index.md#温度補正スケールの係数の誤差)）では、その分もこの成分に入ります。
- `pressure_err_zero_peak_gpa`: ゼロ圧ピーク位置の誤差（`zero_pressure_peak_err`、温度補正時は伝播させた `zero_pressure_peak_at_t0_err`）に由来する成分。誤差を指定しなかった場合や、Diamond Raman Edgeスケールでは `0` になります。

複数の圧力マーカーの平均をとる場合、`pressure_err_peak_gpa` は独立な誤差として扱えますが、`pressure_err_scale_gpa` はマーカー間で完全に相関するため、平均しても小さくなりません。
`pressure_err_zero_peak_gpa` は、同じゼロ圧ピーク位置を使うすべての測定（例えば同じマーカーで測った圧力系列）に共通ですが、別々に測ったゼロ圧ピーク位置を使うマーカーどうしでは独立です。
現在温度・基準温度そのものの誤差は、どの成分にも含まれません。`ruby_kobayashi_2026` 以外の温度補正スケールでは、係数の誤差も含まれません。

`zero_pressure_peak_at_current_t` は、現在温度でのゼロ圧ピークを明示的に計算できるスケールでのみ値が入り、そうでない場合は `null` になります。
`zero_pressure_peak_at_current_t_err` はその誤差で、`zero_pressure_peak_at_current_t` が `null` のときは `null` です。`ruby_kobayashi_2026` で温度補正したときは、温度補正スケールの係数の誤差も含みます。
フィットが失敗した場合は `pressure_gpa`/`pressure_err_gpa`/`pressure_err_peak_gpa`/`pressure_err_scale_gpa`/`pressure_err_zero_peak_gpa`/`zero_pressure_peak_at_current_t`/`zero_pressure_peak_at_current_t_err`/`temperature_warning` はすべて `null` になります。
ダブルピークフィットの場合、圧力計算にはPeak1（較正済みx軸で値が小さい方の主ピーク）が使われます。
横軸がpixelの場合は圧力計算できないため`400 Bad Request`を返します。
また、`sensor`が期待する単位（nm/cm<sup>-1</sup>）と現在有効なcalibrationの軸単位が一致しない場合（例: Wavelength calibrationが有効な状態でRaman系sensorを指定した場合）も同様に`400 Bad Request`になります。
校正のaxis_kindと単位を暗黙に変換することはありません（[Configuration関連エンドポイント](configurations.md)参照）。
