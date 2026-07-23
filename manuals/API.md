# FluoraPressée API リファレンス

FluoraPressée は、同一LAN内の他のPCからHTTP経由で測定をトリガーできるAPIモードを持っています。
校正やROI設定などの基本操作はGUI内で完結させたうえで、ユーザーが明示的に「API Server」パネルの
**Start API Server** ボタンを押した場合のみAPIサーバーが起動します。APIサーバーが起動している間、
GUIの測定・設定系の操作(取得ボタン、露光時間、校正、ROI、フィット設定など)はロックされ、
プロットスタイルや自動レンジ調整などの表示系操作のみ引き続き行えます。**Stop API Server** を押すと
ロックは解除され、ローカルでの操作権が戻ります。

## 起動方法

1. GUIで校正・ROI・分光器設定など、必要な準備をすべて済ませておく。
2. 画面下部の「API Server」パネルでポート番号を指定し(既定 8765)、**Start API Server** を押す。
3. 状態表示ラベルに接続用URL(`http://<このPCのIP>:<port>/docs`)と API キー(`X-API-Key`)が
   表示される。このキーはアプリ初回起動時に一度だけ生成され、`fluora_pressee_api_key.json`
   (リポジトリルート)に永続化されるため、**サーバーを再起動しても、アプリ自体を再起動しても
   同じ値のまま変わらない**。想定される利用形態は「特定の連携アプリケーションに事前にこのキーを
   設定しておき、Start API Server を押した瞬間からその連携アプリが認証済みで叩ける」というもので、
   毎回キーを読み上げて相手に伝える必要はない。
4. `http://<このPCのIP>:<port>/docs` にブラウザでアクセスすると、Swagger UI で全エンドポイントの
   仕様をその場で確認・試行できる。
5. 使い終わったら **Stop API Server** を押す。ウィンドウを閉じる際にサーバーが起動したままでも
   自動的に停止される。

## 認証

すべてのエンドポイント(`/docs`, `/openapi.json` を除く)は `X-API-Key` ヘッダーが必須。
ヘッダーが無い場合・値が一致しない場合はいずれも `401 Unauthorized` を返す。

```
X-API-Key: <API Server パネルに表示されているキー>
```

キーが漏洩した場合や、連携先アプリを変更してキーを差し替えたい場合は、メニューバーの
**API → Regenerate Key** から手動で再発行できる。再発行すると**古いキーはその場で即座に
無効化される**(サーバーを再起動する必要はない)ため、連携アプリ側の設定も新しいキーに
更新すること。更新前に届いたリクエストは古いキーのままなら `401` になる。

## 排他制御

同時に実行できる取得は1つだけ(ローカルのGUI操作・他のAPIリクエストを含めて)。取得中に別の
取得リクエストが来た場合、後から来た方は `409 Conflict`(`{"detail": "acquisition busy"}`)を返す。
`GET /hardware/camera?refresh=true` と `GET /hardware/spectrometer?refresh=true` のライブ状態照会も
同じ排他ゲートを使用する。測定・校正・分光器移動・別のライブ照会と競合した場合は
`409 Conflict`(`{"detail": "instrument busy"}`)を返す。`refresh=false` のキャッシュ取得と
`GET /config` はこの排他ゲートを使用しない。

## エンドポイント一覧

### `GET /status`

現在の状態を返す。

**レスポンス例:**
```json
{
  "busy": false,
  "camera_connected": true,
  "exposure_time_s": 0.1,
  "calibration": {"applied": true, "unit": "Wavelength", "label": "manual-20260709"},
  "roi": {"mode": "1d_roi", "start": 100, "end": 140},
  "background": {"loaded": false, "metadata": null},
  "configuration": {
    "configuration_id": "cfg_...", "slot_id": "slot_...",
    "axis_mode": "calibrated", "calibration_applied": true,
    "unit": "Wavelength"
  },
  "hardware_state": {
    "grating_index": 2, "grooves_per_mm": 1200,
    "actual_center_wavelength_nm": 694.0,
    "roi_mode": "1d_roi", "roi_start": 100, "roi_end": 140
  }
}
```

