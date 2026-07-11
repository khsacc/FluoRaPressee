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
  "background": {"loaded": false, "metadata": null}
}
```

### `POST /calibration`

校正パラメータ(既にGUIまたは他の手段で計算済みの多項式係数)を適用する。校正計算そのものは
このAPIでは行わない。

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
  "exposure_time_s": 0.5,
  "accumulations": 3,
  "dark": {"mode": "none"}
}
```
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
  "timestamp": "2026-07-09T10:11:06.677845"
}
```
- `x` は較正済みなら較正後の単位(nm または cm⁻¹)、未較正ならpixel番号。GUIの "Flip X-axis" 設定
  には依存せず、常に昇順で返す。
- `y_raw` は生データ、`y` はdark減算後(`dark.mode="none"` の場合は `y_raw` と同じ)。
- 2Dイメージモードで取得した場合、`x` は `null`、`y_raw`/`y` はネストした配列(行×列)になる。

### `POST /acquire/fit`

`/acquire` と同じボディに、フィッティングパラメータを追加する。

**追加フィールド:**
```json
{
  "fit_function": "Double pseudo Voigt",
  "fit_range": {"start": 690.0, "end": 700.0}
}
```
- `fit_function`: `"Gauss"`, `"Lorentz"`, `"Pseudo Voigt"`, `"Double Gauss"`, `"Double Lorentz"`,
  `"Double pseudo Voigt"` のいずれか。
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
- `zero_pressure_peak`: 温度補正を使わない場合のゼロ圧力ピーク位置。
- `temperature_correction` は省略可。`enabled: false`、または省略した場合は温度補正無しで
  `zero_pressure_peak` がそのまま使われる。`enabled: true` の場合のみ、`scale` に
  `TEMPERATURE_SCALES` の key を指定し、その温度スケールで
  ゼロ圧力ピークを補正してから圧力を計算する。温度が有効範囲外でも計算自体は続行し、
  `temperature_warning` に警告メッセージが入る。

**レスポンス**: `/acquire/fit` のフィールドに `pressure_gpa`, `pressure_err_gpa`,
`temperature_warning` を追加。
```json
"pressure_gpa": 16.91,
"pressure_err_gpa": 8.26,
"temperature_warning": null
```
フィットが失敗した場合は `pressure_gpa`/`pressure_err_gpa`/`temperature_warning` はすべて
`null` になる。ダブルピークフィットの場合、圧力計算にはPeak1(較正済みx軸で値が小さい方の
主ピーク)が使われる。

## エラーコード一覧

| コード | 意味 |
|---|---|
| 400 | リクエストの内容が不正(`dark.data` の長さ不一致、2Dモードでのフィット要求など) |
| 401 | `X-API-Key` が無い、または一致しない |
| 409 | 他の取得が進行中(ローカルGUIまたは他のAPIリクエスト) |
| 422 | リクエストボディのバリデーションエラー(Pydantic)、または `dark.mode="reuse_loaded"` の
      設定ミスマッチ |
| 500 | 予期しないサーバーエラー |
| 504 | 取得がタイムアウトした |

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

# データ取得+フィット+圧力算出
curl -X POST -H "X-API-Key: <キー>" -H "Content-Type: application/json" \
  -d '{
        "exposure_time_s": 0.5, "accumulations": 3,
        "dark": {"mode": "reuse_loaded"},
        "fit_function": "Double pseudo Voigt",
        "fit_range": {"start": 690, "end": 700},
        "sensor": "ruby", "pressure_scale": "ruby_shen_2020",
        "zero_pressure_peak": 694.30
      }' \
  http://<IP>:8765/acquire/pressure
```

実装の詳細・設計判断の経緯は `work/work_API.md` を参照。
