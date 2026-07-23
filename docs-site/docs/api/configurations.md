---
sidebar_position: 5
title: Configuration関連エンドポイント
description: 保存済みconfigurationの一覧・取得・適用 (GET/POST /configurations)
---

# Configuration関連エンドポイント

## GET /configurations

GUIのLoad Configurationと同じcatalogから、configurationの軽量summaryを返します。既定では
接続中の装置と互換性がある各slotのactive versionだけを返すため、同じ条件で校正を繰り返しても
通常の選択肢は増えません。

- `active_only=true`: `false`にすると旧versionも含めます。
- `include_incompatible=false`: `true`にすると非互換configurationも理由付きで含めます。
- `limit=100`: 1～1000。
- `offset=0`: pagination offset。

応答には`catalog_revision`, `items`, `total`, `limit`, `offset`を含みます。summaryにはgrating、
centre position、ROI、calibration unitを含みますが、calibration係数は含みません。

## `GET /configurations/{configuration_id}`

immutableなconfiguration record全体を返します。`configuration.calibration.coefficients`を使えば、
pixel軸で取得したデータへクライアント側で後から校正を適用できます。現在の装置との互換性も返します。

## POST /configurations/resolve

ES等が保持するstableな`slot_id`を、実行に使うexactな`configuration_id`へ固定します。

```json
{"slot_ids": ["slot_690nm", "slot_694nm", "slot_700nm"]}
```

```json
{
  "catalog_revision": 42,
  "resolved": [
    {"slot_id": "slot_690nm", "configuration_id": "cfg_exact_1"},
    {"slot_id": "slot_694nm", "configuration_id": "cfg_exact_2"},
    {"slot_id": "slot_700nm", "configuration_id": "cfg_exact_3"}
  ]
}
```

ESはsequence検証時にresolveし、実行中は返されたexact IDを使用します。これにより、検証後に
同じslotへ新しい校正が保存されても実行中のconfigurationは暗黙に変化しません。

## `POST /configurations/{configuration_id}/apply`

指定configurationのgrating、centre position、ROIと横軸状態を適用し、移動完了後に応答します。

```json
{"axis_mode": "calibrated"}
```

- `axis_mode="calibrated"`（既定）: 保存済みcalibrationを適用します。
- `axis_mode="pixel"`: grating・centre・ROIだけを適用し、横軸はpixelにします。

応答の`configuration.axis_mode`自体は`"pixel"` / `"native_wavelength"` / `"calibrated"`の3値を
取りえます（Ocean Optics等、FluoraPressée較正なしで独自の波長軸を報告する機種向け。詳細は
[`POST /acquire`](acquire.md)の`x_axis`説明を参照）。リクエストの`axis_mode`パラメータ自体は引き続き
`"calibrated"`/`"pixel"`の2値のみを受け付けます。

`configuration.unit`は`x_axis.unit`とは別の語彙（"Wavelength" / "Raman shift" / "pixel"、
[`POST /calibration`](calibration.md)の`unit`と同じ）を使います。`axis_mode="native_wavelength"`の場合も、
pixelではなく表示モードに応じて"Wavelength"または"Raman shift"を返します。

現在のgrating・centre・ROIが同じslotと一致している場合、装置移動は省略して横軸状態だけを更新します。
応答には`configuration`, `hardware_state`, `display_label`を含みます。