### `GET /hardware/camera`

カメラの識別情報、センサー寸法、露光時間、ROI、binning、温度などを返す。

- `refresh=false`(既定): カメラスレッドが保持しているキャッシュだけを読み、SDK呼び出しを行わない。
- `refresh=true`: カメラスレッドへライブ状態照会を依頼し、共通形式の `status` を追加する。
  測定・分光器移動・別のライブ照会と競合した場合は `409`、10秒以内に完了しない場合は `504`。

**レスポンス例:**
```json
{
  "schema_version": 1,
  "captured_at": "2026-07-22T15:30:00+09:00",
  "mode": "hardware",
  "operational": true,
  "hardware_connected": true,
  "busy": false,
  "backend": "andor_sdk2",
  "metadata_source": "cache",
  "metadata": {
    "identity": {
      "controller_model": "C-1",
      "model": "DU-401",
      "serial_number": "CAM-001"
    },
    "detector_size_px": {"width": 1024, "height": 127},
    "pixel_pitch_um": {"width": 26.0, "height": 26.0},
    "exposure_time_s": 0.1,
    "accumulations": 3,
    "accumulation_mode": "software_sum",
    "roi": {
      "mode": "1d_roi",
      "horizontal_start": 0,
      "horizontal_end": 1024,
      "vertical_start": 100,
      "vertical_end": 127
    },
    "binning": {"horizontal": 1, "vertical": 27},
    "read_mode": "image",
    "output_rows": 1,
    "software_vertical_sum": false,
    "temperature": {
      "current_c": -64.9,
      "setpoint_c": -65.0,
      "status": "locked"
    }
  },
  "status": null
}
```

`mode` は `hardware` または `debug`。`operational` はデバッグバックエンドを含めてAPIから
利用可能か、`hardware_connected` は物理デバイスに接続されているかを表す。debugモードでは
`operational: true`, `hardware_connected: false` となる。

### `GET /hardware/spectrometer`

分光器の識別情報、中心波長、現在のグレーティングを返す。Andor/Princeton Instrumentsとも
同じ公開形式で、通常は各コントローラの `get_cached_hardware_metadata()` の結果を利用する。

- `refresh=false`(既定): DLL/RS-232通信なし。
- `refresh=true`: `get_status_snapshot()` で実機を照会し、`status` を追加する。
  測定・分光器移動・別のライブ照会と競合した場合は `409`、30秒以内に完了しない場合は `504`。

**レスポンス例:**
```json
{
  "schema_version": 1,
  "captured_at": "2026-07-22T15:30:00+09:00",
  "mode": "hardware",
  "operational": true,
  "hardware_connected": true,
  "busy": false,
  "backend": "princeton_acton",
  "metadata_source": "cache",
  "metadata": {
    "identity": {"model": "SP-2750", "serial_number": "SPEC-001"},
    "center_wavelength_nm": 694.0,
    "grating": {"index": 1, "grooves_per_mm": 600, "blaze": null},
    "wavelength_limits_nm": null
  },
  "status": null
}
```

`refresh=true` の `status` は以下の共通形式。取得できない機器固有項目は推測せず
`state: "unsupported"` とする。一部項目だけ失敗した場合はその項目を `state: "error"` とし、
他の取得結果は返す。

```json
{
  "backend": "princeton_acton",
  "available": true,
  "error": null,
  "sections": {
    "Current position": [
      {
        "key": "centre_wavelength",
        "label": "Centre wavelength",
        "value": 694.0,
        "unit": "nm",
        "state": "ok",
        "error": null
      }
    ]
  }
}
```

未接続はHTTP通信の失敗ではないため `200` を返し、`hardware_connected: false`、
`status.available: false` で表現する。

### `GET /config`

現在のプロセスで有効な設定と、`spectrometerConfig.json` に保存されている設定を返す。

