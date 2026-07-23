---
sidebar_position: 6
title: "POST /calibration（非推奨）"
description: 較正係数を直接適用する旧エンドポイント
---

# POST /calibration（非推奨）

係数を直接適用する旧エンドポイントです。新規連携では[configuration関連エンドポイント](configurations.md)を
使用してください。将来削除予定です。

**リクエスト:**
```json
{
  "c0": 694.2, "c1": 0.0153, "c2": 0.0,
  "unit": "Wavelength",
  "laser_wavelength_nm": null,
  "label": "from-remote"
}
```
- `unit` は `"Wavelength"` または `"Raman shift"`。`"Raman shift"` のときは `laser_wavelength_nm`
  が必須（無いと `422`）。
- `label` は省略可（既定 `"api"`）。表示用のラベル文字列。

**レスポンス例:**
```json
{"applied": true, "unit": "Wavelength", "c0": 694.2, "c1": 0.0153, "c2": 0.0, "label": "from-remote"}
```
