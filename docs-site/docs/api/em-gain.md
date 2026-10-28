---
sidebar_position: 6
title: EM Gain
description: カメラのEM Gain対応状況・現在値の取得と変更
---

# EM Gain

Princeton Instruments と Andor SDK2 の対応カメラでは、EM Gain を読み取り・変更できます。すべてのリクエストに `X-API-Key` ヘッダーが必要です。Ocean Optics と EM Gain のないカメラでは `exists: false` を返します。

## GET /hardware/camera/em-gain

カメラスレッドが保持する最後に適用された値と、初期化時に検出した対応範囲を返します。ハードウェアへの新しい問い合わせは行いません。

```json
{
  "exists": true,
  "available": true,
  "gain": 100,
  "minimum": 1,
  "maximum": 1000,
  "increment": 1,
  "instrument_state_token": "a1b2c3d4:5"
}
```

`exists: false` はEM Gainパラメータが検出されていないことを示し、`gain` と範囲は `null` です。`exists: true, available: false` はパラメータはあるものの現在は変更できない状態を示します。カメラが切断された場合も `available: false` になります。

## PUT /hardware/camera/em-gain

```json
{"gain": 100, "expected_state_token": "a1b2c3d4:5"}
```

`gain` は整数で、GETで得た `minimum`・`maximum`・`increment` に従います。Andor SDK2 の書き込み範囲は非Advancedモードに制限した `0..300` で、機種固有のより狭い範囲は書き込み時にSDKが検証します。既にAdvancedモードで設定されている値は読み取れますが、このAPIはAdvanced EM Gain を有効化しません。`expected_state_token` は任意です。変更が完了すると、GETと同じ形式で**実際に適用された値**と更新後のトークンを返します。対応機では、変更時にEM読出しアンプへ切り替わる場合があります。

カメラが準備できていない場合は `503`、非対応・利用不可・範囲外・書き込み失敗は `422`、装置の使用中またはトークン不一致は `409`、変更が10秒以内に完了しない場合は `504` を返します。タイムアウト後も書き込み処理が終わるまで装置の排他制御を維持します。