```json
{
  "schema_version": 1,
  "captured_at": "2026-07-22T15:30:00+09:00",
  "source_file": "spectrometerConfig.json",
  "active_config": {
    "model": "PrincetonInstruments",
    "com_port": "COM3",
    "grating": [],
    "flip_x": false,
    "default_temperature": -65
  },
  "stored_config": {
    "model": "PrincetonInstruments",
    "com_port": "COM3",
    "grating": [],
    "flip_x": false,
    "default_temperature": -65
  },
  "restart_required": false,
  "pending_restart_keys": [],
  "redacted_fields": []
}
```

- `active_config`: 実行中プロセスへ現在適用されている設定。グレーティング、ROI、表示設定などの
  ライブ変更は反映するが、起動時にしか読まれない接続設定は起動時の値を返す。
- `stored_config`: 現在の `spectrometerConfig.json` の内容。
- `restart_required`: `model`, `com_port`, `dll_path`, `PIcam_dll_path`,
  `camera_serial_number` のいずれかに未反映の変更があるか。
- `pending_restart_keys`: 再起動待ちのキー一覧。
- `redacted_fields`: `api_key`, `password`, `token`, `secret` を名前に含むキーをレスポンスから
  除外した場合のパス一覧。APIキー用の別ファイル `fluora_pressee_api_key.json` は常に対象外。

### `GET /configurations`

GUIのLoad Configurationと同じcatalogから、configurationの軽量summaryを返す。既定では
接続中の装置と互換性がある各slotのactive versionだけを返すため、同じ条件で校正を繰り返しても
通常の選択肢は増えない。

- `active_only=true`: `false`にすると旧versionも含める。
- `include_incompatible=false`: `true`にすると非互換configurationも理由付きで含める。
- `limit=100`: 1～1000。
- `offset=0`: pagination offset。

応答には`catalog_revision`, `items`, `total`, `limit`, `offset`を含む。summaryにはgrating、
centre position、ROI、calibration unitを含むが、calibration係数は含まない。

### `GET /configurations/{configuration_id}`

immutableなconfiguration record全体を返す。`configuration.calibration.coefficients`を使えば、
pixel軸で取得したデータへクライアント側で後から校正を適用できる。現在の装置との互換性も返す。

### `POST /configurations/resolve`

ES等が保持するstableな`slot_id`を、実行に使うexactな`configuration_id`へ固定する。

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

ESはsequence検証時にresolveし、実行中は返されたexact IDを使用する。これにより、検証後に
同じslotへ新しい校正が保存されても実行中のconfigurationは暗黙に変化しない。

### `POST /configurations/{configuration_id}/apply`

指定configurationのgrating、centre position、ROIと横軸状態を適用し、移動完了後に応答する。

```json
{"axis_mode": "calibrated"}
```

- `axis_mode="calibrated"`（既定）: 保存済みcalibrationを適用する。
- `axis_mode="pixel"`: grating・centre・ROIだけを適用し、横軸はpixelにする。

応答の`configuration.axis_mode`自体は`"pixel"` / `"native_wavelength"` / `"calibrated"`の3値を
取りうる（Ocean Optics等、FluoraPressée較正なしで独自の波長軸を報告する機種向け。詳細は
`POST /acquire`の`x_axis`説明を参照）。リクエストの`axis_mode`パラメータ自体は引き続き
`"calibrated"`/`"pixel"`の2値のみを受け付ける。

`configuration.unit`は`x_axis.unit`とは別の語彙("Wavelength" / "Raman shift" / "pixel"、
`POST /calibration`の`unit`と同じ)を使う。`axis_mode="native_wavelength"`の場合も、pixelでは
なく表示モードに応じて"Wavelength"または"Raman shift"を返す。

現在のgrating・centre・ROIが同じslotと一致している場合、装置移動は省略して横軸状態だけを更新する。
応答には`configuration`, `hardware_state`, `display_label`を含む。

### `POST /calibration`（deprecated）

係数を直接適用する旧endpoint。新規連携ではconfiguration endpointを使用すること。将来削除予定。

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
  が必須(無いと `422`)。
- `label` は省略可(既定 `"api"`)。表示用のラベル文字列。

**レスポンス例:**
```json
{"applied": true, "unit": "Wavelength", "c0": 694.2, "c1": 0.0153, "c2": 0.0, "label": "from-remote"}
```

### `POST /acquire`

データを1回取得する。

**リクエスト:**
```json
{
  "configuration_id": "cfg_exact_1",
  "axis_mode": "calibrated",
  "exposure_time_s": 0.5,
  "accumulations": 3,
  "dark": {"mode": "none"}
}
```
- `configuration_id`は省略可。省略時は分光器・ROI・横軸を変更せず、現在と同じ条件で取得する。
- `configuration_id`指定時は、互換性確認、configuration適用、移動完了、取得を一つの排他操作として
  実行する。同じ物理条件なら移動を省略する。
- `axis_mode`は`configuration_id`指定時だけ使用でき、`"calibrated"`または`"pixel"`。
  省略時は`"calibrated"`。configurationなしで`axis_mode`だけ指定すると`422`。
- `exposure_time_s` / `accumulations` を省略すると、現在GUIに設定されている値がそのまま使われる。
- `dark.mode`:
  - `"none"`(既定): 減算しない。
  - `"reuse_loaded"`: GUIで現在ロードされている背景ファイルを使って減算する。この取得の
    実際の露光時間・積算数・ROIが、ロード済み背景のメタデータと一致しない場合は
    `422 Unprocessable Entity` を返す(黙って誤った値を減算しない)。どうしても近似的に
    続行したい場合のみ `dark.ignore_mismatch: true` を明示的に指定する(この場合レスポンスに
    `"background_mismatch_warning": true` が付く)。
  - `"provided"`: `dark.data` に生の暗電流スペクトル配列を直接渡す。長さが取得データと一致
    しなければ `400 Bad Request`。

**レスポンス例:**
```json
{
  "x": [690.01, 690.03, ...],
  "y_raw": [1050.0, 1048.0, ...],
  "y": [1050.0, 1048.0, ...],
  "mode": "1d",
  "exposure_time_s": 0.5,
  "accumulations": 3,
  "detector_temperature_c": -64.8,
  "timestamp": "2026-07-09T10:11:06.677845",
  "configuration": {
    "configuration_id": "cfg_exact_1", "slot_id": "slot_690nm",
    "axis_mode": "calibrated", "calibration_applied": true,
    "unit": "Wavelength"
  },
  "hardware_state": {
    "grating_index": 1, "grooves_per_mm": 600,
    "actual_center_wavelength_nm": 690.0,
    "roi_mode": "1d_roi", "roi_start": 45, "roi_end": 65
  },
  "x_axis": {"source": "calibrated", "unit": "nm", "calibrated": true}
}
```
- `x` は較正済みなら較正後の単位(nm または cm⁻¹)、未較正ならpixel番号(Ocean Optics等
  ネイティブ波長軸を持つ機種では、FluoraPressée較正が無くてもその軸を返す)。GUIの
  "Flip X-axis" 設定には依存せず、常に昇順で返す。
- `y_raw` は生データ、`y` はdark減算後(`dark.mode="none"` の場合は `y_raw` と同じ)。
- 2Dイメージモードで取得した場合、`x` は `null`、`y_raw`/`y` はネストした配列(行×列)になる。
- `x_axis`は`x`列の解釈を`configuration.axis_mode`と同じ語彙で明示する:
  - `source`: `"pixel"` / `"native_wavelength"`(FluoraPressée較正なしだが機種側の
    factory-calibratedな波長軸、現状Ocean Opticsのみ) / `"calibrated"`(FluoraPressée較正適用済み)。
  - `unit`: `source="pixel"`なら常に`null`。それ以外はRaman shiftモードなら`"cm-1"`、
    Wavelengthモードなら`"nm"`。
  - `calibrated`: `source == "calibrated"`と等価の真偽値。`false`は「FluoraPressée較正が
    未適用」を意味するだけであり、`native_wavelength`の軸自体が無較正という意味ではない。

### `POST /acquire/fit`

`/acquire` と同じボディに、フィッティングパラメータを追加する。

**追加フィールド:**
```json
{
  "fit_function": "Pseudo Voigt",
  "fit_peak_count": 2,
  "peak_sort_order": "x_desc",
  "baseline_model": "constant",
  "fit_range": {"start": 690.0, "end": 700.0}
}
```
- `fit_function`: `"Gauss"`, `"Lorentz"`, `"Pseudo Voigt"`, `"Moffat"`,
  `"Diamond Raman Edge"` のいずれか。Diamond Raman Edge は負の一次微分を
  pseudo-Voigt＋線形背景でフィットし、`fit_peak_count` は必ず `1` にする。
- `fit_peak_count`: フィットするピーク数。1～5、既定値は2。
- `peak_sort_order`: `"x_desc"`, `"x_asc"`, `"intensity_desc"`, `"intensity_asc"` のいずれか。
- `baseline_model`: `"constant"`, `"linear"`, `"quadratic"`, `"auto_polynomial"` のいずれか。
  省略時は `"constant"`。`auto_polynomial` はBICを用いて0～2次から保守的に選択する。
- `fit_range` は省略可(省略時は取得データ全域でフィット)。
- 2Dイメージモードで取得した場合、フィットは意味を持たないため `400 Bad Request` を返す。

**レスポンス**: `/acquire` のフィールドに `fit` を追加。
```json
"fit": {
  "success": true,
  "x_fit": [690.0, 690.5, ...],
  "y_fit": [1204.5, 1198.2, ...],
    "fit": {
      "is_double": true,
      "Peak1": 694.32, "Peak1_Err": 0.01, "Width1": 1.2, "Width1_Err": 0.05,
      "Peak2": 692.80, "Peak2_Err": 0.02, "Width2": 1.1, "Width2_Err": 0.06,
      "baseline": {
        "requested": "Constant", "selected": "Constant", "degree": 0,
        "basis": "chebyshev", "coefficients": [120.4],
        "coefficient_errors": [2.1], "x_min": 690.0, "x_max": 700.0
      },
      "y_baseline": [120.4, 120.4, ...],
      "R2": 0.998
    }
}
```
フィットが失敗した場合(データ点不足・範囲外など)は `"success": false`, `"fit": null` になる
(HTTPステータスは200のまま — フィット失敗は取得自体の失敗ではないため)。

### `POST /acquire/pressure`

`/acquire/fit` と同じボディに、圧力算出パラメータを追加する。

**追加フィールド:**
```json
{
  "sensor": "ruby",
  "pressure_scale": "ruby_shen_2020",
  "zero_pressure_peak": 694.30,
  "temperature_correction": {
    "enabled": true,
    "scale": "ruby_kobayashi_unpublished",
    "current_t": 300.0,
    "t0": 298.15,
    "zero_pressure_peak_at_t0": 694.30
  }
}
```
- `sensor`/`pressure_scale`: `src/pressureCalc.py` の `SENSORS` / `PRESSURE_SCALES` で定義された key。
- Diamond Raman Edge の場合は `sensor: "diamond_raman_edge"` と
  `diamond_edge_...` スケールを指定する。`fit_function: "Diamond Raman Edge"` と通常の
  ピーク圧力スケール、または通常のピークフィットとDiamond Edgeスケールを組み合わせると
  測定開始前に422エラーになる。Edgeスケール固有の `nu0` を使うため、
  `zero_pressure_peak` の値は計算には使用されない（互換性のためフィールド自体は必須）。
- `zero_pressure_peak`: 温度補正を使わない場合のゼロ圧力ピーク位置。
- `temperature_correction` は省略可。`enabled: false`、または省略した場合は温度補正無しで
  `zero_pressure_peak` がそのまま使われる。`enabled: true` の場合のみ、`scale` に
  `TEMPERATURE_SCALES` の key を指定し、その温度スケールで
  ゼロ圧力ピークを補正してから圧力を計算する。温度が有効範囲外でも計算自体は続行し、
  `temperature_warning` に警告メッセージが入る。
- 圧力スケール側で `T0` が固定されている場合は、リクエスト中の `t0` より
  `src/pressureCalc.py` の定義値が優先される。

**レスポンス**: `/acquire/fit` のフィールドに `pressure_gpa`, `pressure_err_gpa`,
`zero_pressure_peak_at_current_t`, `temperature_warning` を追加。
```json
"pressure_gpa": 16.91,
"pressure_err_gpa": 8.26,
"zero_pressure_peak_at_current_t": 694.312,
"temperature_warning": null
```
`zero_pressure_peak_at_current_t` は、現在温度でのゼロ圧ピークを明示的に計算できる
スケールでのみ値が入り、そうでない場合は `null` になる。
フィットが失敗した場合は `pressure_gpa`/`pressure_err_gpa`/
`zero_pressure_peak_at_current_t`/`temperature_warning` はすべて `null` になる。
ダブルピークフィットの場合、圧力計算にはPeak1(較正済みx軸で値が小さい方の
主ピーク)が使われる。
横軸がpixelの場合は圧力計算できないため`400 Bad Request`を返す。

## エラーコード一覧

| コード | 意味 |
|---|---|
| 400 | リクエストの内容が不正(`dark.data` の長さ不一致、2Dモードでのフィット要求など) |
| 401 | `X-API-Key` が無い、または一致しない |
| 404 | 指定configurationまたはslotが存在しない |
| 409 | 他の操作が進行中、またはconfigurationが装置と非互換 |
| 422 | リクエストボディのバリデーションエラー(Pydantic)、または `dark.mode="reuse_loaded"` の
      設定ミスマッチ |
| 500 | 予期しないサーバーエラー |
| 504 | configuration適用、取得またはライブ状態照会がタイムアウトした |

## 既知の制限

- **リモートからの新規dark取得は未実装**: `dark.mode="reuse_loaded"`/`"provided"` はGUIで
  事前に取得・保存した(またはクライアント自身が用意した)背景データを使うだけで、APIから
  「今すぐdarkを撮り直す」ことはできない。励起光を物理的に遮断するシャッター制御が本アプリに
  無いため。将来シャッター制御が実装された段階で追加を検討する。
- APIサーバーの起動自体が(ポート使用中などの理由で)失敗した場合、GUI側には明示的なエラー
  表示は出ない。ステータスラベルのURLにアクセスできない場合は、ポート番号を変えて再試行する
  こと。

## curl での実行例

```bash
# 状態確認
curl -H "X-API-Key: <キー>" http://<IP>:8765/status

# キャッシュ済みカメラ情報
curl -H "X-API-Key: <キー>" http://<IP>:8765/hardware/camera

# 分光器のライブ詳細情報
curl -H "X-API-Key: <キー>" "http://<IP>:8765/hardware/spectrometer?refresh=true"

# 実行中・保存済みconfig
curl -H "X-API-Key: <キー>" http://<IP>:8765/config

# Load Configurationと同じactive候補
curl -H "X-API-Key: <キー>" http://<IP>:8765/configurations

# configurationを適用してpixel軸で取得
curl -X POST -H "X-API-Key: <キー>" -H "Content-Type: application/json" \
  -d '{"configuration_id":"cfg_...", "axis_mode":"pixel"}' \
  http://<IP>:8765/acquire

# データ取得+フィット+圧力算出
curl -X POST -H "X-API-Key: <キー>" -H "Content-Type: application/json" \
  -d '{
        "exposure_time_s": 0.5, "accumulations": 3,
        "dark": {"mode": "reuse_loaded"},
        "fit_function": "Pseudo Voigt", "fit_peak_count": 2,
        "baseline_model": "constant",
        "fit_range": {"start": 690, "end": 700},
        "sensor": "ruby", "pressure_scale": "ruby_shen_2020",
        "zero_pressure_peak": 694.30
      }' \
  http://<IP>:8765/acquire/pressure
```

実装の詳細・設計判断の経緯は `work/work_API.md` を参照。
